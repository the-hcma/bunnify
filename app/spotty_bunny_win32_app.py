"""Spotty Bunny tray icon + overlay search window (win32).

Windows sibling of ``app/spotty_bunny_app.py``'s ``SpottyBunnyController``.
One thread hosts everything: the tray's message-only window, the overlay
popup window, and the ``WH_KEYBOARD_LL`` chord hook (``app.spotty_bunny_hook_
win32.install_chord_hook``) all live on the thread that calls
:func:`run_spotty_bunny_win32_app`, and ``pump_hook_messages()`` (already in
that module) is the single ``GetMessage``/``DispatchMessage`` loop routing to
whichever HWND owns each message -- there is no second message pump to
coordinate.

Styling is deliberately plain/native (standard system font and colors, a
borderless topmost popup) rather than a pixel-clone of macOS's custom
rounded blue/cream chrome -- lower risk without a Windows machine to look at
it, and more idiomatic for Windows users. The About panel (a stub here,
replaced by #428) follows the same principle.

As much logic as possible lives in plain methods that take/return plain
values (selector mapping, menu dispatch, completion/history/resolve
sequencing) so it can be unit-tested directly, matching
``spotty_bunny_hook_win32.py``'s convention -- only real window/GDI/tray
creation is deferred-imported ``win32*`` glue.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.cli import open_url
from app.client import fetch_key_entries
from app.config import load_spotty_bunny_hotkey, resolve_base_url
from app.spotty_bunny_cli import SpottyBunnyHookError
from app.spotty_bunny_complete import (
    CompletionRow,
    apply_completion,
    completion_navigation_disposition,
    completion_row_after_selector,
    completion_still_current,
    completion_table_should_show,
    completions_for,
    make_spotty_completer,
    should_auto_insert_completion,
)
from app.spotty_bunny_history import (
    HistoryNavigator,
    append_history_line,
    apply_history_selector,
    load_history_lines,
)
from app.spotty_bunny_hook_win32 import (
    InstalledHook,
    install_chord_hook,
    install_console_quit_handler,
    pump_hook_messages,
)
from app.spotty_bunny_hotkey import ChordTracker
from app.spotty_bunny_hotkey_win32 import (
    VK_LCONTROL,
    VK_RCONTROL,
    resolve_win32_chord_vks,
)
from app.spotty_bunny_icon_win32 import make_spotty_bunny_icon_win32
from app.spotty_bunny_io import ThreadIo
from app.spotty_bunny_menu import (
    CHECK_FOR_UPDATES_STATUS,
    INSTALL_STATUS,
    UPGRADE_STATUS,
    logo_menu_specs,
)
from app.spotty_bunny_resolve import lookup_resolved_url, resolve_still_current
from app.spotty_bunny_status import format_spotty_bunny_status
from app.spotty_bunny_tap_health import TAP_HEALTH_CHECK_INTERVAL_S
from app.spotty_bunny_update import (
    badge_should_show,
    refresh_update_status,
    summarize_update_check,
)

logger = logging.getLogger(__name__)

# WM_APP..0xBFFF is reserved for application-private messages (winuser.h).
WM_APP = 0x8000
WM_APP_TOGGLE = WM_APP + 1
WM_APP_RESOLVE_READY = WM_APP + 2
WM_APP_COMPLETIONS_READY = WM_APP + 3
WM_APP_TRAY = WM_APP + 4

TIMER_ID_HEALTH = 1
TIMER_ID_UPDATE = 2
UPDATE_CHECK_INTERVAL_MS = 24 * 60 * 60 * 1000

OVERLAY_WINDOW_CLASS = "BunnifySpottyBunnyOverlay"
TRAY_WINDOW_CLASS = "BunnifySpottyBunnyTray"
TRAY_ICON_ID = 1

VK_TAB = 0x09
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
VK_PRIOR = 0x21  # Page Up
VK_NEXT = 0x22  # Page Down
VK_UP = 0x26
VK_DOWN = 0x28

_VK_SELECTORS: dict[int, str] = {
    VK_TAB: "insertTab:",
    VK_UP: "moveUp:",
    VK_DOWN: "moveDown:",
    VK_PRIOR: "pageUp:",
    VK_NEXT: "pageDown:",
}

UNINSTALL_INFORMATIVE_WIN32 = (
    "Removes the Scheduled Task and stops Spotty Bunny. "
    "Bookmarks and config.toml are kept."
)


def _selector_for_vk(vk_code: int) -> str | None:
    """Map an Edit-control keydown to the Cocoa-selector-name strings that
    ``app.spotty_bunny_complete``/``app.spotty_bunny_history`` consume.

    Only the keys those modules understand are mapped here; Return/Escape
    have their own handling in :meth:`SpottyBunnyWin32Controller.handle_edit_
    keydown`, and everything else (character keys, Home/End, Left/Right) is
    left to the Edit control's own default behavior.
    """
    return _VK_SELECTORS.get(vk_code)


class SpottyBunnyWin32Controller:
    """Owns the tray icon, the overlay window, and the chord hook."""

    def __init__(
        self,
        *,
        get_field_text: Callable[[], str] | None = None,
        set_field_text: Callable[[str], None] | None = None,
        set_status_text: Callable[[str], None] | None = None,
        set_completion_rows: Callable[[list[CompletionRow]], None] | None = None,
        io: Any = None,
    ) -> None:
        self._field_text = ""
        self.get_field_text = get_field_text or (lambda: self._field_text)
        self.set_field_text = set_field_text or self._default_set_field_text
        self.set_status_text = set_status_text or (lambda _text: None)
        self.set_completion_rows = set_completion_rows or (lambda _rows: None)
        self._io = io if io is not None else ThreadIo()

        self.visible = False
        self.about_open = False
        self._resolving = False
        self._chord = ChordTracker()
        self._history = HistoryNavigator(load_history_lines())
        self._completer: object | None = None
        self._base_url = ""
        self._entries: list[object] = []
        self._completion_rows: list[CompletionRow] = []
        self._completion_index = 0
        self._completion_visible = False
        self._completion_prefix = ""
        self._resolve_seq = 0
        self._completion_seq = 0
        self._pending_resolves: dict[int, object] = {}
        self._pending_completions: dict[int, object] = {}
        self._update_status = None
        self._outdated = False
        self._agent_installed = False
        self._open_url_fn: Callable[[str], None] = open_url
        self._append_history_fn: Callable[[str], None] = append_history_line

        # Real Windows handles, set by run_spotty_bunny_win32_app(); left
        # None here so the pure logic above can be unit-tested without them.
        self.hwnd: int | None = None
        self.tray_hwnd: int | None = None
        self.icon_handle: int | None = None
        self._hook: InstalledHook | None = None
        self._left_vk: int | None = None
        self._right_vk: int | None = None
        self.request_quit: Callable[[], None] = lambda: None

    # -- show/hide/toggle --------------------------------------------------

    def show(self) -> None:
        self.set_status_text("")
        self._load_completer_async()
        self.visible = True
        logger.info("show overlay")

    def hide(self) -> None:
        self._resolve_seq += 1
        self._completion_seq += 1
        self._hide_completions()
        if self.about_open:
            self.hide_about()
        self.visible = False
        logger.info("hide overlay")

    def toggle(self) -> None:
        if self.visible:
            self.hide()
        else:
            self.show()

    def dismiss_with_escape(self) -> None:
        if not self.visible:
            return
        if self.about_open:
            self.hide_about()
            return
        self.hide()

    # -- About stub (real dialog lands in #428) -----------------------------

    def show_about(self) -> None:
        self.about_open = True

    def hide_about(self) -> None:
        self.about_open = False

    # -- key handling --------------------------------------------------------

    def handle_edit_keydown(self, vk_code: int) -> bool:
        """Return True when *vk_code* was handled (consumed) here."""
        if vk_code == VK_RETURN:
            self._submit_query()
            return True
        if vk_code == VK_ESCAPE:
            self.dismiss_with_escape()
            return True
        selector = _selector_for_vk(vk_code)
        if selector is None:
            return False
        if selector == "insertTab:":
            self._request_completions()
            return True
        disposition = completion_navigation_disposition(
            selector,
            has_rows=bool(self._completion_rows),
            table_visible=self._completion_visible,
        )
        if disposition == "move":
            self._move_completion(selector)
            return True
        if disposition == "consume":
            return True
        if disposition == "ignore":
            return False
        current = self.get_field_text()
        history_text = apply_history_selector(self._history, current, selector)
        if history_text is not None:
            self.set_field_text(history_text)
            return True
        return False

    # -- completion ----------------------------------------------------------

    def _request_completions(self) -> None:
        prefix = self.get_field_text()
        self._completion_prefix = prefix
        completer = self._completer
        if completer is None:
            return
        self._completion_seq += 1
        seq = self._completion_seq

        def work() -> list[CompletionRow]:
            return completions_for(prefix, completer)

        def on_done(result: object) -> None:
            self._pending_completions[seq] = result
            self.post_app_message(WM_APP_COMPLETIONS_READY, seq, 0)

        self._io.submit(work, on_done)

    def handle_completions_ready(self, seq: int) -> None:
        result = self._pending_completions.pop(seq, None)
        if isinstance(result, BaseException):
            return
        if not completion_still_current(
            expected_seq=self._completion_seq,
            field=self.get_field_text(),
            prefix=self._completion_prefix,
            seq=seq,
        ):
            return
        rows = list(result) if result else []
        self._completion_rows = rows
        self._completion_index = 0
        if should_auto_insert_completion(self._completion_prefix, rows):
            applied = apply_completion(self.get_field_text(), rows[0])
            self.set_field_text(applied)
        self._completion_visible = completion_table_should_show(
            self._completion_prefix, rows
        )
        self.set_completion_rows(rows if self._completion_visible else [])

    def _move_completion(self, selector: str) -> None:
        self._completion_index = completion_row_after_selector(
            self._completion_index,
            row_count=len(self._completion_rows),
            selector=selector,
        )

    def _hide_completions(self) -> None:
        self._completion_rows = []
        self._completion_visible = False
        self.set_completion_rows([])

    # -- resolve/submit --------------------------------------------------------

    def _submit_query(self) -> None:
        if self._resolving:
            return
        query = self.get_field_text().strip()
        if not query and self._completion_visible and self._completion_rows:
            idx = self._completion_index
            if idx < 0 or idx >= len(self._completion_rows):
                idx = 0
            query = apply_completion(
                self._completion_prefix, self._completion_rows[idx]
            ).strip()
            self.set_field_text(query)
        if not query:
            self.hide()
            return
        self._resolve_seq += 1
        seq = self._resolve_seq
        self._resolving = True
        self.set_status_text("")
        cached_base = self._base_url
        opener = self._open_url_fn
        appender = self._append_history_fn

        def work() -> str:
            base_url = cached_base or resolve_base_url(
                persist=False, allow_prompt=False
            )
            url = lookup_resolved_url(query, base_url=base_url)
            if not resolve_still_current(expected_seq=seq, seq=self._resolve_seq):
                return url
            opener(url)
            appender(query)
            return url

        def on_done(result: object) -> None:
            self._pending_resolves[seq] = result
            self.post_app_message(WM_APP_RESOLVE_READY, seq, 0)

        self._io.submit(work, on_done)

    def handle_resolve_ready(self, seq: int) -> None:
        result = self._pending_resolves.pop(seq, None)
        if not resolve_still_current(expected_seq=seq, seq=self._resolve_seq):
            return
        self._resolving = False
        if isinstance(result, BaseException):
            logger.warning("resolve failed: %s", result)
            self._hide_completions()
            self.set_status_text(format_spotty_bunny_status(result))
            return
        logger.info("opened %s", result)
        self.hide()

    # -- completer loading -----------------------------------------------------

    def _load_completer_async(self) -> None:
        def work() -> tuple[object, str, list[object]]:
            base_url = resolve_base_url(persist=False, allow_prompt=False)
            entries = fetch_key_entries(base_url=base_url)
            completer = make_spotty_completer(entries=entries)
            return completer, base_url, list(entries)

        def on_done(result: object) -> None:
            if isinstance(result, BaseException):
                logger.warning("could not load completer: %s", result)
                return
            if not isinstance(result, tuple):
                return
            completer, base_url, entries = result
            self._completer = completer
            self._base_url = base_url
            self._entries = entries

        self._io.submit(work, on_done)

    # -- menu ------------------------------------------------------------------

    def menu_dispatch_table(self) -> dict[str, Callable[[], None]]:
        """Map ``logo_menu_specs()`` action strings to controller methods."""
        return {
            "checkForUpdates:": self.check_for_updates,
            "installSpottyBunny:": self.install_spotty_bunny,
            "quitSpottyBunny:": self.quit_spotty_bunny,
            "uninstallSpottyBunny:": self.uninstall_spotty_bunny,
            "upgradeSpottyBunny:": self.upgrade_spotty_bunny,
        }

    def current_menu_specs(self) -> tuple[tuple[str, str], ...]:
        return logo_menu_specs(installed=self._agent_installed, outdated=self._outdated)

    def dispatch_menu_action(self, action: str) -> None:
        handler = self.menu_dispatch_table().get(action)
        if handler is None:
            logger.warning("unknown Spotty Bunny menu action: %s", action)
            return
        handler()

    def check_for_updates(self) -> None:
        self.set_status_text(CHECK_FOR_UPDATES_STATUS)

        def work() -> object:
            return refresh_update_status(force=True)

        def on_done(result: object) -> None:
            if isinstance(result, BaseException):
                self.set_status_text("Could not check for updates.")
                return
            self._update_status = result
            self._outdated = bool(badge_should_show(result, self_stale=False))
            self.set_status_text(summarize_update_check(result, self_stale=False))

        self._io.submit(work, on_done)

    def install_spotty_bunny(self) -> None:
        from app.spotty_bunny_agent_win32 import install_agent

        self.set_status_text(INSTALL_STATUS)
        code = install_agent()
        self._agent_installed = code == 0
        self.quit_spotty_bunny()

    def uninstall_spotty_bunny(self) -> None:
        from app.spotty_bunny_agent_win32 import uninstall_agent

        uninstall_agent()
        self._agent_installed = False
        self.quit_spotty_bunny()

    def upgrade_spotty_bunny(self) -> None:
        from app.spotty_bunny_agent_win32 import upgrade_agent

        self.set_status_text(UPGRADE_STATUS)
        upgrade_agent()
        self.quit_spotty_bunny()

    def quit_spotty_bunny(self) -> None:
        self.request_quit()

    # -- tap health ------------------------------------------------------------

    def check_event_tap_health(self) -> None:
        """Defensively reinstall the chord hook on every health-check tick.

        Unlike macOS's ``CGEventTap`` (queryable via ``CGEventTapIsEnabled``),
        ``WH_KEYBOARD_LL`` exposes no "is this hook still active" query --
        Windows silently drops a hook whose callback runs too slowly
        (``LowLevelHooksTimeout``), with no notification. Reinstalling
        unconditionally, rather than trying to detect staleness first, is
        the only recovery available without extra polling machinery.
        """
        self._reinstall_hook()

    def _reinstall_hook(self) -> None:
        if self._hook is not None:
            try:
                self._hook.uninstall()
            except OSError:
                pass
            self._hook = None
        try:
            self._hook = install_chord_hook(
                self._chord,
                on_chord=lambda: self.post_app_message(WM_APP_TOGGLE, 0, 0),
                left_vk=self._left_vk if self._left_vk is not None else VK_LCONTROL,
                right_vk=self._right_vk if self._right_vk is not None else VK_RCONTROL,
            )
        except OSError:
            logger.exception("could not reinstall the keyboard hook")

    # -- posting messages to self (overridden with the real HWND at runtime) ---

    def post_app_message(self, message: int, wparam: int, lparam: int) -> None:
        """Deliver *message* back to this controller's own message loop.

        Overridden by :func:`run_spotty_bunny_win32_app` to
        ``win32gui.PostMessage`` against the real overlay HWND; the default
        here (direct dispatch) is what tests use via ``ImmediateIo``.
        """
        self.handle_app_message(message, wparam, lparam)

    def handle_app_message(self, message: int, wparam: int, lparam: int) -> None:
        if message == WM_APP_TOGGLE:
            self.toggle()
        elif message == WM_APP_RESOLVE_READY:
            self.handle_resolve_ready(wparam)
        elif message == WM_APP_COMPLETIONS_READY:
            self.handle_completions_ready(wparam)

    def _default_set_field_text(self, text: str) -> None:
        self._field_text = text


def run_spotty_bunny_win32_app() -> int:
    """Build the tray icon + overlay, install the chord hook, and run.

    Blocks until the process is asked to quit (tray menu "Quit", or the
    console Ctrl+C handler when running in the foreground).
    """
    import win32api  # pyright: ignore[reportMissingModuleSource]
    import win32con  # pyright: ignore[reportMissingModuleSource]
    import win32gui  # pyright: ignore[reportMissingModuleSource]

    controller = SpottyBunnyWin32Controller()
    hotkey_choice = load_spotty_bunny_hotkey()
    controller._left_vk, controller._right_vk = resolve_win32_chord_vks(hotkey_choice)

    hwnd = _create_overlay_window(controller, win32gui=win32gui, win32con=win32con)
    controller.hwnd = hwnd
    controller.post_app_message = lambda message, wparam, lparam: win32gui.PostMessage(
        hwnd, message, wparam, lparam
    )
    controller.request_quit = win32gui.PostQuitMessage

    icon_handle = make_spotty_bunny_icon_win32(16)
    controller.icon_handle = icon_handle
    win32gui.Shell_NotifyIcon(
        win32gui.NIM_ADD,
        (
            hwnd,
            TRAY_ICON_ID,
            win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP,
            WM_APP_TRAY,
            icon_handle,
            "Spotty Bunny",
        ),
    )

    controller._reinstall_hook()
    if controller._hook is None:
        raise SpottyBunnyHookError("could not listen for the hotkey chord")

    win32gui.SetTimer(
        hwnd, TIMER_ID_HEALTH, int(TAP_HEALTH_CHECK_INTERVAL_S * 1000), None
    )
    win32gui.SetTimer(hwnd, TIMER_ID_UPDATE, UPDATE_CHECK_INTERVAL_MS, None)

    unregister_quit_handler = install_console_quit_handler(
        win32api.GetCurrentThreadId()
    )
    try:
        pump_hook_messages()
    finally:
        unregister_quit_handler()
        if controller._hook is not None:
            controller._hook.uninstall()
        win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (hwnd, TRAY_ICON_ID))
        win32gui.DestroyIcon(icon_handle)
        win32gui.DestroyWindow(hwnd)
    return 0


def _create_overlay_window(
    controller: SpottyBunnyWin32Controller, *, win32gui, win32con
) -> int:
    """Create the borderless overlay window and its child controls.

    Kept in one function since none of it is meaningfully unit-testable off
    real Windows (no interactive desktop in CI) -- see the module docstring.
    """
    class_atom = _register_overlay_class(
        controller, win32gui=win32gui, win32con=win32con
    )
    hwnd = win32gui.CreateWindowEx(
        win32con.WS_EX_TOPMOST | win32con.WS_EX_TOOLWINDOW,
        class_atom,
        "Spotty Bunny",
        win32con.WS_POPUP,
        0,
        0,
        420,
        56,
        0,
        0,
        win32gui.GetModuleHandle(None),
        None,
    )
    edit_hwnd = win32gui.CreateWindowEx(
        0,
        "EDIT",
        "",
        win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.ES_AUTOHSCROLL,
        8,
        8,
        404,
        24,
        hwnd,
        0,
        win32gui.GetModuleHandle(None),
        None,
    )
    status_hwnd = win32gui.CreateWindowEx(
        0,
        "STATIC",
        "",
        win32con.WS_CHILD,
        8,
        36,
        404,
        16,
        hwnd,
        0,
        win32gui.GetModuleHandle(None),
        None,
    )
    controller.get_field_text = lambda: win32gui.GetWindowText(edit_hwnd)
    controller.set_field_text = lambda text: win32gui.SetWindowText(edit_hwnd, text)
    controller.set_status_text = lambda text: (
        win32gui.SetWindowText(status_hwnd, text),
        win32gui.ShowWindow(
            status_hwnd, win32con.SW_SHOW if text else win32con.SW_HIDE
        ),
    )
    _subclass_edit_control(edit_hwnd, controller, win32gui=win32gui, win32con=win32con)
    return hwnd


def _subclass_edit_control(
    edit_hwnd: int, controller: SpottyBunnyWin32Controller, *, win32gui, win32con
) -> None:
    """Intercept Tab/Return/Escape/arrow keys before the Edit control's own
    default handling (which would otherwise consume Tab for focus
    navigation and the arrow keys for cursor movement)."""
    original: dict[str, object] = {}

    def _wndproc(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        if msg == win32con.WM_KEYDOWN and controller.handle_edit_keydown(wparam):
            return 0
        return win32gui.CallWindowProc(original["proc"], hwnd, msg, wparam, lparam)

    original["proc"] = win32gui.SetWindowLong(edit_hwnd, win32con.GWL_WNDPROC, _wndproc)


def _register_overlay_class(
    controller: SpottyBunnyWin32Controller, *, win32gui, win32con
):
    wndproc = _make_overlay_wndproc(controller, win32gui=win32gui, win32con=win32con)
    wnd_class = win32gui.WNDCLASS()
    wnd_class.lpfnWndProc = wndproc
    wnd_class.lpszClassName = OVERLAY_WINDOW_CLASS
    wnd_class.hInstance = win32gui.GetModuleHandle(None)
    return win32gui.RegisterClass(wnd_class)


def _make_overlay_wndproc(
    controller: SpottyBunnyWin32Controller, *, win32gui, win32con
):
    def _wndproc(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        if msg in (WM_APP_TOGGLE, WM_APP_RESOLVE_READY, WM_APP_COMPLETIONS_READY):
            controller.handle_app_message(msg, wparam, lparam)
            return 0
        if msg == WM_APP_TRAY:
            _handle_tray_message(
                controller, lparam, win32gui=win32gui, win32con=win32con
            )
            return 0
        if msg == win32con.WM_TIMER:
            if wparam == TIMER_ID_HEALTH:
                controller.check_event_tap_health()
            elif wparam == TIMER_ID_UPDATE:
                controller.check_for_updates()
            return 0
        if msg == win32con.WM_ACTIVATE and wparam == win32con.WA_INACTIVE:
            if not controller.about_open:
                controller.hide()
            return 0
        if msg == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    return _wndproc


def _handle_tray_message(
    controller: SpottyBunnyWin32Controller, lparam: int, *, win32gui, win32con
) -> None:
    if lparam == win32con.WM_LBUTTONUP:
        controller.show_about()
        return
    if lparam == win32con.WM_RBUTTONUP:
        _show_context_menu(controller, win32gui=win32gui, win32con=win32con)


def _show_context_menu(
    controller: SpottyBunnyWin32Controller, *, win32gui, win32con
) -> None:
    menu = win32gui.CreatePopupMenu()
    specs = controller.current_menu_specs()
    ids_to_actions: dict[int, str] = {}
    for index, (title, action) in enumerate(specs):
        item_id = 1000 + index
        ids_to_actions[item_id] = action
        win32gui.AppendMenu(menu, win32con.MF_STRING, item_id, title)
    pos = win32gui.GetCursorPos()
    win32gui.SetForegroundWindow(controller.hwnd)
    selected = win32gui.TrackPopupMenu(
        menu,
        win32con.TPM_LEFTALIGN | win32con.TPM_RETURNCMD,
        pos[0],
        pos[1],
        0,
        controller.hwnd,
        None,
    )
    win32gui.DestroyMenu(menu)
    action = ids_to_actions.get(selected)
    if action is not None:
        controller.dispatch_menu_action(action)

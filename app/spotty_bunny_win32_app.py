"""Spotty Bunny tray icon + overlay search window (win32).

Windows sibling of ``app/spotty_bunny_app.py``'s ``SpottyBunnyController``.
One thread hosts everything: the tray's message-only window, the overlay
popup window, and the ``WH_KEYBOARD_LL`` chord hook (``app.spotty_bunny_hook_
win32.install_chord_hook``) all live on the thread that calls
:func:`run_spotty_bunny_win32_app`, and ``pump_hook_messages()`` (already in
that module) is the single ``GetMessage``/``DispatchMessage`` loop routing to
whichever HWND owns each message -- there is no second message pump to
coordinate.

The overlay follows the macOS panel's look (``app/spotty_bunny_app.py``): a
rounded blue panel with a black rounded text field, placeholder text, the
bunny logo, a centered status line and a completion list. Geometry and colors
are the constants below, and :func:`overlay_layout` is the single place that
turns "status/list visible" into pixel rectangles. The About panel (``app.
spotty_bunny_about_win32``) stays plain/native.

As much logic as possible lives in plain methods that take/return plain
values (selector mapping, menu dispatch, completion/history/resolve
sequencing) so it can be unit-tested directly, matching
``spotty_bunny_hook_win32.py``'s convention -- only real window/GDI/tray
creation is deferred-imported ``win32*`` glue.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.cli import open_url
from app.client import fetch_key_entries
from app.config import load_spotty_bunny_hotkey, resolve_base_url
from app.spotty_bunny_about_win32 import build_about_window
from app.spotty_bunny_cli import SpottyBunnyHookError
from app.spotty_bunny_complete import (
    CompletionRow,
    apply_completion,
    completion_browse_all,
    completion_navigation_disposition,
    completion_row_after_selector,
    completion_still_current,
    completion_table_should_show,
    completions_for,
    make_spotty_completer,
    should_auto_insert_completion,
)
from app.spotty_bunny_focus_win32 import take_foreground
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
from app.spotty_bunny_icon_win32 import _rgb, make_spotty_bunny_icon_win32
from app.spotty_bunny_io import ThreadIo
from app.spotty_bunny_menu import (
    CHECK_FOR_UPDATES_STATUS,
    INSTALL_STATUS,
    UPGRADE_STATUS,
    logo_menu_specs,
)
from app.spotty_bunny_resolve import lookup_resolved_url, resolve_still_current
from app.spotty_bunny_status import SHORTCUTS_LOAD_FAILED, format_spotty_bunny_status
from app.spotty_bunny_tap_health import (
    TAP_HEALTH_CHECK_INTERVAL_S,
    TAP_STATE_OK,
    SpottyBunnyHealth,
    try_write_spotty_bunny_health,
)
from app.spotty_bunny_update import (
    badge_should_show,
    cache_is_stale,
    read_cached_update_status,
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

OVERLAY_TOP_FRACTION = 0.45
OVERLAY_WINDOW_CLASS = "BunnifySpottyBunnyOverlay"
TRAY_WINDOW_CLASS = "BunnifySpottyBunnyTray"
TRAY_ICON_ID = 1

# Overlay geometry (pixels) and colors, mirroring app/spotty_bunny_app.py.
# GDI's RoundRect takes the corner ellipse's diameter, so the *_RADIUS values
# are twice macOS's corner radii (10 for the panel, 8 for the field).
EDIT_HEIGHT = 30
FIELD_HEIGHT = 56
FIELD_PLACEHOLDER = "Type a shortcut (e.g., gh, c, yt, docs). Tab is your friend :)"
FIELD_RADIUS = 16
FIELD_TEXT_INSET = 12
LOGO_GAP = 8
LOGO_RGB = (0xFF, 0xFF, 0xFF)
LOGO_SIZE = 40
PANEL_FILL_RGB = (0x5C, 0x8C, 0xD6)
PANEL_FRAME_RGB = (0x1A, 0x47, 0x8F)
PANEL_INSET = 10
PANEL_RADIUS = 20
PANEL_WIDTH = 640
PLACEHOLDER_RGB = (0x8C, 0x8C, 0x8C)
ROW_GAP = 8
STATUS_HEIGHT = 24
STATUS_RGB = (0xFF, 0xC2, 0x85)
TABLE_HEIGHT = 140

Rect = tuple[int, int, int, int]

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

_LBN_SELCHANGE = 1  # winuser.h: fired when a LISTBOX's selection changes.
_STN_CLICKED = 0  # winuser.h: a STATIC with SS_NOTIFY was clicked.


class _OverlayTheme:
    """GDI brushes and current geometry shared with the overlay's wndproc.

    The window procedure paints the panel chrome and colors the child
    controls; ``layout`` is updated whenever the status line or list appears
    or disappears so the black field rectangle is painted where the field
    currently is.
    """

    def __init__(self, *, win32gui) -> None:
        self.black_brush = win32gui.CreateSolidBrush(_rgb(0, 0, 0))
        self.fill_brush = win32gui.CreateSolidBrush(_rgb(*PANEL_FILL_RGB))
        self.layout = overlay_layout()
        # Set once the logo control exists; the wndproc matches clicks by it.
        self.logo_hwnd = 0


def _selector_for_vk(vk_code: int) -> str | None:
    """Map an Edit-control keydown to the Cocoa-selector-name strings that
    ``app.spotty_bunny_complete``/``app.spotty_bunny_history`` consume.

    Only the keys those modules understand are mapped here; Return/Escape
    have their own handling in :meth:`SpottyBunnyWin32Controller.handle_edit_
    keydown`, and everything else (character keys, Home/End, Left/Right) is
    left to the Edit control's own default behavior.
    """
    return _VK_SELECTORS.get(vk_code)


@dataclass(frozen=True)
class OverlayLayout:
    """Pixel rectangles ``(x, y, width, height)`` inside the overlay panel."""

    edit: Rect
    field: Rect
    logo: Rect
    panel_height: int
    panel_width: int
    rows: Rect
    status: Rect


class SpottyBunnyWin32Controller:
    """Owns the tray icon, the overlay window, and the chord hook."""

    def __init__(
        self,
        *,
        get_field_text: Callable[[], str] | None = None,
        set_field_text: Callable[[str], None] | None = None,
        set_status_text: Callable[[str], None] | None = None,
        set_completion_rows: Callable[[list[CompletionRow]], None] | None = None,
        set_window_visible: Callable[[bool], None] | None = None,
        io: Any = None,
    ) -> None:
        self._field_text = ""
        self.get_field_text = get_field_text or (lambda: self._field_text)
        self.set_field_text = set_field_text or self._default_set_field_text
        self.set_status_text = set_status_text or (lambda _text: None)
        self.set_completion_rows = set_completion_rows or (lambda _rows: None)
        self.set_completion_index: Callable[[int], None] = lambda _index: None
        self.set_window_visible = set_window_visible or (lambda _visible: None)
        self.set_icon_outdated: Callable[[bool], None] = lambda _outdated: None
        self.set_logo_outdated: Callable[[bool], None] = lambda _outdated: None
        self._io = io if io is not None else ThreadIo()

        self.visible = False
        self.about_open = False
        self.about_opening = False
        self._resolving = False
        self._chord = ChordTracker()
        self._history = HistoryNavigator(load_history_lines())
        self._completer: object | None = None
        self._shortcuts_load_failed = False
        self._base_url = ""
        self._entries: list[object] = []
        self._completion_rows: list[CompletionRow] = []
        self._completion_index = 0
        self._completion_visible = False
        self._completion_prefix = ""
        # Guards handle_field_changed() against reacting to our own
        # set_field_text() calls below (auto-insert, arrow-selection) --
        # mirrors macOS's controlTextDidChange_/_applying_completion.
        self._applying_completion = False
        self._resolve_seq = 0
        self._completion_seq = 0
        self._pending_resolves: dict[int, object] = {}
        self._pending_completions: dict[int, object] = {}
        self._update_status = read_cached_update_status()
        self._outdated = bool(badge_should_show(self._update_status, self_stale=False))
        self._update_check_pending = False
        self._update_check_requeue = False
        self._agent_installed = False
        self._open_url_fn: Callable[[str], None] = open_url
        self._append_history_fn: Callable[[str], None] = append_history_line

        # Real Windows handles, set by run_spotty_bunny_win32_app(); left
        # None here so the pure logic above can be unit-tested without them.
        self.hwnd: int | None = None
        self.tray_hwnd: int | None = None
        self.icon_handle: int | None = None
        self.about_hwnd: int | None = None
        self._hook: InstalledHook | None = None
        self._left_vk: int | None = None
        self._right_vk: int | None = None
        self.request_quit: Callable[[], None] = lambda: None
        self.focus_field: Callable[[], None] = lambda: None
        self.create_about_window: Callable[[], int] = lambda: 0
        self.destroy_about_window: Callable[[int], None] = lambda _hwnd: None

    # -- show/hide/toggle --------------------------------------------------

    def show(self) -> None:
        self.set_field_text("")
        self.set_status_text("")
        # Rebuild rather than reuse: a session-long tray process would
        # otherwise never see queries appended by earlier resolves (the
        # navigator built once in __init__ never learns about them), and a
        # stale field would silently resubmit or get concatenated onto the
        # next typed query.
        self._history = HistoryNavigator(load_history_lines())
        self._shortcuts_load_failed = False
        self._load_completer_async()
        self.visible = True
        self.set_window_visible(True)
        if cache_is_stale(self._update_status.checked_at):
            self._refresh_update_status(force=False, announce=False)
        logger.info("show overlay")

    def hide(self) -> None:
        self._resolve_seq += 1
        self._completion_seq += 1
        self._resolving = False
        self._hide_completions()
        if self.about_open:
            self.hide_about()
        self.visible = False
        self.set_window_visible(False)
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

    # -- About panel ---------------------------------------------------------

    def show_about(self) -> None:
        """Create the real About popup (idempotent while already open).

        ``about_open`` is set only after ``create_about_window()``
        actually returns -- if it raises, the flag must stay False, or
        the overlay's WM_ACTIVATE auto-hide gate would stay suppressed
        and every later tray left-click would be swallowed by the
        already-open guard above, with no About window to show for it.
        """
        if self.about_open:
            return
        # Creating the popup activates it, which deactivates the overlay
        # (WM_ACTIVATE) before about_open can be set. When About was opened
        # from the overlay's own logo, that would hide the overlay it was
        # clicked on, so gate the auto-hide during creation only; about_open
        # itself still flips only after creation succeeds.
        self.about_opening = True
        try:
            self.about_hwnd = self.create_about_window()
        finally:
            self.about_opening = False
        self.about_open = True
        logger.info("show About panel")

    def hide_about(self) -> None:
        """Clear the flags before the fallible destroy, not after.

        A raise from destroy_about_window() must not leave about_open
        stuck True with a hwnd that's gone (or never existed) -- our own
        state staying consistent matters more than guaranteeing the OS
        call itself succeeded.
        """
        hwnd = self.about_hwnd
        self.about_hwnd = None
        self.about_open = False
        if hwnd is not None:
            self.destroy_about_window(hwnd)

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
            if self._shortcuts_load_failed:
                self.set_status_text(SHORTCUTS_LOAD_FAILED)
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
            self._apply_field_text_from_completion(applied)
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
        self.set_completion_index(self._completion_index)
        # Browse-all (empty prefix) keeps the field empty -- _submit_query's
        # empty-field fallback reads _completion_index directly in that
        # case. Otherwise the field must follow the highlight (mirrors
        # macOS's _move_completion), or Return submits whatever was
        # auto-inserted on Tab instead of the row the user just selected.
        if completion_browse_all(self._completion_prefix):
            return
        row = self._completion_rows[self._completion_index]
        self._apply_field_text_from_completion(
            apply_completion(self._completion_prefix, row)
        )

    def _apply_field_text_from_completion(self, text: str) -> None:
        """set_field_text(), without handle_field_changed() invalidating
        the very completion rows this write is applying."""
        self._applying_completion = True
        try:
            self.set_field_text(text)
        finally:
            self._applying_completion = False

    def handle_completion_selected(self, index: int) -> None:
        """A mouse click selected LISTBOX row *index* (LBN_SELCHANGE).

        Clicking a Windows LISTBOX gives it keyboard focus as a side effect
        of the click itself -- without explicitly focusing the field back,
        every subsequent keystroke (including Escape) would go to the
        listbox instead of the subclassed Edit control, leaving the
        overlay with no way to dismiss it from the keyboard.
        """
        if index < 0 or index >= len(self._completion_rows):
            self.focus_field()
            return
        self._completion_index = index
        self.set_completion_index(index)
        if not completion_browse_all(self._completion_prefix):
            row = self._completion_rows[index]
            self._apply_field_text_from_completion(
                apply_completion(self._completion_prefix, row)
            )
        self.focus_field()

    def handle_field_changed(self) -> None:
        """Drop stale completion rows once the field no longer matches any
        of them (EN_CHANGE from the Edit control).

        Without this, arrow-key navigation or Return after further typing
        would keep acting on rows computed for a prefix the user has since
        changed -- see app/spotty_bunny_app.py's controlTextDidChange_,
        which this mirrors.
        """
        if self._applying_completion:
            return
        self.set_status_text("")
        if not self._completion_rows:
            return
        text = self.get_field_text()
        if any(
            apply_completion(self._completion_prefix, row) == text
            for row in self._completion_rows
        ):
            return
        self._hide_completions()

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
                self._shortcuts_load_failed = True
                return
            if not isinstance(result, tuple):
                return
            completer, base_url, entries = result
            self._completer = completer
            self._base_url = base_url
            self._entries = entries
            self._shortcuts_load_failed = False

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
        self._refresh_update_status(force=True, announce=True)

    def _refresh_update_status(self, *, force: bool, announce: bool) -> None:
        """Re-check the PyPI cache in the background.

        ``announce=False`` mirrors macOS's quiet startup/stale-cache
        recheck: the icon badge still updates, but no status text is
        touched (there's nothing user-initiated to report on).

        Only one refresh runs at a time (mirrors macOS's
        ``_update_check_pending``/``_update_check_requeue``,
        app/spotty_bunny_app.py:1086) -- otherwise a quiet background
        refresh started while stale and a user-initiated "Check for
        Updates" can race, and whichever's fetch resolves last silently
        overwrites the other's more recent result.
        """
        if self._update_check_pending:
            if force:
                self._update_check_requeue = True
            return
        self._update_check_pending = True

        def work() -> object:
            return refresh_update_status(force=force)

        def on_done(result: object) -> None:
            self._update_check_pending = False
            requeue = self._update_check_requeue
            self._update_check_requeue = False
            if isinstance(result, BaseException):
                logger.warning("update check failed: %s", result)
                if announce:
                    self.set_status_text("Could not check for updates.")
            else:
                self._update_status = result
                outdated = bool(badge_should_show(result, self_stale=False))
                if outdated != self._outdated:
                    self._outdated = outdated
                    self.set_icon_outdated(outdated)
                if announce:
                    self.set_status_text(
                        summarize_update_check(result, self_stale=False)
                    )
            if requeue:
                self.set_status_text(CHECK_FOR_UPDATES_STATUS)
                self._refresh_update_status(force=True, announce=True)

        self._io.submit(work, on_done)

    def refresh_agent_installed(self) -> None:
        """Sync ``_agent_installed`` with the real Scheduled Task state.

        Called once at startup so the tray menu offers Uninstall/Upgrade
        (not Install) when this process was itself launched by an
        already-registered task -- e.g. at logon.
        """
        from app.spotty_bunny_agent_win32 import is_agent_installed

        self._agent_installed = is_agent_installed()

    def install_spotty_bunny(self) -> None:
        """Install, then quit so the Scheduled Task owns the overlay.

        Only quits on success -- like macOS's ``_install_ready``, a
        failure (missing rights, schtasks unavailable, the overlay never
        coming up, ...) leaves this process running with the failure
        surfaced in the status line, rather than killing the only running
        overlay over a failed install.
        """
        from app.spotty_bunny_agent_win32 import install_agent

        self.set_status_text(INSTALL_STATUS)
        code = install_agent()
        if code != 0:
            logger.warning("install failed (exit code %s)", code)
            self.set_status_text("Install failed. See the log for details.")
            return
        self._agent_installed = True
        self.quit_spotty_bunny()

    def uninstall_spotty_bunny(self) -> None:
        """Remove the Scheduled Task, then quit so it stops running.

        Only quits on success -- unlike macOS's plist unlink (which can't
        meaningfully fail), a real ``schtasks /Delete`` denial leaves the
        task registered, so telling the user it's gone and killing the
        only running overlay would leave it silently relaunched at the
        next logon instead.
        """
        from app.spotty_bunny_agent_win32 import uninstall_agent

        code = uninstall_agent()
        if code != 0:
            logger.warning("uninstall failed (exit code %s)", code)
            self.set_status_text("Uninstall failed. See the log for details.")
            return
        self._agent_installed = False
        self.quit_spotty_bunny()

    def upgrade_spotty_bunny(self) -> None:
        """Upgrade, then quit so the Scheduled Task relaunches the new build."""
        from app.spotty_bunny_agent_win32 import upgrade_agent

        self.set_status_text(UPGRADE_STATUS)
        code = upgrade_agent()
        if code != 0:
            logger.warning("upgrade failed (exit code %s)", code)
            self.set_status_text("Upgrade failed. See the log for details.")
            return
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
        the only recovery available without extra polling machinery. This
        also re-resolves the configured chord (mirroring macOS's
        ``_resolve_configured_chord``), so ``spotty-bunny hotkey <choice>``'s
        "wait for the next health check" hint holds true on Windows too.
        """
        self.resolve_and_set_chord_vks()
        self._reinstall_hook()

    def resolve_and_set_chord_vks(self) -> None:
        """Read the configured hotkey choice into ``_left_vk``/``_right_vk``.

        ``load_spotty_bunny_hotkey()`` raises ``ValueError`` for a
        hand-edited, invalid ``config.toml`` value -- degrade to the
        Control chord (mirroring macOS's ``_resolve_configured_chord``)
        rather than letting that crash the whole process before a tray
        icon ever appears.
        """
        try:
            choice = load_spotty_bunny_hotkey()
        except ValueError:
            logger.warning("invalid spotty_bunny_hotkey config value; using auto")
            choice = "auto"
        self._left_vk, self._right_vk = resolve_win32_chord_vks(choice)

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


def overlay_layout(
    *, rows_visible: bool = False, status_visible: bool = False
) -> OverlayLayout:
    """Lay out the overlay panel, top to bottom: field row, status, list.

    The field row (text field plus the logo at its right edge) is always
    there; the status line and the completion list each add their own height
    only while visible, as on macOS (``PANEL_HEIGHT`` 76 when compact).
    """
    field_width = PANEL_WIDTH - 2 * PANEL_INSET - LOGO_SIZE - LOGO_GAP
    inner_width = PANEL_WIDTH - 2 * PANEL_INSET
    field = (PANEL_INSET, PANEL_INSET, field_width, FIELD_HEIGHT)
    edit = (
        PANEL_INSET + FIELD_TEXT_INSET,
        PANEL_INSET + (FIELD_HEIGHT - EDIT_HEIGHT) // 2,
        field_width - 2 * FIELD_TEXT_INSET,
        EDIT_HEIGHT,
    )
    logo = (
        PANEL_WIDTH - PANEL_INSET - LOGO_SIZE,
        PANEL_INSET + (FIELD_HEIGHT - LOGO_SIZE) // 2,
        LOGO_SIZE,
        LOGO_SIZE,
    )
    bottom = PANEL_INSET + FIELD_HEIGHT
    status = (PANEL_INSET, bottom + ROW_GAP, inner_width, STATUS_HEIGHT)
    if status_visible:
        bottom += ROW_GAP + STATUS_HEIGHT
    rows = (PANEL_INSET, bottom + ROW_GAP, inner_width, TABLE_HEIGHT)
    if rows_visible:
        bottom += ROW_GAP + TABLE_HEIGHT
    return OverlayLayout(
        edit=edit,
        field=field,
        logo=logo,
        panel_height=bottom + PANEL_INSET,
        panel_width=PANEL_WIDTH,
        rows=rows,
        status=status,
    )


def overlay_origin(
    work_area: tuple[int, int, int, int], width: int, height: int
) -> tuple[int, int]:
    """Top-left corner for a *width* x *height* overlay inside *work_area*.

    Mirrors macOS ``SpottyBunnyController._center_panel``: centered
    horizontally, and vertically the panel's origin sits 55% up the free
    height (measured from the bottom), i.e. its top edge is
    ``OVERLAY_TOP_FRACTION`` (45%) of the free height below the top of the
    work area. *work_area* is ``(left, top, right, bottom)`` and excludes the
    taskbar. An overlay larger than the work area is pinned to its top-left.
    """
    left, top, right, bottom = work_area
    x = left + max(0, (right - left - width) // 2)
    y = top + max(0, int((bottom - top - height) * OVERLAY_TOP_FRACTION))
    return x, y


def run_spotty_bunny_win32_app() -> int:
    """Build the tray icon + overlay, install the chord hook, and run.

    Blocks until the process is asked to quit (tray menu "Quit", or the
    console Ctrl+C handler when running in the foreground).
    """
    import win32api  # pyright: ignore[reportMissingModuleSource]
    import win32con  # pyright: ignore[reportMissingModuleSource]
    import win32gui  # pyright: ignore[reportMissingModuleSource]

    controller = SpottyBunnyWin32Controller()
    controller.resolve_and_set_chord_vks()
    controller.refresh_agent_installed()

    hwnd = _create_overlay_window(controller, win32gui=win32gui, win32con=win32con)
    controller.hwnd = hwnd
    controller.post_app_message = lambda message, wparam, lparam: win32gui.PostMessage(
        hwnd, message, wparam, lparam
    )
    controller.request_quit = win32gui.PostQuitMessage
    controller.create_about_window = lambda: build_about_window(
        controller, win32gui=win32gui, win32con=win32con, win32api=win32api
    )
    controller.destroy_about_window = win32gui.DestroyWindow

    icon_state: dict[str, int] = {
        "handle": make_spotty_bunny_icon_win32(16, outdated=controller._outdated)
    }
    controller.icon_handle = icon_state["handle"]
    win32gui.Shell_NotifyIcon(
        win32gui.NIM_ADD,
        (
            hwnd,
            TRAY_ICON_ID,
            win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP,
            WM_APP_TRAY,
            icon_state["handle"],
            "Spotty Bunny",
        ),
    )

    def _set_icon_outdated(outdated: bool) -> None:
        old_handle = icon_state["handle"]
        icon_state["handle"] = make_spotty_bunny_icon_win32(16, outdated=outdated)
        controller.icon_handle = icon_state["handle"]
        controller.set_logo_outdated(outdated)
        win32gui.Shell_NotifyIcon(
            win32gui.NIM_MODIFY,
            (
                hwnd,
                TRAY_ICON_ID,
                win32gui.NIF_ICON,
                WM_APP_TRAY,
                icon_state["handle"],
                "Spotty Bunny",
            ),
        )
        win32gui.DestroyIcon(old_handle)

    controller.set_icon_outdated = _set_icon_outdated

    controller._reinstall_hook()
    if controller._hook is None:
        raise SpottyBunnyHookError("could not listen for the hotkey chord")
    # Record this process's own tap state now: the health file otherwise still
    # holds the previous run's until a chord fires (#534). Hand the write an
    # empty snapshot to build on: by default a write keeps the prior
    # last_chord/last_event, which belong to a process that no longer exists.
    try_write_spotty_bunny_health(
        previous=SpottyBunnyHealth(
            last_chord_at=None,
            last_event_at=None,
            reinstall_failures=0,
            tap=TAP_STATE_OK,
            updated_at=0.0,
        ),
        reinstall_failures=0,
        tap=TAP_STATE_OK,
    )
    _set_window_timer(hwnd, TIMER_ID_HEALTH, int(TAP_HEALTH_CHECK_INTERVAL_S * 1000))
    _set_window_timer(hwnd, TIMER_ID_UPDATE, UPDATE_CHECK_INTERVAL_MS)

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
        win32gui.DestroyIcon(icon_state["handle"])
        win32gui.DestroyWindow(hwnd)
    return 0


def _center_overlay(hwnd: int, *, win32api, win32con, win32gui) -> None:
    """Move *hwnd* to :func:`overlay_origin` on the primary monitor.

    Repeated on every show, because the window's height changes with the
    status line and completion list. Leaves the window where it is if the
    monitor or window geometry cannot be read.
    """
    try:
        monitor = win32api.MonitorFromPoint((0, 0), win32con.MONITOR_DEFAULTTOPRIMARY)
        work_area = win32api.GetMonitorInfo(monitor)["Work"]
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        x, y = overlay_origin(work_area, right - left, bottom - top)
        win32gui.SetWindowPos(
            hwnd,
            win32con.HWND_TOPMOST,
            x,
            y,
            0,
            0,
            win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
        )
    except win32gui.error:
        logger.warning("could not center the overlay; leaving it where it is")


def _create_font(win32gui, *, height: int) -> int:
    """A ClearType Segoe UI font *height* pixels tall (the Windows UI font)."""
    spec = win32gui.LOGFONT()
    spec.lfFaceName = "Segoe UI"
    spec.lfHeight = -height
    spec.lfQuality = 5  # CLEARTYPE_QUALITY
    return win32gui.CreateFontIndirect(spec)


def _create_overlay_window(
    controller: SpottyBunnyWin32Controller, *, win32gui, win32con
) -> int:
    """Create the borderless overlay window and its child controls.

    Kept in one function since none of it is meaningfully unit-testable off
    real Windows (no interactive desktop in CI) -- see the module docstring.
    """
    theme = _OverlayTheme(win32gui=win32gui)
    class_atom = _register_overlay_class(
        controller, theme=theme, win32gui=win32gui, win32con=win32con
    )
    layout = theme.layout
    module = win32gui.GetModuleHandle(None)
    hwnd = win32gui.CreateWindowEx(
        win32con.WS_EX_TOPMOST | win32con.WS_EX_TOOLWINDOW,
        class_atom,
        "Spotty Bunny",
        win32con.WS_POPUP | win32con.WS_CLIPCHILDREN,
        0,
        0,
        layout.panel_width,
        layout.panel_height,
        0,
        0,
        module,
        None,
    )
    edit_hwnd = win32gui.CreateWindowEx(
        0,
        "EDIT",
        "",
        win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.ES_AUTOHSCROLL,
        *layout.edit,
        hwnd,
        0,
        module,
        None,
    )
    logo_hwnd = win32gui.CreateWindowEx(
        0,
        "STATIC",
        "",
        # SS_NOTIFY makes the STATIC report clicks (STN_CLICKED) to its parent,
        # which opens About, like the bunny button on the macOS panel.
        win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.SS_ICON | win32con.SS_NOTIFY,
        *layout.logo,
        hwnd,
        0,
        module,
        None,
    )
    theme.logo_hwnd = logo_hwnd
    status_hwnd = win32gui.CreateWindowEx(
        0,
        "STATIC",
        "",
        win32con.WS_CHILD | win32con.SS_CENTER | win32con.SS_NOPREFIX,
        *layout.status,
        hwnd,
        0,
        module,
        None,
    )
    list_hwnd = win32gui.CreateWindowEx(
        0,
        "LISTBOX",
        "",
        win32con.WS_CHILD
        | win32con.WS_VSCROLL
        | win32con.LBS_NOTIFY
        | win32con.LBS_NOINTEGRALHEIGHT,
        *layout.rows,
        hwnd,
        0,
        module,
        None,
    )
    field_font = _create_font(win32gui, height=22)
    small_font = _create_font(win32gui, height=17)
    win32gui.SendMessage(edit_hwnd, win32con.WM_SETFONT, field_font, True)
    win32gui.SendMessage(status_hwnd, win32con.WM_SETFONT, small_font, True)
    win32gui.SendMessage(list_hwnd, win32con.WM_SETFONT, small_font, True)

    visible_rows = {"rows": False, "status": False}

    def _relayout() -> None:
        """Resize the panel and reposition its children for the visible rows."""
        current = overlay_layout(
            rows_visible=visible_rows["rows"], status_visible=visible_rows["status"]
        )
        theme.layout = current
        left, top, _right, _bottom = win32gui.GetWindowRect(hwnd)
        win32gui.SetWindowPos(
            hwnd,
            0,
            left,
            top,
            current.panel_width,
            current.panel_height,
            win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE,
        )
        win32gui.SetWindowRgn(
            hwnd,
            win32gui.CreateRoundRectRgn(
                0,
                0,
                current.panel_width + 1,
                current.panel_height + 1,
                PANEL_RADIUS,
                PANEL_RADIUS,
            ),
            True,
        )
        win32gui.MoveWindow(edit_hwnd, *current.edit, True)
        win32gui.MoveWindow(logo_hwnd, *current.logo, True)
        win32gui.MoveWindow(status_hwnd, *current.status, True)
        win32gui.MoveWindow(list_hwnd, *current.rows, True)
        win32gui.ShowWindow(
            status_hwnd,
            win32con.SW_SHOW if visible_rows["status"] else win32con.SW_HIDE,
        )
        win32gui.ShowWindow(
            list_hwnd, win32con.SW_SHOW if visible_rows["rows"] else win32con.SW_HIDE
        )
        win32gui.InvalidateRect(hwnd, None, True)

    def _set_logo_outdated(outdated: bool) -> None:
        icon = make_spotty_bunny_icon_win32(
            LOGO_SIZE,
            background_rgb=PANEL_FILL_RGB,
            glyph_rgb=LOGO_RGB,
            outdated=outdated,
        )
        previous = win32gui.SendMessage(
            logo_hwnd, win32con.STM_SETIMAGE, win32con.IMAGE_ICON, icon
        )
        if previous:
            win32gui.DestroyIcon(previous)

    _relayout()
    _set_logo_outdated(controller._outdated)
    controller.set_logo_outdated = _set_logo_outdated
    controller.get_field_text = lambda: win32gui.GetWindowText(edit_hwnd)
    controller.set_field_text = lambda text: _set_edit_text(
        edit_hwnd, text, win32gui=win32gui, win32con=win32con
    )

    def _set_status_text(text: str) -> None:
        win32gui.SetWindowText(status_hwnd, text)
        visible_rows["status"] = bool(text)
        _relayout()

    controller.set_status_text = _set_status_text

    def _set_completion_rows(rows: list[CompletionRow]) -> None:
        win32gui.SendMessage(list_hwnd, win32con.LB_RESETCONTENT, 0, 0)
        for row in rows:
            label = f"{row.insert}  {row.meta}" if row.meta else row.insert
            win32gui.SendMessage(list_hwnd, win32con.LB_ADDSTRING, 0, label)
        if rows:
            win32gui.SendMessage(list_hwnd, win32con.LB_SETCURSEL, 0, 0)
        visible_rows["rows"] = bool(rows)
        _relayout()

    controller.set_completion_rows = _set_completion_rows
    controller.set_completion_index = lambda index: win32gui.SendMessage(
        list_hwnd, win32con.LB_SETCURSEL, index, 0
    )

    def _set_window_visible(visible: bool) -> None:
        if visible:
            import win32api  # pyright: ignore[reportMissingModuleSource]
            import win32process  # pyright: ignore[reportMissingModuleSource]

            _show_overlay_window(
                hwnd,
                edit_hwnd,
                win32api=win32api,
                win32con=win32con,
                win32gui=win32gui,
                win32process=win32process,
            )
        else:
            win32gui.ShowWindow(hwnd, win32con.SW_HIDE)

    controller.set_window_visible = _set_window_visible
    controller.focus_field = lambda: win32gui.SetFocus(edit_hwnd)
    _subclass_edit_control(
        edit_hwnd, controller, font=field_font, win32gui=win32gui, win32con=win32con
    )
    return hwnd


def _draw_placeholder(edit_hwnd: int, font: int, *, win32con, win32gui) -> None:
    """Draw the gray hint text into an empty Edit control.

    ``EM_SETCUEBANNER`` needs common-controls v6, which the Python launcher's
    manifest does not opt in to, so paint it by hand after the Edit control's
    own paint.
    """
    if win32gui.GetWindowTextLength(edit_hwnd):
        return
    hdc = win32gui.GetDC(edit_hwnd)
    try:
        old_font = win32gui.SelectObject(hdc, font)
        win32gui.SetBkMode(hdc, win32con.TRANSPARENT)
        win32gui.SetTextColor(hdc, _rgb(*PLACEHOLDER_RGB))
        win32gui.DrawText(
            hdc,
            FIELD_PLACEHOLDER,
            -1,
            win32gui.GetClientRect(edit_hwnd),
            win32con.DT_LEFT
            | win32con.DT_VCENTER
            | win32con.DT_SINGLELINE
            | win32con.DT_NOPREFIX,
        )
        win32gui.SelectObject(hdc, old_font)
    finally:
        win32gui.ReleaseDC(edit_hwnd, hdc)


def _paint_overlay(hwnd: int, theme: _OverlayTheme, *, win32con, win32gui) -> None:
    """Paint the rounded panel frame and the black rounded field behind the Edit."""
    hdc, paint = win32gui.BeginPaint(hwnd)
    frame_pen = None
    old_pen = None
    old_brush = None
    try:
        _left, _top, right, bottom = win32gui.GetClientRect(hwnd)
        frame_pen = win32gui.CreatePen(win32con.PS_SOLID, 2, _rgb(*PANEL_FRAME_RGB))
        old_pen = win32gui.SelectObject(hdc, frame_pen)
        old_brush = win32gui.SelectObject(hdc, theme.fill_brush)
        win32gui.RoundRect(hdc, 1, 1, right - 1, bottom - 1, PANEL_RADIUS, PANEL_RADIUS)
        field_x, field_y, field_width, field_height = theme.layout.field
        win32gui.SelectObject(hdc, win32gui.GetStockObject(win32con.NULL_PEN))
        win32gui.SelectObject(hdc, theme.black_brush)
        win32gui.RoundRect(
            hdc,
            field_x,
            field_y,
            field_x + field_width + 1,
            field_y + field_height + 1,
            FIELD_RADIUS,
            FIELD_RADIUS,
        )
    finally:
        # Runs on failure too, so a painting error cannot leak the frame pen
        # or leave the DC with our objects selected. Deselect before deleting:
        # GDI will not delete an object that is still selected into a DC.
        try:
            if old_pen is not None:
                win32gui.SelectObject(hdc, old_pen)
            if old_brush is not None:
                win32gui.SelectObject(hdc, old_brush)
            if frame_pen is not None:
                win32gui.DeleteObject(frame_pen)
        finally:
            win32gui.EndPaint(hwnd, paint)


def _subclass_edit_control(
    edit_hwnd: int,
    controller: SpottyBunnyWin32Controller,
    *,
    font: int | None = None,
    win32gui,
    win32con,
) -> None:
    """Intercept Tab/Return/Escape/arrow keys before the Edit control's own
    default handling (which would otherwise consume Tab for focus
    navigation and the arrow keys for cursor movement), and draw the
    placeholder hint when the field is empty."""
    original: dict[str, object] = {}

    def _wndproc(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        if msg == win32con.WM_KEYDOWN and controller.handle_edit_keydown(wparam):
            return 0
        result = win32gui.CallWindowProc(original["proc"], hwnd, msg, wparam, lparam)
        if font is not None and msg == win32con.WM_PAINT:
            _draw_placeholder(hwnd, font, win32con=win32con, win32gui=win32gui)
        return result

    original["proc"] = win32gui.SetWindowLong(edit_hwnd, win32con.GWL_WNDPROC, _wndproc)


def _register_overlay_class(
    controller: SpottyBunnyWin32Controller,
    *,
    theme: _OverlayTheme | None = None,
    win32gui,
    win32con,
):
    wndproc = _make_overlay_wndproc(
        controller, theme=theme, win32gui=win32gui, win32con=win32con
    )
    wnd_class = win32gui.WNDCLASS()
    wnd_class.lpfnWndProc = wndproc
    wnd_class.lpszClassName = OVERLAY_WINDOW_CLASS
    wnd_class.hInstance = win32gui.GetModuleHandle(None)
    # Without a background brush, the margins around the EDIT/STATIC/LISTBOX
    # children (never covered by a child control) are never painted and show
    # whatever was on screen behind the popup.
    wnd_class.hbrBackground = (
        theme.fill_brush if theme is not None else win32con.COLOR_WINDOW + 1
    )
    return win32gui.RegisterClass(wnd_class)


def _make_overlay_wndproc(
    controller: SpottyBunnyWin32Controller,
    *,
    theme: _OverlayTheme | None = None,
    win32gui,
    win32con,
):
    def _wndproc(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        if theme is not None:
            if msg == win32con.WM_PAINT:
                _paint_overlay(hwnd, theme, win32con=win32con, win32gui=win32gui)
                return 0
            if msg in (win32con.WM_CTLCOLOREDIT, win32con.WM_CTLCOLORLISTBOX):
                win32gui.SetTextColor(wparam, _rgb(0xFF, 0xFF, 0xFF))
                win32gui.SetBkColor(wparam, _rgb(0, 0, 0))
                return theme.black_brush
            if msg == win32con.WM_CTLCOLORSTATIC:
                win32gui.SetBkMode(wparam, win32con.TRANSPARENT)
                win32gui.SetTextColor(wparam, _rgb(*STATUS_RGB))
                return theme.fill_brush
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
            if not (controller.about_open or controller.about_opening):
                controller.hide()
            return 0
        if msg == win32con.WM_CONTEXTMENU:
            # A right-click on the bunny logo. The static reports it to its
            # parent as WM_CONTEXTMENU (wparam = the clicked control) once it
            # has SS_NOTIFY; show the same action menu as the tray icon and
            # the macOS logo. Other controls keep the default handling.
            if theme is not None and theme.logo_hwnd and wparam == theme.logo_hwnd:
                _show_context_menu(controller, win32gui=win32gui, win32con=win32con)
                return 0
        if msg == win32con.WM_COMMAND:
            # EN_CHANGE's (0x0300) and LBN_SELCHANGE's (1) notification
            # codes don't overlap, so no need to also check lparam's
            # control HWND against a specific edit/listbox handle here.
            # STN_CLICKED is 0, which other controls could also send, so the
            # logo is identified by its own HWND (lparam). Its other
            # notifications must be swallowed here too: STN_DBLCLK is 1, the
            # same value as LBN_SELCHANGE, and would otherwise be handled
            # below as a completion-list selection.
            notify_code = (wparam >> 16) & 0xFFFF
            if theme is not None and theme.logo_hwnd and lparam == theme.logo_hwnd:
                if notify_code == _STN_CLICKED:
                    controller.show_about()
                return 0
            if notify_code == win32con.EN_CHANGE:
                controller.handle_field_changed()
                return 0
            if notify_code == _LBN_SELCHANGE:
                index = win32gui.SendMessage(lparam, win32con.LB_GETCURSEL, 0, 0)
                controller.handle_completion_selected(index)
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


def _set_edit_text(edit_hwnd: int, text: str, *, win32gui, win32con) -> None:
    """Replace the EDIT control's text and leave the caret at its end.

    ``SetWindowText`` resets an EDIT's caret to position 0, so after Tab
    completion, history navigation or a list selection the user would be left
    at the start of the new text (#541). ``EM_SETSEL`` counts UTF-16 code units.
    """
    win32gui.SetWindowText(edit_hwnd, text)
    # surrogatepass: an EDIT can hold an unpaired surrogate (pasted from a file
    # name, say) and it comes straight back here via history/completion.
    end = len(text.encode("utf-16-le", errors="surrogatepass")) // 2
    win32gui.SendMessage(edit_hwnd, win32con.EM_SETSEL, end, end)
    win32gui.SendMessage(edit_hwnd, win32con.EM_SCROLLCARET, 0, 0)


def _set_window_timer(hwnd: int, timer_id: int, interval_ms: int) -> None:
    """Start a ``WM_TIMER`` timer on *hwnd*.

    pywin32 312 exposes no ``SetTimer`` (``win32gui.SetTimer`` raises
    ``AttributeError``), so call ``user32.SetTimer`` directly. Raises
    ``OSError`` when Windows refuses (for example an invalid *hwnd*).
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SetTimer.argtypes = [
        wintypes.HWND,
        ctypes.c_size_t,
        wintypes.UINT,
        ctypes.c_void_p,
    ]
    user32.SetTimer.restype = ctypes.c_size_t
    if not user32.SetTimer(hwnd, timer_id, interval_ms, None):
        raise ctypes.WinError(ctypes.get_last_error())


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
    try:
        win32gui.SetForegroundWindow(controller.hwnd)
    except win32gui.error:
        # The foreground lock may refuse a background process; the menu still
        # works without it (it just may not dismiss on an outside click).
        logger.warning("SetForegroundWindow refused for the tray menu; continuing")
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


def _show_overlay_window(
    hwnd: int, edit_hwnd: int, *, win32api, win32con, win32gui, win32process
) -> None:
    """Center the overlay, show it, and give its text box focus, best effort."""
    _center_overlay(hwnd, win32api=win32api, win32con=win32con, win32gui=win32gui)
    win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
    take_foreground(
        hwnd, win32api=win32api, win32gui=win32gui, win32process=win32process
    )
    try:
        win32gui.SetFocus(edit_hwnd)
    except win32gui.error:
        logger.warning("SetFocus on the overlay text box failed; continuing")

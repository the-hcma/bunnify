"""Spotty Bunny About panel (win32): native SysLink common control.

Windows sibling of ``app/spotty_bunny_about.py``. Deliberately plain and
native -- a borderless topmost popup with standard system font/colors,
one ``SysLink`` control per paragraph -- rather than a pixel-clone of
macOS's custom rounded chrome, matching ``spotty_bunny_win32_app.py``'s
overlay. No dynamic text measurement (GDI's ``DrawText``/``LM_GETIDEALSIZE``
sizing loop macOS's dynamic panel uses): a fixed-size window is a smaller,
more verifiable surface without a real Windows machine to look at either.
"""

from __future__ import annotations

import ctypes
import html
import logging
import os
from collections.abc import Callable
from typing import TYPE_CHECKING

from app.spotty_bunny_about_info import (
    about_details_text_and_links,
    about_link_spans,
    about_version_text_and_links,
    handle_about_link_click,
    load_about_runtime_info,
    server_skew_message,
)
from app.spotty_bunny_update import read_cached_update_status
from app.version import get_build_info

if TYPE_CHECKING:
    from app.spotty_bunny_win32_app import SpottyBunnyWin32Controller

logger = logging.getLogger(__name__)

ABOUT_COPYRIGHT = "Copyright © 2026 Henrique Andrade (GitHub's thehcma)"
ABOUT_GITHUB_HANDLE = "thehcma"
ABOUT_GITHUB_PROFILE_URL = "https://github.com/thehcma"
ABOUT_SUMMARY_WIN32 = (
    "Search and open your Bunnify shortcuts from anywhere on Windows. "
    "Hold Control and press the other Control key to show this box "
    "(run `spotty-bunny hotkey` to view/change), type a shortcut (Tab "
    "completes, like the CLI), and press Enter to open it in your "
    "browser. Text that is not a shortcut opens a Google search, like "
    "the browser. Esc hides the box."
)
ABOUT_WINDOW_CLASS = "BunnifySpottyBunnyAbout"

ABOUT_WIDTH = 440
ABOUT_PAD = 12
ABOUT_ROW_GAP = 6

_SYSLINK_CLASS = "SysLink"
_ICC_LINK_CLASS = 0x00000800
_NM_CLICK = -2
_NM_RETURN = -3


def to_syslink_markup(text: str, links: tuple[tuple[str, str], ...]) -> str:
    """Return SysLink markup: link spans wrapped in ``<A HREF>``, rest escaped.

    A literal ``&``/``<``/``>`` in a path or URL can't otherwise break
    SysLink's own markup parser -- both the plain-text runs and the link
    text are HTML-escaped; only the URL attribute value is left for
    ``html.escape(..., quote=True)`` to quote-escape separately.
    """
    parts: list[str] = []
    cursor = 0
    for start, length, url in about_link_spans(text, links):
        parts.append(html.escape(text[cursor:start]))
        link_text = text[start : start + length]
        parts.append(
            f'<A HREF="{html.escape(url, quote=True)}">{html.escape(link_text)}</A>'
        )
        cursor = start + length
    parts.append(html.escape(text[cursor:]))
    return "".join(parts)


def build_about_window(
    controller: SpottyBunnyWin32Controller,
    *,
    win32gui,
    win32con,
    win32api,
) -> int:
    """Create, position, and show the About popup. Returns its hwnd."""
    _init_syslink_class()
    class_atom = _register_about_class(controller, win32gui=win32gui, win32con=win32con)

    package_version, commit = get_build_info()
    runtime = load_about_runtime_info()
    status = read_cached_update_status()
    version_text, version_links = about_version_text_and_links(package_version, commit)
    details_text, details_links = about_details_text_and_links(runtime)
    skew_text = server_skew_message(runtime)
    update_text = (
        None
        if not status.outdated or not status.latest
        else f"Update available: {status.latest}"
    )

    row_heights = [24, 54, 20, 20, 72]
    if update_text is not None:
        row_heights.append(20)
    if skew_text is not None:
        row_heights.append(36)
    height = ABOUT_PAD * 2 + sum(row_heights) + ABOUT_ROW_GAP * (len(row_heights) - 1)

    left, top = _anchor_near_cursor(ABOUT_WIDTH, height, win32api=win32api)
    hwnd = win32gui.CreateWindowEx(
        win32con.WS_EX_TOPMOST | win32con.WS_EX_TOOLWINDOW,
        class_atom,
        "About Spotty Bunny",
        win32con.WS_POPUP | win32con.WS_BORDER,
        left,
        top,
        ABOUT_WIDTH,
        height,
        0,
        0,
        win32gui.GetModuleHandle(None),
        None,
    )

    inner_width = ABOUT_WIDTH - 2 * ABOUT_PAD
    y = ABOUT_PAD
    _create_static(
        hwnd, "Spotty Bunny", x=ABOUT_PAD, y=y, width=inner_width, height=24, bold=True
    )
    y += 24 + ABOUT_ROW_GAP
    _create_static(
        hwnd, ABOUT_SUMMARY_WIN32, x=ABOUT_PAD, y=y, width=inner_width, height=54
    )
    y += 54 + ABOUT_ROW_GAP
    _create_syslink(
        hwnd,
        to_syslink_markup(version_text, version_links),
        x=ABOUT_PAD,
        y=y,
        width=inner_width,
        height=20,
        win32gui=win32gui,
        win32con=win32con,
    )
    y += 20 + ABOUT_ROW_GAP
    _create_syslink(
        hwnd,
        to_syslink_markup(
            ABOUT_COPYRIGHT, ((ABOUT_GITHUB_HANDLE, ABOUT_GITHUB_PROFILE_URL),)
        ),
        x=ABOUT_PAD,
        y=y,
        width=inner_width,
        height=20,
        win32gui=win32gui,
        win32con=win32con,
    )
    y += 20 + ABOUT_ROW_GAP
    _create_syslink(
        hwnd,
        to_syslink_markup(details_text, details_links),
        x=ABOUT_PAD,
        y=y,
        width=inner_width,
        height=72,
        win32gui=win32gui,
        win32con=win32con,
    )
    y += 72 + ABOUT_ROW_GAP
    if update_text is not None:
        _create_static(
            hwnd, update_text, x=ABOUT_PAD, y=y, width=inner_width, height=20
        )
        y += 20 + ABOUT_ROW_GAP
    if skew_text is not None:
        _create_static(hwnd, skew_text, x=ABOUT_PAD, y=y, width=inner_width, height=36)

    win32gui.ShowWindow(hwnd, win32con.SW_SHOWNORMAL)
    win32gui.SetForegroundWindow(hwnd)
    win32gui.SetFocus(hwnd)
    return hwnd


def _anchor_near_cursor(width: int, height: int, *, win32api) -> tuple[int, int]:
    """Anchor near the cursor at click time, clamped on-screen.

    Windows has no tray-icon-rect equivalent to ``NSStatusItem``'s frame
    (``Shell_NotifyIcon`` doesn't return one), so this isn't a literal
    port of macOS's ``position_about_panel`` math.
    """
    cursor_x, cursor_y = win32api.GetCursorPos()
    screen_width = win32api.GetSystemMetrics(0)  # SM_CXSCREEN
    screen_height = win32api.GetSystemMetrics(1)  # SM_CYSCREEN
    left = min(max(cursor_x, 0), max(screen_width - width, 0))
    top = min(max(cursor_y, 0), max(screen_height - height, 0))
    return left, top


def _handle_link_click(
    url: str, *, opener: Callable[[str], None] | None = None
) -> None:
    """Open *url* -- a local file via :func:`handle_about_link_click`, or
    otherwise directly via *opener* (default ``os.startfile``, which also
    launches http(s) URLs through the OS's registered handler -- unlike
    AppKit's ``NSTextView``, ``SysLink`` has no built-in browser-open)."""
    launch = opener if opener is not None else os.startfile
    if handle_about_link_click(url, start_file=launch):
        return
    try:
        launch(url)
    except OSError:
        logger.warning("could not open About link: %s", url)


def _url_from_notify(lparam: int) -> str | None:
    """Extract a ``SysLink``'s clicked URL from a ``WM_NOTIFY`` lParam.

    None when *lparam* isn't a link-click notification (``NM_CLICK`` /
    ``NM_RETURN``) -- every other ``WM_NOTIFY`` reuses the same ``NMHDR``
    prefix, so the header is read first to check ``code`` before treating
    the payload as an ``NMLINK``.
    """
    header = ctypes.cast(lparam, ctypes.POINTER(_NMHDR))[0]
    if header.code not in (_NM_CLICK, _NM_RETURN):
        return None
    link = ctypes.cast(lparam, ctypes.POINTER(_NMLINK))[0]
    return link.item.szUrl


def _init_syslink_class() -> None:
    """Register the ``SysLink`` common control class if not already loaded.

    Needed because a raw ``CreateWindowEx("SysLink", ...)`` can fail
    without it -- normally implied by a comctl32-v6 application manifest,
    which a bare pipx-installed script doesn't have.
    """
    icc = _INITCOMMONCONTROLSEX(ctypes.sizeof(_INITCOMMONCONTROLSEX), _ICC_LINK_CLASS)
    ctypes.windll.comctl32.InitCommonControlsEx(ctypes.byref(icc))


def _create_static(
    hwnd: int, text: str, *, x: int, y: int, width: int, height: int, bold: bool = False
) -> int:
    import win32con  # pyright: ignore[reportMissingModuleSource]
    import win32gui  # pyright: ignore[reportMissingModuleSource]

    style = win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.SS_LEFT
    child = win32gui.CreateWindowEx(
        0,
        "STATIC",
        text,
        style,
        x,
        y,
        width,
        height,
        hwnd,
        0,
        win32gui.GetModuleHandle(None),
        None,
    )
    if bold:
        win32gui.SendMessage(
            child, win32con.WM_SETFONT, _bold_title_font(win32gui, win32con), True
        )
    return child


_title_font: int | None = None


def _bold_title_font(win32gui, win32con) -> int:
    """Return a shared bold title font, created once per process.

    Not deleted on About-window teardown -- created at most once per
    process (memoized here, same as :func:`_register_about_class`), not
    once per ``show_about()``, so there's nothing to leak across repeat
    opens.
    """
    global _title_font
    font = _title_font
    if font is None:
        font = win32gui.CreateFont(
            (18, 0, 0, 0, win32con.FW_BOLD, 0, 0, 0, 0, 0, 0, 0, 0, "")
        )
        _title_font = font
    return font


def _create_syslink(
    hwnd: int,
    markup: str,
    *,
    x: int,
    y: int,
    width: int,
    height: int,
    win32gui,
    win32con,
) -> int:
    return win32gui.CreateWindowEx(
        0,
        _SYSLINK_CLASS,
        markup,
        win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.WS_TABSTOP,
        x,
        y,
        width,
        height,
        hwnd,
        0,
        win32gui.GetModuleHandle(None),
        None,
    )


_about_class_registered = False


def _register_about_class(
    controller: SpottyBunnyWin32Controller, *, win32gui, win32con
) -> str:
    """Register the About window class once per process.

    Unlike the overlay's class (registered exactly once, at startup),
    ``build_about_window`` runs on every ``show_about()`` -- registering
    the same class name twice raises, so this is memoized rather than
    caught. The single controller instance never changes across calls,
    so the wndproc closure this registers stays valid for the process's
    whole lifetime.
    """
    global _about_class_registered
    if _about_class_registered:
        return ABOUT_WINDOW_CLASS
    wndproc = _make_about_wndproc(controller, win32gui=win32gui, win32con=win32con)
    wnd_class = win32gui.WNDCLASS()
    wnd_class.lpfnWndProc = wndproc
    wnd_class.lpszClassName = ABOUT_WINDOW_CLASS
    wnd_class.hInstance = win32gui.GetModuleHandle(None)
    win32gui.RegisterClass(wnd_class)
    _about_class_registered = True
    return ABOUT_WINDOW_CLASS


def _make_about_wndproc(controller: SpottyBunnyWin32Controller, *, win32gui, win32con):
    def _wndproc(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        if msg == win32con.WM_NOTIFY:
            url = _url_from_notify(lparam)
            if url is not None:
                _handle_link_click(url)
            return 0
        if msg == win32con.WM_KEYDOWN and wparam == win32con.VK_ESCAPE:
            controller.hide_about()
            return 0
        if msg == win32con.WM_ACTIVATE and wparam == win32con.WA_INACTIVE:
            controller.hide_about()
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    return _wndproc


class _INITCOMMONCONTROLSEX(ctypes.Structure):
    _fields_ = (("dwSize", ctypes.c_uint), ("dwICC", ctypes.c_uint))


class _NMHDR(ctypes.Structure):
    _fields_ = (
        ("hwndFrom", ctypes.c_void_p),
        ("idFrom", ctypes.c_size_t),
        ("code", ctypes.c_int),
    )


class _LITEM(ctypes.Structure):
    _fields_ = (
        ("mask", ctypes.c_uint),
        ("iLink", ctypes.c_int),
        ("state", ctypes.c_uint),
        ("stateMask", ctypes.c_uint),
        ("szID", ctypes.c_wchar * 48),
        ("szUrl", ctypes.c_wchar * 2084),
    )


class _NMLINK(ctypes.Structure):
    _fields_ = (("hdr", _NMHDR), ("item", _LITEM))

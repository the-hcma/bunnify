"""Low-level Windows keyboard hook feeding ChordTracker (win32).

Installs a ``WH_KEYBOARD_LL`` hook, the Windows analogue of the macOS
``CGEventTap`` feed in ``app/spotty_bunny_app.py``'s
``_create_event_tap_callback``. The hook install/chain/uninstall calls go
through ``ctypes`` against ``user32.dll`` — verified against pywin32's own
source that it does **not** expose ``SetWindowsHookEx``, ``CallNextHookEx``,
or ``UnhookWindowsHookEx`` as callable Python functions (those three exist
only inside pythonwin's internal C++ MFC message hook, unrelated to this).
``pywin32`` is still used for what it does expose:
``win32api.GetModuleHandle``, ``win32con.WH_KEYBOARD_LL``, and
``win32gui.PumpMessages`` for the message loop a hook needs on its
installing thread — a hook only fires while that loop runs.

A low-level hook can swallow events if its callback returns non-zero
instead of calling ``CallNextHookEx`` — this module always calls it,
matching the macOS tap's listen-only behavior: Spotty Bunny watches keys,
it never intercepts them.

The event-handling logic (:func:`_handle_hook_event`) takes plain ints and
an injectable ``on_chord``/``record_activity``, so it's fully unit-testable
without ``pywin32`` or ``ctypes.windll``. Only :func:`install_chord_hook`
(and, through the ``ctypes.WinDLL`` handle it hands to :class:`InstalledHook`,
its ``.uninstall()``), :func:`pump_hook_messages`, and
:func:`run_console_listener` touch ``win32api``/``win32con``/``win32gui``/
``ctypes.windll`` — those imports and calls are deferred inside each
function (like ``spotty_bunny_cli.py``'s PyObjC loading) so this module
stays importable on any platform, and are the one part of this file that
can't be exercised outside a real Windows message loop.
"""

from __future__ import annotations

import ctypes
import logging
import time
from collections.abc import Callable, Sequence
from ctypes import wintypes

from app.spotty_bunny_hotkey import ChordTracker
from app.spotty_bunny_hotkey_win32 import (
    VK_LCONTROL,
    VK_RCONTROL,
    apply_win32_key_event,
)
from app.spotty_bunny_tap_health import TAP_STATE_OK, try_write_spotty_bunny_health

logger = logging.getLogger(__name__)

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012

_KEY_DOWN_MESSAGES = frozenset({WM_KEYDOWN, WM_SYSKEYDOWN})
_KEY_UP_MESSAGES = frozenset({WM_KEYUP, WM_SYSKEYUP})


class KBDLLHOOKSTRUCT(ctypes.Structure):
    """winuser.h's ``KBDLLHOOKSTRUCT`` — what a ``WH_KEYBOARD_LL`` lParam points to."""

    _fields_ = (
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        # ULONG_PTR: pointer-sized: ctypes.wintypes has no alias for it.
        ("dwExtraInfo", ctypes.c_size_t),
    )


def _handle_hook_event(
    tracker: ChordTracker,
    *,
    n_code: int,
    w_param: int,
    l_param: Sequence[int],
    on_chord: Callable[[], None],
    left_vk: int = VK_LCONTROL,
    right_vk: int = VK_RCONTROL,
    record_activity: Callable[[], None] | None = None,
) -> None:
    """Apply one raw hook callback invocation to *tracker*.

    ``l_param`` is a sequence whose ``[0]`` is the virtual-key code (the
    real callback in :func:`install_chord_hook` passes a decoded
    :class:`KBDLLHOOKSTRUCT`'s field values; tests pass a plain tuple). A
    negative *n_code* means "don't process this event", per the Windows
    hook contract.

    *on_chord* and *record_activity* run only when the chord actually
    completes — matching ``spotty_bunny_app.py``'s macOS
    ``_create_event_tap_callback``/``_record_tap_activity``, never on every
    Control keystroke. Ctrl is used constantly elsewhere (copy/paste/undo),
    and this callback runs on the OS hook thread, which Windows silently
    unhooks if it's too slow (``LowLevelHooksTimeout``, default 300 ms) —
    so it must stay cheap on every event that isn't a chord completion.
    """
    if n_code < 0:
        return
    if w_param not in _KEY_DOWN_MESSAGES and w_param not in _KEY_UP_MESSAGES:
        return
    vk_code = l_param[0]
    if vk_code not in (left_vk, right_vk):
        return
    key_down = w_param in _KEY_DOWN_MESSAGES
    fired = apply_win32_key_event(
        tracker,
        vk_code=vk_code,
        key_down=key_down,
        left_vk=left_vk,
        right_vk=right_vk,
    )
    if not fired:
        return
    logger.info("chord complete (vk_code=%s)", vk_code)
    if record_activity is not None:
        record_activity()
    on_chord()


def _record_hook_activity() -> None:
    now = time.time()
    try_write_spotty_bunny_health(
        last_chord_at=now, last_event_at=now, tap=TAP_STATE_OK
    )


class InstalledHook:
    """A live ``WH_KEYBOARD_LL`` hook. Keeps its ctypes callback alive.

    ``ctypes`` doesn't hold a reference to a ``WINFUNCTYPE`` instance on
    Windows' behalf — if it were only a local variable inside
    :func:`install_chord_hook`, it would be garbage-collected once that
    function returns, leaving Windows calling into freed memory the next
    time a Control key moves. Holding it here for as long as the caller
    holds this object avoids that.
    """

    def __init__(self, handle: int, callback: object, user32: ctypes.WinDLL) -> None:
        self.handle = handle
        self._callback = callback
        self._user32 = user32

    def uninstall(self) -> None:
        self._user32.UnhookWindowsHookEx(self.handle)


def install_chord_hook(
    tracker: ChordTracker,
    *,
    on_chord: Callable[[], None],
    left_vk: int = VK_LCONTROL,
    right_vk: int = VK_RCONTROL,
) -> InstalledHook:
    """Install the low-level keyboard hook and return its handle.

    Requires ``pywin32`` (optional extra ``windows``); raises ``ImportError``
    otherwise. Call :func:`pump_hook_messages` afterwards to run the message
    loop the hook needs, and ``.uninstall()`` on the returned handle when
    done.
    """
    import win32api  # pyright: ignore[reportMissingModuleSource]
    import win32con  # pyright: ignore[reportMissingModuleSource]

    # use_last_error=True so a failed SetWindowsHookExW's GetLastError() is
    # captured correctly by ctypes.get_last_error() below — ctypes.windll's
    # convenience objects don't do this reliably.
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    hook_proc_type = ctypes.WINFUNCTYPE(
        ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
    )
    user32.SetWindowsHookExW.restype = wintypes.HHOOK
    user32.SetWindowsHookExW.argtypes = (
        ctypes.c_int,
        hook_proc_type,
        wintypes.HINSTANCE,
        wintypes.DWORD,
    )
    user32.CallNextHookEx.restype = ctypes.c_ssize_t
    user32.CallNextHookEx.argtypes = (
        wintypes.HHOOK,
        ctypes.c_int,
        wintypes.WPARAM,
        wintypes.LPARAM,
    )
    user32.UnhookWindowsHookEx.restype = wintypes.BOOL
    user32.UnhookWindowsHookEx.argtypes = (wintypes.HHOOK,)

    def _handler(n_code: int, w_param: int, l_param: int) -> int:
        if n_code >= 0:
            kbd = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            kbd_fields = (
                kbd.vkCode,
                kbd.scanCode,
                kbd.flags,
                kbd.time,
                kbd.dwExtraInfo,
            )
            _handle_hook_event(
                tracker,
                n_code=n_code,
                w_param=w_param,
                l_param=kbd_fields,
                on_chord=on_chord,
                left_vk=left_vk,
                right_vk=right_vk,
                record_activity=_record_hook_activity,
            )
        # `handle` is resolved from the enclosing scope at call time, by
        # which point install_chord_hook has already returned it below —
        # Windows can't invoke this callback before SetWindowsHookExW does.
        return user32.CallNextHookEx(handle, n_code, w_param, l_param)

    callback = hook_proc_type(_handler)
    handle = user32.SetWindowsHookExW(
        win32con.WH_KEYBOARD_LL, callback, win32api.GetModuleHandle(None), 0
    )
    if not handle:
        raise OSError(
            ctypes.get_last_error(), "SetWindowsHookExW(WH_KEYBOARD_LL) failed"
        )
    return InstalledHook(handle, callback, user32)


def pump_hook_messages() -> None:
    """Run the Windows message loop a low-level hook needs. Blocks."""
    import win32gui  # pyright: ignore[reportMissingModuleSource]

    win32gui.PumpMessages()


def run_console_listener() -> None:
    """Manual smoke test: print to stdout on each chord, run until Ctrl+C.

    Not wired into the ``spotty-bunny`` CLI yet (the tray/overlay UI,
    https://github.com/the-hcma/bunnify/issues/426, owns that). Run
    directly with ``python -m app.spotty_bunny_hook_win32`` on Windows to
    confirm the hook fires before that UI lands.

    ``win32gui.PumpMessages()`` blocks inside ``GetMessage`` until a
    ``WM_QUIT`` is posted to this thread's message queue. Ctrl+C in a
    console is a *console control event*, not a window message — Python's
    SIGINT handler never runs while the thread is parked in that call, so
    nothing would ever post ``WM_QUIT`` and Ctrl+C would appear to do
    nothing. ``SetConsoleCtrlHandler`` runs its callback on a separate OS
    thread specifically so it can interrupt a blocked thread like this one;
    the handler posts ``WM_QUIT`` to this thread by id, letting
    ``pump_hook_messages()`` return and the ``finally`` below actually run.
    """
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    main_thread_id = kernel32.GetCurrentThreadId()

    ctrl_handler_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
    kernel32.SetConsoleCtrlHandler.restype = wintypes.BOOL
    kernel32.SetConsoleCtrlHandler.argtypes = (ctrl_handler_type, wintypes.BOOL)

    def _on_console_ctrl(_event: int) -> bool:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.PostThreadMessageW.restype = wintypes.BOOL
        user32.PostThreadMessageW.argtypes = (
            wintypes.DWORD,
            ctypes.c_uint,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )
        user32.PostThreadMessageW(main_thread_id, WM_QUIT, 0, 0)
        return True

    ctrl_handler = ctrl_handler_type(_on_console_ctrl)
    kernel32.SetConsoleCtrlHandler(ctrl_handler, True)

    tracker = ChordTracker()
    hook = install_chord_hook(tracker, on_chord=lambda: print("chord!", flush=True))
    print("Listening for the dual-Control chord. Ctrl+C to exit.")
    try:
        pump_hook_messages()
    finally:
        kernel32.SetConsoleCtrlHandler(ctrl_handler, False)
        hook.uninstall()


if __name__ == "__main__":
    run_console_listener()

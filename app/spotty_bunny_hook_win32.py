"""Low-level Windows keyboard hook feeding ChordTracker (win32).

Installs a ``WH_KEYBOARD_LL`` hook via ``pywin32``, the Windows analogue of
the macOS ``CGEventTap`` feed in ``app/spotty_bunny_app.py``'s
``_create_event_tap_callback``. A low-level hook can swallow events if its
callback returns non-zero instead of calling ``CallNextHookEx`` — this
module always calls it, matching the macOS tap's listen-only behavior:
Spotty Bunny watches keys, it never intercepts them.

Requires a Windows message loop on the installing thread
(:func:`pump_hook_messages`), so a hook only fires while that loop runs.

The event-handling logic (:func:`_handle_hook_event`) takes plain ints and
an injectable ``on_chord``/``record_activity``, so it's fully unit-testable
without ``pywin32``. Only :func:`install_chord_hook`,
:func:`pump_hook_messages`, and :func:`run_console_listener` touch
``win32api``/``win32con``/``win32gui`` — those imports are deferred inside
each function (like ``spotty_bunny_cli.py``'s PyObjC loading) so this
module stays importable on any platform, and are the one part of this file
that can't be exercised outside a real Windows message loop.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence

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

_KEY_DOWN_MESSAGES = frozenset({WM_KEYDOWN, WM_SYSKEYDOWN})
_KEY_UP_MESSAGES = frozenset({WM_KEYUP, WM_SYSKEYUP})


def _handle_hook_event(
    tracker: ChordTracker,
    *,
    n_code: int,
    w_param: int,
    l_param: Sequence[int],
    on_chord: Callable[[], None],
    left_vk: int = VK_LCONTROL,
    right_vk: int = VK_RCONTROL,
    record_activity: Callable[[bool], None] | None = None,
) -> None:
    """Apply one raw hook callback invocation to *tracker*.

    ``l_param`` is the ``pywin32``-decoded ``KBDLLHOOKSTRUCT`` tuple
    ``(vkCode, scanCode, flags, time, dwExtraInfo)`` — only ``[0]`` (the
    virtual-key code) is used. A negative *n_code* means "don't process
    this event", per the Windows hook contract.
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
    if record_activity is not None:
        record_activity(fired)
    if fired:
        logger.info("chord complete (vk_code=%s)", vk_code)
        on_chord()


def _record_hook_activity(*, chord: bool) -> None:
    now = time.time()
    try_write_spotty_bunny_health(
        last_chord_at=now if chord else None,
        last_event_at=now,
        tap=TAP_STATE_OK,
    )


def install_chord_hook(
    tracker: ChordTracker,
    *,
    on_chord: Callable[[], None],
    left_vk: int = VK_LCONTROL,
    right_vk: int = VK_RCONTROL,
) -> object:
    """Install the low-level keyboard hook and return its handle.

    Requires ``pywin32`` (optional extra ``windows``); raises ``ImportError``
    otherwise. Call :func:`pump_hook_messages` afterwards to run the message
    loop the hook needs, and ``win32api.UnhookWindowsHookEx(handle)`` when
    done.
    """
    # types-pywin32 (dev-only stub package) resolves these for pyright on any
    # platform; the real pywin32 source only installs on win32 (windows extra).
    import win32api  # pyright: ignore[reportMissingModuleSource]
    import win32con  # pyright: ignore[reportMissingModuleSource]

    def _handler(n_code: int, w_param: int, l_param: Sequence[int]) -> int:
        _handle_hook_event(
            tracker,
            n_code=n_code,
            w_param=w_param,
            l_param=l_param,
            on_chord=on_chord,
            left_vk=left_vk,
            right_vk=right_vk,
            record_activity=lambda fired: _record_hook_activity(chord=fired),
        )
        # `handle` is resolved from the enclosing scope at call time, by
        # which point install_chord_hook has already returned it below —
        # Windows can't invoke this callback before SetWindowsHookEx does.
        return win32api.CallNextHookEx(handle, n_code, w_param, l_param)

    handle = win32api.SetWindowsHookEx(
        win32con.WH_KEYBOARD_LL,
        _handler,
        win32api.GetModuleHandle(None),
        0,
    )
    if handle is None:
        raise OSError("SetWindowsHookEx(WH_KEYBOARD_LL) returned NULL")
    return handle


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
    """
    import win32api  # pyright: ignore[reportMissingModuleSource]

    tracker = ChordTracker()
    handle = install_chord_hook(tracker, on_chord=lambda: print("chord!", flush=True))
    print("Listening for the dual-Control chord. Ctrl+C to exit.")
    try:
        pump_hook_messages()
    finally:
        win32api.UnhookWindowsHookEx(handle)


if __name__ == "__main__":
    run_console_listener()

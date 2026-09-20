"""Foreground-lock handling shared by Spotty Bunny's Windows windows.

Both the search overlay (``app.spotty_bunny_win32_app``) and the About popup
(``app.spotty_bunny_about_win32``) need to come to the front when the user
triggers them, and both hit the same restriction: Windows refuses
``SetForegroundWindow`` from a process that is not already in the foreground,
and pywin32 then raises ``pywintypes.error (0, ...)``. One helper keeps the
workaround and the "never raise" contract in a single place.

``win32*`` modules are passed in (and imported by the callers, deferred), so
this module stays importable on any platform and is testable with fakes.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def take_foreground(hwnd: int, *, win32api, win32gui, win32process) -> None:
    """Ask Windows to make *hwnd* the foreground window without ever raising.

    A background process is normally refused (``SetForegroundWindow`` raises
    ``pywintypes.error (0, ...)``). Attaching to the current foreground
    window's input queue for the duration of the call is the standard way
    around that foreground lock. Any refusal is logged, not propagated, so
    the window still appears.
    """
    this_thread = win32api.GetCurrentThreadId()
    try:
        foreground = win32gui.GetForegroundWindow()
        foreground_thread = (
            win32process.GetWindowThreadProcessId(foreground)[0] if foreground else 0
        )
    except win32gui.error:
        # The foreground window can close between the two calls; pywin32 then
        # raises the same (0, ...) error shape as a refused SetForegroundWindow.
        logger.warning("could not resolve the foreground window; continuing")
        foreground_thread = 0
    attached = False
    if foreground_thread and foreground_thread != this_thread:
        try:
            win32process.AttachThreadInput(this_thread, foreground_thread, True)
            attached = True
        except win32gui.error:
            logger.warning("could not attach to the foreground thread; continuing")
    try:
        win32gui.SetForegroundWindow(hwnd)
    except win32gui.error:
        logger.warning("SetForegroundWindow refused; continuing without focus grab")
    finally:
        if attached:
            try:
                win32process.AttachThreadInput(this_thread, foreground_thread, False)
            except win32gui.error:
                logger.warning("could not detach from the foreground thread")

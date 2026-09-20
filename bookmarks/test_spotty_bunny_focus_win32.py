from __future__ import annotations

from unittest.mock import MagicMock

from django.test import SimpleTestCase

from app.spotty_bunny_focus_win32 import take_foreground


class _FakeGuiError(Exception):
    """Stand-in for ``win32gui.error`` (``pywintypes.error``)."""


def _modules(
    *, foreground: int = 100, foreground_tid: int = 555, this_tid: int = 1
) -> tuple[MagicMock, MagicMock, MagicMock]:
    """``(win32gui, win32api, win32process)`` fakes; the foreground window is
    owned by thread 555 and this process runs on thread 1."""
    win32gui = MagicMock()
    win32gui.error = _FakeGuiError
    win32gui.GetForegroundWindow = MagicMock(return_value=foreground)
    win32api = MagicMock()
    win32api.GetCurrentThreadId = MagicMock(return_value=this_tid)
    win32process = MagicMock()
    win32process.GetWindowThreadProcessId = MagicMock(
        return_value=(foreground_tid, 4242)
    )
    return win32gui, win32api, win32process


def _take(win32gui, win32api, win32process, hwnd: int = 10) -> None:
    take_foreground(
        hwnd, win32api=win32api, win32gui=win32gui, win32process=win32process
    )


class TakeForegroundTests(SimpleTestCase):
    def test_asks_for_the_requested_window(self) -> None:
        win32gui, win32api, win32process = _modules()
        _take(win32gui, win32api, win32process, hwnd=77)
        win32gui.SetForegroundWindow.assert_called_once_with(77)

    def test_attaches_to_the_foreground_thread_around_the_call(self) -> None:
        win32gui, win32api, win32process = _modules()
        order: list[str] = []
        win32process.AttachThreadInput = MagicMock(
            side_effect=lambda _a, _b, attach: order.append(f"attach={attach}")
        )
        win32gui.SetForegroundWindow = MagicMock(
            side_effect=lambda _h: order.append("foreground")
        )
        _take(win32gui, win32api, win32process)
        self.assertEqual(order, ["attach=True", "foreground", "attach=False"])
        win32process.AttachThreadInput.assert_any_call(1, 555, True)
        win32process.AttachThreadInput.assert_any_call(1, 555, False)

    def test_a_refused_foreground_call_does_not_raise_and_still_detaches(self) -> None:
        win32gui, win32api, win32process = _modules()
        win32gui.SetForegroundWindow = MagicMock(
            side_effect=_FakeGuiError(0, "SetForegroundWindow", "")
        )
        with self.assertLogs("app.spotty_bunny_focus_win32", level="WARNING"):
            _take(win32gui, win32api, win32process)
        win32process.AttachThreadInput.assert_called_with(1, 555, False)

    def test_no_attach_when_nothing_has_the_foreground(self) -> None:
        win32gui, win32api, win32process = _modules(foreground=0)
        _take(win32gui, win32api, win32process)
        win32process.AttachThreadInput.assert_not_called()
        win32gui.SetForegroundWindow.assert_called_once_with(10)

    def test_no_attach_when_the_foreground_is_this_thread(self) -> None:
        win32gui, win32api, win32process = _modules(foreground_tid=1, this_tid=1)
        _take(win32gui, win32api, win32process)
        win32process.AttachThreadInput.assert_not_called()

    def test_a_failed_attach_still_tries_the_foreground_call(self) -> None:
        win32gui, win32api, win32process = _modules()
        win32process.AttachThreadInput = MagicMock(
            side_effect=_FakeGuiError(5, "AttachThreadInput", "")
        )
        _take(win32gui, win32api, win32process)
        win32gui.SetForegroundWindow.assert_called_once_with(10)
        # Never attached, so there is nothing to detach.
        self.assertEqual(win32process.AttachThreadInput.call_count, 1)

    def test_a_failed_detach_does_not_raise(self) -> None:
        win32gui, win32api, win32process = _modules()

        def attach_thread_input(_this_thread, _foreground_thread, attach):
            if not attach:
                raise _FakeGuiError(5, "AttachThreadInput", "")

        win32process.AttachThreadInput = MagicMock(side_effect=attach_thread_input)
        _take(win32gui, win32api, win32process)
        win32gui.SetForegroundWindow.assert_called_once_with(10)

    def test_a_foreground_window_that_vanishes_is_not_fatal(self) -> None:
        win32gui, win32api, win32process = _modules()
        win32process.GetWindowThreadProcessId = MagicMock(
            side_effect=_FakeGuiError(0, "GetWindowThreadProcessId", "")
        )
        _take(win32gui, win32api, win32process)
        win32process.AttachThreadInput.assert_not_called()
        win32gui.SetForegroundWindow.assert_called_once_with(10)

    def test_a_failing_foreground_query_is_not_fatal(self) -> None:
        win32gui, win32api, win32process = _modules()
        win32gui.GetForegroundWindow = MagicMock(
            side_effect=_FakeGuiError(0, "GetForegroundWindow", "")
        )
        _take(win32gui, win32api, win32process)
        win32process.AttachThreadInput.assert_not_called()
        win32gui.SetForegroundWindow.assert_called_once_with(10)

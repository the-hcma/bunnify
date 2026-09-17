from __future__ import annotations

import ctypes
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from app.spotty_bunny_hook_win32 import (
    KBDLLHOOKSTRUCT,
    WM_KEYDOWN,
    WM_KEYUP,
    WM_SYSKEYDOWN,
    WM_SYSKEYUP,
    InstalledHook,
    _handle_hook_event,
    install_chord_hook,
)
from app.spotty_bunny_hotkey import ChordTracker
from app.spotty_bunny_hotkey_win32 import VK_LCONTROL, VK_RCONTROL

_UNRELATED_MESSAGE = 0x0201  # WM_LBUTTONDOWN


class HandleHookEventTests(SimpleTestCase):
    def test_chord_fires_on_matching_keydown(self) -> None:
        tracker = ChordTracker()
        on_chord = MagicMock()
        _handle_hook_event(
            tracker,
            n_code=0,
            w_param=WM_KEYDOWN,
            l_param=(VK_LCONTROL, 0, 0, 0, 0),
            on_chord=on_chord,
        )
        on_chord.assert_not_called()
        _handle_hook_event(
            tracker,
            n_code=0,
            w_param=WM_KEYDOWN,
            l_param=(VK_RCONTROL, 0, 0, 0, 0),
            on_chord=on_chord,
        )
        on_chord.assert_called_once()

    def test_negative_n_code_is_ignored(self) -> None:
        tracker = ChordTracker()
        on_chord = MagicMock()
        _handle_hook_event(
            tracker,
            n_code=-1,
            w_param=WM_KEYDOWN,
            l_param=(VK_LCONTROL, 0, 0, 0, 0),
            on_chord=on_chord,
        )
        self.assertFalse(tracker.held_left)
        on_chord.assert_not_called()

    def test_non_key_message_is_ignored(self) -> None:
        tracker = ChordTracker()
        _handle_hook_event(
            tracker,
            n_code=0,
            w_param=_UNRELATED_MESSAGE,
            l_param=(VK_LCONTROL, 0, 0, 0, 0),
            on_chord=MagicMock(),
        )
        self.assertFalse(tracker.held_left)

    def test_unrelated_vk_code_is_ignored(self) -> None:
        tracker = ChordTracker()
        _handle_hook_event(
            tracker,
            n_code=0,
            w_param=WM_KEYDOWN,
            l_param=(0x41, 0, 0, 0, 0),  # 'A'
            on_chord=MagicMock(),
        )
        self.assertFalse(tracker.held_left)

    def test_keyup_releases_held_state(self) -> None:
        tracker = ChordTracker()
        on_chord = MagicMock()
        _handle_hook_event(
            tracker,
            n_code=0,
            w_param=WM_KEYDOWN,
            l_param=(VK_LCONTROL, 0, 0, 0, 0),
            on_chord=on_chord,
        )
        _handle_hook_event(
            tracker,
            n_code=0,
            w_param=WM_KEYUP,
            l_param=(VK_LCONTROL, 0, 0, 0, 0),
            on_chord=on_chord,
        )
        self.assertFalse(tracker.held_left)

    def test_syskeydown_syskeyup_are_treated_as_keydown_keyup(self) -> None:
        tracker = ChordTracker()
        on_chord = MagicMock()
        _handle_hook_event(
            tracker,
            n_code=0,
            w_param=WM_SYSKEYDOWN,
            l_param=(VK_LCONTROL, 0, 0, 0, 0),
            on_chord=on_chord,
        )
        self.assertTrue(tracker.held_left)
        _handle_hook_event(
            tracker,
            n_code=0,
            w_param=WM_SYSKEYUP,
            l_param=(VK_LCONTROL, 0, 0, 0, 0),
            on_chord=on_chord,
        )
        self.assertFalse(tracker.held_left)

    def test_record_activity_called_only_on_chord_fire(self) -> None:
        tracker = ChordTracker()
        record_activity = MagicMock()
        _handle_hook_event(
            tracker,
            n_code=0,
            w_param=WM_KEYDOWN,
            l_param=(VK_LCONTROL, 0, 0, 0, 0),
            on_chord=MagicMock(),
            record_activity=record_activity,
        )
        record_activity.assert_not_called()
        _handle_hook_event(
            tracker,
            n_code=0,
            w_param=WM_KEYDOWN,
            l_param=(VK_RCONTROL, 0, 0, 0, 0),
            on_chord=MagicMock(),
            record_activity=record_activity,
        )
        record_activity.assert_called_once_with()


def _make_fake_win32_modules() -> tuple[ModuleType, ModuleType]:
    win32api = ModuleType("win32api")
    win32api.GetModuleHandle = MagicMock(return_value=0)
    win32con = ModuleType("win32con")
    win32con.WH_KEYBOARD_LL = 13
    return win32api, win32con


def _identity_winfunctype(_restype, *_argtypes):
    """Stand in for ctypes.WINFUNCTYPE(...): returns *fn* unwrapped.

    ctypes.WINFUNCTYPE only exists on Windows, so install_chord_hook can't
    run end to end off Windows. This fake keeps install_chord_hook's own
    argument-wiring logic executing normally (real ctypes.WinDLL is faked
    too, below) while sidestepping the one factory call that's genuinely
    platform-locked, so everything else in the function — including the
    real ctypes.cast/KBDLLHOOKSTRUCT pointer decoding — still runs as
    written.
    """

    def _decorator(fn):
        return fn

    return _decorator


class InstallChordHookTests(SimpleTestCase):
    def test_install_calls_set_windows_hook_ex_with_keyboard_ll_and_module_handle(
        self,
    ) -> None:
        win32api, win32con = _make_fake_win32_modules()
        win32api.GetModuleHandle = MagicMock(return_value=0xABCD)
        fake_user32 = MagicMock()
        fake_user32.SetWindowsHookExW = MagicMock(return_value=999)
        tracker = ChordTracker()
        with (
            patch.dict(sys.modules, {"win32api": win32api, "win32con": win32con}),
            patch("ctypes.WinDLL", return_value=fake_user32, create=True),
            patch("ctypes.WINFUNCTYPE", _identity_winfunctype, create=True),
        ):
            hook = install_chord_hook(tracker, on_chord=MagicMock())
        self.assertIsInstance(hook, InstalledHook)
        self.assertEqual(hook.handle, 999)
        fake_user32.SetWindowsHookExW.assert_called_once()
        args = fake_user32.SetWindowsHookExW.call_args.args
        self.assertEqual(args[0], win32con.WH_KEYBOARD_LL)
        self.assertEqual(args[2], 0xABCD)

    def test_zero_handle_raises(self) -> None:
        win32api, win32con = _make_fake_win32_modules()
        fake_user32 = MagicMock()
        fake_user32.SetWindowsHookExW = MagicMock(return_value=0)
        tracker = ChordTracker()
        with (
            patch.dict(sys.modules, {"win32api": win32api, "win32con": win32con}),
            patch("ctypes.WinDLL", return_value=fake_user32, create=True),
            patch("ctypes.WINFUNCTYPE", _identity_winfunctype, create=True),
            patch("ctypes.get_last_error", return_value=5, create=True),
        ):
            with self.assertRaises(OSError):
                install_chord_hook(tracker, on_chord=MagicMock())

    def test_uninstall_calls_unhook_windows_hook_ex_via_ctypes(self) -> None:
        fake_user32 = MagicMock()
        InstalledHook(999, object(), fake_user32).uninstall()
        fake_user32.UnhookWindowsHookEx.assert_called_once_with(999)

    def test_handler_decodes_real_kbdllhookstruct_pointer_and_dispatches(self) -> None:
        """Exercises install_chord_hook's real ctypes.cast/pointer decoding.

        KBDLLHOOKSTRUCT, ctypes.cast, and ctypes.POINTER are ordinary
        ctypes — not Windows-only — so a genuine struct built here and
        addressed with ctypes.addressof() proves the handler's pointer
        decoding is correct without needing an actual Windows hook thread.
        Also asserts the handler *returns* CallNextHookEx's chained result
        (never a value of its own) — a WH_KEYBOARD_LL callback that returns
        non-zero swallows the key system-wide, so this is the one contract
        that actually matters on real Windows.
        """
        win32api, win32con = _make_fake_win32_modules()
        fake_user32 = MagicMock()
        fake_user32.SetWindowsHookExW = MagicMock(return_value=999)
        # A distinguishable, non-zero/non-default value: proves the handler
        # returns exactly what CallNextHookEx returned, not 0 or 1 of its own.
        fake_user32.CallNextHookEx = MagicMock(return_value=7)
        tracker = ChordTracker()
        on_chord = MagicMock()
        health_dir = TemporaryDirectory()
        self.addCleanup(health_dir.cleanup)
        with (
            patch.dict(sys.modules, {"win32api": win32api, "win32con": win32con}),
            patch("ctypes.WinDLL", return_value=fake_user32, create=True),
            patch("ctypes.WINFUNCTYPE", _identity_winfunctype, create=True),
            patch(
                "app.spotty_bunny_tap_health.data_dir",
                return_value=Path(health_dir.name),
            ),
        ):
            install_chord_hook(tracker, on_chord=on_chord)
            handler = fake_user32.SetWindowsHookExW.call_args.args[1]

            # A negative n_code ("don't process this event") must still
            # chain to CallNextHookEx and leave a fresh tracker untouched.
            unprocessed = KBDLLHOOKSTRUCT(
                vkCode=VK_LCONTROL, scanCode=0, flags=0, time=0
            )
            self.assertEqual(handler(-1, WM_KEYDOWN, ctypes.addressof(unprocessed)), 7)
            self.assertFalse(tracker.held_left)

            left = KBDLLHOOKSTRUCT(vkCode=VK_LCONTROL, scanCode=0, flags=0, time=0)
            self.assertEqual(handler(0, WM_KEYDOWN, ctypes.addressof(left)), 7)
            on_chord.assert_not_called()

            right = KBDLLHOOKSTRUCT(vkCode=VK_RCONTROL, scanCode=0, flags=0, time=0)
            self.assertEqual(handler(0, WM_KEYDOWN, ctypes.addressof(right)), 7)
            on_chord.assert_called_once()

        self.assertEqual(fake_user32.CallNextHookEx.call_count, 3)
        health_file = Path(health_dir.name) / ".spotty-bunny-health"
        self.assertIn("tap: ok", health_file.read_text(encoding="utf-8"))

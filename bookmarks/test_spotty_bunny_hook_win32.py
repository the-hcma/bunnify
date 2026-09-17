from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from app.spotty_bunny_hook_win32 import (
    WM_KEYDOWN,
    WM_KEYUP,
    WM_SYSKEYDOWN,
    WM_SYSKEYUP,
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

    def test_record_activity_called_with_fired_flag(self) -> None:
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
        record_activity.assert_called_once_with(False)
        record_activity.reset_mock()
        _handle_hook_event(
            tracker,
            n_code=0,
            w_param=WM_KEYDOWN,
            l_param=(VK_RCONTROL, 0, 0, 0, 0),
            on_chord=MagicMock(),
            record_activity=record_activity,
        )
        record_activity.assert_called_once_with(True)


def _make_fake_win32_modules() -> tuple[ModuleType, ModuleType]:
    win32api = ModuleType("win32api")
    win32api.SetWindowsHookEx = MagicMock(return_value=12345)
    win32api.CallNextHookEx = MagicMock(return_value=0)
    win32api.GetModuleHandle = MagicMock(return_value=0)
    win32api.UnhookWindowsHookEx = MagicMock()
    win32con = ModuleType("win32con")
    win32con.WH_KEYBOARD_LL = 13
    return win32api, win32con


class InstallChordHookTests(SimpleTestCase):
    def test_install_registers_hook_and_returns_handle(self) -> None:
        win32api, win32con = _make_fake_win32_modules()
        tracker = ChordTracker()
        with patch.dict(sys.modules, {"win32api": win32api, "win32con": win32con}):
            handle = install_chord_hook(tracker, on_chord=MagicMock())
        self.assertEqual(handle, 12345)
        win32api.SetWindowsHookEx.assert_called_once()
        args = win32api.SetWindowsHookEx.call_args.args
        self.assertEqual(args[0], win32con.WH_KEYBOARD_LL)

    def test_installed_handler_dispatches_to_chord_logic_and_chains(self) -> None:
        win32api, win32con = _make_fake_win32_modules()
        tracker = ChordTracker()
        on_chord = MagicMock()
        with patch.dict(sys.modules, {"win32api": win32api, "win32con": win32con}):
            install_chord_hook(tracker, on_chord=on_chord)
            handler = win32api.SetWindowsHookEx.call_args.args[1]
            handler(0, WM_KEYDOWN, (VK_LCONTROL, 0, 0, 0, 0))
            on_chord.assert_not_called()
            handler(0, WM_KEYDOWN, (VK_RCONTROL, 0, 0, 0, 0))
            on_chord.assert_called_once()
            self.assertEqual(win32api.CallNextHookEx.call_count, 2)

    def test_null_handle_raises(self) -> None:
        win32api, win32con = _make_fake_win32_modules()
        win32api.SetWindowsHookEx = MagicMock(return_value=None)
        tracker = ChordTracker()
        with patch.dict(sys.modules, {"win32api": win32api, "win32con": win32con}):
            with self.assertRaises(OSError):
                install_chord_hook(tracker, on_chord=MagicMock())

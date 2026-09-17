from __future__ import annotations

from django.test import SimpleTestCase

from app.spotty_bunny_hotkey import ChordTracker
from app.spotty_bunny_hotkey_win32 import (
    VK_LCONTROL,
    VK_RCONTROL,
    apply_win32_key_event,
)


class ApplyWin32KeyEventTests(SimpleTestCase):
    def test_hold_left_then_tap_right_fires(self) -> None:
        tracker = ChordTracker()
        self.assertFalse(
            apply_win32_key_event(tracker, vk_code=VK_LCONTROL, key_down=True)
        )
        self.assertTrue(
            apply_win32_key_event(tracker, vk_code=VK_RCONTROL, key_down=True)
        )

    def test_hold_right_then_tap_left_fires(self) -> None:
        tracker = ChordTracker()
        self.assertFalse(
            apply_win32_key_event(tracker, vk_code=VK_RCONTROL, key_down=True)
        )
        self.assertTrue(
            apply_win32_key_event(tracker, vk_code=VK_LCONTROL, key_down=True)
        )

    def test_releasing_then_repressing_fires_again(self) -> None:
        tracker = ChordTracker()
        apply_win32_key_event(tracker, vk_code=VK_LCONTROL, key_down=True)
        self.assertTrue(
            apply_win32_key_event(tracker, vk_code=VK_RCONTROL, key_down=True)
        )
        apply_win32_key_event(tracker, vk_code=VK_RCONTROL, key_down=False)
        apply_win32_key_event(tracker, vk_code=VK_LCONTROL, key_down=False)
        apply_win32_key_event(tracker, vk_code=VK_LCONTROL, key_down=True)
        self.assertTrue(
            apply_win32_key_event(tracker, vk_code=VK_RCONTROL, key_down=True)
        )

    def test_auto_repeat_keydown_does_not_refire(self) -> None:
        tracker = ChordTracker()
        apply_win32_key_event(tracker, vk_code=VK_LCONTROL, key_down=True)
        self.assertTrue(
            apply_win32_key_event(tracker, vk_code=VK_RCONTROL, key_down=True)
        )
        # OS auto-repeat resends WM_KEYDOWN while a key is held.
        self.assertFalse(
            apply_win32_key_event(tracker, vk_code=VK_RCONTROL, key_down=True)
        )

    def test_unrelated_key_is_ignored(self) -> None:
        tracker = ChordTracker()
        apply_win32_key_event(tracker, vk_code=VK_LCONTROL, key_down=True)
        self.assertFalse(apply_win32_key_event(tracker, vk_code=0x41, key_down=True))
        self.assertFalse(tracker.held_right)
        self.assertTrue(
            apply_win32_key_event(tracker, vk_code=VK_RCONTROL, key_down=True)
        )

    def test_custom_left_right_vk_codes(self) -> None:
        tracker = ChordTracker()
        left_alt, right_alt = 0xA4, 0xA5
        apply_win32_key_event(
            tracker,
            vk_code=left_alt,
            key_down=True,
            left_vk=left_alt,
            right_vk=right_alt,
        )
        self.assertTrue(
            apply_win32_key_event(
                tracker,
                vk_code=right_alt,
                key_down=True,
                left_vk=left_alt,
                right_vk=right_alt,
            )
        )

from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase

from app.spotty_bunny_keyboard import (
    KeyboardDevice,
    has_external_keyboard,
    list_connected_keyboards,
    parse_ioreg_keyboards,
)

_BUILT_IN_KEYBOARD_BLOCK = """\
+-o AppleHIDTransportHIDDevice  <class AppleHIDTransportHIDDevice, id 0x1>
  | {
  |   "Built-In" = Yes
  |   "Product" = "Apple Internal Keyboard / Trackpad"
  |   "DeviceUsagePairs" = ({"DeviceUsagePage"=1,"DeviceUsage"=6})
  | }
"""

_EXTERNAL_KEYBOARD_BLOCK = """\
+-o AppleUSBHIDKeyboardDriver  <class AppleUSBHIDKeyboardDriver, id 0x2>
  | {
  |   "Product" = "Generic USB Keyboard"
  |   "DeviceUsagePairs" = ({"DeviceUsagePage"=1,"DeviceUsage"=6})
  | }
"""

_NON_KEYBOARD_BLOCK = """\
+-o AppleMultitouchDevice  <class AppleMultitouchDevice, id 0x3>
  | {
  |   "Built-In" = Yes
  |   "Product" = "Apple Internal Trackpad"
  |   "DeviceUsagePairs" = ({"DeviceUsagePage"=13,"DeviceUsage"=5})
  | }
"""

_KEYBOARD_BACKLIGHT_BLOCK = """\
+-o AppleBacklightDriver  <class AppleBacklightDriver, id 0x4>
  | {
  |   "Built-In" = Yes
  |   "Product" = "Keyboard Backlight"
  | }
"""


class ParseIoregKeyboardsTests(SimpleTestCase):
    def test_empty_text_returns_no_devices(self) -> None:
        self.assertEqual(parse_ioreg_keyboards(""), [])

    def test_built_in_only_reports_no_external_keyboard(self) -> None:
        devices = parse_ioreg_keyboards(_BUILT_IN_KEYBOARD_BLOCK)
        self.assertEqual(
            devices,
            [
                KeyboardDevice(
                    product="Apple Internal Keyboard / Trackpad", built_in=True
                )
            ],
        )
        self.assertFalse(has_external_keyboard(devices))

    def test_external_usb_keyboard_without_built_in_field_is_external(self) -> None:
        devices = parse_ioreg_keyboards(_EXTERNAL_KEYBOARD_BLOCK)
        self.assertEqual(
            devices,
            [KeyboardDevice(product="Generic USB Keyboard", built_in=False)],
        )
        self.assertTrue(has_external_keyboard(devices))

    def test_mixed_built_in_and_external_reports_external(self) -> None:
        text = _BUILT_IN_KEYBOARD_BLOCK + _EXTERNAL_KEYBOARD_BLOCK
        devices = parse_ioreg_keyboards(text)
        self.assertEqual(len(devices), 2)
        self.assertTrue(has_external_keyboard(devices))

    def test_non_keyboard_usage_pair_is_ignored(self) -> None:
        self.assertEqual(parse_ioreg_keyboards(_NON_KEYBOARD_BLOCK), [])

    def test_product_name_fallback_matches_keyboard_backlight(self) -> None:
        """No usage pair; "Keyboard" in the product name still counts."""
        devices = parse_ioreg_keyboards(_KEYBOARD_BACKLIGHT_BLOCK)
        self.assertEqual(
            devices,
            [KeyboardDevice(product="Keyboard Backlight", built_in=True)],
        )

    def test_no_root_entries_returns_no_devices(self) -> None:
        self.assertEqual(parse_ioreg_keyboards("garbage, no entries here"), [])


class ListConnectedKeyboardsTests(SimpleTestCase):
    def test_ioreg_failure_returns_empty_list(self) -> None:
        with patch("app.spotty_bunny_keyboard._run_ioreg", return_value=None):
            self.assertEqual(list_connected_keyboards(), [])

    def test_ioreg_success_is_parsed(self) -> None:
        with patch(
            "app.spotty_bunny_keyboard._run_ioreg",
            return_value=_BUILT_IN_KEYBOARD_BLOCK,
        ):
            devices = list_connected_keyboards()
        self.assertEqual(
            devices,
            [
                KeyboardDevice(
                    product="Apple Internal Keyboard / Trackpad", built_in=True
                )
            ],
        )

    def test_has_external_keyboard_defaults_to_live_lookup(self) -> None:
        with patch(
            "app.spotty_bunny_keyboard.list_connected_keyboards",
            return_value=[KeyboardDevice(product="Ext", built_in=False)],
        ):
            self.assertTrue(has_external_keyboard())

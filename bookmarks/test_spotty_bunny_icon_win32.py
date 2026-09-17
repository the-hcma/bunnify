from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from app.spotty_bunny_icon_win32 import (
    _outdated_badge_geometry,
    make_spotty_bunny_icon_win32,
)


class OutdatedBadgeGeometryTests(SimpleTestCase):
    def test_badge_is_inset_from_top_right_corner(self) -> None:
        center_x, center_y, radius = _outdated_badge_geometry(40.0)
        self.assertAlmostEqual(radius, 40.0 * 0.14)
        self.assertAlmostEqual(center_x, 40.0 - radius - 1.0)
        self.assertAlmostEqual(center_y, 40.0 - radius - 1.0)

    def test_badge_scales_with_size(self) -> None:
        small = _outdated_badge_geometry(16.0)
        large = _outdated_badge_geometry(32.0)
        self.assertLess(small[2], large[2])


def _make_fake_win32_modules() -> tuple[ModuleType, ModuleType, ModuleType]:
    win32gui = ModuleType("win32gui")
    win32gui.GetDC = MagicMock(return_value=1)
    win32gui.ReleaseDC = MagicMock()
    win32gui.CreateCompatibleDC = MagicMock(side_effect=[2, 3])
    win32gui.CreateCompatibleBitmap = MagicMock(return_value=4)
    win32gui.CreateBitmap = MagicMock(return_value=5)
    win32gui.SelectObject = MagicMock(return_value=0)
    win32gui.GetSysColor = MagicMock(return_value=0xFFFFFF)
    win32gui.CreateSolidBrush = MagicMock(return_value=6)
    win32gui.FillRect = MagicMock()
    win32gui.DeleteObject = MagicMock()
    win32gui.PatBlt = MagicMock()
    win32gui.DeleteDC = MagicMock()
    win32gui.CreateIconIndirect = MagicMock(return_value=42)
    win32gui.RGB = lambda r, g, b: (r << 16) | (g << 8) | b
    win32gui.RoundRect = MagicMock()
    win32gui.Ellipse = MagicMock()
    win32gui.Polygon = MagicMock()

    win32con = ModuleType("win32con")
    win32con.COLOR_WINDOW = 5
    win32con.BLACKNESS = 0x42
    win32con.TRANSPARENT = 1
    win32con.DT_CENTER = 0x1
    win32con.DT_VCENTER = 0x4
    win32con.DT_SINGLELINE = 0x20

    win32ui = ModuleType("win32ui")
    win32ui.error = RuntimeError

    return win32gui, win32con, win32ui


class MakeSpottyBunnyIconWin32Tests(SimpleTestCase):
    def test_draws_glyph_and_returns_icon_handle(self) -> None:
        win32gui, win32con, win32ui = _make_fake_win32_modules()
        fake_dc = MagicMock()
        win32ui.CreateFont = MagicMock(return_value=object())
        win32ui.CreateDCFromHandle = MagicMock(return_value=fake_dc)
        with patch.dict(
            sys.modules,
            {"win32gui": win32gui, "win32con": win32con, "win32ui": win32ui},
        ):
            icon = make_spotty_bunny_icon_win32(16, outdated=False)
        self.assertEqual(icon, 42)
        fake_dc.SelectObject.assert_called_once()
        fake_dc.DrawText.assert_called_once()
        win32gui.CreateIconIndirect.assert_called_once()
        win32gui.RoundRect.assert_not_called()

    def test_outdated_draws_badge(self) -> None:
        win32gui, win32con, win32ui = _make_fake_win32_modules()
        fake_dc = MagicMock()
        win32ui.CreateFont = MagicMock(return_value=object())
        win32ui.CreateDCFromHandle = MagicMock(return_value=fake_dc)
        with patch.dict(
            sys.modules,
            {"win32gui": win32gui, "win32con": win32con, "win32ui": win32ui},
        ):
            make_spotty_bunny_icon_win32(32, outdated=True)
        win32gui.Ellipse.assert_called_once()
        win32gui.Polygon.assert_called_once()

    def test_font_creation_failure_falls_back_to_plain_shape(self) -> None:
        win32gui, win32con, win32ui = _make_fake_win32_modules()
        win32ui.CreateFont = MagicMock(side_effect=win32ui.error("no font"))
        with patch.dict(
            sys.modules,
            {"win32gui": win32gui, "win32con": win32con, "win32ui": win32ui},
        ):
            icon = make_spotty_bunny_icon_win32(16, outdated=False)
        self.assertEqual(icon, 42)
        win32gui.RoundRect.assert_called_once()

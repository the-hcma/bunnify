from __future__ import annotations

import sys
from types import ModuleType
from unittest import skipUnless
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from app.spotty_bunny_icon_win32 import (
    _outdated_badge_geometry,
    _rgb,
    make_spotty_bunny_icon_win32,
)


class RgbTests(SimpleTestCase):
    def test_packs_a_colorref_in_bgr_order(self) -> None:
        self.assertEqual(_rgb(0xEB, 0x73, 0x1F), 0x1F73EB)

    def test_extremes(self) -> None:
        self.assertEqual(_rgb(0, 0, 0), 0)
        self.assertEqual(_rgb(0xFF, 0xFF, 0xFF), 0xFFFFFF)


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

    def test_does_not_delete_the_borrowed_memory_dc_through_the_wrapper(self) -> None:
        # win32ui.CreateDCFromHandle only wraps mem_dc; DeleteDC() on the
        # wrapper destroys the caller's HDC, so the later CreateCompatibleDC /
        # DeleteDC on it fail with "The handle is invalid".
        win32gui, win32con, win32ui = _make_fake_win32_modules()
        fake_dc = MagicMock()
        win32ui.CreateFont = MagicMock(return_value=object())
        win32ui.CreateDCFromHandle = MagicMock(return_value=fake_dc)
        with patch.dict(
            sys.modules,
            {"win32gui": win32gui, "win32con": win32con, "win32ui": win32ui},
        ):
            make_spotty_bunny_icon_win32(16, outdated=False)
        fake_dc.DeleteDC.assert_not_called()

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


@skipUnless(sys.platform == "win32", "needs the real Win32 GDI")
class RealWin32IconTests(SimpleTestCase):
    """Run the actual GDI calls -- the fakes above cannot see invalid handles."""

    def test_builds_a_real_icon_with_the_emoji_glyph(self) -> None:
        import win32gui  # pyright: ignore[reportMissingModuleSource]

        icon = make_spotty_bunny_icon_win32(16)
        try:
            self.assertTrue(icon)
        finally:
            win32gui.DestroyIcon(icon)

    def test_builds_a_real_outdated_icon(self) -> None:
        import win32gui  # pyright: ignore[reportMissingModuleSource]

        icon = make_spotty_bunny_icon_win32(32, outdated=True)
        try:
            self.assertTrue(icon)
        finally:
            win32gui.DestroyIcon(icon)

    def test_builds_a_real_fallback_icon_when_the_font_is_missing(self) -> None:
        import win32gui  # pyright: ignore[reportMissingModuleSource]
        import win32ui  # pyright: ignore[reportMissingModuleSource]

        with patch.object(win32ui, "CreateFont", side_effect=win32ui.error("no font")):
            icon = make_spotty_bunny_icon_win32(16)
        try:
            self.assertTrue(icon)
        finally:
            win32gui.DestroyIcon(icon)

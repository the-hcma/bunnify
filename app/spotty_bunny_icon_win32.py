"""Spotty Bunny tray icon (GDI drawing; win32).

Mirrors ``app/spotty_bunny_icon.py``'s AppKit drawing (same emoji glyph, same
proportional sizing, same outdated-badge overlay), but GDI has no equivalent
of ``NSAttributedString.drawAtPoint_`` for a Cocoa ``NSImage`` — this draws
the glyph into a memory device context with ``TextOut`` instead and converts
the result to an ``HICON``.

``win32gui``/``win32ui``/``win32con`` imports are deferred inside
:func:`make_spotty_bunny_icon_win32`, matching ``spotty_bunny_hook_win32.py``'s
convention, so this module stays importable on any platform. If the emoji
font can't be resolved (unlikely, but not guaranteed on every Windows image),
falls back to a plain filled shape rather than failing outright -- a legible
tray icon beats a missing one.
"""

from __future__ import annotations

import logging

BUNNIFY_LOGO_EMOJI = "🐰"
EMOJI_FONT_NAME = "Segoe UI Emoji"

logger = logging.getLogger(__name__)


def _outdated_badge_geometry(side: float) -> tuple[float, float, float]:
    """Return ``(center_x, center_y, radius)`` for the outdated-badge circle.

    Same proportions as ``spotty_bunny_icon.py``'s ``_outdated_badge``: a
    small circle inset from the top-right corner.
    """
    radius = side * 0.14
    center = side - radius - 1.0
    return center, center, radius


def make_spotty_bunny_icon_win32(size: int, *, outdated: bool = False) -> int:
    """Return an ``HICON`` handle for the tray, *size*x*size* pixels.

    The caller owns the returned handle and must destroy it (``win32gui
    .DestroyIcon``) once no longer needed (e.g. before replacing it via a
    later ``Shell_NotifyIcon`` update, and on shutdown).
    """
    import win32con  # pyright: ignore[reportMissingModuleSource]
    import win32gui  # pyright: ignore[reportMissingModuleSource]
    import win32ui  # pyright: ignore[reportMissingModuleSource]

    side = int(size)
    screen_dc = win32gui.GetDC(0)
    mem_dc = win32gui.CreateCompatibleDC(screen_dc)
    color_bitmap = win32gui.CreateCompatibleBitmap(screen_dc, side, side)
    mask_bitmap = win32gui.CreateBitmap(side, side, 1, 1, None)
    win32gui.ReleaseDC(0, screen_dc)
    try:
        win32gui.SelectObject(mem_dc, color_bitmap)
        background = win32gui.GetSysColor(win32con.COLOR_WINDOW)
        brush = win32gui.CreateSolidBrush(background)
        win32gui.FillRect(mem_dc, (0, 0, side, side), brush)
        win32gui.DeleteObject(brush)
        _draw_glyph_or_fallback(mem_dc, side, win32con=win32con, win32ui=win32ui)
        if outdated:
            _draw_outdated_badge(mem_dc, side, win32gui=win32gui, win32con=win32con)
        # Compatible with mem_dc, not the already-released screen_dc (a
        # stale/NULL HDC here would make SelectObject silently delete
        # mask_bitmap instead of drawing into it).
        mono_dc = win32gui.CreateCompatibleDC(mem_dc)
        win32gui.SelectObject(mono_dc, mask_bitmap)
        win32gui.PatBlt(mono_dc, 0, 0, side, side, win32con.BLACKNESS)
        win32gui.DeleteDC(mono_dc)
        icon_info = (True, 0, 0, mask_bitmap, color_bitmap)
        return win32gui.CreateIconIndirect(icon_info)
    finally:
        win32gui.DeleteDC(mem_dc)


def _draw_glyph_or_fallback(mem_dc: int, side: int, *, win32con, win32ui) -> None:
    try:
        font = win32ui.CreateFont(
            {
                "name": EMOJI_FONT_NAME,
                "height": int(side * 0.82),
            }
        )
    except win32ui.error:
        logger.warning(
            "could not create %s at size %s; falling back to a plain icon shape",
            EMOJI_FONT_NAME,
            side,
        )
        _draw_fallback_shape(mem_dc, side, win32con=win32con)
        return
    dc = win32ui.CreateDCFromHandle(mem_dc)
    try:
        dc.SelectObject(font)
        dc.SetBkMode(win32con.TRANSPARENT)
        rect = (0, 0, side, side)
        dc.DrawText(
            BUNNIFY_LOGO_EMOJI,
            rect,
            win32con.DT_CENTER | win32con.DT_VCENTER | win32con.DT_SINGLELINE,
        )
    finally:
        dc.DeleteDC()


def _draw_fallback_shape(mem_dc: int, side: int, *, win32con) -> None:
    """A plain filled rounded square -- legible with no font dependency."""
    import win32gui  # pyright: ignore[reportMissingModuleSource]

    inset = max(1, int(side * 0.12))
    brush = win32gui.CreateSolidBrush(win32gui.RGB(0x6B, 0x4C, 0x2A))
    old_brush = win32gui.SelectObject(mem_dc, brush)
    try:
        win32gui.RoundRect(
            mem_dc,
            inset,
            inset,
            side - inset,
            side - inset,
            inset,
            inset,
        )
    finally:
        win32gui.SelectObject(mem_dc, old_brush)
        win32gui.DeleteObject(brush)


def _draw_outdated_badge(mem_dc: int, side: int, *, win32gui, win32con) -> None:
    center_x, center_y, radius = _outdated_badge_geometry(float(side))
    left = int(center_x - radius)
    top = int(center_y - radius)
    right = int(center_x + radius)
    bottom = int(center_y + radius)
    badge_brush = win32gui.CreateSolidBrush(win32gui.RGB(0xEB, 0x73, 0x1F))
    old_brush = win32gui.SelectObject(mem_dc, badge_brush)
    try:
        win32gui.Ellipse(mem_dc, left, top, right, bottom)
    finally:
        win32gui.SelectObject(mem_dc, old_brush)
        win32gui.DeleteObject(badge_brush)
    arrow_half = radius * 0.42
    points = (
        (int(center_x), int(center_y - radius * 0.45)),
        (int(center_x - arrow_half), int(center_y + radius * 0.22)),
        (int(center_x + arrow_half), int(center_y + radius * 0.22)),
    )
    white_brush = win32gui.CreateSolidBrush(win32gui.RGB(0xFF, 0xFF, 0xFF))
    old_brush = win32gui.SelectObject(mem_dc, white_brush)
    try:
        win32gui.Polygon(mem_dc, points)
    finally:
        win32gui.SelectObject(mem_dc, old_brush)
        win32gui.DeleteObject(white_brush)

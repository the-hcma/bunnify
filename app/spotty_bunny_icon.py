"""Spotty Bunny panel icon (AppKit drawing; imported only on macOS)."""

from __future__ import annotations

# pyright: reportMissingImports=false
from Cocoa import (
    NSBezierPath,
    NSColor,
    NSFont,
    NSFontAttributeName,
    NSImage,
    NSMakeRect,
    NSMakeSize,
)
from Foundation import NSAttributedString

BUNNIFY_LOGO_EMOJI = "🐰"


def make_spotty_bunny_icon(size: float, *, outdated: bool = False) -> NSImage:
    """Return the same 🐰 logo as the web UI at *size*×*size* points."""
    side = float(size)
    image = NSImage.alloc().initWithSize_(NSMakeSize(side, side))
    image.lockFocus()
    try:
        NSColor.clearColor().set()
        NSBezierPath.fillRect_(NSMakeRect(0.0, 0.0, side, side))

        font = NSFont.systemFontOfSize_(side * 0.82)
        attributed = NSAttributedString.alloc().initWithString_attributes_(
            BUNNIFY_LOGO_EMOJI,
            {NSFontAttributeName: font},
        )
        bounds = attributed.size()
        origin_x = (side - bounds.width) / 2.0
        origin_y = (side - bounds.height) / 2.0
        attributed.drawAtPoint_((origin_x, origin_y))

        if outdated:
            _outdated_badge(side)
    finally:
        image.unlockFocus()
    image.setSize_(NSMakeSize(side, side))
    return image


def _outdated_badge(side: float) -> None:
    """Draw a small up-arrow badge in the top-right (update available)."""
    radius = side * 0.14
    center_x = side - radius - 1.0
    center_y = side - radius - 1.0
    badge = NSBezierPath.bezierPathWithOvalInRect_(
        NSMakeRect(center_x - radius, center_y - radius, radius * 2.0, radius * 2.0)
    )
    _rgba(0.92, 0.45, 0.12).setFill()
    badge.fill()
    _rgba(1.0, 1.0, 1.0).setFill()
    arrow = NSBezierPath.bezierPath()
    arrow.moveToPoint_((center_x, center_y + radius * 0.45))
    arrow.lineToPoint_((center_x - radius * 0.42, center_y - radius * 0.22))
    arrow.lineToPoint_((center_x + radius * 0.42, center_y - radius * 0.22))
    arrow.closePath()
    arrow.fill()


def _rgba(red: float, green: float, blue: float, alpha: float = 1.0) -> NSColor:
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(red, green, blue, alpha)

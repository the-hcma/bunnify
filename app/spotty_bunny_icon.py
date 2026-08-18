"""Spotty Bunny panel icon (AppKit drawing; imported only on macOS)."""

from __future__ import annotations

# pyright: reportMissingImports=false
from Cocoa import (
    NSBezierPath,
    NSColor,
    NSImage,
    NSMakeRect,
    NSMakeSize,
)


def _rgba(red: float, green: float, blue: float, alpha: float = 1.0) -> NSColor:
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(red, green, blue, alpha)


def _spot(center_x: float, center_y: float, radius: float, color: NSColor) -> None:
    spot = NSBezierPath.bezierPathWithOvalInRect_(
        NSMakeRect(center_x - radius, center_y - radius, radius * 2.0, radius * 2.0)
    )
    color.setFill()
    spot.fill()


def make_spotty_bunny_icon(size: float, *, outdated: bool = False) -> NSImage:
    """Return a spotty bunny face icon at *size*×*size* points."""
    side = float(size)
    image = NSImage.alloc().initWithSize_(NSMakeSize(side, side))
    image.lockFocus()
    try:
        NSColor.clearColor().set()
        NSBezierPath.fillRect_(NSMakeRect(0.0, 0.0, side, side))

        fur = _rgba(0.98, 0.94, 0.96)
        ear_outer = _rgba(0.94, 0.78, 0.84)
        ear_inner = _rgba(1.0, 0.82, 0.88)
        stroke = _rgba(0.42, 0.24, 0.34)
        spot_color = _rgba(0.82, 0.48, 0.58)

        for center_x in (side * 0.34, side * 0.66):
            outer = NSBezierPath.bezierPathWithOvalInRect_(
                NSMakeRect(
                    center_x - side * 0.09,
                    side * 0.46,
                    side * 0.18,
                    side * 0.44,
                )
            )
            ear_outer.setFill()
            outer.fill()
            stroke.set()
            outer.setLineWidth_(1.1)
            outer.stroke()

            inner = NSBezierPath.bezierPathWithOvalInRect_(
                NSMakeRect(
                    center_x - side * 0.05,
                    side * 0.50,
                    side * 0.10,
                    side * 0.28,
                )
            )
            ear_inner.setFill()
            inner.fill()

        face = NSBezierPath.bezierPathWithOvalInRect_(
            NSMakeRect(side * 0.18, side * 0.10, side * 0.64, side * 0.58)
        )
        fur.setFill()
        face.fill()
        stroke.set()
        face.setLineWidth_(1.3)
        face.stroke()

        _spot(side * 0.28, side * 0.52, side * 0.035, spot_color)
        _spot(side * 0.72, side * 0.48, side * 0.03, spot_color)
        _spot(side * 0.58, side * 0.22, side * 0.025, spot_color)

        eye_color = _rgba(0.18, 0.12, 0.16)
        for center_x in (side * 0.40, side * 0.60):
            eye = NSBezierPath.bezierPathWithOvalInRect_(
                NSMakeRect(
                    center_x - side * 0.04,
                    side * 0.34,
                    side * 0.08,
                    side * 0.10,
                )
            )
            eye_color.setFill()
            eye.fill()

        nose = NSBezierPath.bezierPathWithOvalInRect_(
            NSMakeRect(side * 0.46, side * 0.24, side * 0.08, side * 0.06)
        )
        _rgba(0.94, 0.55, 0.64).setFill()
        nose.fill()

        tooth_color = _rgba(0.99, 0.98, 0.97)
        for left in (side * 0.47, side * 0.53):
            tooth = NSBezierPath.bezierPathWithRect_(
                NSMakeRect(left, side * 0.14, side * 0.045, side * 0.07)
            )
            tooth_color.setFill()
            tooth.fill()
            stroke.set()
            tooth.setLineWidth_(0.8)
            tooth.stroke()

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

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


def make_spotty_bunny_icon(size: float) -> NSImage:
    """Return a simple bunny face icon at *size*×*size* points."""
    side = float(size)
    image = NSImage.alloc().initWithSize_(NSMakeSize(side, side))
    image.lockFocus()
    try:
        NSColor.clearColor().set()
        NSBezierPath.fillRect_(NSMakeRect(0.0, 0.0, side, side))

        ear_color = _rgba(0.95, 0.72, 0.78)
        face_color = _rgba(1.0, 0.92, 0.94)
        stroke = _rgba(0.45, 0.28, 0.36)

        for center_x in (side * 0.32, side * 0.68):
            ear = NSBezierPath.bezierPathWithOvalInRect_(
                NSMakeRect(
                    center_x - side * 0.12,
                    side * 0.52,
                    side * 0.24,
                    side * 0.34,
                )
            )
            ear_color.setFill()
            ear.fill()
            stroke.set()
            ear.setLineWidth_(1.2)
            ear.stroke()

        face = NSBezierPath.bezierPathWithOvalInRect_(
            NSMakeRect(side * 0.14, side * 0.08, side * 0.72, side * 0.72)
        )
        face_color.setFill()
        face.fill()
        stroke.set()
        face.setLineWidth_(1.4)
        face.stroke()

        eye_color = _rgba(0.25, 0.18, 0.22)
        for center_x in (side * 0.38, side * 0.62):
            eye = NSBezierPath.bezierPathWithOvalInRect_(
                NSMakeRect(
                    center_x - side * 0.045,
                    side * 0.38,
                    side * 0.09,
                    side * 0.11,
                )
            )
            eye_color.setFill()
            eye.fill()

        nose = NSBezierPath.bezierPathWithOvalInRect_(
            NSMakeRect(side * 0.44, side * 0.28, side * 0.12, side * 0.09)
        )
        _rgba(0.92, 0.55, 0.62).setFill()
        nose.fill()
    finally:
        image.unlockFocus()
    image.setSize_(NSMakeSize(side, side))
    return image

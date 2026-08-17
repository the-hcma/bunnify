"""Spotty Bunny about panel (AppKit; imported only on macOS)."""

from __future__ import annotations

# pyright: reportMissingImports=false
from Cocoa import (
    NSBackingStoreBuffered,
    NSColor,
    NSFloatingWindowLevel,
    NSFont,
    NSMakeRect,
    NSPanel,
    NSTextField,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
)
from Foundation import NSMakeRange, NSMutableAttributedString

from app.version import get_build_info

ABOUT_COPYRIGHT = "Copyright © 2026 thehcma"
ABOUT_LICENSE = "MIT License"
ABOUT_PANEL_HEIGHT = 188.0
ABOUT_PANEL_WIDTH = 320.0
ABOUT_TAGLINE = "Quick shortcut overlay for Bunnify"
SPOTTY_BUNNY_REPO_URL = "https://github.com/the-hcma/bunnify"


def build_about_panel() -> NSPanel:
    """Return a small floating panel with version and project links."""
    panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0.0, 0.0, ABOUT_PANEL_WIDTH, ABOUT_PANEL_HEIGHT),
        NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
        NSBackingStoreBuffered,
        False,
    )
    panel.setLevel_(NSFloatingWindowLevel + 1)
    panel.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces)
    panel.setFloatingPanel_(True)
    panel.setHidesOnDeactivate_(False)
    panel.setBecomesKeyOnlyIfNeeded_(True)
    panel.setReleasedWhenClosed_(False)
    panel.setBackgroundColor_(NSColor.windowBackgroundColor())

    package_version, commit = get_build_info()
    y = ABOUT_PANEL_HEIGHT - 24.0

    title = _label(
        NSMakeRect(16.0, y - 22.0, ABOUT_PANEL_WIDTH - 32.0, 22.0),
        "Spotty Bunny",
        font=NSFont.boldSystemFontOfSize_(16.0),
    )
    panel.contentView().addSubview_(title)
    y -= 30.0

    tagline = _label(
        NSMakeRect(16.0, y - 18.0, ABOUT_PANEL_WIDTH - 32.0, 18.0),
        ABOUT_TAGLINE,
        color=NSColor.secondaryLabelColor(),
    )
    panel.contentView().addSubview_(tagline)
    y -= 24.0

    version_line = _label(
        NSMakeRect(16.0, y - 18.0, ABOUT_PANEL_WIDTH - 32.0, 18.0),
        f"Version {package_version} · commit {commit}",
        color=NSColor.secondaryLabelColor(),
    )
    panel.contentView().addSubview_(version_line)
    y -= 24.0

    copyright_line = _label(
        NSMakeRect(16.0, y - 18.0, ABOUT_PANEL_WIDTH - 32.0, 18.0),
        ABOUT_COPYRIGHT,
    )
    panel.contentView().addSubview_(copyright_line)
    y -= 20.0

    license_line = _label(
        NSMakeRect(16.0, y - 18.0, ABOUT_PANEL_WIDTH - 32.0, 18.0),
        ABOUT_LICENSE,
        color=NSColor.secondaryLabelColor(),
    )
    panel.contentView().addSubview_(license_line)
    y -= 28.0

    link = NSTextField.alloc().initWithFrame_(
        NSMakeRect(16.0, y - 18.0, ABOUT_PANEL_WIDTH - 32.0, 18.0)
    )
    link.setEditable_(False)
    link.setSelectable_(True)
    link.setBezeled_(False)
    link.setDrawsBackground_(False)
    link.setAllowsEditingTextAttributes_(True)
    link.setFont_(NSFont.systemFontOfSize_(13.0))
    repo_text = "github.com/the-hcma/bunnify"
    attributed = NSMutableAttributedString.alloc().initWithString_(repo_text)
    from AppKit import NSLinkAttributeName

    attributed.addAttribute_value_range_(
        NSLinkAttributeName,
        SPOTTY_BUNNY_REPO_URL,
        NSMakeRange(0, len(repo_text)),
    )
    attributed.addAttribute_value_range_(
        "NSColor",
        NSColor.linkColor(),
        NSMakeRange(0, len(repo_text)),
    )
    link.setAttributedStringValue_(attributed)
    panel.contentView().addSubview_(link)
    return panel


def position_about_panel(panel: NSPanel, *, anchor_frame) -> None:
    """Place *panel* just below the logo area on the anchor window."""
    frame = panel.frame()
    frame.origin.x = anchor_frame.origin.x + 8.0
    frame.origin.y = anchor_frame.origin.y - frame.size.height - 8.0
    panel.setFrame_display_(frame, True)


def _label(frame, text: str, *, font=None, color=None) -> NSTextField:
    field = NSTextField.alloc().initWithFrame_(frame)
    field.setEditable_(False)
    field.setSelectable_(False)
    field.setBezeled_(False)
    field.setDrawsBackground_(False)
    field.setStringValue_(text)
    field.setFont_(font or NSFont.systemFontOfSize_(13.0))
    if color is not None:
        field.setTextColor_(color)
    return field

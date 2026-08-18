"""Spotty Bunny about panel (AppKit; imported only on macOS)."""

from __future__ import annotations

import math
from collections.abc import Callable

import objc

# pyright: reportMissingImports=false
from Cocoa import (
    NSBackingStoreBuffered,
    NSColor,
    NSCursor,
    NSFloatingWindowLevel,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSLineBreakByWordWrapping,
    NSLinkAttributeName,
    NSMakeRect,
    NSMakeSize,
    NSPanel,
    NSStringDrawingUsesFontLeading,
    NSStringDrawingUsesLineFragmentOrigin,
    NSTextField,
    NSTrackingActiveAlways,
    NSTrackingArea,
    NSTrackingCursorUpdate,
    NSTrackingInVisibleRect,
    NSTrackingMouseEnteredAndExited,
    NSUnderlineStyleAttributeName,
    NSUnderlineStyleSingle,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
)
from Foundation import NSAttributedString, NSMakeRange, NSMutableAttributedString

from app.spotty_bunny_about_info import (
    about_link_spans,
    handle_about_link_click,
    load_about_runtime_info,
)
from app.spotty_bunny_hotkey import ESCAPE_KEYCODE
from app.spotty_bunny_update import UpdateStatus, read_cached_update_status
from app.version import get_build_info

ABOUT_BORDER_WIDTH = 2.0
ABOUT_CELL_PAD = 8.0
ABOUT_COPYRIGHT = "Copyright © 2026 Henrique Andrade (GitHub's thehcma)"
ABOUT_CORNER_RADIUS = 16.0
ABOUT_FILL_RGB = (0.97, 0.93, 0.84)
ABOUT_FRAME_RGB = (0.42, 0.28, 0.12)
ABOUT_GITHUB_HANDLE = "thehcma"
ABOUT_GITHUB_PROFILE_URL = "https://github.com/thehcma"
ABOUT_INSET = 16.0
ABOUT_LABEL_RGB = (0.16, 0.12, 0.08)
ABOUT_LICENSE = "MIT License"
ABOUT_LICENSE_URL = "https://github.com/the-hcma/bunnify/blob/main/LICENSE"
ABOUT_LINK_RGB = (0.08, 0.28, 0.58)
ABOUT_MUTED_RGB = (0.38, 0.30, 0.22)
ABOUT_PANEL_MAX_WIDTH = 640.0
ABOUT_PANEL_MIN_WIDTH = 320.0
ABOUT_ROW_GAP = 8.0
ABOUT_SUMMARY = (
    "Search and open your Bunnify shortcuts from anywhere on macOS. "
    "Hold one Control and tap the other to show this box, type a shortcut "
    "(Tab completes, like the CLI), and press Return to open it in your browser. "
    "Esc hides the box."
)
ABOUT_WARN_RGB = (0.62, 0.28, 0.08)
SPOTTY_BUNNY_REPO_URL = "https://github.com/the-hcma/bunnify"


class SpottyBunnyAboutPanel(NSPanel):
    """About card that can take key focus so Escape dismisses only this panel."""

    def canBecomeKeyWindow(self) -> bool:
        return True

    def cancelOperation_(self, sender) -> None:
        delegate = self.delegate()
        if delegate is not None:
            delegate.dismissWithEscape_(sender)

    def keyDown_(self, event) -> None:
        if int(event.keyCode()) == ESCAPE_KEYCODE:
            self.cancelOperation_(self)
            return
        objc.super(SpottyBunnyAboutPanel, self).keyDown_(event)

    def keyUp_(self, event) -> None:
        if int(event.keyCode()) == ESCAPE_KEYCODE:
            delegate = self.delegate()
            if delegate is not None:
                delegate.releaseEscape_(self)
            return
        objc.super(SpottyBunnyAboutPanel, self).keyUp_(event)

    def performKeyEquivalent_(self, event) -> bool:
        if int(event.keyCode()) == ESCAPE_KEYCODE:
            self.cancelOperation_(self)
            return True
        return bool(
            objc.super(SpottyBunnyAboutPanel, self).performKeyEquivalent_(event)
        )


def apply_spotty_chrome(
    view,
    *,
    corner_radius: float = ABOUT_CORNER_RADIUS,
    fill_rgb: tuple[float, float, float] = ABOUT_FILL_RGB,
    frame_rgb: tuple[float, float, float] = ABOUT_FRAME_RGB,
) -> None:
    """Paint a rounded fill and frame on *view*."""
    view.setWantsLayer_(True)
    layer = view.layer()
    layer.setCornerRadius_(corner_radius)
    layer.setMasksToBounds_(True)
    layer.setBackgroundColor_(_srgb_color(fill_rgb).CGColor())
    layer.setBorderColor_(_srgb_color(frame_rgb).CGColor())
    layer.setBorderWidth_(ABOUT_BORDER_WIDTH)


def build_about_panel(*, update: UpdateStatus | None = None) -> NSPanel:
    """Return a small floating panel with version and project links."""
    title_font = NSFont.boldSystemFontOfSize_(16.0)
    body_font = NSFont.systemFontOfSize_(13.0)
    package_version, commit = get_build_info()
    runtime = load_about_runtime_info()
    status = update if update is not None else read_cached_update_status()
    version_text = f"Version {package_version} · commit {commit}"
    update_text = (
        None
        if not status.outdated or not status.latest
        else f"Update available: {status.latest}"
    )
    repo_text = "Repository: github.com/the-hcma/bunnify"
    license_text = f"License: {ABOUT_LICENSE}"
    bookmarks_text = f"Bookmarks: {runtime.bookmarks_display}"
    github_text = (
        None if runtime.github_display is None else f"GitHub: {runtime.github_display}"
    )
    inner_cap = ABOUT_PANEL_MAX_WIDTH - 2.0 * ABOUT_INSET
    needed_width = max(
        _measure_text("Spotty Bunny", title_font, max_width=inner_cap)[0],
        _measure_text(ABOUT_COPYRIGHT, body_font, max_width=inner_cap)[0],
        _measure_text(bookmarks_text, body_font, max_width=inner_cap)[0],
        _measure_text(license_text, body_font, max_width=inner_cap)[0],
        _measure_text(repo_text, body_font, max_width=inner_cap)[0],
        _measure_text(runtime.server_display, body_font, max_width=inner_cap)[0],
        _measure_text(version_text, body_font, max_width=inner_cap)[0],
        0.0
        if github_text is None
        else _measure_text(github_text, body_font, max_width=inner_cap)[0],
        0.0
        if update_text is None
        else _measure_text(update_text, body_font, max_width=inner_cap)[0],
    )
    width = min(
        ABOUT_PANEL_MAX_WIDTH,
        max(ABOUT_PANEL_MIN_WIDTH, needed_width + 2.0 * ABOUT_INSET + ABOUT_CELL_PAD),
    )
    inner = width - 2.0 * ABOUT_INSET
    copy_height = max(
        22.0,
        _measure_text(ABOUT_COPYRIGHT, body_font, max_width=inner)[1] + ABOUT_CELL_PAD,
    )
    summary_height = max(
        36.0,
        _measure_text(ABOUT_SUMMARY, body_font, max_width=inner)[1] + ABOUT_CELL_PAD,
    )
    bookmarks_height = max(
        18.0,
        _measure_text(bookmarks_text, body_font, max_width=inner)[1] + ABOUT_CELL_PAD,
    )
    repo_license_height = max(
        36.0,
        _measure_text(f"{repo_text}\n{license_text}", body_font, max_width=inner)[1]
        + ABOUT_CELL_PAD,
    )
    github_height = (
        0.0
        if github_text is None
        else max(
            18.0,
            _measure_text(github_text, body_font, max_width=inner)[1] + ABOUT_CELL_PAD,
        )
    )
    server_height = max(
        18.0,
        _measure_text(runtime.server_display, body_font, max_width=inner)[1]
        + ABOUT_CELL_PAD,
    )
    rows: list[tuple[float, Callable[[float, float], NSTextField]]] = [
        (
            22.0,
            lambda y, h: _label(
                NSMakeRect(ABOUT_INSET, y, inner, h),
                "Spotty Bunny",
                font=title_font,
            ),
        ),
        (
            summary_height,
            lambda y, h: _label(
                NSMakeRect(ABOUT_INSET, y, inner, h),
                ABOUT_SUMMARY,
                wrap=True,
            ),
        ),
        (
            18.0,
            lambda y, h: _label(
                NSMakeRect(ABOUT_INSET, y, inner, h),
                version_text,
                color=_srgb_color(ABOUT_MUTED_RGB),
            ),
        ),
    ]
    if update_text is not None:
        notice = update_text
        rows.append(
            (
                18.0,
                lambda y, h: _label(
                    NSMakeRect(ABOUT_INSET, y, inner, h),
                    notice,
                    color=_srgb_color(ABOUT_WARN_RGB),
                ),
            )
        )
    rows.extend(
        [
            (
                copy_height,
                lambda y, h: _link_field(
                    NSMakeRect(ABOUT_INSET, y, inner, h),
                    ABOUT_COPYRIGHT,
                    ABOUT_GITHUB_HANDLE,
                    ABOUT_GITHUB_PROFILE_URL,
                ),
            ),
            (
                repo_license_height,
                lambda y, h: _multi_link_field(
                    NSMakeRect(ABOUT_INSET, y, inner, h),
                    f"{repo_text}\n{license_text}",
                    (
                        ("github.com/the-hcma/bunnify", SPOTTY_BUNNY_REPO_URL),
                        (ABOUT_LICENSE, ABOUT_LICENSE_URL),
                    ),
                ),
            ),
            (
                bookmarks_height,
                lambda y, h: _link_field(
                    NSMakeRect(ABOUT_INSET, y, inner, h),
                    bookmarks_text,
                    runtime.bookmarks_display,
                    runtime.bookmarks_uri,
                ),
            ),
        ]
    )
    if (
        github_text is not None
        and runtime.github_display is not None
        and runtime.github_url is not None
    ):
        github_label = github_text
        github_link = runtime.github_display
        github_href = runtime.github_url
        rows.append(
            (
                github_height,
                lambda y, h: _link_field(
                    NSMakeRect(ABOUT_INSET, y, inner, h),
                    github_label,
                    github_link,
                    github_href,
                ),
            )
        )
    rows.append(
        (
            server_height,
            lambda y, h: _link_field(
                NSMakeRect(ABOUT_INSET, y, inner, h),
                runtime.server_display,
                runtime.server_url,
                runtime.server_url,
            ),
        )
    )
    gap = ABOUT_ROW_GAP
    height = ABOUT_INSET * 2.0 + sum(row_h for row_h, _ in rows) + gap * (len(rows) - 1)

    panel = SpottyBunnyAboutPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0.0, 0.0, width, height),
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
    panel.setOpaque_(False)
    panel.setBackgroundColor_(NSColor.clearColor())
    panel.setHasShadow_(True)
    apply_spotty_chrome(panel.contentView())

    y = height - ABOUT_INSET
    for row_h, factory in rows:
        y -= row_h
        panel.contentView().addSubview_(factory(y, row_h))
        y -= gap
    return panel


def position_about_panel(panel: NSPanel, *, anchor_frame) -> None:
    """Place *panel* just below the logo (right side of the search window)."""
    frame = panel.frame()
    frame.origin.x = (
        anchor_frame.origin.x + anchor_frame.size.width - frame.size.width - 8.0
    )
    frame.origin.y = anchor_frame.origin.y - frame.size.height - 8.0
    panel.setFrame_display_(frame, True)


class _AboutLinkField(NSTextField):
    """Link label that shows a pointing-hand cursor over the field."""

    def cancelOperation_(self, sender) -> None:
        window = self.window()
        if window is not None:
            window.cancelOperation_(sender)

    def control_textView_doCommandBySelector_(self, _control, _text_view, selector):
        name = selector if isinstance(selector, str) else str(selector)
        if name in {"cancel:", "cancelOperation:"}:
            self.cancelOperation_(self)
            return True
        return False

    def cursorUpdate_(self, _event) -> None:
        NSCursor.pointingHandCursor().set()

    def mouseEntered_(self, _event) -> None:
        NSCursor.pointingHandCursor().set()

    def mouseExited_(self, _event) -> None:
        NSCursor.arrowCursor().set()

    def resetCursorRects(self) -> None:
        objc.super(_AboutLinkField, self).resetCursorRects()
        self.addCursorRect_cursor_(self.bounds(), NSCursor.pointingHandCursor())

    def textView_clickedOnLink_atIndex_(self, _view, link, _index) -> bool:
        return handle_about_link_click(str(link))

    def updateTrackingAreas(self) -> None:
        objc.super(_AboutLinkField, self).updateTrackingAreas()
        for area in tuple(self.trackingAreas() or ()):
            self.removeTrackingArea_(area)
        options = (
            NSTrackingActiveAlways
            | NSTrackingCursorUpdate
            | NSTrackingInVisibleRect
            | NSTrackingMouseEnteredAndExited
        )
        area = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            self.bounds(),
            options,
            self,
            None,
        )
        self.addTrackingArea_(area)

    def viewDidMoveToWindow(self) -> None:
        objc.super(_AboutLinkField, self).viewDidMoveToWindow()
        self.updateTrackingAreas()


def _label(
    frame, text: str, *, font=None, color=None, wrap: bool = False
) -> NSTextField:
    field = NSTextField.alloc().initWithFrame_(frame)
    field.setEditable_(False)
    field.setSelectable_(False)
    field.setBezeled_(False)
    field.setDrawsBackground_(False)
    field.setStringValue_(text)
    field.setFont_(font or NSFont.systemFontOfSize_(13.0))
    field.setTextColor_(color if color is not None else _srgb_color(ABOUT_LABEL_RGB))
    if wrap:
        field.setUsesSingleLineMode_(False)
        field.setLineBreakMode_(NSLineBreakByWordWrapping)
        field.cell().setWraps_(True)
    return field


def _link_field(frame, text: str, link_text: str, url: str) -> NSTextField:
    """Return a selectable wrapping label with *link_text* inside *text* as a URL."""
    field = _AboutLinkField.alloc().initWithFrame_(frame)
    field.setEditable_(False)
    field.setSelectable_(True)
    field.setBezeled_(False)
    field.setDrawsBackground_(False)
    field.setAllowsEditingTextAttributes_(True)
    field.setUsesSingleLineMode_(False)
    field.setLineBreakMode_(NSLineBreakByWordWrapping)
    field.cell().setWraps_(True)
    field.setFont_(NSFont.systemFontOfSize_(13.0))
    attributed = NSMutableAttributedString.alloc().initWithString_(text)
    attributed.addAttribute_value_range_(
        NSForegroundColorAttributeName,
        _srgb_color(ABOUT_LABEL_RGB),
        NSMakeRange(0, len(text)),
    )
    start = text.rfind(link_text)
    if start >= 0:
        span = NSMakeRange(start, len(link_text))
        attributed.addAttribute_value_range_(NSLinkAttributeName, url, span)
        attributed.addAttribute_value_range_(
            NSForegroundColorAttributeName,
            _srgb_color(ABOUT_LINK_RGB),
            span,
        )
        attributed.addAttribute_value_range_(
            NSUnderlineStyleAttributeName,
            NSUnderlineStyleSingle,
            span,
        )
    field.setAttributedStringValue_(attributed)
    field.setDelegate_(field)
    return field


def _measure_text(text: str, font, *, max_width: float) -> tuple[float, float]:
    attributed = NSAttributedString.alloc().initWithString_attributes_(
        text,
        {NSFontAttributeName: font},
    )
    bounds = attributed.boundingRectWithSize_options_(
        NSMakeSize(max_width, 10000.0),
        NSStringDrawingUsesLineFragmentOrigin | NSStringDrawingUsesFontLeading,
    )
    return float(math.ceil(bounds.size.width)), float(math.ceil(bounds.size.height))


def _multi_link_field(
    frame,
    text: str,
    links: tuple[tuple[str, str], ...],
) -> NSTextField:
    """Return a wrapping label with each *(link_text, url)* span as a hyperlink."""
    field = _AboutLinkField.alloc().initWithFrame_(frame)
    field.setEditable_(False)
    field.setSelectable_(True)
    field.setBezeled_(False)
    field.setDrawsBackground_(False)
    field.setAllowsEditingTextAttributes_(True)
    field.setUsesSingleLineMode_(False)
    field.setLineBreakMode_(NSLineBreakByWordWrapping)
    field.cell().setWraps_(True)
    field.setFont_(NSFont.systemFontOfSize_(13.0))
    attributed = NSMutableAttributedString.alloc().initWithString_(text)
    attributed.addAttribute_value_range_(
        NSForegroundColorAttributeName,
        _srgb_color(ABOUT_LABEL_RGB),
        NSMakeRange(0, len(text)),
    )
    for start, length, url in about_link_spans(text, links):
        span = NSMakeRange(start, length)
        attributed.addAttribute_value_range_(NSLinkAttributeName, url, span)
        attributed.addAttribute_value_range_(
            NSForegroundColorAttributeName,
            _srgb_color(ABOUT_LINK_RGB),
            span,
        )
        attributed.addAttribute_value_range_(
            NSUnderlineStyleAttributeName,
            NSUnderlineStyleSingle,
            span,
        )
    field.setAttributedStringValue_(attributed)
    field.setDelegate_(field)
    return field


def _srgb_color(rgb: tuple[float, float, float]):
    red, green, blue = rgb
    return NSColor.colorWithSRGBRed_green_blue_alpha_(red, green, blue, 1.0)

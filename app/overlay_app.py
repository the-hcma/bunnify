# pyright: reportMissingImports=false
"""macOS overlay UI (PyObjC). Imported only after Cocoa/Quartz are available."""

from __future__ import annotations

import sys

import objc
from Cocoa import (
    NSApp,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBackingStoreBuffered,
    NSColor,
    NSFloatingWindowLevel,
    NSFont,
    NSMakeRect,
    NSObject,
    NSPanel,
    NSScreen,
    NSTextField,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowStyleMaskFullSizeContentView,
    NSWindowStyleMaskTitled,
)
from PyObjCTools import AppHelper
from Quartz import (
    CFMachPortCreateRunLoopSource,
    CFRunLoopAddSource,
    CFRunLoopGetCurrent,
    CGEventGetIntegerValueField,
    CGEventMaskBit,
    CGEventSourceKeyState,
    CGEventTapCreate,
    CGEventTapEnable,
    kCFRunLoopCommonModes,
    kCGEventFlagsChanged,
    kCGEventKeyDown,
    kCGEventKeyUp,
    kCGEventSourceStateHIDSystemState,
    kCGEventTapDisabledByTimeout,
    kCGEventTapDisabledByUserInput,
    kCGEventTapOptionListenOnly,
    kCGHeadInsertEventTap,
    kCGHIDEventTap,
    kCGKeyboardEventKeycode,
    kCGSessionEventTap,
)

from app.overlay_cli import OverlayEventTapError
from app.overlay_hotkey import (
    CONTROL_LEFT_KEYCODE,
    CONTROL_RIGHT_KEYCODE,
    ChordTracker,
    apply_hid_snapshot,
)

PANEL_HEIGHT = 80.0
PANEL_WIDTH = 640.0


class OverlayController(NSObject):
    """Owns the floating search panel and toggles it from the Control chord."""

    def control_textView_doCommandBySelector_(self, _control, _text_view, selector):
        """Dismiss on Esc/Return via the field editor (not NSTextField.keyDown_)."""
        name = selector if isinstance(selector, str) else str(selector)
        if name in {"cancelOperation:", "insertNewline:"}:
            self.hide()
            return True
        return False

    def hide(self) -> None:
        panel = getattr(self, "panel", None)
        if panel is not None:
            panel.orderOut_(None)
        self.visible = False

    def init(self):
        self = objc.super(OverlayController, self).init()
        if self is None:
            return None
        self.callback = None
        self.chord = ChordTracker()
        self.field = None
        self.panel = None
        self.source = None
        self.tap = None
        self.visible = False
        self._build_panel()
        return self

    def show(self) -> None:
        if self.field is not None:
            self.field.setStringValue_("")
        self._center_panel()
        if self.panel is not None:
            self.panel.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)
        if self.panel is not None and self.field is not None:
            self.panel.makeFirstResponder_(self.field)
        self.visible = True

    def toggle(self) -> None:
        if self.visible:
            self.hide()
        else:
            self.show()

    def windowDidResignKey_(self, _notification) -> None:
        self.hide()

    def _build_panel(self) -> None:
        style = NSWindowStyleMaskTitled | NSWindowStyleMaskFullSizeContentView
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0.0, 0.0, PANEL_WIDTH, PANEL_HEIGHT),
            style,
            NSBackingStoreBuffered,
            False,
        )
        panel.setTitle_("bunnify")
        panel.setTitlebarAppearsTransparent_(True)
        panel.setLevel_(NSFloatingWindowLevel)
        panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        panel.setHidesOnDeactivate_(True)
        panel.setReleasedWhenClosed_(False)
        panel.setDelegate_(self)

        field = NSTextField.alloc().initWithFrame_(
            NSMakeRect(16.0, 16.0, PANEL_WIDTH - 32.0, 40.0)
        )
        field.setEditable_(True)
        field.setSelectable_(True)
        field.setBezeled_(True)
        field.setFont_(NSFont.systemFontOfSize_(20.0))
        field.setPlaceholderString_("Type a shortcut…")
        field.setBackgroundColor_(NSColor.textBackgroundColor())
        field.setDelegate_(self)
        panel.contentView().addSubview_(field)

        self.field = field
        self.panel = panel

    def _center_panel(self) -> None:
        if self.panel is None:
            return
        screen = NSScreen.mainScreen()
        if screen is None:
            return
        visible = screen.visibleFrame()
        frame = self.panel.frame()
        origin_x = visible.origin.x + (visible.size.width - frame.size.width) / 2.0
        origin_y = visible.origin.y + (visible.size.height - frame.size.height) * 0.55
        self.panel.setFrameOrigin_((origin_x, origin_y))


def run_overlay_app() -> int:
    """Run NSApplication until the process is interrupted."""
    NSApplication.sharedApplication()
    NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    controller = OverlayController.alloc().init()
    _install_event_tap(controller)
    print(
        "bunnify-overlay: hold one Control, press the other for the search box "
        "(Ctrl-C to quit)",
        file=sys.stderr,
    )
    try:
        AppHelper.runEventLoop()
    except KeyboardInterrupt:
        AppHelper.stopEventLoop()
        return 0
    return 0


def _control_key_down(keycode: int) -> bool:
    return bool(CGEventSourceKeyState(kCGEventSourceStateHIDSystemState, keycode))


def _event_mask() -> int:
    return (
        CGEventMaskBit(kCGEventKeyDown)
        | CGEventMaskBit(kCGEventKeyUp)
        | CGEventMaskBit(kCGEventFlagsChanged)
    )


def _install_event_tap(controller: OverlayController) -> None:
    tap_holder: dict[str, object] = {}

    def callback(_proxy, event_type, event, _refcon):
        tap = tap_holder.get("tap")
        if event_type in (
            kCGEventTapDisabledByTimeout,
            kCGEventTapDisabledByUserInput,
        ):
            if tap is not None:
                CGEventTapEnable(tap, True)
            return event
        keycode = int(CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode))
        if event_type != kCGEventFlagsChanged and keycode not in {
            CONTROL_LEFT_KEYCODE,
            CONTROL_RIGHT_KEYCODE,
        }:
            return event
        if apply_hid_snapshot(
            controller.chord,
            keycode=keycode,
            left_down=_control_key_down(CONTROL_LEFT_KEYCODE),
            right_down=_control_key_down(CONTROL_RIGHT_KEYCODE),
        ):
            controller.toggle()
        return event

    tap = CGEventTapCreate(
        kCGSessionEventTap,
        kCGHeadInsertEventTap,
        kCGEventTapOptionListenOnly,
        _event_mask(),
        callback,
        None,
    )
    if tap is None:
        tap = CGEventTapCreate(
            kCGHIDEventTap,
            kCGHeadInsertEventTap,
            kCGEventTapOptionListenOnly,
            _event_mask(),
            callback,
            None,
        )
    if tap is None:
        raise OverlayEventTapError("event tap was not created")
    tap_holder["tap"] = tap
    source = CFMachPortCreateRunLoopSource(None, tap, 0)
    CFRunLoopAddSource(CFRunLoopGetCurrent(), source, kCFRunLoopCommonModes)
    CGEventTapEnable(tap, True)
    controller.callback = callback
    controller.source = source
    controller.tap = tap

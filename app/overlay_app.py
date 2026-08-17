# pyright: reportMissingImports=false
"""macOS overlay UI (PyObjC). Imported only after Cocoa/Quartz are available."""

from __future__ import annotations

import logging
import signal
import sys

import objc
from Cocoa import (
    NSApp,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBackingStoreBuffered,
    NSColor,
    NSEvent,
    NSEventTypeApplicationDefined,
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
    NSWindowStyleMaskNonactivatingPanel,
    NSWindowStyleMaskTitled,
)
from PyObjCTools import MachSignals
from Quartz import (
    CFMachPortCreateRunLoopSource,
    CFRunLoopAddSource,
    CFRunLoopGetCurrent,
    CGEventGetFlags,
    CGEventGetIntegerValueField,
    CGEventMaskBit,
    CGEventSourceKeyState,
    CGEventTapCreate,
    CGEventTapEnable,
    kCFRunLoopCommonModes,
    kCGEventFlagMaskAlternate,
    kCGEventFlagMaskCommand,
    kCGEventFlagMaskControl,
    kCGEventFlagMaskSecondaryFn,
    kCGEventFlagMaskShift,
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
    DEVICE_LEFT_CONTROL_MASK,
    DEVICE_RIGHT_CONTROL_MASK,
    ChordTracker,
    apply_hid_snapshot,
    describe_key,
    resolve_control_snapshot,
)

PANEL_HEIGHT = 80.0
PANEL_WIDTH = 640.0

logger = logging.getLogger(__name__)


class OverlayController(NSObject):
    """Owns the floating search panel and toggles it from the Control chord."""

    def control_textView_doCommandBySelector_(self, _control, _text_view, selector):
        """Dismiss on Esc/Return via the field editor (not NSTextField.keyDown_)."""
        name = selector if isinstance(selector, str) else str(selector)
        if name in {"cancelOperation:", "insertNewline:"}:
            logger.info("field-editor command %s → hide", name)
            self.hide()
            return True
        logger.debug("field-editor command ignored: %s", name)
        return False

    def hide(self) -> None:
        logger.info("hide panel (was visible=%s)", self.visible)
        panel = getattr(self, "panel", None)
        if panel is not None:
            panel.orderOut_(None)
        self._became_key = False
        self.visible = False

    def init(self):
        self = objc.super(OverlayController, self).init()
        if self is None:
            return None
        self._became_key = False
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
        self._became_key = False
        self.visible = True
        logger.info("show panel")
        if self.panel is not None:
            # Accessory apps stay inactive; orderFrontRegardless still maps the
            # panel. Nonactivating style lets it become key without a dock bounce.
            self.panel.orderFrontRegardless()
            self.panel.makeKeyAndOrderFront_(None)
        if self.panel is not None and self.field is not None:
            self.panel.makeFirstResponder_(self.field)

    def toggle(self) -> None:
        logger.info("toggle (visible=%s)", self.visible)
        if self.visible:
            self.hide()
        else:
            self.show()

    def windowDidBecomeKey_(self, _notification) -> None:
        logger.debug("windowDidBecomeKey")
        self._became_key = True

    def windowDidResignKey_(self, _notification) -> None:
        # Accessory + Terminal: resign fires before the panel ever becomes key.
        # Only dismiss after a successful key cycle (click-away / app switch).
        logger.debug("windowDidResignKey became_key=%s", self._became_key)
        if self._became_key:
            self.hide()

    def _build_panel(self) -> None:
        style = (
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskFullSizeContentView
            | NSWindowStyleMaskNonactivatingPanel
        )
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
        panel.setFloatingPanel_(True)
        panel.setHidesOnDeactivate_(False)
        panel.setBecomesKeyOnlyIfNeeded_(False)
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
    """Run NSApplication until SIGINT (Ctrl-C) or NSApp.stop_."""
    NSApplication.sharedApplication()
    NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    NSApp.finishLaunching()
    controller = OverlayController.alloc().init()
    logger.info("NSApplication ready (activationPolicy=accessory)")
    _install_event_tap(controller)
    print(
        "bunnify-overlay: hold one Control, press the other for the search box "
        "(Ctrl-C to quit)",
        file=sys.stderr,
    )
    logger.info("event loop starting (MachSignals SIGINT → NSApp.stop_)")
    # AppHelper.runEventLoop() skips Mach SIGINT when NSApp already exists.
    MachSignals.signal(signal.SIGINT, _quit_on_sigint)
    NSApp.run()
    logger.info("event loop exited")
    return 0


def _control_key_down(keycode: int) -> bool:
    return bool(CGEventSourceKeyState(kCGEventSourceStateHIDSystemState, keycode))


def _describe_event_key(keycode: int, flags: int) -> str:
    return describe_key(
        keycode,
        command=bool(flags & kCGEventFlagMaskCommand),
        control=bool(flags & kCGEventFlagMaskControl),
        fn=bool(flags & kCGEventFlagMaskSecondaryFn),
        option=bool(flags & kCGEventFlagMaskAlternate),
        shift=bool(flags & kCGEventFlagMaskShift),
    )


def _event_mask() -> int:
    return (
        CGEventMaskBit(kCGEventKeyDown)
        | CGEventMaskBit(kCGEventKeyUp)
        | CGEventMaskBit(kCGEventFlagsChanged)
    )


def _event_type_name(event_type: int) -> str:
    names = {
        int(kCGEventFlagsChanged): "flagsChanged",
        int(kCGEventKeyDown): "keyDown",
        int(kCGEventKeyUp): "keyUp",
        int(kCGEventTapDisabledByTimeout): "tapDisabledByTimeout",
        int(kCGEventTapDisabledByUserInput): "tapDisabledByUserInput",
    }
    return names.get(int(event_type), f"type:{event_type}")


def _install_event_tap(controller: OverlayController) -> None:
    tap_holder: dict[str, object] = {}

    def callback(_proxy, event_type, event, _refcon):
        tap = tap_holder.get("tap")
        if event_type in (
            kCGEventTapDisabledByTimeout,
            kCGEventTapDisabledByUserInput,
        ):
            logger.warning(
                "event tap disabled (%s); re-enabling",
                _event_type_name(event_type),
            )
            if tap is not None:
                CGEventTapEnable(tap, True)
            return event
        keycode = int(CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode))
        flags = int(CGEventGetFlags(event))
        hid_left = _control_key_down(CONTROL_LEFT_KEYCODE)
        hid_right = _control_key_down(CONTROL_RIGHT_KEYCODE)
        flag_left = bool(flags & DEVICE_LEFT_CONTROL_MASK)
        flag_right = bool(flags & DEVICE_RIGHT_CONTROL_MASK)
        key_name = _describe_event_key(keycode, flags)
        if event_type != kCGEventFlagsChanged and keycode not in {
            CONTROL_LEFT_KEYCODE,
            CONTROL_RIGHT_KEYCODE,
        }:
            logger.debug(
                "tap %s %s keycode=%s hid left=%s right=%s (ignored for chord)",
                _event_type_name(event_type),
                key_name,
                keycode,
                hid_left,
                hid_right,
            )
            return event
        left_down, right_down = resolve_control_snapshot(
            keycode=keycode,
            hid_left=hid_left,
            hid_right=hid_right,
            flag_left=flag_left,
            flag_right=flag_right,
            held_left=controller.chord.held_left,
            held_right=controller.chord.held_right,
        )
        fired = apply_hid_snapshot(
            controller.chord,
            keycode=keycode,
            left_down=left_down,
            right_down=right_down,
        )
        logger.debug(
            "tap %s %s keycode=%s flags=0x%x hid L=%s R=%s flag L=%s R=%s "
            "resolved L=%s R=%s tracker L=%s R=%s fired=%s",
            _event_type_name(event_type),
            key_name,
            keycode,
            flags,
            hid_left,
            hid_right,
            flag_left,
            flag_right,
            left_down,
            right_down,
            controller.chord.held_left,
            controller.chord.held_right,
            fired,
        )
        if fired:
            logger.info(
                "chord complete %s keycode=%s resolved left=%s right=%s",
                key_name,
                keycode,
                left_down,
                right_down,
            )
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
    tap_kind = "session"
    if tap is None:
        logger.info("session event tap unavailable; trying HID tap")
        tap = CGEventTapCreate(
            kCGHIDEventTap,
            kCGHeadInsertEventTap,
            kCGEventTapOptionListenOnly,
            _event_mask(),
            callback,
            None,
        )
        tap_kind = "hid"
    if tap is None:
        logger.error("CGEventTapCreate returned None for session and HID")
        raise OverlayEventTapError("event tap was not created")
    logger.info("listen-only %s event tap installed", tap_kind)
    tap_holder["tap"] = tap
    source = CFMachPortCreateRunLoopSource(None, tap, 0)
    CFRunLoopAddSource(CFRunLoopGetCurrent(), source, kCFRunLoopCommonModes)
    CGEventTapEnable(tap, True)
    controller.callback = callback
    controller.source = source
    controller.tap = tap


def _post_wake_event() -> None:
    """Wake NSApp.run() so NSApp.stop_ takes effect."""
    other_event = getattr(
        NSEvent,
        "otherEventWithType_location_modifierFlags_timestamp_windowNumber"
        "_context_subtype_data1_data2_",
    )
    wake = other_event(
        NSEventTypeApplicationDefined,
        (0.0, 0.0),
        0,
        0.0,
        0,
        None,
        0,
        0,
        0,
    )
    NSApp.postEvent_atStart_(wake, True)


def _quit_on_sigint(_signum: int) -> None:
    logger.info("SIGINT received; stopping NSApp")
    NSApp.stop_(None)
    _post_wake_event()

# pyright: reportMissingImports=false
"""Spotty Bunny macOS UI (PyObjC). Imported only after Cocoa/Quartz are available."""

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
    NSImageScaleProportionallyUpOrDown,
    NSImageView,
    NSMakeRect,
    NSObject,
    NSPanel,
    NSScreen,
    NSScrollView,
    NSTableColumn,
    NSTableView,
    NSTextField,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowStyleMaskFullSizeContentView,
    NSWindowStyleMaskNonactivatingPanel,
    NSWindowStyleMaskTitled,
)
from Foundation import NSIndexSet, NSOperationQueue, NSThread
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

from app.cli import open_url
from app.client import fetch_key_entries, fetch_suggestions
from app.config import resolve_base_url
from app.spotty_bunny_cli import SpottyBunnyEventTapError
from app.spotty_bunny_complete import (
    CompletionRow,
    apply_completion,
    completion_row_after_selector,
    completion_still_current,
    completions_for,
    make_spotty_completer,
)
from app.spotty_bunny_history import (
    HistoryNavigator,
    append_history_line,
    apply_history_selector,
    load_history_lines,
)
from app.spotty_bunny_hotkey import (
    CONTROL_LEFT_KEYCODE,
    CONTROL_RIGHT_KEYCODE,
    DEVICE_LEFT_CONTROL_MASK,
    DEVICE_RIGHT_CONTROL_MASK,
    ChordTracker,
    apply_control_event,
    describe_key,
)
from app.spotty_bunny_icon import make_spotty_bunny_icon
from app.spotty_bunny_io import ThreadIo
from app.spotty_bunny_quit import (
    WAKE_EVENT_SELECTOR,
    post_application_wake_event,
    quit_ns_app,
)
from app.spotty_bunny_resolve import lookup_resolved_url, resolve_still_current

FIELD_PLACEHOLDER = "Type a shortcut (e.g., gh, c, search hello)"
LOGO_LEFT = 16.0
LOGO_SIZE = 40.0
LOGO_TOP = 24.0
PANEL_HEIGHT = 80.0
PANEL_WIDTH = 640.0
TABLE_HEIGHT = 140.0
FIELD_LEFT = LOGO_LEFT + LOGO_SIZE + 12.0
FIELD_WIDTH = PANEL_WIDTH - FIELD_LEFT - 16.0

logger = logging.getLogger(__name__)


class SpottyBunnyController(NSObject):
    """Owns the floating search panel and toggles it from the Control chord."""

    def controlTextDidChange_(self, _notification) -> None:
        if self._applying_completion:
            return
        if self._completion_rows:
            self._hide_completions()

    def control_textView_doCommandBySelector_(self, _control, _text_view, selector):
        """Tab completions, history up/down, dismiss on Esc/Return."""
        name = selector if isinstance(selector, str) else str(selector)
        if name == "insertTab:":
            self._request_completions()
            return True
        if self._completion_rows and name in {
            "moveDown:",
            "moveUp:",
            "pageDown:",
            "pageUp:",
        }:
            self._move_completion(name)
            return True
        current = ""
        if self.field is not None:
            current = str(self.field.stringValue())
        history_text = apply_history_selector(self._history, current, name)
        if history_text is not None:
            logger.debug("history %s → %r", name, history_text)
            if self.field is not None:
                self.field.setStringValue_(history_text)
            return True
        if name in {"cancelOperation:"}:
            logger.info("field-editor command %s → hide", name)
            self.hide()
            return True
        if name == "insertNewline:":
            self._submit_query()
            return True
        logger.debug("field-editor command ignored: %s", name)
        return False

    def hide(self) -> None:
        logger.info("hide panel (was visible=%s)", self.visible)
        self._resolve_seq += 1
        self._resolving = False
        self._hide_completions()
        self._set_status("")
        panel = getattr(self, "panel", None)
        if panel is not None:
            panel.orderOut_(None)
        self._became_key = False
        self.visible = False

    def init(self):
        self = objc.super(SpottyBunnyController, self).init()
        if self is None:
            return None
        self._applying_completion = False
        self._became_key = False
        self._base_url = ""
        self._completer = None
        self._completion_prefix = ""
        self._completion_rows: list[CompletionRow] = []
        self._completion_seq = 0
        self._history = HistoryNavigator()
        self._io = ThreadIo()
        self._resolve_seq = 0
        self._resolving = False
        self._shortcuts_load_failed = False
        self.callback = None
        self.chord = ChordTracker()
        self.field = None
        self.logo = None
        self.panel = None
        self.scroll = None
        self.source = None
        self.status = None
        self.table = None
        self.tap = None
        self.visible = False
        self._build_panel()
        return self

    def numberOfRowsInTableView_(self, _table) -> int:
        return len(self._completion_rows)

    def show(self) -> None:
        self._history = HistoryNavigator(load_history_lines())
        self._hide_completions()
        self._set_status("")
        self._shortcuts_load_failed = False
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
        self._io.submit(self._load_completer, self._completer_loaded)

    def tableView_objectValueForTableColumn_row_(self, _table, column, row: int):
        if row < 0 or row >= len(self._completion_rows):
            return ""
        item = self._completion_rows[row]
        ident = str(column.identifier())
        if ident == "key":
            return item.insert
        if ident == "meta":
            return item.meta
        return ""

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
        panel.setTitle_("spotty-bunny")
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

        logo = NSImageView.alloc().initWithFrame_(
            NSMakeRect(LOGO_LEFT, LOGO_TOP, LOGO_SIZE, LOGO_SIZE)
        )
        logo.setImage_(make_spotty_bunny_icon(LOGO_SIZE))
        logo.setImageScaling_(NSImageScaleProportionallyUpOrDown)
        panel.contentView().addSubview_(logo)

        field = NSTextField.alloc().initWithFrame_(
            NSMakeRect(FIELD_LEFT, 16.0, FIELD_WIDTH, 40.0)
        )
        field.setEditable_(True)
        field.setSelectable_(True)
        field.setBezeled_(True)
        field.setFont_(NSFont.systemFontOfSize_(20.0))
        field.setPlaceholderString_(FIELD_PLACEHOLDER)
        field.setBackgroundColor_(NSColor.textBackgroundColor())
        field.setDelegate_(self)
        panel.contentView().addSubview_(field)

        status = NSTextField.alloc().initWithFrame_(
            NSMakeRect(16.0, 4.0, PANEL_WIDTH - 32.0, 14.0)
        )
        status.setEditable_(False)
        status.setSelectable_(False)
        status.setBezeled_(False)
        status.setDrawsBackground_(False)
        status.setFont_(NSFont.systemFontOfSize_(11.0))
        status.setStringValue_("")
        panel.contentView().addSubview_(status)

        scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(16.0, 16.0, PANEL_WIDTH - 32.0, TABLE_HEIGHT - 8.0)
        )
        scroll.setHasVerticalScroller_(True)
        scroll.setHidden_(True)
        table = NSTableView.alloc().init()
        key_col = NSTableColumn.alloc().initWithIdentifier_("key")
        key_col.setTitle_("Shortcut")
        key_col.setWidth_(160.0)
        meta_col = NSTableColumn.alloc().initWithIdentifier_("meta")
        meta_col.setTitle_("Description")
        meta_col.setWidth_(400.0)
        table.addTableColumn_(key_col)
        table.addTableColumn_(meta_col)
        table.setDataSource_(self)
        table.setDelegate_(self)
        table.setHeaderView_(None)
        scroll.setDocumentView_(table)
        panel.contentView().addSubview_(scroll)

        self.field = field
        self.logo = logo
        self.panel = panel
        self.scroll = scroll
        self.status = status
        self.table = table

    def _center_panel(self) -> None:
        if self.panel is None:
            return
        screen = _primary_screen()
        if screen is None:
            return
        visible = screen.visibleFrame()
        frame = self.panel.frame()
        origin_x = visible.origin.x + (visible.size.width - frame.size.width) / 2.0
        origin_y = visible.origin.y + (visible.size.height - frame.size.height) * 0.55
        self.panel.setFrameOrigin_((origin_x, origin_y))

    def _completer_loaded(self, result: object) -> None:
        def apply() -> None:
            if isinstance(result, Exception):
                logger.warning("could not load shortcuts: %s", result)
                self._shortcuts_load_failed = True
                return
            completer, base_url = result  # type: ignore[misc]
            self._completer = completer
            self._base_url = base_url
            self._shortcuts_load_failed = False
            self._set_status("")
            logger.info("shortcut completer ready")

        _run_on_main(apply)

    def _completions_ready(self, result: object, *, seq: int) -> None:
        def apply() -> None:
            field = str(self.field.stringValue()) if self.field is not None else ""
            if not completion_still_current(
                expected_seq=seq,
                field=field,
                prefix=self._completion_prefix,
                seq=self._completion_seq,
            ):
                return
            if not self.visible:
                return
            if isinstance(result, Exception):
                logger.warning("completion failed: %s", result)
                return
            self._show_completions(result)  # type: ignore[arg-type]

        _run_on_main(apply)

    def _hide_completions(self) -> None:
        self._completion_seq += 1
        self._completion_prefix = ""
        self._completion_rows = []
        if self.table is not None:
            self.table.reloadData()
        self._set_table_visible(False)

    def _load_completer(self) -> object:
        base_url = resolve_base_url(persist=False, allow_prompt=False)
        entries = fetch_key_entries(base_url=base_url)
        completer = make_spotty_completer(
            entries=entries,
            suggestions_fn=lambda query: fetch_suggestions(query, base_url=base_url),
        )
        return completer, base_url

    def _move_completion(self, selector: str) -> None:
        if not self._completion_rows or self.table is None or self.field is None:
            return
        idx = completion_row_after_selector(
            int(self.table.selectedRow()),
            row_count=len(self._completion_rows),
            selector=selector,
        )
        self.table.selectRowIndexes_byExtendingSelection_(
            NSIndexSet.indexSetWithIndex_(idx),
            False,
        )
        self.table.scrollRowToVisible_(idx)
        row = self._completion_rows[idx]
        self._set_field_text(apply_completion(self._completion_prefix, row))

    def _request_completions(self) -> None:
        if self._completer is None or self.field is None:
            logger.warning("tab ignored (completer not ready)")
            if self._completer is None and self._shortcuts_load_failed:
                self._set_status("could not load shortcuts")
            return
        text = str(self.field.stringValue())
        self._completion_rows = []
        if self.table is not None:
            self.table.reloadData()
        self._set_table_visible(False)
        self._completion_prefix = text
        self._completion_seq += 1
        seq = self._completion_seq
        completer = self._completer
        self._io.submit(
            lambda: completions_for(text, completer),
            lambda result: self._completions_ready(result, seq=seq),
        )

    def _resolve_ready(self, result: object, *, seq: int) -> None:
        def apply() -> None:
            if not resolve_still_current(expected_seq=seq, seq=self._resolve_seq):
                return
            self._resolving = False
            if isinstance(result, Exception):
                logger.warning("resolve failed: %s", result)
                self._hide_completions()
                self._set_status(str(result))
                return
            logger.info("opened %s", result)
            self.hide()

        _run_on_main(apply)

    def _set_field_text(self, text: str) -> None:
        if self.field is None:
            return
        self._applying_completion = True
        try:
            self.field.setStringValue_(text)
        finally:
            self._applying_completion = False

    def _set_status(self, message: str) -> None:
        if self.status is None:
            return
        self.status.setStringValue_(message)
        color = NSColor.systemRedColor() if message else NSColor.secondaryLabelColor()
        self.status.setTextColor_(color)

    def _set_table_visible(self, visible: bool) -> None:
        if self.scroll is None or self.panel is None or self.field is None:
            return
        self.scroll.setHidden_(not visible)
        frame = self.panel.frame()
        frame.size.height = PANEL_HEIGHT + (TABLE_HEIGHT if visible else 0.0)
        self.panel.setFrame_display_(frame, True)
        if visible:
            self.field.setFrame_(
                NSMakeRect(FIELD_LEFT, 16.0 + TABLE_HEIGHT, FIELD_WIDTH, 40.0)
            )
            self.scroll.setFrame_(
                NSMakeRect(16.0, 16.0, PANEL_WIDTH - 32.0, TABLE_HEIGHT - 8.0)
            )
        else:
            self.field.setFrame_(NSMakeRect(FIELD_LEFT, 16.0, FIELD_WIDTH, 40.0))
        self._center_panel()

    def _show_completions(self, rows: list[CompletionRow]) -> None:
        self._completion_rows = rows
        if not rows:
            self._hide_completions()
            return
        if self.field is not None:
            self._set_field_text(apply_completion(self._completion_prefix, rows[0]))
        if self.table is not None:
            self.table.reloadData()
            self.table.selectRowIndexes_byExtendingSelection_(
                NSIndexSet.indexSetWithIndex_(0),
                False,
            )
            self.table.scrollRowToVisible_(0)
        self._set_table_visible(len(rows) > 1)

    def _submit_query(self) -> None:
        if self.field is None or self._resolving:
            return
        query = str(self.field.stringValue()).strip()
        if not query:
            self.hide()
            return
        self._resolve_seq += 1
        seq = self._resolve_seq
        self._resolving = True
        self._set_status("")
        cached_base = self._base_url

        def work() -> str:
            base_url = cached_base or resolve_base_url(
                persist=False, allow_prompt=False
            )
            url = lookup_resolved_url(query, base_url=base_url)
            if not resolve_still_current(expected_seq=seq, seq=self._resolve_seq):
                return url
            open_url(url)
            append_history_line(query)
            return url

        self._io.submit(work, lambda result: self._resolve_ready(result, seq=seq))


def _primary_screen():
    """Return the menu-bar (main) display, not a secondary monitor."""
    main = NSScreen.mainScreen()
    if main is not None:
        return main
    screens = NSScreen.screens()
    return screens[0] if screens else None


def run_spotty_bunny_app() -> int:
    """Run NSApplication until SIGINT (Ctrl-C) or NSApp.stop_."""
    NSApplication.sharedApplication()
    NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    NSApp.finishLaunching()
    controller = SpottyBunnyController.alloc().init()
    logger.info("NSApplication ready (activationPolicy=accessory)")
    _install_event_tap(controller)
    print(
        "spotty-bunny: hold one Control, press the other for the search box "
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


def _install_event_tap(controller: SpottyBunnyController) -> None:
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
        if event_type != kCGEventFlagsChanged:
            logger.debug(
                "tap %s %s keycode=%s hid left=%s right=%s (ignored for chord)",
                _event_type_name(event_type),
                key_name,
                keycode,
                hid_left,
                hid_right,
            )
            return event
        fired = apply_control_event(
            controller.chord,
            keycode=keycode,
            hid_left=hid_left,
            hid_right=hid_right,
            flag_left=flag_left,
            flag_right=flag_right,
            control_flag=bool(flags & kCGEventFlagMaskControl),
            flags_changed=True,
        )
        logger.debug(
            "tap %s %s keycode=%s flags=0x%x hid L=%s R=%s flag L=%s R=%s "
            "tracker L=%s R=%s fired=%s",
            _event_type_name(event_type),
            key_name,
            keycode,
            flags,
            hid_left,
            hid_right,
            flag_left,
            flag_right,
            controller.chord.held_left,
            controller.chord.held_right,
            fired,
        )
        if fired:
            logger.info(
                "chord complete %s keycode=%s tracker left=%s right=%s",
                key_name,
                keycode,
                controller.chord.held_left,
                controller.chord.held_right,
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
        raise SpottyBunnyEventTapError("event tap was not created")
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
    other_event = getattr(NSEvent, WAKE_EVENT_SELECTOR)
    post_application_wake_event(
        event_type=NSEventTypeApplicationDefined,
        ns_app=NSApp,
        other_event=other_event,
    )


def _quit_on_sigint(_signum: int) -> None:
    logger.info("SIGINT received; stopping NSApp")
    quit_ns_app(ns_app=NSApp, post_wake=_post_wake_event)


def _run_on_main(fn: object) -> None:
    """Run *fn* on the AppKit thread (completion callbacks arrive off-main)."""
    callback = fn if callable(fn) else lambda: None
    if NSThread.isMainThread():
        callback()
        return
    NSOperationQueue.mainQueue().addOperationWithBlock_(callback)

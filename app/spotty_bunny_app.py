# pyright: reportMissingImports=false
"""Spotty Bunny macOS UI (PyObjC). Imported only after Cocoa/Quartz are available."""

from __future__ import annotations

import logging
import math
import os
import signal
import sys
import time

import objc
from Cocoa import (
    NSAlert,
    NSAlertFirstButtonReturn,
    NSAlertStyleWarning,
    NSApp,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBackingStoreBuffered,
    NSBezelStyleShadowlessSquare,
    NSButton,
    NSColor,
    NSEvent,
    NSEventModifierFlagCommand,
    NSEventModifierFlagControl,
    NSEventModifierFlagDeviceIndependentFlagsMask,
    NSEventModifierFlagOption,
    NSEventModifierFlagShift,
    NSEventTypeApplicationDefined,
    NSFloatingWindowLevel,
    NSFocusRingTypeNone,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSImageScaleProportionallyUpOrDown,
    NSLayoutManager,
    NSLineBreakByClipping,
    NSLineBreakByWordWrapping,
    NSMakeRect,
    NSMakeSize,
    NSMenu,
    NSMenuItem,
    NSMutableParagraphStyle,
    NSObject,
    NSPanel,
    NSParagraphStyleAttributeName,
    NSScreen,
    NSScrollView,
    NSSelectionAffinityUpstream,
    NSStringDrawingUsesFontLeading,
    NSStringDrawingUsesLineFragmentOrigin,
    NSTableColumn,
    NSTableView,
    NSTextAlignmentCenter,
    NSTextAlignmentLeft,
    NSTextField,
    NSTextFieldCell,
    NSView,
    NSViewHeightSizable,
    NSViewWidthSizable,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
    NSWorkspace,
)
from Foundation import (
    NSAttributedString,
    NSIndexSet,
    NSMakeRange,
    NSMutableAttributedString,
    NSOperationQueue,
    NSThread,
    NSTimer,
    NSWorkspaceDidWakeNotification,
)
from PyObjCTools import MachSignals
from Quartz import (
    CFMachPortCreateRunLoopSource,
    CFMachPortInvalidate,
    CFRunLoopAddSource,
    CFRunLoopGetCurrent,
    CFRunLoopRemoveSource,
    CGEventGetFlags,
    CGEventGetIntegerValueField,
    CGEventMaskBit,
    CGEventSourceKeyState,
    CGEventTapCreate,
    CGEventTapEnable,
    CGEventTapIsEnabled,
    CGRequestListenEventAccess,
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
from app.github_complete import (
    bootstrap_github_completion_cache,
    can_offer_gh_install,
    entries_need_github_completion,
    gh_install_guidance,
    gh_is_available,
    github_completion_unavailable_message,
    github_token_from_environ,
    install_gh_via_homebrew,
    resolve_github_token,
    warn_github_completion,
)
from app.spotty_bunny_about import (
    apply_spotty_chrome,
    build_about_panel,
    position_about_panel,
)
from app.spotty_bunny_agent import (
    bootout_loaded_agent,
    install_agent,
    is_agent_installed,
    refresh_agent_plist,
    uninstall_agent,
)
from app.spotty_bunny_cli import SpottyBunnyEventTapError
from app.spotty_bunny_complete import (
    CompletionRow,
    apply_completion,
    completion_browse_all,
    completion_navigation_disposition,
    completion_row_after_selector,
    completion_still_current,
    completion_table_should_show,
    completions_for,
    field_editor_selector_name,
    github_param_completion_blocked_message,
    is_tab_completion_selector,
    make_spotty_completer,
    should_auto_insert_completion,
    surface_blocked_github_completion,
)
from app.spotty_bunny_edit import (
    edit_action_for_key,
    edit_command_modifiers_ok,
    is_line_navigation_selector,
    is_line_start_selector,
    line_navigation_modifies_selection,
    line_navigation_selected_range,
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
    ESCAPE_KEYCODE,
    PAGE_DOWN_KEYCODE,
    PAGE_UP_KEYCODE,
    TAB_KEYCODE,
    ChordTracker,
    apply_control_event,
    describe_key,
    page_selector_for_keycode,
)
from app.spotty_bunny_icon import make_spotty_bunny_icon
from app.spotty_bunny_io import ThreadIo
from app.spotty_bunny_menu import (
    INSTALL_STATUS,
    UNINSTALL_INFORMATIVE,
    UNINSTALL_MENU_TITLE,
    UPGRADE_STATUS,
    logo_menu_specs,
)
from app.spotty_bunny_quit import (
    WAKE_EVENT_SELECTOR,
    post_application_wake_event,
    quit_ns_app,
)
from app.spotty_bunny_resolve import lookup_resolved_url, resolve_still_current
from app.spotty_bunny_status import (
    SHORTCUTS_LOAD_FAILED,
    canned_spotty_bunny_status_lines,
    format_spotty_bunny_status,
    status_text_runs,
    wrap_status_preferring_punctuation,
)
from app.spotty_bunny_tap_health import (
    TAP_HEALTH_CHECK_INTERVAL_S,
    TAP_STATE_DISABLED,
    TAP_STATE_MISSING,
    TAP_STATE_OK,
    TAP_STATE_REINSTALLING,
    decide_tap_health_check,
    process_reinstall_failure,
    read_spotty_bunny_health,
    reset_reinstall_failures,
    try_write_spotty_bunny_health,
)
from app.spotty_bunny_update import (
    UpdateStatus,
    cache_is_stale,
    read_cached_update_status,
    refresh_update_status,
)
from app.version import get_build_info

FIELD_CORNER_RADIUS = 8.0
FIELD_HEIGHT = 56.0
FIELD_PLACEHOLDER = "Type a shortcut (e.g., gh, c, yt, docs). Tab is your friend :)"
FIELD_TEXT_INSET = 12.0
LOGO_GAP = 8.0
LOGO_SIZE = 40.0
PANEL_CORNER_RADIUS = 10.0
PANEL_FILL_RGB = (0.36, 0.55, 0.84)
PANEL_FRAME_RGB = (0.10, 0.28, 0.56)
PANEL_HEIGHT = 76.0
PANEL_INSET = 10.0
PANEL_WIDTH = 640.0
STATUS_COMMAND_FONT = "Courier"
STATUS_ERROR_RGB = (1.0, 0.76, 0.52)
STATUS_FONT_SIZE = 16.0
STATUS_INSET = 8.0
TABLE_HEIGHT = 140.0
FIELD_LEFT = PANEL_INSET
LOGO_LEFT = PANEL_WIDTH - FIELD_LEFT - LOGO_SIZE
FIELD_WIDTH = LOGO_LEFT - FIELD_LEFT - LOGO_GAP
STATUS_WRAP_WIDTH = PANEL_WIDTH - 2.0 * PANEL_INSET

logger = logging.getLogger(__name__)


class SpottyBunnyController(NSObject):
    """Owns the floating search panel and toggles it from the Control chord."""

    def completeWithTab_(self, _sender) -> None:
        """Run Tab completion (field editor or panel key-view)."""
        self._request_completions()

    def controlTextDidBeginEditing_(self, _notification) -> None:
        self._paint_search_editor()

    def controlTextDidChange_(self, _notification) -> None:
        if self._applying_completion:
            return
        if self.status is not None and str(self.status.stringValue()):
            self._set_status("")
        if not self._completion_rows:
            return
        text = str(self.field.stringValue()) if self.field is not None else ""
        if any(
            apply_completion(self._completion_prefix, row) == text
            for row in self._completion_rows
        ):
            return
        self._hide_completions()

    def control_textView_doCommandBySelector_(self, _control, text_view, selector):
        """Tab completions, history up/down, Home/End, dismiss on Esc/Return."""
        name = field_editor_selector_name(selector)
        if is_tab_completion_selector(name):
            self.completeWithTab_(None)
            return True
        if is_line_navigation_selector(name):
            self._apply_line_navigation(text_view, name)
            return True
        disposition = completion_navigation_disposition(
            name,
            has_rows=bool(self._completion_rows),
            table_visible=self._completion_table_visible(),
        )
        if disposition == "move":
            self._move_completion(name)
            return True
        if disposition == "consume":
            return True
        if disposition == "ignore":
            return False
        current = ""
        if self.field is not None:
            current = str(self.field.stringValue())
        history_text = apply_history_selector(self._history, current, name)
        if history_text is not None:
            logger.debug("history %s → %r", name, history_text)
            if self.field is not None:
                self.field.setStringValue_(history_text)
            return True
        if name in {"cancel:", "cancelOperation:"}:
            self.dismissWithEscape_(None)
            return True
        if name == "insertNewline:":
            self._submit_query()
            return True
        logger.debug("field-editor command ignored: %s", name)
        return False

    def checkEventTapHealth_(self, _timer) -> None:
        """Periodic timer: re-enable or reinstall a stale CGEventTap."""
        _check_event_tap_health(self)

    def dismissWithEscape_(self, _sender) -> None:
        """Hide About first, then the overlay. Ignore repeats until key-up."""
        if self._escape_held:
            return
        self._escape_held = True
        if not self.visible:
            return
        if self._about_open:
            self.hideAbout_(None)
            return
        logger.info("escape → hide")
        self.hide()

    def hide(self) -> None:
        logger.info("hide panel (was visible=%s)", self.visible)
        self._resolve_seq += 1
        self._resolving = False
        self._hide_about_panel()
        self._hide_completions()
        self._set_status("")
        panel = getattr(self, "panel", None)
        if panel is not None:
            panel.orderOut_(None)
        self._became_key = False
        self.visible = False

    def hideAbout_(self, _sender) -> None:
        """Dismiss the about card without hiding the search overlay."""
        self._hide_about_panel()
        if self.visible and self.panel is not None:
            self.panel.makeKeyAndOrderFront_(None)
            if self.field is not None:
                self.panel.makeFirstResponder_(self.field)
                self._paint_search_editor()

    def init(self):
        self = objc.super(SpottyBunnyController, self).init()
        if self is None:
            return None
        self._about_panel = None
        self._about_open = False
        self._applying_completion = False
        self._became_key = False
        self._base_url = ""
        self._completer = None
        self._completion_prefix = ""
        self._completion_rows: list[CompletionRow] = []
        self._completion_seq = 0
        self._entries: list = []
        self._escape_held = False
        self._history = HistoryNavigator()
        self._io = ThreadIo()
        self._logo_menu = None
        self._resolve_seq = 0
        self._resolving = False
        self._shortcuts_load_failed = False
        self._update_check_pending = False
        self._update_status = read_cached_update_status()
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
        self._tap_health_timer = None
        self.visible = False
        self._build_panel()
        self._apply_update_status()
        self._io.submit(get_build_info, lambda _result: None)
        self._schedule_update_check()
        return self

    def installSpottyBunny_(self, _sender) -> None:
        """Install the login LaunchAgent, then quit so launchd owns the overlay."""
        logger.info("install from logo menu")
        self._set_status(INSTALL_STATUS)
        self._io.submit(self._perform_install, self._install_ready)

    def menuNeedsUpdate_(self, menu) -> None:
        self._rebuild_logo_menu(menu)

    def numberOfRowsInTableView_(self, _table) -> int:
        return len(self._completion_rows)

    def quitSpottyBunny_(self, _sender) -> None:
        """Stop this process; boot out the LaunchAgent so KeepAlive cannot respawn."""
        logger.info("quit from logo menu")
        bootout_loaded_agent()
        quit_ns_app(ns_app=NSApp, post_wake=_post_wake_event)

    def releaseEscape_(self, _sender) -> None:
        """Arm the next Esc after the key-up of a tap or field-editor dismiss."""
        self._escape_held = False

    def showAbout_(self, _sender) -> None:
        self._toggle_about_panel()

    def show(self) -> None:
        self._escape_held = False
        self._history = HistoryNavigator(load_history_lines())
        self._hide_about_panel()
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
            self._paint_search_editor()
        self._io.submit(self._load_completer, self._completer_loaded)
        if cache_is_stale(self._update_status.checked_at):
            self._schedule_update_check()

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

    def uninstallSpottyBunny_(self, _sender) -> None:
        """Confirm, remove the LaunchAgent, and quit this process."""
        if not _confirm_uninstall():
            return
        logger.info("uninstall from logo menu")
        uninstall_agent()
        quit_ns_app(ns_app=NSApp, post_wake=_post_wake_event)

    def upgradeSpottyBunny_(self, _sender) -> None:
        """Upgrade via pipx, rewrite the plist, then quit so KeepAlive relaunches."""
        logger.info("upgrade from logo menu")
        self._set_status(UPGRADE_STATUS)
        self._io.submit(self._perform_upgrade, self._upgrade_ready)

    def windowDidBecomeKey_(self, _notification) -> None:
        logger.debug("windowDidBecomeKey")
        self._became_key = True
        self._paint_search_editor()

    def windowDidResignKey_(self, notification) -> None:
        # Accessory + Terminal: resign fires before the panel ever becomes key.
        # Only dismiss after a successful key cycle (click-away / app switch).
        # Keep the overlay up while About is open (link clicks activate the
        # browser and would otherwise hide everything).
        logger.debug("windowDidResignKey became_key=%s", self._became_key)
        if not self.visible:
            return
        if self._about_open:
            return
        resigning = notification.object()
        if resigning is self.panel and self._became_key:
            self.hide()

    def workspaceDidWake_(self, _notification) -> None:
        """Reinstall the event tap after sleep/wake."""
        logger.info("system wake; reinstalling event tap")
        _reinstall_event_tap(self)

    def _apply_line_navigation(self, text_view, selector: str) -> None:
        """Move or extend the caret for Home/End (and Cocoa document aliases)."""
        length = int(text_view.string().length())
        selected = text_view.selectedRange()
        location, sel_length = line_navigation_selected_range(
            text_length=length,
            selected_location=int(selected.location),
            selected_length=int(selected.length),
            to_start=is_line_start_selector(selector),
            modify=line_navigation_modifies_selection(selector),
            affinity_upstream=(
                int(text_view.selectionAffinity()) == int(NSSelectionAffinityUpstream)
            ),
        )
        text_view.setSelectedRange_(NSMakeRange(location, sel_length))

    def _apply_update_status(self) -> None:
        outdated = self._update_status.outdated
        if self.logo is not None:
            self.logo.setImage_(make_spotty_bunny_icon(LOGO_SIZE, outdated=outdated))
        if self._logo_menu is not None:
            self._rebuild_logo_menu(self._logo_menu)
        if self._about_open:
            self._present_about_panel()

    def _build_panel(self) -> None:
        style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        panel = SpottyBunnyPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0.0, 0.0, PANEL_WIDTH, PANEL_HEIGHT),
            style,
            NSBackingStoreBuffered,
            False,
        )
        panel.setLevel_(NSFloatingWindowLevel)
        panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        panel.setFloatingPanel_(True)
        panel.setHidesOnDeactivate_(False)
        panel.setBecomesKeyOnlyIfNeeded_(False)
        panel.setReleasedWhenClosed_(False)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setDelegate_(self)

        chrome = NSView.alloc().initWithFrame_(panel.contentView().bounds())
        chrome.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        apply_spotty_chrome(
            chrome,
            corner_radius=PANEL_CORNER_RADIUS,
            fill_rgb=PANEL_FILL_RGB,
            frame_rgb=PANEL_FRAME_RGB,
        )
        panel.setContentView_(chrome)

        logo = SpottyBunnyLogoButton.alloc().initWithFrame_(
            NSMakeRect(
                LOGO_LEFT,
                PANEL_INSET + (FIELD_HEIGHT - LOGO_SIZE) / 2.0,
                LOGO_SIZE,
                LOGO_SIZE,
            )
        )
        logo.setBezelStyle_(NSBezelStyleShadowlessSquare)
        logo.setBordered_(False)
        logo.setImage_(
            make_spotty_bunny_icon(LOGO_SIZE, outdated=self._update_status.outdated)
        )
        logo.setImageScaling_(NSImageScaleProportionallyUpOrDown)
        logo.setTarget_(self)
        logo.setAction_("showAbout:")
        logo.setRefusesFirstResponder_(True)
        menu = NSMenu.alloc().initWithTitle_("")
        menu.setDelegate_(self)
        self._logo_menu = menu
        self._rebuild_logo_menu(menu)
        logo.setMenu_(menu)
        panel.contentView().addSubview_(logo)

        field = SpottyBunnySearchField.alloc().initWithFrame_(
            NSMakeRect(FIELD_LEFT, PANEL_INSET, FIELD_WIDTH, FIELD_HEIGHT)
        )
        cell = _CenteredFieldCell.alloc().initTextCell_("")
        cell.setEditable_(True)
        cell.setSelectable_(True)
        cell.setScrollable_(True)
        cell.setWraps_(False)
        cell.setBezeled_(False)
        cell.setBordered_(False)
        cell.setDrawsBackground_(True)
        cell.setBackgroundColor_(NSColor.blackColor())
        cell.setTextColor_(NSColor.whiteColor())
        cell.setAlignment_(NSTextAlignmentLeft)
        field.setCell_(cell)
        field.setEditable_(True)
        field.setSelectable_(True)
        field.setBezeled_(False)
        field.setBordered_(False)
        field.setFocusRingType_(NSFocusRingTypeNone)
        field.setAlignment_(NSTextAlignmentLeft)
        field.setFont_(NSFont.systemFontOfSize_(20.0))
        placeholder_style = NSMutableParagraphStyle.alloc().init()
        placeholder_style.setAlignment_(NSTextAlignmentLeft)
        field.setPlaceholderAttributedString_(
            NSAttributedString.alloc().initWithString_attributes_(
                FIELD_PLACEHOLDER,
                {
                    NSFontAttributeName: NSFont.systemFontOfSize_(20.0),
                    NSParagraphStyleAttributeName: placeholder_style,
                    "NSColor": NSColor.colorWithWhite_alpha_(0.55, 1.0),
                },
            )
        )
        field.setDrawsBackground_(True)
        field.setBackgroundColor_(NSColor.blackColor())
        field.setTextColor_(NSColor.whiteColor())
        field.setWantsLayer_(True)
        field.layer().setCornerRadius_(FIELD_CORNER_RADIUS)
        field.layer().setMasksToBounds_(True)
        field.layer().setBackgroundColor_(NSColor.blackColor().CGColor())
        field.setDelegate_(self)
        field.setRefusesFirstResponder_(False)
        panel.contentView().addSubview_(field)

        status = NSTextField.alloc().initWithFrame_(
            NSMakeRect(PANEL_INSET, PANEL_INSET, STATUS_WRAP_WIDTH, STATUS_FONT_SIZE)
        )
        status_cell = _CenteredWrappingFieldCell.alloc().initTextCell_("")
        status_cell.setEditable_(False)
        status_cell.setSelectable_(False)
        status_cell.setScrollable_(False)
        status_cell.setWraps_(True)
        status.setCell_(status_cell)
        status.setEditable_(False)
        status.setSelectable_(False)
        status.setBezeled_(False)
        status.setDrawsBackground_(False)
        status.setHidden_(True)
        status.setUsesSingleLineMode_(False)
        status.setLineBreakMode_(NSLineBreakByWordWrapping)
        status.setAlignment_(NSTextAlignmentCenter)
        status.setFont_(NSFont.systemFontOfSize_(STATUS_FONT_SIZE))
        status.setStringValue_("")
        panel.contentView().addSubview_(status)

        scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(
                PANEL_INSET,
                PANEL_INSET,
                PANEL_WIDTH - 2.0 * PANEL_INSET,
                TABLE_HEIGHT - 8.0,
            )
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
        table.setRefusesFirstResponder_(True)
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
        frame.origin.x = (
            visible.origin.x + (visible.size.width - frame.size.width) / 2.0
        )
        frame.origin.y = (
            visible.origin.y + (visible.size.height - frame.size.height) * 0.55
        )
        self.panel.setFrame_display_(frame, True)
        if self._about_panel is not None and self._about_panel.isVisible():
            position_about_panel(self._about_panel, anchor_frame=frame)

    def _completer_loaded(self, result: object) -> None:
        def apply() -> None:
            if isinstance(result, Exception):
                logger.warning("could not load shortcuts: %s", result)
                self._shortcuts_load_failed = True
                self._set_status(format_spotty_bunny_status(result))
                return
            completer, base_url, entries = result  # type: ignore[misc]
            self._completer = completer
            self._base_url = base_url
            self._entries = entries
            self._shortcuts_load_failed = False
            self._set_status("")
            logger.info("shortcut completer ready")
            self._maybe_offer_gh_install()

        _run_on_main(apply)

    def _completion_table_visible(self) -> bool:
        return self.scroll is not None and not self.scroll.isHidden()

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
            rows, blocked_message = result  # type: ignore[misc]
            self._show_completions(rows, blocked_message=blocked_message)

        _run_on_main(apply)

    def _gh_install_ready(self, result: object) -> None:
        def apply() -> None:
            if isinstance(result, Exception):
                logger.warning("gh install failed: %s", result)
                self._set_status(format_spotty_bunny_status(result))
                return
            if result:
                self._set_status("gh installed — run: gh auth login")
                return
            self._set_status(gh_install_guidance())

        _run_on_main(apply)

    def _hide_about_panel(self) -> None:
        if self._about_panel is not None:
            self._about_panel.orderOut_(None)
        self._about_open = False

    def _toggle_about_panel(self) -> None:
        if self._about_open:
            self.hideAbout_(None)
            return
        self._present_about_panel()

    def _hide_completions(self) -> None:
        self._completion_seq += 1
        self._completion_prefix = ""
        self._completion_rows = []
        if self.table is not None:
            self.table.reloadData()
        self._set_table_visible(False)

    def _install_ready(self, result: object) -> None:
        def apply() -> None:
            if isinstance(result, Exception):
                logger.warning("install failed: %s", result)
                self._set_status(format_spotty_bunny_status(result))
                return
            logger.info("install finished; quitting for LaunchAgent")
            quit_ns_app(ns_app=NSApp, post_wake=_post_wake_event)

        _run_on_main(apply)

    def _layout_search_chrome(
        self, *, table_visible: bool, status_message: str | None = None
    ) -> None:
        status_band = self._status_band_height(status_message)
        table = TABLE_HEIGHT if table_visible else 0.0
        origin_y = PANEL_INSET + table + status_band
        if self.field is not None:
            self.field.setFrame_(
                NSMakeRect(FIELD_LEFT, origin_y, FIELD_WIDTH, FIELD_HEIGHT)
            )
        if self.logo is not None:
            self.logo.setFrame_(
                NSMakeRect(
                    LOGO_LEFT,
                    origin_y + (FIELD_HEIGHT - LOGO_SIZE) / 2.0,
                    LOGO_SIZE,
                    LOGO_SIZE,
                )
            )
        if self.status is not None:
            has_status = status_band > 0.0
            self.status.setHidden_(not has_status)
            if has_status:
                if table_visible:
                    origin_status = PANEL_INSET + table
                    status_height = status_band
                else:
                    origin_status = 0.0
                    status_height = origin_y
                self.status.setFrame_(
                    NSMakeRect(
                        PANEL_INSET, origin_status, STATUS_WRAP_WIDTH, status_height
                    )
                )

    def _load_completer(self) -> object:
        base_url = resolve_base_url(persist=False, allow_prompt=False)
        entries = fetch_key_entries(base_url=base_url)
        if entries_need_github_completion(entries):
            token = resolve_github_token()
            if token:
                bootstrap_github_completion_cache(
                    url_templates=[entry.url for entry in entries],
                    token=token,
                )
            else:
                warn_github_completion(
                    "github-startup-unavailable",
                    "GitHub Tab completion unavailable at startup: %s",
                    github_completion_unavailable_message(),
                )
        completer = make_spotty_completer(
            entries=entries,
            suggestions_fn=lambda query: fetch_suggestions(query, base_url=base_url),
        )
        return completer, base_url, entries

    def _maybe_offer_gh_install(self) -> None:
        """Surface missing ``gh``; admins with Homebrew may install in-place."""
        if not entries_need_github_completion(self._entries):
            return
        if github_token_from_environ() or gh_is_available():
            return
        guidance = gh_install_guidance()
        if can_offer_gh_install() and _confirm_install_gh():
            self._set_status("Installing gh via Homebrew…")
            self._io.submit(install_gh_via_homebrew, self._gh_install_ready)
            return
        self._set_status(guidance)

    def _move_completion(self, selector: str) -> None:
        if (
            not self._completion_rows
            or not self._completion_table_visible()
            or self.table is None
            or self.field is None
        ):
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
        if completion_browse_all(self._completion_prefix):
            return
        row = self._completion_rows[idx]
        self._set_field_text(apply_completion(self._completion_prefix, row))

    def _paint_search_editor(self) -> None:
        if self.field is None:
            return
        editor = self.field.currentEditor()
        if editor is None:
            return
        inner = self.field.cell().drawingRectForBounds_(self.field.bounds())
        editor.setFrame_(inner)
        editor.setDrawsBackground_(False)
        editor.setBackgroundColor_(NSColor.blackColor())
        editor.setTextColor_(NSColor.whiteColor())
        editor.setInsertionPointColor_(NSColor.whiteColor())
        editor.setAlignment_(NSTextAlignmentLeft)
        editor.setFont_(self.field.font())
        editor.setTextContainerInset_(NSMakeSize(0.0, 0.0))
        container = editor.textContainer()
        if container is not None:
            container.setLineFragmentPadding_(0.0)

    def _perform_install(self) -> None:
        if install_agent(skip_chord_confirm=True) != 0:
            raise RuntimeError("LaunchAgent install failed")

    def _perform_upgrade(self) -> None:
        from app.cli import run_upgrade

        # Bounce only the server agent here; bouncing Spotty from inside the
        # overlay would kill this process mid-upgrade. Plist refresh + quit
        # lets launchd relaunch Spotty with the new binary.
        run_upgrade(
            print_fn=lambda message: logger.info("%s", message),
            refresh_launch_agents="server",
        )
        if refresh_agent_plist() != 0:
            raise RuntimeError("LaunchAgent plist refresh failed")

    def _present_about_panel(self) -> None:
        if self._about_panel is not None:
            self._about_panel.setDelegate_(None)
            self._about_panel.orderOut_(None)
            self._about_panel.close()
            self._about_panel = None
        self._about_panel = build_about_panel(update=self._update_status)
        self._about_panel.setDelegate_(self)
        if self.panel is not None:
            position_about_panel(self._about_panel, anchor_frame=self.panel.frame())
        self._about_open = True
        self._about_panel.orderFrontRegardless()
        self._about_panel.makeKeyAndOrderFront_(None)

    def _rebuild_logo_menu(self, menu) -> None:
        menu.removeAllItems()
        for title, action in logo_menu_specs(
            installed=is_agent_installed(),
            outdated=self._update_status.outdated,
        ):
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                title,
                action,
                "",
            )
            item.setTarget_(self)
            menu.addItem_(item)

    def _request_completions(self) -> None:
        if self._completer is None or self.field is None:
            logger.warning("tab ignored (completer not ready)")
            if self._completer is None and self._shortcuts_load_failed:
                self._set_status(SHORTCUTS_LOAD_FAILED)
            return
        text = str(self.field.stringValue())
        logger.info("tab complete %r", text)
        self._completion_rows = []
        if self.table is not None:
            self.table.reloadData()
        self._set_table_visible(False)
        self._completion_prefix = text
        self._completion_seq += 1
        seq = self._completion_seq
        completer = self._completer
        entries = list(self._entries)

        def fetch() -> object:
            rows = completions_for(text, completer)
            blocked: str | None = None
            if not rows:
                # Resolve token off the AppKit thread (gh auth token / keychain).
                blocked = github_param_completion_blocked_message(text, entries)
            return rows, blocked

        self._io.submit(
            fetch,
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
                self._set_status(format_spotty_bunny_status(result))
                return
            logger.info("opened %s", result)
            self.hide()

        _run_on_main(apply)

    def _set_field_text(self, text: str) -> None:
        if self.field is None:
            return
        self._applying_completion = True
        self.field.setStringValue_(text)
        editor = self.field.currentEditor()
        if editor is not None:
            editor.setString_(text)
            editor.setSelectedRange_(NSMakeRange(len(text), 0))

        def clear_flag() -> None:
            self._applying_completion = False

        # Deferred so a delayed controlTextDidChange_ still sees the flag and
        # does not immediately hide the completion table we just showed.
        NSOperationQueue.mainQueue().addOperationWithBlock_(clear_flag)

    def _set_status(self, message: str) -> None:
        if self.status is None:
            return
        if message:
            self.status.setAttributedStringValue_(
                self._status_attributed(message, color=self._status_error_color())
            )
        else:
            self.status.setStringValue_("")
        table_visible = self.scroll is not None and not self.scroll.isHidden()
        if self.panel is not None:
            frame = self.panel.frame()
            frame.size.height = (
                PANEL_HEIGHT
                + (TABLE_HEIGHT if table_visible else 0.0)
                + self._status_band_height(message)
            )
            self.panel.setFrame_display_(frame, True)
        self._layout_search_chrome(table_visible=table_visible, status_message=message)
        self._center_panel()

    def _set_table_visible(self, visible: bool) -> None:
        if self.scroll is None or self.panel is None or self.field is None:
            return
        self.scroll.setHidden_(not visible)
        frame = self.panel.frame()
        frame.size.height = (
            PANEL_HEIGHT
            + (TABLE_HEIGHT if visible else 0.0)
            + self._status_band_height()
        )
        self.panel.setFrame_display_(frame, True)
        self._layout_search_chrome(table_visible=visible)
        if visible:
            self.scroll.setFrame_(
                NSMakeRect(
                    PANEL_INSET,
                    PANEL_INSET,
                    PANEL_WIDTH - 2.0 * PANEL_INSET,
                    TABLE_HEIGHT - 8.0,
                )
            )
        self._center_panel()

    def _schedule_update_check(self) -> None:
        if self._update_check_pending:
            return
        self._update_check_pending = True
        self._io.submit(refresh_update_status, self._update_check_ready)

    def _show_completions(
        self,
        rows: list[CompletionRow],
        *,
        blocked_message: str | None = None,
    ) -> None:
        self._completion_rows = rows
        if not rows:
            prefix = self._completion_prefix
            self._hide_completions()
            surface_blocked_github_completion(
                prefix,
                blocked_message,
                set_status=self._set_status,
            )
            return
        self._set_status("")
        if self.field is not None and should_auto_insert_completion(
            self._completion_prefix, rows
        ):
            self._set_field_text(apply_completion(self._completion_prefix, rows[0]))
        if self.table is not None:
            self.table.reloadData()
            self.table.selectRowIndexes_byExtendingSelection_(
                NSIndexSet.indexSetWithIndex_(0),
                False,
            )
            self.table.scrollRowToVisible_(0)
        self._set_table_visible(
            completion_table_should_show(self._completion_prefix, rows)
        )

    def _status_attributed(self, message: str, *, color):
        """Build wrapping, centered status copy with Courier command spans."""
        wrapped = wrap_status_preferring_punctuation(
            message, fits=self._status_line_fits
        )
        return self._status_runs_attributed(wrapped, color=color)

    def _status_band_height(self, message: str | None = None) -> float:
        text = message
        if text is None and self.status is not None:
            text = str(self.status.stringValue())
        if not text:
            return 0.0
        current = self._status_text_height(text)
        canned = max(
            (
                self._status_text_height(line)
                for line in canned_spotty_bunny_status_lines()
            ),
            default=current,
        )
        return 2.0 * STATUS_INSET + max(current, canned)

    def _status_error_color(self):
        red, green, blue = STATUS_ERROR_RGB
        return NSColor.colorWithSRGBRed_green_blue_alpha_(red, green, blue, 1.0)

    def _status_line_fits(self, text: str) -> bool:
        attributed = self._status_runs_attributed(
            text.replace("\n", " "),
            color=self._status_error_color(),
            wrap=False,
        )
        bounds = attributed.boundingRectWithSize_options_(
            NSMakeSize(10000.0, 10000.0),
            NSStringDrawingUsesLineFragmentOrigin | NSStringDrawingUsesFontLeading,
        )
        return float(math.ceil(bounds.size.width)) <= STATUS_WRAP_WIDTH

    def _status_runs_attributed(self, message: str, *, color, wrap: bool = True):
        body = NSFont.systemFontOfSize_(STATUS_FONT_SIZE)
        mono = NSFont.fontWithName_size_(STATUS_COMMAND_FONT, STATUS_FONT_SIZE)
        if mono is None:
            mono = NSFont.userFixedPitchFontOfSize_(STATUS_FONT_SIZE)
        result = NSMutableAttributedString.alloc().init()
        for text, is_command in status_text_runs(message):
            chunk = NSAttributedString.alloc().initWithString_attributes_(
                text,
                {
                    NSFontAttributeName: mono if is_command else body,
                    NSForegroundColorAttributeName: color,
                },
            )
            result.appendAttributedString_(chunk)
        if result.length() == 0:
            return result
        paragraph = NSMutableParagraphStyle.alloc().init()
        paragraph.setAlignment_(NSTextAlignmentCenter)
        if wrap:
            paragraph.setLineBreakMode_(NSLineBreakByWordWrapping)
        else:
            paragraph.setLineBreakMode_(NSLineBreakByClipping)
        result.addAttribute_value_range_(
            NSParagraphStyleAttributeName,
            paragraph,
            NSMakeRange(0, result.length()),
        )
        return result

    def _status_text_height(self, message: str) -> float:
        if not message:
            return 0.0
        attributed = self._status_attributed(message, color=self._status_error_color())
        bounds = attributed.boundingRectWithSize_options_(
            NSMakeSize(STATUS_WRAP_WIDTH, 10000.0),
            NSStringDrawingUsesLineFragmentOrigin | NSStringDrawingUsesFontLeading,
        )
        return float(math.ceil(bounds.size.height))

    def _submit_query(self) -> None:
        if self.field is None or self._resolving:
            return
        query = str(self.field.stringValue()).strip()
        if (
            not query
            and self._completion_table_visible()
            and self._completion_rows
            and self.table is not None
        ):
            idx = int(self.table.selectedRow())
            if idx < 0:
                idx = 0
            if idx < len(self._completion_rows):
                query = apply_completion(
                    self._completion_prefix, self._completion_rows[idx]
                ).strip()
                self._set_field_text(query)
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

    def _update_check_ready(self, result: object) -> None:
        def apply() -> None:
            self._update_check_pending = False
            if isinstance(result, Exception):
                logger.warning("PyPI version check failed: %s", result)
                return
            if isinstance(result, UpdateStatus):
                self._update_status = result
                self._apply_update_status()

        _run_on_main(apply)

    def _upgrade_ready(self, result: object) -> None:
        def apply() -> None:
            if isinstance(result, Exception):
                logger.warning("upgrade failed: %s", result)
                self._set_status(format_spotty_bunny_status(result))
                return
            logger.info("upgrade finished; quitting for relaunch")
            quit_ns_app(ns_app=NSApp, post_wake=_post_wake_event)

        _run_on_main(apply)


class SpottyBunnyLogoButton(NSButton):
    """Bunny icon: left-click About; right-click Install/Quit/Uninstall/Upgrade."""

    def rightMouseDown_(self, event) -> None:
        menu = self.menu()
        if menu is None:
            objc.super(SpottyBunnyLogoButton, self).rightMouseDown_(event)
            return
        NSMenu.popUpContextMenu_withEvent_forView_(menu, event, self)


class SpottyBunnyPanel(NSPanel):
    """Borderless floating panel that can still host a key field editor."""

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
        if int(event.keyCode()) == TAB_KEYCODE:
            delegate = self.delegate()
            if delegate is not None:
                delegate.completeWithTab_(self)
            return
        if int(event.keyCode()) in {PAGE_DOWN_KEYCODE, PAGE_UP_KEYCODE}:
            delegate = self.delegate()
            selector = page_selector_for_keycode(int(event.keyCode()))
            if (
                delegate is not None
                and selector is not None
                and getattr(delegate, "_completion_table_visible", lambda: False)()
                and getattr(delegate, "_completion_rows", None)
            ):
                delegate._move_completion(selector)
                return
        objc.super(SpottyBunnyPanel, self).keyDown_(event)

    def keyUp_(self, event) -> None:
        if int(event.keyCode()) == ESCAPE_KEYCODE:
            delegate = self.delegate()
            if delegate is not None:
                delegate.releaseEscape_(self)
            return
        objc.super(SpottyBunnyPanel, self).keyUp_(event)

    def performKeyEquivalent_(self, event) -> bool:
        if int(event.keyCode()) == ESCAPE_KEYCODE:
            self.cancelOperation_(self)
            return True
        if _dispatch_edit_key_equivalent(event):
            return True
        return bool(objc.super(SpottyBunnyPanel, self).performKeyEquivalent_(event))


class SpottyBunnySearchField(NSTextField):
    """Search field that keeps Cut/Copy/Paste working without an Edit menu bar."""

    def performKeyEquivalent_(self, event) -> bool:
        if _dispatch_edit_key_equivalent(event):
            return True
        return bool(
            objc.super(SpottyBunnySearchField, self).performKeyEquivalent_(event)
        )


def _primary_screen():
    """Return the menu-bar display (screens[0]), not the keyboard-focus screen."""
    screens = NSScreen.screens()
    return screens[0] if screens else None


def run_spotty_bunny_app() -> int:
    """Run NSApplication until SIGINT (Ctrl-C) or NSApp.stop_."""
    NSApplication.sharedApplication()
    NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    NSApp.finishLaunching()
    _install_edit_menu()
    controller = SpottyBunnyController.alloc().init()
    logger.info("NSApplication ready (activationPolicy=accessory)")
    _install_event_tap(controller)
    _register_wake_observer(controller)
    _schedule_tap_health_checks(controller)
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


class _CenteredFieldCell(NSTextFieldCell):
    """Pad the search field; left-align and vertically center hint and caret."""

    def drawInteriorWithFrame_inView_(self, rect, view):
        objc.super(_CenteredFieldCell, self).drawInteriorWithFrame_inView_(
            self._vertically_centered_text_rect(rect),
            view,
        )

    def drawingRectForBounds_(self, rect):
        return self._vertically_centered_text_rect(rect)

    def editWithFrame_inView_editor_delegate_event_(
        self, rect, view, editor, delegate, event
    ):
        objc.super(
            _CenteredFieldCell, self
        ).editWithFrame_inView_editor_delegate_event_(
            self._vertically_centered_text_rect(rect),
            view,
            editor,
            delegate,
            event,
        )

    def selectWithFrame_inView_editor_delegate_start_length_(
        self, rect, view, editor, delegate, start, length
    ):
        objc.super(
            _CenteredFieldCell, self
        ).selectWithFrame_inView_editor_delegate_start_length_(
            self._vertically_centered_text_rect(rect),
            view,
            editor,
            delegate,
            start,
            length,
        )

    def titleRectForBounds_(self, rect):
        return self._vertically_centered_text_rect(rect)

    def _padded_rect(self, rect):
        return NSMakeRect(
            rect.origin.x + FIELD_TEXT_INSET,
            rect.origin.y + FIELD_TEXT_INSET,
            max(0.0, rect.size.width - 2.0 * FIELD_TEXT_INSET),
            max(0.0, rect.size.height - 2.0 * FIELD_TEXT_INSET),
        )

    def _text_line_height(self) -> float:
        font = self.font()
        if font is None:
            return 0.0
        return float(NSLayoutManager.alloc().init().defaultLineHeightForFont_(font))

    def _vertically_centered_text_rect(self, rect):
        padded = self._padded_rect(rect)
        text_height = self._text_line_height()
        if text_height <= 0.0 or padded.size.height <= text_height:
            return padded
        inset = (padded.size.height - text_height) / 2.0
        return NSMakeRect(
            padded.origin.x,
            padded.origin.y + inset,
            padded.size.width,
            text_height,
        )


class _CenteredWrappingFieldCell(NSTextFieldCell):
    """Wrap status copy and center the text block vertically in the cell."""

    def drawInteriorWithFrame_inView_(self, rect, view):
        attributed = self.attributedStringValue()
        if attributed is not None and int(attributed.length()) > 0:
            attributed.drawWithRect_options_(
                self._centered_title_rect(rect),
                NSStringDrawingUsesLineFragmentOrigin | NSStringDrawingUsesFontLeading,
            )
            return
        objc.super(_CenteredWrappingFieldCell, self).drawInteriorWithFrame_inView_(
            self._centered_title_rect(rect),
            view,
        )

    def titleRectForBounds_(self, rect):
        return self._centered_title_rect(
            objc.super(_CenteredWrappingFieldCell, self).titleRectForBounds_(rect)
        )

    def _centered_title_rect(self, rect):
        attributed = self.attributedStringValue()
        if attributed is None or int(attributed.length()) == 0:
            text = str(self.stringValue() or "")
            if not text:
                return rect
            font = self.font() or NSFont.systemFontOfSize_(STATUS_FONT_SIZE)
            attributed = NSAttributedString.alloc().initWithString_attributes_(
                text,
                {NSFontAttributeName: font},
            )
        bounds = attributed.boundingRectWithSize_options_(
            NSMakeSize(rect.size.width, 10000.0),
            NSStringDrawingUsesLineFragmentOrigin | NSStringDrawingUsesFontLeading,
        )
        text_height = float(math.ceil(bounds.size.height))
        if rect.size.height <= text_height:
            return rect
        inset = (rect.size.height - text_height) / 2.0
        return NSMakeRect(
            rect.origin.x,
            rect.origin.y + inset,
            rect.size.width,
            text_height,
        )


def _confirm_install_gh() -> bool:
    """Ask before running ``brew install gh`` from the overlay."""
    alert = NSAlert.alloc().init()
    alert.setAlertStyle_(NSAlertStyleWarning)
    alert.setMessageText_("Install GitHub CLI?")
    alert.setInformativeText_(
        "Repo Tab completion needs the GitHub CLI (gh). "
        "Install it with Homebrew now (brew install gh)?"
    )
    alert.addButtonWithTitle_("Install")
    alert.addButtonWithTitle_("Not now")
    return int(alert.runModal()) == int(NSAlertFirstButtonReturn)


def _confirm_uninstall() -> bool:
    """Ask before removing the LaunchAgent. Uninstall is the first button."""
    alert = NSAlert.alloc().init()
    alert.setAlertStyle_(NSAlertStyleWarning)
    alert.setMessageText_(UNINSTALL_MENU_TITLE)
    alert.setInformativeText_(UNINSTALL_INFORMATIVE)
    alert.addButtonWithTitle_(UNINSTALL_MENU_TITLE)
    alert.addButtonWithTitle_("Cancel")
    return int(alert.runModal()) == int(NSAlertFirstButtonReturn)


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


def _dispatch_edit_key_equivalent(event) -> bool:
    """Send Cut/Copy/Paste/Select All/Undo to the first responder when possible."""
    flags = int(event.modifierFlags()) & int(
        NSEventModifierFlagDeviceIndependentFlagsMask
    )
    command = bool(flags & int(NSEventModifierFlagCommand))
    control = bool(flags & int(NSEventModifierFlagControl))
    option = bool(flags & int(NSEventModifierFlagOption))
    shift = bool(flags & int(NSEventModifierFlagShift))
    if not edit_command_modifiers_ok(command=command, control=control, option=option):
        return False
    characters = event.charactersIgnoringModifiers() or ""
    action = edit_action_for_key(str(characters), command=True, shift=shift)
    if action is None:
        return False
    return bool(NSApp.sendAction_to_from_(action, None, None))


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


def _check_event_tap_health(controller: SpottyBunnyController) -> None:
    """Re-enable or reinstall the tap when macOS disables it silently."""
    tap = controller.tap
    action = decide_tap_health_check(
        tap_is_none=tap is None,
        tap_enabled=_event_tap_enabled(tap) if tap is not None else False,
    )
    if action == "reinstall":
        logger.warning("event tap health check: tap missing; reinstalling")
        _reinstall_event_tap(controller)
        return
    if action == "ok":
        try_write_spotty_bunny_health(tap=TAP_STATE_OK)
        return
    logger.warning("event tap health check: tap disabled; re-enabling")
    assert tap is not None
    CGEventTapEnable(tap, True)
    if _event_tap_enabled(tap):
        try_write_spotty_bunny_health(tap=TAP_STATE_OK)
        return
    try_write_spotty_bunny_health(tap=TAP_STATE_DISABLED)
    logger.warning("event tap health check: re-enable failed; reinstalling")
    _reinstall_event_tap(controller)


def _create_event_tap_callback(
    controller: SpottyBunnyController,
    *,
    tap_holder: dict[str, object],
) -> object:
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
                if _event_tap_enabled(tap):
                    try_write_spotty_bunny_health(tap=TAP_STATE_OK)
                else:
                    _run_on_main(lambda: _reinstall_event_tap(controller))
            else:
                try_write_spotty_bunny_health(tap=TAP_STATE_DISABLED)
            return event
        keycode = int(CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode))
        flags = int(CGEventGetFlags(event))
        hid_left = _control_key_down(CONTROL_LEFT_KEYCODE)
        hid_right = _control_key_down(CONTROL_RIGHT_KEYCODE)
        flag_left = bool(flags & DEVICE_LEFT_CONTROL_MASK)
        flag_right = bool(flags & DEVICE_RIGHT_CONTROL_MASK)
        key_name = _describe_event_key(keycode, flags)
        if keycode == ESCAPE_KEYCODE:
            if event_type == kCGEventKeyDown and controller.visible:
                logger.info("tap Escape → dismiss")
                _run_on_main(lambda: controller.dismissWithEscape_(None))
            elif event_type == kCGEventKeyUp:
                _run_on_main(lambda: controller.releaseEscape_(None))
            return event
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

            def chord_action() -> None:
                controller.toggle()
                _record_tap_activity(chord=True)

            _run_on_main(chord_action)
        return event

    return callback


def _event_tap_enabled(tap: object) -> bool:
    return bool(CGEventTapIsEnabled(tap))


def _exit_after_tap_failure(failures: int) -> None:
    logger.error(
        "event tap reinstall failed %s times; exiting for KeepAlive restart",
        failures,
    )
    os._exit(1)


def _handle_reinstall_failure() -> None:
    prior = read_spotty_bunny_health()
    failures, should_exit = process_reinstall_failure(prior)
    try_write_spotty_bunny_health(
        tap=TAP_STATE_MISSING,
        reinstall_failures=failures,
    )
    if should_exit:
        _exit_after_tap_failure(failures)


def _install_event_tap(controller: SpottyBunnyController) -> None:
    tap_holder: dict[str, object] = {}
    callback = _create_event_tap_callback(controller, tap_holder=tap_holder)
    CGRequestListenEventAccess()
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
    try_write_spotty_bunny_health(tap=TAP_STATE_OK, reinstall_failures=0)
    reset_reinstall_failures()


def _record_tap_activity(*, chord: bool) -> None:
    now = time.time()
    try_write_spotty_bunny_health(
        last_chord_at=now if chord else None,
        last_event_at=now,
        tap=TAP_STATE_OK,
    )


def _register_wake_observer(controller: SpottyBunnyController) -> None:
    center = NSWorkspace.sharedWorkspace().notificationCenter()
    center.addObserver_selector_name_object_(
        controller,
        "workspaceDidWake:",
        NSWorkspaceDidWakeNotification,
        None,
    )


def _reinstall_event_tap(controller: SpottyBunnyController) -> None:
    try_write_spotty_bunny_health(tap=TAP_STATE_REINSTALLING)
    try:
        _teardown_event_tap(controller)
        _install_event_tap(controller)
    except SpottyBunnyEventTapError:
        _handle_reinstall_failure()
        return
    except Exception:
        logger.exception("event tap reinstall failed unexpectedly")
        _handle_reinstall_failure()
        return
    try_write_spotty_bunny_health(tap=TAP_STATE_OK, reinstall_failures=0)
    reset_reinstall_failures()


def _schedule_tap_health_checks(controller: SpottyBunnyController) -> None:
    controller._tap_health_timer = (
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            TAP_HEALTH_CHECK_INTERVAL_S,
            controller,
            "checkEventTapHealth:",
            None,
            True,
        )
    )


def _teardown_event_tap(controller: SpottyBunnyController) -> None:
    tap = controller.tap
    source = controller.source
    if tap is not None:
        CGEventTapEnable(tap, False)
        CFMachPortInvalidate(tap)
    if source is not None:
        CFRunLoopRemoveSource(CFRunLoopGetCurrent(), source, kCFRunLoopCommonModes)
    controller.callback = None
    controller.source = None
    controller.tap = None


def _install_edit_menu() -> None:
    """Install a hidden Edit menu so Command cut/copy/paste reach the field editor."""
    main = NSMenu.alloc().initWithTitle_("MainMenu")
    edit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Edit", None, "")
    edit_menu = NSMenu.alloc().initWithTitle_("Edit")
    command = int(NSEventModifierFlagCommand)
    command_shift = command | int(NSEventModifierFlagShift)
    for title, action, key, modifiers in (
        ("Undo", "undo:", "z", command),
        ("Redo", "redo:", "z", command_shift),
        ("Cut", "cut:", "x", command),
        ("Copy", "copy:", "c", command),
        ("Paste", "paste:", "v", command),
        ("Select All", "selectAll:", "a", command),
    ):
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            title, action, key
        )
        item.setKeyEquivalentModifierMask_(modifiers)
        edit_menu.addItem_(item)
    edit_item.setSubmenu_(edit_menu)
    main.addItem_(edit_item)
    NSApp.setMainMenu_(main)


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

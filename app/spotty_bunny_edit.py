"""Standard Edit-menu key equivalents for accessory apps without a menu bar."""

from __future__ import annotations

# Command+letter → first-responder action (ASCII lowercase).
EDIT_COMMAND_ACTIONS: dict[str, str] = {
    "a": "selectAll:",
    "c": "copy:",
    "v": "paste:",
    "x": "cut:",
    "z": "undo:",
}

# Command+Shift+letter → first-responder action.
EDIT_COMMAND_SHIFT_ACTIONS: dict[str, str] = {
    "z": "redo:",
}

# Home/End (and document-scroll aliases) → caret begin/end of the field.
# On macOS, dedicated Home/End keys historically map to document scroll, which
# is a no-op in a single-line NSTextField — remap them to line begin/end.
LINE_END_SELECTORS = frozenset(
    {
        "moveToEndOfDocument:",
        "moveToEndOfDocumentAndModifySelection:",
        "moveToEndOfLine:",
        "moveToEndOfLineAndModifySelection:",
        "moveToRightEndOfLine:",
        "moveToRightEndOfLineAndModifySelection:",
        "scrollToEndOfDocument:",
    }
)

LINE_START_SELECTORS = frozenset(
    {
        "moveToBeginningOfDocument:",
        "moveToBeginningOfDocumentAndModifySelection:",
        "moveToBeginningOfLine:",
        "moveToBeginningOfLineAndModifySelection:",
        "moveToLeftEndOfLine:",
        "moveToLeftEndOfLineAndModifySelection:",
        "scrollToBeginningOfDocument:",
    }
)


def edit_action_for_key(
    characters: str,
    *,
    command: bool,
    shift: bool,
) -> str | None:
    """Return a Cocoa edit selector for a Command key chord, else ``None``."""
    if not command or not characters:
        return None
    key = characters[:1].lower()
    if shift:
        return EDIT_COMMAND_SHIFT_ACTIONS.get(key)
    return EDIT_COMMAND_ACTIONS.get(key)


def edit_command_modifiers_ok(
    *,
    command: bool,
    control: bool,
    option: bool,
) -> bool:
    """True when modifiers are a Command edit chord (Caps Lock / Fn ignored)."""
    return command and not control and not option


def is_line_end_selector(selector: str) -> bool:
    """True when *selector* should place the caret (or selection) at line end."""
    return selector in LINE_END_SELECTORS


def is_line_navigation_selector(selector: str) -> bool:
    """True when *selector* is Home/End / line / document begin-or-end."""
    return selector in LINE_START_SELECTORS or selector in LINE_END_SELECTORS


def is_line_start_selector(selector: str) -> bool:
    """True when *selector* should place the caret (or selection) at line start."""
    return selector in LINE_START_SELECTORS


def line_navigation_modifies_selection(selector: str) -> bool:
    """True when *selector* extends the selection (Shift+Home/End variants)."""
    return selector.endswith("AndModifySelection:")


def line_navigation_selected_range(
    *,
    text_length: int,
    selected_location: int,
    selected_length: int,
    to_start: bool,
    modify: bool,
    affinity_upstream: bool,
) -> tuple[int, int]:
    """Return ``(location, length)`` for a Home/End (optionally Shift) move.

    Non-modify collapses the caret to the start or end of the field. Modify
    keeps AppKit's selection anchor fixed and moves the active end: upstream
    affinity means the anchor is at ``location + length`` (backward selection);
    otherwise the anchor is at ``location``.
    """
    if not modify:
        if to_start:
            return (0, 0)
        return (text_length, 0)
    if selected_length > 0 and affinity_upstream:
        anchor = selected_location + selected_length
    else:
        anchor = selected_location
    if to_start:
        return (0, max(0, anchor))
    return (anchor, max(0, text_length - anchor))

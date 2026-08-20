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

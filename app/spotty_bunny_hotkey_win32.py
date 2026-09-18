"""Windows virtual-key event adapter for ChordTracker (win32).

``WH_KEYBOARD_LL`` delivers exactly one ``WM_KEYDOWN`` per physical press
(repeated on OS auto-repeat while held) and one ``WM_KEYUP`` per release,
with ``VK_LCONTROL``/``VK_RCONTROL`` already disambiguated by Windows.
That's simpler than macOS Quartz's ``flagsChanged``, which needs
:func:`app.spotty_bunny_hotkey.apply_control_event`'s HID-blind /
duplicate-echo handling to work around sensor ambiguity — this adapter just
tracks each Control key's held state and syncs it into the shared,
platform-agnostic :class:`~app.spotty_bunny_hotkey.ChordTracker`.

Pure and import-light on purpose (no ``pywin32``) so it stays testable on
any platform; the actual hook installation lives in
:mod:`app.spotty_bunny_hook_win32`.
"""

from __future__ import annotations

import logging

from app.spotty_bunny_hotkey import ChordTracker

logger = logging.getLogger(__name__)

VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3


def apply_win32_key_event(
    tracker: ChordTracker,
    *,
    vk_code: int,
    key_down: bool,
    left_vk: int = VK_LCONTROL,
    right_vk: int = VK_RCONTROL,
) -> bool:
    """Update *tracker* from one ``WH_KEYBOARD_LL`` key event.

    Returns True when the chord completes. Keys other than *left_vk*/
    *right_vk* are ignored without touching the tracker's held state.
    """
    if vk_code == left_vk:
        return tracker.sync(left_down=key_down, right_down=tracker.held_right)
    if vk_code == right_vk:
        return tracker.sync(left_down=tracker.held_left, right_down=key_down)
    return False


def resolve_win32_chord_vks(choice: str) -> tuple[int, int]:
    """Resolve a configured hotkey *choice* to a ``(left_vk, right_vk)`` pair.

    Windows keyboards essentially always have two physical Control keys, so
    unlike macOS's ``resolve_auto_chord_keys``, ``"auto"`` needs no
    external-keyboard heuristic here -- it resolves to the same Control
    chord as ``"control"``. Windows has no Option/Command keys, so
    ``"option"``/``"command"`` (meaningful only on macOS, e.g. a config.toml
    shared across a dual-boot setup) fall back to the Control chord too,
    logged once so a mismatch doesn't look silently ignored.
    """
    normalized = choice.strip().lower()
    if normalized in ("option", "command"):
        logger.warning(
            "hotkey choice %r has no Windows equivalent; using the Control chord",
            choice,
        )
    return VK_LCONTROL, VK_RCONTROL

"""Dual-Control chord tracker (pure Python, no AppKit)."""

from __future__ import annotations

CONTROL_LEFT_KEYCODE = 59
CONTROL_RIGHT_KEYCODE = 62


class ChordTracker:
    """Fire once when the second Control key goes down while the first is held.

    Hold left *or* right Control, then press the other. Releasing either key
    returns to a one-held or idle state so a later press can fire again.
    Pressing both from idle in a single update does not fire.
    """

    def __init__(self) -> None:
        self._held_left = False
        self._held_right = False

    def sync(self, *, left_down: bool, right_down: bool) -> bool:
        """Update held state. Return True when the chord completes."""
        fired = (left_down and not self._held_left and self._held_right) or (
            right_down and not self._held_right and self._held_left
        )
        self._held_left = left_down
        self._held_right = right_down
        return fired

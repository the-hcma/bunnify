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

    @property
    def held_left(self) -> bool:
        return self._held_left

    @property
    def held_right(self) -> bool:
        return self._held_right

    def sync(self, *, left_down: bool, right_down: bool) -> bool:
        """Update held state. Return True when the chord completes."""
        fired = (left_down and not self._held_left and self._held_right) or (
            right_down and not self._held_right and self._held_left
        )
        self._held_left = left_down
        self._held_right = right_down
        return fired


def apply_hid_snapshot(
    tracker: ChordTracker,
    *,
    keycode: int,
    left_down: bool,
    right_down: bool,
) -> bool:
    """Apply a HID snapshot from one Control key event.

    When both keys already read down but the tracker is idle (batched
    ``flagsChanged``), treat *keycode* as the completing press so a fast
    hold-one-then-the-other still fires. A single ``sync(True, True)`` from
    idle still does not fire.
    """
    idle = not tracker.held_left and not tracker.held_right
    if idle and left_down and right_down:
        if keycode == CONTROL_LEFT_KEYCODE:
            tracker.sync(left_down=False, right_down=True)
            return tracker.sync(left_down=True, right_down=True)
        if keycode == CONTROL_RIGHT_KEYCODE:
            tracker.sync(left_down=True, right_down=False)
            return tracker.sync(left_down=True, right_down=True)
    return tracker.sync(left_down=left_down, right_down=right_down)

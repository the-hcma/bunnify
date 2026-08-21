"""Dual-Control chord tracker (pure Python, no AppKit)."""

from __future__ import annotations

import time
from collections.abc import Callable

CONTROL_LEFT_KEYCODE = 59
CONTROL_RIGHT_KEYCODE = 62
ESCAPE_KEYCODE = 53
PAGE_DOWN_KEYCODE = 121
PAGE_UP_KEYCODE = 116
TAB_KEYCODE = 48


class ChordTracker:
    """Fire once when the second Control key goes down while the first is held.

    Hold left *or* right Control, then press the other. Releasing either key
    returns to a one-held or idle state so a later press can fire again.
    Pressing both from idle in a single update does not fire.
    """

    def __init__(self, *, monotonic: Callable[[], float] | None = None) -> None:
        self._held_left = False
        self._held_right = False
        self._last_event_at = 0.0
        self._last_event_signature: tuple[int, bool, bool, bool, bool, bool] | None = (
            None
        )
        self._monotonic = time.monotonic if monotonic is None else monotonic

    @property
    def held_left(self) -> bool:
        return self._held_left

    @property
    def held_right(self) -> bool:
        return self._held_right

    def record_event_signature(
        self, signature: tuple[int, bool, bool, bool, bool, bool]
    ) -> bool:
        """Return True when *signature* is a duplicate within the echo window.

        HID-blind Control press and release can share the same sensor bits.
        Ignore only echoes that arrive inside ``DUPLICATE_EVENT_WINDOW_S`` so a
        later release or repress still toggles.
        """
        now = self._monotonic()
        if (
            signature == self._last_event_signature
            and now - self._last_event_at < DUPLICATE_EVENT_WINDOW_S
        ):
            return True
        self._last_event_at = now
        self._last_event_signature = signature
        return False

    def sync(self, *, left_down: bool, right_down: bool) -> bool:
        """Update held state. Return True when the chord completes."""
        fired = (left_down and not self._held_left and self._held_right) or (
            right_down and not self._held_right and self._held_left
        )
        self._held_left = left_down
        self._held_right = right_down
        return fired


# IOKit IOLLEvent.h: NX_DEVICELCTLKEYMASK / NX_DEVICERCTLKEYMASK in CGEvent flags.
DEVICE_LEFT_CONTROL_MASK = 0x00000001
DEVICE_RIGHT_CONTROL_MASK = 0x00002000
# Quartz may deliver two flagsChanged for one physical press a few ms apart.
DUPLICATE_EVENT_WINDOW_S = 0.008

# Carbon HIToolbox Events.h kVK_* (ANSI US). Ordered by keycode.
KEYCODE_NAMES: dict[int, str] = {
    0: "A",
    1: "S",
    2: "D",
    3: "F",
    4: "H",
    5: "G",
    6: "Z",
    7: "X",
    8: "C",
    9: "V",
    10: "Section",
    11: "B",
    12: "Q",
    13: "W",
    14: "E",
    15: "R",
    16: "Y",
    17: "T",
    18: "1",
    19: "2",
    20: "3",
    21: "4",
    22: "6",
    23: "5",
    24: "=",
    25: "9",
    26: "7",
    27: "-",
    28: "8",
    29: "0",
    30: "]",
    31: "O",
    32: "U",
    33: "[",
    34: "I",
    35: "P",
    36: "Return",
    37: "L",
    38: "J",
    39: "'",
    40: "K",
    41: ";",
    42: "\\",
    43: ",",
    44: "/",
    45: "N",
    46: "M",
    47: ".",
    48: "Tab",
    49: "Space",
    50: "`",
    51: "Delete",
    53: "Escape",
    54: "rightCommand",
    55: "leftCommand",
    56: "leftShift",
    57: "capsLock",
    58: "leftOption",
    59: "leftControl",
    60: "rightShift",
    61: "rightOption",
    62: "rightControl",
    63: "fn",
    64: "F17",
    65: "Keypad.",
    67: "Keypad*",
    69: "Keypad+",
    71: "KeypadClear",
    72: "VolumeUp",
    73: "VolumeDown",
    74: "Mute",
    75: "Keypad/",
    76: "KeypadEnter",
    78: "Keypad-",
    79: "F18",
    80: "F19",
    81: "Keypad=",
    82: "Keypad0",
    83: "Keypad1",
    84: "Keypad2",
    85: "Keypad3",
    86: "Keypad4",
    87: "Keypad5",
    88: "Keypad6",
    89: "Keypad7",
    91: "Keypad8",
    92: "Keypad9",
    96: "F5",
    97: "F6",
    98: "F7",
    99: "F3",
    100: "F8",
    101: "F9",
    103: "F11",
    105: "F13",
    106: "F16",
    107: "F14",
    109: "F10",
    111: "F12",
    113: "F15",
    114: "Help",
    115: "Home",
    116: "PageUp",
    117: "ForwardDelete",
    118: "F4",
    119: "End",
    120: "F2",
    121: "PageDown",
    122: "F1",
    123: "LeftArrow",
    124: "RightArrow",
    125: "DownArrow",
    126: "UpArrow",
}

MODIFIER_KEYCODES = frozenset(
    {
        54,
        55,
        56,
        57,
        58,
        CONTROL_LEFT_KEYCODE,
        60,
        61,
        CONTROL_RIGHT_KEYCODE,
        63,
    }
)


def apply_control_event(
    tracker: ChordTracker,
    *,
    control_flag: bool,
    flag_left: bool,
    flag_right: bool,
    flags_changed: bool,
    hid_left: bool,
    hid_right: bool,
    keycode: int,
) -> bool:
    """Resolve and apply one tap event.

    ``keyDown`` / ``keyUp`` are ignored. Duplicate ``flagsChanged`` snapshots
    (same keycode and sensor bits) inside ``DUPLICATE_EVENT_WINDOW_S`` are
    ignored so a HID-blind Control press cannot toggle off on the echo event.
    The same snapshot after that window is a real release or repress.
    """
    if not flags_changed:
        return False
    signature = (keycode, hid_left, hid_right, flag_left, flag_right, control_flag)
    if tracker.record_event_signature(signature):
        return False
    left_down, right_down = resolve_control_snapshot(
        keycode=keycode,
        hid_left=hid_left,
        hid_right=hid_right,
        flag_left=flag_left,
        flag_right=flag_right,
        held_left=tracker.held_left,
        held_right=tracker.held_right,
        control_flag=control_flag,
        flags_changed=True,
    )
    return apply_hid_snapshot(
        tracker,
        keycode=keycode,
        left_down=left_down,
        right_down=right_down,
    )


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


def describe_key(
    keycode: int,
    *,
    command: bool = False,
    control: bool = False,
    fn: bool = False,
    option: bool = False,
    shift: bool = False,
) -> str:
    """Human-readable key name, with modifiers (``CTRL-A``)."""
    name = KEYCODE_NAMES.get(keycode, f"keycode:{keycode}")
    if keycode in MODIFIER_KEYCODES:
        return name
    parts: list[str] = []
    if control:
        parts.append("CTRL")
    if option:
        parts.append("OPT")
    if shift:
        parts.append("SHIFT")
    if command:
        parts.append("CMD")
    if fn:
        parts.append("FN")
    parts.append(name)
    return "-".join(parts)


def page_selector_for_keycode(keycode: int) -> str | None:
    """Map Page Up/Down keycodes to completion navigation selectors."""
    if keycode == PAGE_UP_KEYCODE:
        return "pageUp:"
    if keycode == PAGE_DOWN_KEYCODE:
        return "pageDown:"
    return None


def resolve_control_snapshot(
    *,
    keycode: int,
    hid_left: bool,
    hid_right: bool,
    flag_left: bool,
    flag_right: bool,
    held_left: bool,
    held_right: bool,
    control_flag: bool = False,
    flags_changed: bool = True,
) -> tuple[bool, bool]:
    """Merge HID, device-dependent flags, and the event keycode.

    ``CGEventSourceKeyState`` often stays False for right Control. Quartz
    still delivers ``flagsChanged`` with keycode 62 and may set
    ``NX_DEVICERCTLKEYMASK``. If both miss, treat that keycode as an edge
    against the tracker's previous held state — only on ``flagsChanged``,
    never on ``keyDown`` / ``keyUp``. A HID-blind held key stays down while
    ``control_flag`` is set and the event names a different key. When the
    Control modifier is fully up, both keys are released.
    """
    left_seen = hid_left or flag_left
    right_seen = hid_right or flag_right
    left_down = left_seen
    right_down = right_seen
    if flags_changed:
        if keycode == CONTROL_LEFT_KEYCODE and not left_seen:
            left_down = not held_left
        if keycode == CONTROL_RIGHT_KEYCODE and not right_seen:
            right_down = not held_right
    if held_left and not left_down and keycode != CONTROL_LEFT_KEYCODE and control_flag:
        left_down = True
    if (
        held_right
        and not right_down
        and keycode != CONTROL_RIGHT_KEYCODE
        and control_flag
    ):
        right_down = True
    if flags_changed and not control_flag and not left_seen and not right_seen:
        left_down = False
        right_down = False
    return left_down, right_down

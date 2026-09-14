"""Detect whether an external (non-built-in) keyboard is connected.

Standard MacBook built-in keyboards expose only one physical Control key, so
the historical dual-Control Spotty Bunny chord cannot be pressed on a
built-in-only setup. This module lets ``spotty_bunny_hotkey = "auto"`` pick a
working default: the dual-Control chord when a full external keyboard is
attached, or the built-in Option pair otherwise.

Detection shells out to ``ioreg`` (present on every macOS install) rather than
binding IOKit's ``IOHIDManager`` C API directly, keeping this module free of
any new compiled/PyObjC dependency. The text-parsing logic below is pure and
unit-tested against captured ``ioreg`` output; only :func:`list_connected_keyboards`
touches the subprocess boundary, so it is the sole seam callers need to mock.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

IOREG_TIMEOUT_S = 5.0
KEYBOARD_USAGE_PAGE = 1
KEYBOARD_USAGE = 6

_BUILT_IN_PATTERN = re.compile(r'"Built-In"\s*=\s*(Yes|No)')
_PRODUCT_PATTERN = re.compile(r'"Product"\s*=\s*"([^"]*)"')
_USAGE_PAIR_PATTERN = re.compile(
    r'"DeviceUsagePage"\s*=\s*(\d+)\s*,\s*"DeviceUsage"\s*=\s*(\d+)'
)
# A top-level ioreg tree entry starts a new physical device at column 0.
_ROOT_ENTRY_PATTERN = re.compile(r"^\+-o (\S.*)$", re.MULTILINE)


@dataclass(frozen=True)
class KeyboardDevice:
    """One physical keyboard reported by IOKit's HID device registry."""

    product: str
    built_in: bool


def list_connected_keyboards() -> list[KeyboardDevice]:
    """Return currently connected keyboard devices via ``ioreg``.

    Returns an empty list (rather than raising) when ``ioreg`` is missing,
    times out, or its output cannot be parsed — callers should treat that as
    "unknown" and fall back to a safe default.
    """
    text = _run_ioreg()
    if text is None:
        return []
    return parse_ioreg_keyboards(text)


def has_external_keyboard(devices: list[KeyboardDevice] | None = None) -> bool:
    """Return True when at least one connected keyboard is not built-in."""
    resolved = list_connected_keyboards() if devices is None else devices
    return any(not device.built_in for device in resolved)


def parse_ioreg_keyboards(text: str) -> list[KeyboardDevice]:
    """Parse ``ioreg -r -c IOHIDDevice -l`` text into keyboard devices.

    Each top-level ``+-o`` entry is one physical HID device; its properties
    (and those of its child interfaces/drivers) are searched for a
    ``Product`` name, a keyboard ``DeviceUsagePairs`` entry (usage page 1,
    usage 6), and a ``Built-In`` flag. Devices without a keyboard usage pair
    and without "Keyboard" in their product name are not returned. A missing
    ``Built-In`` field is treated as external (only Apple-internal hardware
    reports it).
    """
    starts = [match.start() for match in _ROOT_ENTRY_PATTERN.finditer(text)]
    if not starts:
        return []
    starts.append(len(text))

    devices: list[KeyboardDevice] = []
    for start, end in zip(starts, starts[1:], strict=False):
        block = text[start:end]
        is_keyboard_usage = any(
            int(page) == KEYBOARD_USAGE_PAGE and int(usage) == KEYBOARD_USAGE
            for page, usage in _USAGE_PAIR_PATTERN.findall(block)
        )
        product_match = _PRODUCT_PATTERN.search(block)
        product = product_match.group(1) if product_match else ""
        is_keyboard_name = "keyboard" in product.lower()
        if not is_keyboard_usage and not is_keyboard_name:
            continue
        built_in_match = _BUILT_IN_PATTERN.search(block)
        built_in = built_in_match is not None and built_in_match.group(1) == "Yes"
        devices.append(KeyboardDevice(product=product, built_in=built_in))
    return devices


def _run_ioreg() -> str | None:
    try:
        result = subprocess.run(  # noqa: S603 (fixed args, no shell, no user input)
            ["/usr/sbin/ioreg", "-r", "-c", "IOHIDDevice", "-l"],
            capture_output=True,
            text=True,
            timeout=IOREG_TIMEOUT_S,
            check=False,
        )
    except OSError, subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None
    return result.stdout

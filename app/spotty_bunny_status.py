"""User-facing Spotty Bunny status lines (no AppKit)."""

from __future__ import annotations

import re
from collections.abc import Callable

SHORTCUTS_LOAD_FAILED = (
    "Could not load shortcuts — the Bunnify server is not running. "
    "Start it with `bunnify setup`."
)
TIMEOUT_CONTACTING_SERVER = (
    "Timed out contacting the Bunnify server. "
    "Check that it is running (`bunnify setup`)."
)
UNKNOWN_SHORTCUT_HINT = "Unknown shortcut. Press Tab to list matching shortcuts."


def canned_spotty_bunny_status_lines() -> tuple[str, ...]:
    """Known overlay errors used to size the window without leftover empty space."""
    return (
        SHORTCUTS_LOAD_FAILED,
        TIMEOUT_CONTACTING_SERVER,
        UNKNOWN_SHORTCUT_HINT,
    )


def format_spotty_bunny_status(error: object) -> str:
    """Turn a load/resolve failure into a wrapping overlay status line."""
    text = str(error).strip()
    lowered = text.lower()
    if _server_unreachable(error, lowered):
        return SHORTCUTS_LOAD_FAILED
    if "timed out" in lowered:
        return TIMEOUT_CONTACTING_SERVER
    if "unknown shortcut" in lowered:
        return UNKNOWN_SHORTCUT_HINT
    return text or SHORTCUTS_LOAD_FAILED


def status_punctuation_chunks(message: str) -> tuple[str, ...]:
    """Split *message* after punctuation so wrapping can prefer those breaks."""
    return tuple(part for part in _STATUS_PUNCT_BREAK.split(message.strip()) if part)


def status_text_runs(message: str) -> tuple[tuple[str, bool], ...]:
    """Split *message* on backticks into ``(text, is_command)`` runs."""
    return tuple(
        (part, index % 2 == 1) for index, part in enumerate(message.split("`")) if part
    )


def wrap_status_preferring_punctuation(
    message: str, *, fits: Callable[[str], bool]
) -> str:
    """Insert newlines so a wrapping line prefers to break after punctuation."""
    if not message or fits(message):
        return message
    chunks = status_punctuation_chunks(message)
    if len(chunks) <= 1:
        return message
    lines: list[str] = []
    current = ""
    for chunk in chunks:
        candidate = f"{current} {chunk}" if current else chunk
        if current and not fits(candidate):
            lines.append(current)
            current = chunk
        else:
            current = candidate
    if current:
        lines.append(current)
    return "\n".join(lines)


_STATUS_PUNCT_BREAK = re.compile(r"(?<=[.!?:;—–])\s+")


def _server_unreachable(error: object, lowered: str) -> bool:
    if isinstance(error, ConnectionError | TimeoutError):
        return True
    markers = (
        "cannot reach",
        "connection refused",
        "errno 61",
        "failed to establish",
        "is `./scripts/bunnify-server` running",
        "network is unreachable",
        "not running",
    )
    return any(marker in lowered for marker in markers)

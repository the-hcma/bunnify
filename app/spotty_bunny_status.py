"""User-facing Spotty Bunny status lines (no AppKit)."""

from __future__ import annotations

SHORTCUTS_LOAD_FAILED = (
    "Could not load shortcuts — the Bunnify server is not running. "
    "Start it with bunnify setup."
)


def format_spotty_bunny_status(error: object) -> str:
    """Turn a load/resolve failure into a wrapping overlay status line."""
    text = str(error).strip()
    lowered = text.lower()
    if _server_unreachable(error, lowered):
        return SHORTCUTS_LOAD_FAILED
    if "timed out" in lowered:
        return (
            "Timed out contacting the Bunnify server. "
            "Check that it is running (bunnify setup)."
        )
    if "unknown shortcut" in lowered:
        hint = text if text else "Unknown shortcut"
        return f"{hint}. Press Tab to list matching shortcuts."
    return text or SHORTCUTS_LOAD_FAILED


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

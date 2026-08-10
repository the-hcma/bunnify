"""Structured shortcut catalog for the keys API and CLI usage listing."""

from __future__ import annotations

from typing import Any

from .models import Bookmark
from .resolve import PLACEHOLDER_PATTERN

SPECIAL_ENTRIES: tuple[tuple[str, str, str], ...] = (
    ("h", "Show all bookmarks", "/list/"),
    ("cmd", "Command palette", "/cmd/"),
)


def placeholders_for_url(url: str) -> list[str]:
    """Ordered unique placeholder names from a bookmark URL template."""
    return list(dict.fromkeys(PLACEHOLDER_PATTERN.findall(url)))


def build_key_catalog() -> list[dict[str, Any]]:
    """Return specials + bookmarks as JSON-ready key entries."""
    entries: list[dict[str, Any]] = [
        {
            "key": key,
            "description": description,
            "url": url,
            "params": [],
        }
        for key, description, url in SPECIAL_ENTRIES
    ]
    for bookmark in Bookmark.objects.order_by("key"):
        entries.append(
            {
                "key": bookmark.key,
                "description": bookmark.description or "",
                "url": bookmark.url,
                "params": placeholders_for_url(bookmark.url),
            }
        )
    return entries


def catalog_payload() -> dict[str, Any]:
    """JSON payload for ``/api/keys/`` (string keys + structured entries)."""
    entries = build_key_catalog()
    return {
        "keys": [entry["key"] for entry in entries],
        "entries": entries,
    }

"""Structured shortcut catalog for the keys API and CLI usage listing."""

from __future__ import annotations

from typing import Any

from app.completion_spec import parse_complete_map

from .models import Bookmark
from .resolve import PLACEHOLDER_PATTERN

SPECIAL_ENTRIES: tuple[tuple[str, str, str], ...] = (
    ("h", "Show all bookmarks", "/list/"),
    ("cmd", "Command palette", "/cmd/"),
)


def placeholders_for_url(url: str) -> list[str]:
    """Ordered unique placeholder names from a bookmark URL template."""
    return list(dict.fromkeys(PLACEHOLDER_PATTERN.findall(url)))


def _complete_payload(raw: object) -> dict[str, dict[str, str]] | None:
    if not isinstance(raw, dict) or not raw:
        return None
    parsed = parse_complete_map(raw)
    if parsed is None:
        return None
    return {
        param: {
            "kind": spec.kind,
            **({"org": spec.org} if spec.org else {}),
            **({"repo_param": spec.repo_param} if spec.repo_param else {}),
        }
        for param, spec in sorted(parsed.items())
    }


def build_key_catalog() -> list[dict[str, Any]]:
    """Return specials + bookmarks as JSON-ready key entries."""
    entries: list[dict[str, Any]] = [
        {
            "key": key,
            "description": description,
            "url": url,
            "params": [],
            "optional_params": [],
        }
        for key, description, url in SPECIAL_ENTRIES
    ]
    for bookmark in Bookmark.objects.order_by("key"):
        defaults = bookmark.defaults if isinstance(bookmark.defaults, dict) else {}
        complete = bookmark.complete if isinstance(bookmark.complete, dict) else {}
        params = placeholders_for_url(bookmark.url)
        entry: dict[str, Any] = {
            "key": bookmark.key,
            "description": bookmark.description or "",
            "url": bookmark.url,
            "params": params,
            "optional_params": [name for name in params if name in defaults],
        }
        complete_payload = _complete_payload(complete)
        if complete_payload:
            entry["complete"] = complete_payload
        entries.append(entry)
    return entries


def catalog_payload() -> dict[str, Any]:
    """JSON payload for ``/api/keys/`` (string keys + structured entries)."""
    entries = build_key_catalog()
    return {
        "keys": [entry["key"] for entry in entries],
        "entries": entries,
    }

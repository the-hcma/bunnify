"""Resolve a Spotty Bunny query the same way as the CLI (strict)."""

from __future__ import annotations

from collections.abc import Callable

from app.cli import open_url
from app.client import resolve_shortcut
from app.spotty_bunny_history import append_history_line


def resolve_query(
    query: str,
    *,
    base_url: str,
    append_fn: Callable[[str], None] | None = None,
    open_fn: Callable[..., None] | None = None,
    resolve_fn: Callable[..., object] | None = None,
) -> str:
    """Resolve *query* strictly, open the URL, then append REPL history.

    Returns the opened URL. Raises ``ClientError`` (or the resolver's error)
    on failure; history is not written then.
    """
    text = query.strip()
    if not text:
        raise ValueError("empty query")
    resolve = resolve_fn or resolve_shortcut
    opener = open_fn or open_url
    append = append_fn or append_history_line
    resolved = resolve(text, base_url=base_url, strict=True)
    url = getattr(resolved, "url", None)
    if not isinstance(url, str) or not url:
        raise ValueError("resolve response missing url")
    opener(url)
    append(text)
    return url

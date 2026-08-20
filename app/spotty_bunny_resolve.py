"""Resolve a Spotty Bunny query like browser search (Google fallback)."""

from __future__ import annotations

from collections.abc import Callable

from app.cli import open_url
from app.client import resolve_shortcut
from app.spotty_bunny_history import append_history_line


def lookup_resolved_url(
    query: str,
    *,
    base_url: str,
    resolve_fn: Callable[..., object] | None = None,
) -> str:
    """Resolve *query* and return the URL without opening or history.

    Uses non-strict resolve so unknown shortcuts become a Google search, matching
    the browser ``/search/`` behavior. The CLI stays strict separately.
    """
    text = query.strip()
    if not text:
        raise ValueError("empty query")
    resolve = resolve_fn or resolve_shortcut
    resolved = resolve(text, base_url=base_url, strict=False)
    url = getattr(resolved, "url", None)
    if not isinstance(url, str) or not url:
        raise ValueError("resolve response missing url")
    return url


def resolve_query(
    query: str,
    *,
    base_url: str,
    append_fn: Callable[[str], None] | None = None,
    open_fn: Callable[..., None] | None = None,
    resolve_fn: Callable[..., object] | None = None,
) -> str:
    """Resolve *query*, open the URL, then append REPL history.

    Unknown shortcuts fall back to Google search (same as the browser). Returns
    the opened URL. Raises ``ClientError`` (or the resolver's error) on failure;
    history is not written then.
    """
    text = query.strip()
    opener = open_fn or open_url
    append = append_fn or append_history_line
    url = lookup_resolved_url(query, base_url=base_url, resolve_fn=resolve_fn)
    opener(url)
    append(text)
    return url


def resolve_still_current(*, expected_seq: int, seq: int) -> bool:
    """True when an async Enter result still matches the submit that requested it."""
    return seq == expected_seq

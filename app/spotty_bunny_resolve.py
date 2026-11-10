"""Resolve a Spotty Bunny query like browser search (Google fallback)."""

from __future__ import annotations

from collections.abc import Callable

from app.browser_spec import BrowserSpec
from app.cli import open_url
from app.client import ResolvedShortcut, resolve_shortcut
from app.spotty_bunny_history import append_history_line


def lookup_resolved(
    query: str,
    *,
    base_url: str,
    resolve_fn: Callable[..., object] | None = None,
) -> ResolvedShortcut:
    """Resolve *query* without opening or history (URL plus any browser pin).

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
    browser = getattr(resolved, "browser", None)
    return ResolvedShortcut(
        url=url,
        kind=getattr(resolved, "kind", None),
        key=getattr(resolved, "key", None),
        browser=browser if isinstance(browser, BrowserSpec) else None,
    )


def lookup_resolved_url(
    query: str,
    *,
    base_url: str,
    resolve_fn: Callable[..., object] | None = None,
) -> str:
    """Resolve *query* and return only the URL (no browser pin)."""
    return lookup_resolved(query, base_url=base_url, resolve_fn=resolve_fn).url


def open_resolved(
    resolved: ResolvedShortcut,
    *,
    open_fn: Callable[..., None] | None = None,
) -> None:
    """Open a resolved shortcut, honoring its browser pin when it has one."""
    opener = open_fn or open_url
    if resolved.browser is None:
        opener(resolved.url)
    else:
        opener(resolved.url, browser=resolved.browser)


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
    resolved = lookup_resolved(query, base_url=base_url, resolve_fn=resolve_fn)
    open_resolved(resolved, open_fn=opener)
    append(text)
    return resolved.url


def resolve_still_current(*, expected_seq: int, seq: int) -> bool:
    """True when an async Enter result still matches the submit that requested it."""
    return seq == expected_seq

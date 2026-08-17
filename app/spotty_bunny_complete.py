"""Headless CLI completer wrapper for Spotty Bunny (no AppKit)."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from prompt_toolkit.completion import CompleteEvent, Completer
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import to_formatted_text, to_plain_text

from app.client import KeyEntry
from app.interactive import FirstTokenFuzzyCompleter, ShortcutCompleter
from app.theme import Theme


@dataclass(frozen=True)
class CompletionRow:
    """One completion candidate for the search box / table."""

    insert: str
    meta: str
    start_position: int


def apply_completion(current: str, row: CompletionRow) -> str:
    """Replace the in-progress token in *current* with *row.insert*."""
    start = row.start_position
    if start < 0:
        return current[: len(current) + start] + row.insert
    return current[:start] + row.insert


def completions_for(text: str, completer: Completer) -> list[CompletionRow]:
    """Ask *completer* for Tab candidates at the end of *text*."""
    document = Document(text=text, cursor_position=len(text))
    event = CompleteEvent(text_inserted=False, completion_requested=True)
    rows: list[CompletionRow] = []
    for item in completer.get_completions(document, event):
        rows.append(
            CompletionRow(
                insert=item.text,
                meta=_plain(item.display_meta),
                start_position=item.start_position,
            )
        )
    return rows


def make_spotty_completer(
    *,
    entries: Iterable[KeyEntry],
    param_suggest_fn: Callable[..., list[str]] | None = None,
    suggestions_fn: Callable[[str], list[str]] | None = None,
) -> FirstTokenFuzzyCompleter:
    """FirstTokenFuzzyCompleter over ShortcutCompleter (no REPL meta commands)."""
    listing = list(entries)
    inner = ShortcutCompleter(
        [entry.key for entry in listing],
        theme=Theme(enabled=False),
        include_meta=False,
        suggestions_fn=suggestions_fn,
        entries=listing,
        param_suggest_fn=param_suggest_fn,
    )
    return FirstTokenFuzzyCompleter(inner)


def _plain(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return to_plain_text(to_formatted_text(value))

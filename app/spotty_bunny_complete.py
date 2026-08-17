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


COMPLETION_PAGE_STEP = 5


def completion_row_after_selector(
    current: int,
    *,
    row_count: int,
    selector: str,
    page_step: int = COMPLETION_PAGE_STEP,
) -> int:
    """Return the completion table row index after a navigation selector."""
    if row_count <= 0:
        return 0
    idx = current if current >= 0 else 0
    if selector == "moveUp:":
        return max(0, idx - 1)
    if selector == "moveDown:":
        return min(row_count - 1, idx + 1)
    if selector == "pageUp:":
        return max(0, idx - page_step)
    if selector == "pageDown:":
        return min(row_count - 1, idx + page_step)
    return idx


def apply_completion(current: str, row: CompletionRow) -> str:
    """Apply *row* like prompt_toolkit (start_position is relative to the cursor)."""
    begin = len(current) + row.start_position
    if begin < 0:
        begin = 0
    return current[:begin] + row.insert


def completion_still_current(
    *,
    expected_seq: int,
    field: str,
    prefix: str,
    seq: int,
) -> bool:
    """True when an async Tab result still matches the field that requested it."""
    return seq == expected_seq and field == prefix


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

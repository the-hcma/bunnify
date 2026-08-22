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


COMPLETION_NAVIGATION_SELECTORS = frozenset(
    {
        "moveDown:",
        "moveUp:",
        "pageDown:",
        "pageUp:",
        "scrollPageDown:",
        "scrollPageUp:",
    }
)

COMPLETION_PAGE_SELECTORS = frozenset(
    {
        "pageDown:",
        "pageUp:",
        "scrollPageDown:",
        "scrollPageUp:",
    }
)

COMPLETION_PAGE_STEP = 5

TAB_COMPLETION_SELECTORS = frozenset(
    {
        "insertBacktab:",
        "insertTab:",
        "selectNextKeyView:",
        "selectPreviousKeyView:",
    }
)


def apply_completion(current: str, row: CompletionRow) -> str:
    """Apply *row* like prompt_toolkit (start_position is relative to the cursor)."""
    begin = len(current) + row.start_position
    if begin < 0:
        begin = 0
    return current[:begin] + row.insert


def completion_browse_all(prefix: str) -> bool:
    """True when Tab should list every shortcut without inserting the first."""
    return not prefix.strip()


def completion_navigation_disposition(
    selector: str,
    *,
    has_rows: bool,
    table_visible: bool,
) -> str | None:
    """How the field editor should treat a completion-navigation selector.

    Returns ``move`` (update selection), ``consume`` (swallow without moving),
    ``ignore`` (do not handle; do not fall through to history), or ``None``
    when the selector is not completion navigation / there are no rows.
    """
    if not has_rows or not is_completion_navigation_selector(selector):
        return None
    if is_page_navigation_selector(selector):
        return "move" if table_visible else "ignore"
    return "move" if table_visible else "consume"


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
    action = normalize_completion_navigation_selector(selector)
    if action == "moveUp:":
        return max(0, idx - 1)
    if action == "moveDown:":
        return min(row_count - 1, idx + 1)
    if action == "pageUp:":
        return max(0, idx - page_step)
    if action == "pageDown:":
        return min(row_count - 1, idx + page_step)
    return idx


def completion_still_current(
    *,
    expected_seq: int,
    field: str,
    prefix: str,
    seq: int,
) -> bool:
    """True when an async Tab result still matches the field that requested it."""
    return seq == expected_seq and field == prefix


def completion_table_should_show(prefix: str, rows: list[CompletionRow]) -> bool:
    """Whether the completion table should appear for *rows* under *prefix*."""
    if not rows:
        return False
    if completion_browse_all(prefix):
        return True
    return len(rows) > 1


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


def field_editor_selector_name(selector: object) -> str:
    """Normalize a Cocoa ``doCommandBySelector:`` argument to an ObjC name."""
    if isinstance(selector, (bytes, bytearray)):
        return bytes(selector).decode("ascii", errors="replace")
    raw = getattr(selector, "selector", None)
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw).decode("ascii", errors="replace")
    if isinstance(raw, str) and raw:
        return raw
    text = selector if isinstance(selector, str) else str(selector)
    marker = "selector "
    start = text.find(marker)
    if start >= 0:
        token = text[start + len(marker) :].split(" ", 1)[0]
        if token:
            return token
    return text


def is_completion_navigation_selector(selector: object) -> bool:
    """True when *selector* should move the Tab completion selection."""
    return field_editor_selector_name(selector) in COMPLETION_NAVIGATION_SELECTORS


def is_page_navigation_selector(selector: object) -> bool:
    """True when *selector* is a Page Up/Down (or scroll-page) command."""
    return field_editor_selector_name(selector) in COMPLETION_PAGE_SELECTORS


def is_tab_completion_selector(selector: object) -> bool:
    """True when *selector* should trigger Spotty Bunny Tab completion."""
    return field_editor_selector_name(selector) in TAB_COMPLETION_SELECTORS


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


def normalize_completion_navigation_selector(selector: str) -> str:
    """Map Cocoa page-scroll selectors to Spotty Bunny page navigation names."""
    if selector == "scrollPageUp:":
        return "pageUp:"
    if selector == "scrollPageDown:":
        return "pageDown:"
    return selector


def should_auto_insert_completion(prefix: str, rows: list[CompletionRow]) -> bool:
    """True when the first Tab candidate should replace the field text."""
    return bool(rows) and not completion_browse_all(prefix)


def _plain(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return to_plain_text(to_formatted_text(value))

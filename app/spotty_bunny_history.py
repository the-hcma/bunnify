"""Shared REPL history for Spotty Bunny (prompt_toolkit FileHistory format)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from prompt_toolkit.history import FileHistory

from app.interactive import history_file_path

HISTORY_DOWN_SELECTORS = frozenset({"moveDown:"})
HISTORY_UP_SELECTORS = frozenset({"moveUp:"})


class HistoryNavigator:
    """Walk REPL history with up/down. Newest entries are last."""

    def __init__(self, lines: Sequence[str] | None = None) -> None:
        self._draft = ""
        self._lines = list(lines or ())
        self._cursor = len(self._lines)

    def down(self, current: str) -> str:
        """Newer entry, or the live draft past the newest line."""
        if self._cursor >= len(self._lines):
            return current
        self._capture_draft(current)
        self._cursor += 1
        if self._cursor >= len(self._lines):
            return self._draft
        return self._lines[self._cursor]

    def up(self, current: str) -> str:
        """Older entry. Saves *current* as the draft when it is not a stored line."""
        if not self._lines:
            return current
        self._capture_draft(current)
        if self._cursor > 0:
            self._cursor -= 1
        return self._lines[self._cursor]

    def _capture_draft(self, current: str) -> None:
        if self._cursor >= len(self._lines):
            self._draft = current
            return
        if current != self._lines[self._cursor]:
            self._draft = current


def append_history_line(line: str, *, path: Path | None = None) -> None:
    """Append one query in FileHistory format for the CLI REPL to read back."""
    text = line.strip()
    if not text:
        return
    dest = path if path is not None else history_file_path()
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        FileHistory(str(dest)).append_string(text)
    except OSError:
        return


def apply_history_selector(
    navigator: HistoryNavigator,
    current: str,
    selector: str,
) -> str | None:
    """Return new field text for an up/down selector, else ``None``."""
    if selector in HISTORY_UP_SELECTORS:
        return navigator.up(current)
    if selector in HISTORY_DOWN_SELECTORS:
        return navigator.down(current)
    return None


def load_history_lines(*, path: Path | None = None) -> list[str]:
    """Load FileHistory strings (oldest first) from the shared REPL file."""
    dest = path if path is not None else history_file_path()
    if not dest.is_file():
        return []
    try:
        newest_first = list(FileHistory(str(dest)).load_history_strings())
    except OSError, UnicodeDecodeError:
        return []
    newest_first.reverse()
    return newest_first

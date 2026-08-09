"""Interactive prompt with in-process tab completion."""

from __future__ import annotations

import readline
from collections.abc import Callable


class ShortcutCompleter:
    """Readline completer that completes the first token against shortcut keys."""

    def __init__(self, keys: list[str]) -> None:
        self._keys = sorted(keys)
        self._matches: list[str] = []

    def complete(self, text: str, state: int) -> str | None:
        if state == 0:
            begidx = readline.get_begidx()
            buffer = readline.get_line_buffer()
            # Only complete the shortcut key (first token).
            if " " in buffer[:begidx]:
                self._matches = []
            else:
                needle = text.lower()
                self._matches = [
                    key for key in self._keys if key.lower().startswith(needle)
                ]
        try:
            return self._matches[state]
        except IndexError:
            return None


def read_shortcut_query(
    *,
    keys: list[str],
    prompt: str = "> ",
    input_fn: Callable[[str], str] | None = None,
) -> str | None:
    """
    Prompt for a shortcut query with tab completion.

    Returns ``None`` when the user cancels (EOF / empty after interrupt).
    """
    if input_fn is not None:
        try:
            value = input_fn(prompt)
        except EOFError:
            return None
        return value.strip() or None

    completer = ShortcutCompleter(keys)
    previous_completer = readline.get_completer()
    readline.set_completer(completer.complete)
    readline.parse_and_bind("tab: complete")
    try:
        try:
            value = input(prompt)
        except EOFError:
            print()
            return None
        except KeyboardInterrupt:
            print()
            return None
    finally:
        readline.set_completer(previous_completer)

    stripped = value.strip()
    return stripped or None

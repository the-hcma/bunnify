"""ANSI color theme for the Bunnify CLI (TTY + NO_COLOR + --color)."""

from __future__ import annotations

import os
import sys


class Theme:
    """ANSI styling for stdout/stderr when coloring is enabled.

    Mirrors the domesti-bot REPL theme so interactive sessions feel consistent
    across HCMA CLIs (prompt_toolkit completion styles + ANSI for print).
    """

    __slots__ = ("_enabled",)

    def __init__(self, *, enabled: bool) -> None:
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _s(self, codes: str, text: str) -> str:
        if not self._enabled:
            return text
        return f"\033[{codes}m{text}\033[0m"

    def brand(self, text: str) -> str:
        return self._s("36;1", text)

    def cmd(self, text: str) -> str:
        return self._s("33;1", text)

    def dim(self, text: str) -> str:
        return self._s("2", text)

    def err(self, text: str) -> str:
        return self._s("31", text)

    def header(self, text: str) -> str:
        return self._s("34;1", text)

    def meta(self, text: str) -> str:
        return self._s("90", text)

    def ok(self, text: str) -> str:
        return self._s("32", text)

    def state(self, text: str) -> str:
        return self._s("36", text)

    def warn(self, text: str) -> str:
        return self._s("33", text)

    def url(self, text: str) -> str:
        return self._s("35", text)

    def completion_command_style(self) -> str:
        """prompt_toolkit style for REPL meta-commands (help / quit / …)."""
        return "bold ansiyellow" if self._enabled else ""

    def completion_key_style(self) -> str:
        """prompt_toolkit style for shortcut keys."""
        return "bold ansicyan" if self._enabled else ""

    def completion_param_style(self) -> str:
        """prompt_toolkit style for parameter / suggestion completions."""
        return "bold ansibrightmagenta" if self._enabled else ""


def stdout_color_enabled(mode: str) -> bool:
    """Resolve whether ANSI colors should be emitted for stdout."""
    if (os.environ.get("NO_COLOR") or "").strip():
        return False
    if mode == "never":
        return False
    if mode == "always":
        return True
    return sys.stdout.isatty()

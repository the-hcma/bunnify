"""Interactive REPL helpers: prompt_toolkit completion, history, edit modes."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from pathlib import Path

from platformdirs import user_cache_dir
from prompt_toolkit import HTML, PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import (
    CompleteEvent,
    Completer,
    Completion,
    FuzzyCompleter,
)
from prompt_toolkit.document import Document
from prompt_toolkit.enums import EditingMode
from prompt_toolkit.formatted_text import AnyFormattedText
from prompt_toolkit.history import FileHistory, InMemoryHistory

from app.client import ClientError
from app.theme import Theme

try:
    import readline as readline_module
except ModuleNotFoundError:
    readline_module = None

REPL_META_COMMANDS: tuple[tuple[str, str], ...] = (
    ("edit-mode", "Switch Emacs vs Vim keys: edit-mode emacs | vim"),
    ("exit", "Leave the REPL"),
    ("help", "Show this help"),
    ("keys", "List known shortcut keys"),
    ("quit", "Leave the REPL"),
    ("refresh", "Re-fetch shortcut keys from the server"),
)

REPL_META_NAMES = tuple(name for name, _ in REPL_META_COMMANDS)
_EDIT_MODE_SUBARGS = ("emacs", "vim")


def normalize_edit_mode_choice(raw: str | None) -> str:
    """Normalize ``BUNNIFY_EDIT_MODE`` (or similar) to ``emacs`` or ``vim``.

    Default is **vim** (domesti-bot parity). Accepts emacs/e and vim/vi/v.
    """
    if raw is None:
        return "vim"
    text = str(raw).strip().lower()
    if not text:
        return "vim"
    if text in ("emacs", "e"):
        return "emacs"
    if text in ("vi", "vim", "v"):
        return "vim"
    return "vim"


def editing_mode_enum(mode: str) -> EditingMode:
    if normalize_edit_mode_choice(mode) == "emacs":
        return EditingMode.EMACS
    return EditingMode.VI


def history_file_path() -> Path:
    """Persistent REPL history under the user cache directory."""
    return Path(user_cache_dir("bunnify")) / "repl_history"


class ShortcutCompleter(Completer):
    """
    Tab-complete the first token against meta-commands + shortcut keys.

    After a space, completes via optional ``suggestions_fn`` (server OpenSearch
    suggestions) so parameterized shortcuts stay discoverable.
    """

    def __init__(
        self,
        keys: Iterable[str],
        *,
        theme: Theme | None = None,
        include_meta: bool = True,
        suggestions_fn: Callable[[str], list[str]] | None = None,
    ) -> None:
        self._keys = sorted(keys)
        self._theme = theme or Theme(enabled=False)
        self._include_meta = include_meta
        self._suggestions_fn = suggestions_fn

    def set_keys(self, keys: Iterable[str]) -> None:
        self._keys = sorted(keys)

    def get_completions(
        self,
        document: Document,
        complete_event: CompleteEvent,
    ):
        del complete_event
        text = document.text_before_cursor
        if " " in text:
            yield from self._param_completions(text)
            return

        partial = text
        needle = partial.lower()
        cmd_style = self._theme.completion_command_style()
        key_style = self._theme.completion_key_style()

        if self._include_meta:
            key_set = {key.lower() for key in self._keys}
            for name, blurb in REPL_META_COMMANDS:
                if name.lower() in key_set:
                    continue
                if name.lower().startswith(needle):
                    yield Completion(
                        name,
                        start_position=-len(partial),
                        style=cmd_style,
                        display_meta=blurb,
                    )

        for key in self._keys:
            if key.lower().startswith(needle):
                yield Completion(
                    key,
                    start_position=-len(partial),
                    style=key_style,
                    display_meta="shortcut",
                )

    def _param_completions(self, text: str):
        if self._suggestions_fn is None:
            # Still offer edit-mode subargs when completing that meta command.
            parts = text.split(None, 1)
            if len(parts) == 2 and parts[0].lower() == "edit-mode":
                prefix = parts[1].lower()
                style = self._theme.completion_param_style()
                for alias in _EDIT_MODE_SUBARGS:
                    if alias.startswith(prefix):
                        yield Completion(
                            alias,
                            start_position=-len(parts[1]),
                            style=style,
                            display_meta="edit-mode",
                        )
            return

        try:
            suggestions = self._suggestions_fn(text)
        except ClientError:
            return
        except OSError:
            return
        except ValueError:
            return
        style = self._theme.completion_param_style()
        seen: set[str] = set()
        for item in suggestions:
            if item in seen:
                continue
            seen.add(item)
            # Prefer completing the trailing fragment when the suggestion
            # shares the typed prefix; otherwise replace the whole buffer.
            if item.lower().startswith(text.lower()):
                yield Completion(
                    item,
                    start_position=-len(text),
                    style=style,
                    display_meta="suggestion",
                )
            else:
                last = text.rsplit(None, 1)[-1]
                if item.lower().startswith(last.lower()):
                    yield Completion(
                        item,
                        start_position=-len(last),
                        style=style,
                        display_meta="suggestion",
                    )


class ReadlineShortcutCompleter:
    """Readline completer that completes the first token against shortcut keys."""

    def __init__(self, keys: list[str]) -> None:
        self._keys = sorted(keys)
        self._matches: list[str] = []

    def complete(self, text: str, state: int) -> str | None:
        if readline_module is None:
            return None
        if state == 0:
            begidx = readline_module.get_begidx()
            buffer = readline_module.get_line_buffer()
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


def repl_prompt_message(theme: Theme) -> AnyFormattedText:
    if not theme.enabled:
        return "bunnify> "
    return HTML(
        '<style fg="ansicyan"><b>bunnify</b></style>'
        '<style fg="ansibrightblack"> &gt; </style>'
    )


def create_repl_session(
    *,
    keys: list[str],
    theme: Theme,
    editing_mode: EditingMode = EditingMode.VI,
    suggestions_fn: Callable[[str], list[str]] | None = None,
    history_path: Path | None = None,
) -> tuple[PromptSession[str], ShortcutCompleter]:
    """
    Build a prompt_toolkit session (domesti-bot parity + history / fuzzy).

    Returns ``(session, completer)`` so the REPL can call ``completer.set_keys``
    after ``refresh``.
    """
    inner = ShortcutCompleter(
        keys,
        theme=theme,
        include_meta=True,
        suggestions_fn=suggestions_fn,
    )
    # FuzzyCompleter makes Tab forgiving (domesti-bot uses prefix-only; we go further).
    completer: Completer = FuzzyCompleter(inner, enable_fuzzy=True)

    path = history_path if history_path is not None else history_file_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        history = FileHistory(str(path))
    except OSError:
        history = InMemoryHistory()

    session: PromptSession[str] = PromptSession(
        completer=completer,
        complete_while_typing=False,
        editing_mode=editing_mode,
        history=history,
        auto_suggest=AutoSuggestFromHistory(),
    )
    return session, inner


def read_shortcut_query(
    *,
    keys: list[str],
    prompt: str = "> ",
    input_fn: Callable[[str], str] | None = None,
) -> str | None:
    """
    Prompt once for a shortcut query with tab completion.

    Returns ``None`` on EOF / cancel. Returns ``\"\"`` for an empty line so
    callers (REPL) can skip and continue — matching prompt_toolkit behavior.
    """
    if input_fn is not None:
        try:
            value = input_fn(prompt)
        except EOFError:
            return None
        return value.strip()

    if readline_module is None:
        try:
            value = input(prompt)
        except EOFError:
            print()
            return None
        except KeyboardInterrupt:
            print()
            return None
        return value.strip()

    completer = ReadlineShortcutCompleter(keys)
    previous_completer = readline_module.get_completer()
    readline_module.set_completer(completer.complete)
    readline_module.parse_and_bind("tab: complete")
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
        readline_module.set_completer(previous_completer)

    return value.strip()


def default_edit_mode_from_environ(
    environ: dict[str, str] | None = None,
) -> str:
    env = environ if environ is not None else os.environ
    return normalize_edit_mode_choice(env.get("BUNNIFY_EDIT_MODE"))

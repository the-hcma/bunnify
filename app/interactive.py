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

from app.client import ClientError, KeyEntry
from app.github_complete import suggest_param_values
from app.theme import Theme

try:
    import readline as readline_module
except ModuleNotFoundError:
    readline_module = None

REPL_META_COMMANDS: tuple[tuple[str, str], ...] = (
    ("edit-mode", "Switch Emacs vs Vim keys: edit-mode emacs | vim"),
    ("exit", "Leave the REPL"),
    ("help", "Show this help"),
    ("keys", "List shortcuts with params / description / target"),
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


def completion_token_state(text: str) -> tuple[str, list[str], str, int]:
    """
    Split ``text`` into ``(key, completed_args, prefix, arg_index)``.

    ``arg_index`` is the parameter index currently being typed (0-based).
    A trailing space means the next empty argument is being completed.
    """
    stripped_right = text.rstrip(" \t")
    trailing_space = len(text) > len(stripped_right)
    tokens = stripped_right.split()
    if not tokens:
        return "", [], "", 0
    key = tokens[0]
    args = tokens[1:]
    if trailing_space:
        return key, args, "", len(args)
    if not args:
        return key, [], "", 0
    return key, args[:-1], args[-1], len(args) - 1


class ShortcutCompleter(Completer):
    """
    Tab-complete the first token against meta-commands + shortcut keys.

    After a space, prefers GitHub-aware parameter completions from key
    metadata, then falls back to optional OpenSearch ``suggestions_fn``.
    """

    def __init__(
        self,
        keys: Iterable[str],
        *,
        theme: Theme | None = None,
        include_meta: bool = True,
        suggestions_fn: Callable[[str], list[str]] | None = None,
        entries: Iterable[KeyEntry] | None = None,
        param_suggest_fn: Callable[..., list[str]] | None = None,
    ) -> None:
        self._keys = sorted(keys)
        self._theme = theme or Theme(enabled=False)
        self._include_meta = include_meta
        self._suggestions_fn = suggestions_fn
        self._entries_by_key: dict[str, KeyEntry] = {}
        self._param_suggest_fn = param_suggest_fn or suggest_param_values
        if entries is not None:
            self.set_entries(entries)

    def set_keys(self, keys: Iterable[str]) -> None:
        self._keys = sorted(keys)

    def set_entries(self, entries: Iterable[KeyEntry]) -> None:
        mapping = {entry.key: entry for entry in entries}
        self._entries_by_key = mapping
        self._keys = sorted(mapping.keys()) if mapping else self._keys

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
                entry = self._entries_by_key.get(key)
                meta = "shortcut"
                if entry is not None:
                    if entry.params:
                        meta = " ".join(entry.params)
                    elif entry.description:
                        meta = entry.description[:40]
                yield Completion(
                    key,
                    start_position=-len(partial),
                    style=key_style,
                    display_meta=meta,
                )

    def _param_completions(self, text: str):
        key, filled_args, prefix, arg_index = completion_token_state(text)
        style = self._theme.completion_param_style()

        key_set = {candidate.lower() for candidate in self._keys}
        if key.lower() == "edit-mode" and "edit-mode" not in key_set:
            needle = prefix.lower()
            for alias in _EDIT_MODE_SUBARGS:
                if alias.startswith(needle):
                    yield Completion(
                        alias,
                        start_position=-len(prefix),
                        style=style,
                        display_meta="edit-mode",
                    )
            return

        entry = self._entries_by_key.get(key)
        if entry is None:
            # Case-insensitive key lookup.
            lowered = key.lower()
            for candidate_key, candidate in self._entries_by_key.items():
                if candidate_key.lower() == lowered:
                    entry = candidate
                    break

        yielded = False
        if entry is not None and entry.params and arg_index < len(entry.params):
            param_name = entry.params[arg_index]
            try:
                values = self._param_suggest_fn(
                    param_name=param_name,
                    url_template=entry.url,
                    filled_args=filled_args,
                    prefix=prefix,
                )
            except OSError:
                values = []
            except ValueError:
                values = []
            except TypeError:
                values = []
            seen: set[str] = set()
            for value in values:
                if value in seen:
                    continue
                seen.add(value)
                yielded = True
                yield Completion(
                    value,
                    start_position=-len(prefix),
                    style=style,
                    display_meta=param_name,
                )

        if yielded or self._suggestions_fn is None:
            return

        try:
            suggestions = self._suggestions_fn(text)
        except ClientError:
            return
        except OSError:
            return
        except ValueError:
            return
        seen_suggestions: set[str] = set()
        for item in suggestions:
            if item in seen_suggestions:
                continue
            seen_suggestions.add(item)
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
    entries: Iterable[KeyEntry] | None = None,
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
        entries=entries,
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

"""Interactive REPL helpers: prompt_toolkit completion, history, edit modes."""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import NamedTuple

from platformdirs import user_cache_dir
from prompt_toolkit import HTML, PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import (
    CompleteEvent,
    Completer,
    Completion,
)
from prompt_toolkit.document import Document
from prompt_toolkit.enums import EditingMode
from prompt_toolkit.formatted_text import AnyFormattedText, StyleAndTextTuples
from prompt_toolkit.history import FileHistory, InMemoryHistory

from app.client import ClientError, KeyEntry
from app.github_complete import suggest_param_values
from app.theme import Theme
from app.usage import format_completion_meta

try:
    import readline as readline_module
except ModuleNotFoundError:
    readline_module = None

logger = logging.getLogger(__name__)

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

    After a finished key (exact match with params, or a trailing space),
    prefers GitHub-aware parameter completions from key metadata. Does not
    fall back to OpenSearch key suggestions while completing params.
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

    def _lookup_entry(self, key: str) -> KeyEntry | None:
        entry = self._entries_by_key.get(key)
        if entry is not None:
            return entry
        lowered = key.lower()
        for candidate_key, candidate in self._entries_by_key.items():
            if candidate_key.lower() == lowered:
                return candidate
        return None

    def wants_param_completion(self, text: str) -> bool:
        """True when Tab should complete shortcut/meta parameters, not keys."""
        stripped = text.strip()
        if not stripped:
            return False
        key = stripped.split(None, 1)[0]
        key_set = {candidate.lower() for candidate in self._keys}
        if key.lower() == "edit-mode" and "edit-mode" not in key_set:
            return True
        if any(ch.isspace() for ch in text):
            entry = self._lookup_entry(key)
            return entry is not None and bool(entry.params)
        entry = self._lookup_entry(stripped)
        return entry is not None and bool(entry.params)

    def _has_separator(self, text: str) -> bool:
        return any(ch.isspace() for ch in text)

    def get_completions(
        self,
        document: Document,
        complete_event: CompleteEvent,
    ):
        del complete_event
        text = document.text_before_cursor
        if self.wants_param_completion(text):
            yield from self._param_completions(text)
            # Still offer longer key names when the token is an exact key that
            # is also a prefix of other keys (e.g. pr → prh).
            if not self._has_separator(text):
                yield from self._longer_key_completions(text)
            return

        if self._has_separator(text):
            # Multi-token input that is not a known param slot (unknown key,
            # or a no-arg shortcut with extra text): OpenSearch suggestions.
            yield from self._suggestion_completions(text)
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
                if entry is not None:
                    meta = format_completion_meta(
                        params=entry.params,
                        optional_params=entry.optional_params,
                        description=entry.description,
                    )
                else:
                    meta = "shortcut"
                yield Completion(
                    key,
                    start_position=-len(partial),
                    style=key_style,
                    display_meta=meta,
                )

    def _longer_key_completions(self, text: str):
        needle = text.lower()
        key_style = self._theme.completion_key_style()

        for key in self._keys:
            if key.lower().startswith(needle) and key.lower() != needle:
                entry = self._entries_by_key.get(key)
                if entry is not None:
                    meta = format_completion_meta(
                        params=entry.params,
                        optional_params=entry.optional_params,
                        description=entry.description,
                    )
                else:
                    meta = "shortcut"
                yield Completion(
                    key,
                    start_position=-len(text),
                    style=key_style,
                    display_meta=meta,
                )

    def _param_completions(self, text: str):
        # Exact finished key with no trailing whitespace → complete first arg.
        insert_key_prefix = not self._has_separator(text)
        effective = f"{text.rstrip()} " if insert_key_prefix else text
        key, filled_args, prefix, arg_index = completion_token_state(effective)
        style = self._theme.completion_param_style()

        key_set = {candidate.lower() for candidate in self._keys}
        if key.lower() == "edit-mode" and "edit-mode" not in key_set:
            needle = prefix.lower()
            for alias in _EDIT_MODE_SUBARGS:
                if alias.startswith(needle):
                    if insert_key_prefix:
                        yield Completion(
                            f"{key} {alias}",
                            start_position=-len(text),
                            display=alias,
                            style=style,
                            display_meta="edit-mode",
                        )
                    else:
                        yield Completion(
                            alias,
                            start_position=-len(prefix),
                            style=style,
                            display_meta="edit-mode",
                        )
            return

        entry = self._lookup_entry(key)
        if entry is None or not entry.params:
            return
        if arg_index >= len(entry.params):
            return
        param_name = entry.params[arg_index]
        try:
            values = self._param_suggest_fn(
                param_name=param_name,
                url_template=entry.url,
                filled_args=filled_args,
                prefix=prefix,
            )
        except (OSError, ValueError, TypeError) as exc:
            logger.debug(
                "param suggestion failed for %r on key %r: %s",
                param_name,
                entry.key,
                exc,
                exc_info=True,
            )
            values = []
        seen: set[str] = set()
        # Value rows keep the command blurb so Tab still shows what the shortcut does.
        value_meta = format_completion_meta(
            description=entry.description,
            fallback=param_name,
        )
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            if insert_key_prefix:
                yield Completion(
                    f"{entry.key} {value}",
                    start_position=-len(text),
                    display=value,
                    style=style,
                    display_meta=value_meta,
                )
            else:
                yield Completion(
                    value,
                    start_position=-len(prefix),
                    style=style,
                    display_meta=value_meta,
                )

    def _suggestion_completions(self, text: str):
        if self._suggestions_fn is None:
            return
        style = self._theme.completion_param_style()
        try:
            suggestions = self._suggestions_fn(text)
        except (ClientError, OSError, ValueError) as exc:
            logger.debug(
                "OpenSearch suggestion failed for %r: %s",
                text,
                exc,
                exc_info=True,
            )
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


class _FuzzyMatch(NamedTuple):
    match_length: int
    start_pos: int
    completion: Completion
    from_key: bool


def _best_fuzzy_match(needle: str, haystack: str) -> tuple[int, int] | None:
    """Best prompt_toolkit-style subsequence match: ``(match_length, start_pos)``.

    Matching is case-insensitive (``str.casefold``); positions refer to the
    original ``haystack`` (ASCII-safe; same approach as prompt_toolkit's
    ``re.IGNORECASE`` fuzzy completer).
    """
    if not needle:
        return 0, 0
    if not haystack:
        return None
    # Casefold both sides so "Translate" matches "Google Translate …".
    folded_needle = needle.casefold()
    folded_haystack = haystack.casefold()
    pat = ".*?".join(map(re.escape, folded_needle))
    pat = f"(?=({pat}))"
    regex = re.compile(pat)
    matches = list(regex.finditer(folded_haystack))
    if not matches:
        return None
    best = min(matches, key=lambda match: (match.start(), len(match.group(1))))
    return len(best.group(1)), best.start()


def _fuzzy_highlight_display(
    word: str,
    *,
    match_length: int,
    start_pos: int,
    needle: str,
) -> AnyFormattedText:
    """Highlight subsequence matches on a completion label (prompt_toolkit parity)."""
    if match_length == 0:
        return word

    result: StyleAndTextTuples = []
    result.append(("class:fuzzymatch.outside", word[:start_pos]))
    characters = list(needle.casefold())
    for char in word[start_pos : start_pos + match_length]:
        classname = "class:fuzzymatch.inside"
        if characters and char.casefold() == characters[0]:
            classname += ".character"
            del characters[0]
        result.append((classname, char))
    result.append(("class:fuzzymatch.outside", word[start_pos + match_length :]))
    return result


class FirstTokenFuzzyCompleter(Completer):
    """Fuzzy-match the first token against shortcut keys *and* descriptions.

    Matching is case-insensitive. Offered completions always insert/display the
    command key (or meta name); descriptions are used only for matching and
    ranking.
    """

    def __init__(self, inner: ShortcutCompleter) -> None:
        self._inner = inner

    def _match_haystacks(self, completion: Completion) -> tuple[str, str]:
        """Return ``(key_text, shortcut_description)`` for fuzzy matching."""
        key_text = completion.text
        entry = self._inner._lookup_entry(key_text)
        return key_text, entry.description if entry is not None else ""

    def get_completions(
        self,
        document: Document,
        complete_event: CompleteEvent,
    ):
        text = document.text_before_cursor
        if self._inner.wants_param_completion(text) or any(ch.isspace() for ch in text):
            yield from self._inner.get_completions(document, complete_event)
            return

        needle = text
        # Ask the inner completer for the full candidate set (empty first token).
        empty = Document(text="", cursor_position=0)
        candidates = list(self._inner.get_completions(empty, complete_event))

        if needle == "":
            yield from candidates
            return

        fuzzy_matches: list[_FuzzyMatch] = []
        for completion in candidates:
            key_text, description = self._match_haystacks(completion)
            key_hit = _best_fuzzy_match(needle, key_text)
            if key_hit is not None:
                match_length, start_pos = key_hit
                fuzzy_matches.append(
                    _FuzzyMatch(match_length, start_pos, completion, True)
                )
                continue
            desc_hit = _best_fuzzy_match(needle, description)
            if desc_hit is not None:
                match_length, start_pos = desc_hit
                fuzzy_matches.append(
                    _FuzzyMatch(match_length, start_pos, completion, False)
                )

        fuzzy_matches.sort(
            key=lambda match: (
                0 if match.from_key else 1,
                match.start_pos,
                match.match_length,
            )
        )

        for match in fuzzy_matches:
            if match.from_key:
                display: AnyFormattedText = _fuzzy_highlight_display(
                    match.completion.text,
                    match_length=match.match_length,
                    start_pos=match.start_pos,
                    needle=needle,
                )
            else:
                # Description-only hit: keep the plain command key as the label.
                display = match.completion.display
            yield Completion(
                text=match.completion.text,
                start_position=-len(needle),
                display_meta=match.completion.display_meta,
                display=display,
                style=match.completion.style,
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
    # Fuzzy only on the first token so param values (repos / PRs) are not filtered.
    completer: Completer = FirstTokenFuzzyCompleter(inner)

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

"""Bunnify CLI — open shortcuts in the default browser."""

from __future__ import annotations

import shutil
import subprocess
import sys
import webbrowser
from collections.abc import Callable
from pathlib import Path

import click
from prompt_toolkit.enums import EditingMode
from prompt_toolkit.shortcuts import CompleteStyle

from app.client import (
    ClientError,
    fetch_keys,
    fetch_suggestions,
    resolve_shortcut,
)
from app.config import ENV_VAR, env_file_path, resolve_base_url
from app.interactive import (
    REPL_META_COMMANDS,
    REPL_META_NAMES,
    create_repl_session,
    default_edit_mode_from_environ,
    editing_mode_enum,
    normalize_edit_mode_choice,
    read_shortcut_query,
    repl_prompt_message,
)
from app.theme import Theme, stdout_color_enabled


def open_url(url: str, *, opener: Callable[[str], bool] | None = None) -> None:
    """Open ``url`` in the platform default browser."""
    open_fn = opener or webbrowser.open
    opened = open_fn(url)
    if opened is False:
        raise ClientError(f"Failed to open browser for {url}")


def pick_key_with_fzf(
    keys: list[str],
    *,
    query: str = "",
    fzf_bin: str | None = None,
) -> str | None:
    """Fuzzy-pick a shortcut key via fzf. Returns ``None`` if cancelled."""
    binary = fzf_bin or shutil.which("fzf")
    if not binary:
        raise ClientError(
            "fzf not found on PATH. Install fzf or pass an exact shortcut."
        )
    command = [
        binary,
        "--prompt=bunnify> ",
        "--height=40%",
        "--layout=reverse",
        "--exit-0",
    ]
    if query:
        command.extend(["--query", query, "--select-1"])
    try:
        completed = subprocess.run(
            command,
            input="\n".join(keys) + ("\n" if keys else ""),
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )
    except subprocess.TimeoutExpired as exc:
        raise ClientError("fzf timed out") from exc
    if completed.returncode != 0:
        return None
    selected = completed.stdout.strip()
    return selected or None


def matching_keys(keys: list[str], prefix: str) -> list[str]:
    """Return keys that start with ``prefix`` (case-insensitive)."""
    needle = prefix.lower()
    return [key for key in keys if key.lower().startswith(needle)]


def build_query_from_args(args: tuple[str, ...]) -> str:
    return " ".join(args).strip()


def _print_repl_help(theme: Theme) -> None:
    click.echo(theme.header("Commands"))
    rows: list[tuple[str, str]] = [
        ("<shortcut> [args]", "Resolve and open a bookmark / special"),
        *REPL_META_COMMANDS,
    ]
    width = max(len(name) for name, _ in rows)
    for name, blurb in rows:
        gap = " " * (width - len(name) + 2)
        click.echo(f"  {theme.cmd(name)}{gap}{theme.dim(blurb)}")
    click.echo()
    click.echo(
        theme.dim(
            "Tip: Tab fuzzy-completes shortcuts and meta-commands; history "
            "auto-suggests prior lines. edit-mode emacs | vim switches keys. "
            "Ctrl-D / Ctrl-C leave the REPL."
        )
    )


def _expand_query(
    query: str,
    *,
    keys: list[str],
    fzf_picker: Callable[..., str | None],
) -> str:
    """Expand an ambiguous sole-token prefix via unique match or fzf."""
    parts = query.split(None, 1)
    key_token = parts[0]
    rest = parts[1] if len(parts) > 1 else ""
    if key_token in keys:
        return query
    matches = matching_keys(keys, key_token)
    if len(matches) > 1:
        selected = fzf_picker(matches, query=key_token)
        if selected is None:
            raise ClientError("No shortcut selected")
        return f"{selected} {rest}".strip()
    if len(matches) == 1:
        return f"{matches[0]} {rest}".strip()
    return query


def _handle_resolved(
    query: str,
    *,
    base_url: str,
    theme: Theme,
    print_url: bool,
    open_browser: bool,
    opener: Callable[[str], bool] | None,
) -> None:
    resolved = resolve_shortcut(query, base_url=base_url, strict=True)
    if print_url:
        click.echo(resolved.url)
    if open_browser:
        open_url(resolved.url, opener=opener)
        kind = resolved.kind or "url"
        key = resolved.key or ""
        meta = f"{kind}" + (f":{key}" if key else "")
        click.echo(
            f"{theme.ok('opened')} {theme.url(resolved.url)} {theme.meta(f'({meta})')}",
            err=True,
        )


def _apply_edit_mode(
    session: object | None,
    arg: str,
    *,
    theme: Theme,
) -> None:
    sub = arg.strip().lower()
    if sub in ("emacs", "e"):
        mode = EditingMode.EMACS
        label = "Emacs"
    elif sub in ("vim", "vi", "v"):
        mode = EditingMode.VI
        label = "Vim"
    else:
        click.echo(theme.err("Usage: edit-mode emacs | vim"), err=True)
        return
    if session is not None and hasattr(session, "editing_mode"):
        session.editing_mode = mode  # type: ignore[attr-defined]
    click.echo(theme.ok(f"Line editing: {label}"))


def _run_repl(
    *,
    base_url: str,
    theme: Theme,
    print_url: bool,
    open_browser: bool,
    opener: Callable[[str], bool] | None,
    input_fn: Callable[[str], str] | None,
    fzf_picker: Callable[..., str | None],
    editing_mode: EditingMode,
) -> None:
    keys = fetch_keys(base_url=base_url)
    click.echo(
        f"{theme.brand('bunnify')} "
        f"{theme.dim('interactive — Tab fuzzy-completes; quit to exit')}"
    )
    click.echo(
        theme.meta(
            f"server {base_url} · {len(keys)} shortcuts · "
            f"edit-mode {'emacs' if editing_mode == EditingMode.EMACS else 'vim'}"
        )
    )

    if input_fn is not None:
        # Test / non-TTY injection path: loop until EOF (None).
        while True:
            line = read_shortcut_query(
                keys=list(REPL_META_NAMES) + keys,
                prompt="bunnify> ",
                input_fn=input_fn,
            )
            if line is None:
                break
            if not line:
                continue
            if not _dispatch_repl_line(
                line,
                keys=keys,
                base_url=base_url,
                theme=theme,
                print_url=print_url,
                open_browser=open_browser,
                opener=opener,
                fzf_picker=fzf_picker,
                session=None,
                set_keys=None,
            ):
                break
        return

    def suggestions_fn(query: str) -> list[str]:
        return fetch_suggestions(query, base_url=base_url)

    session, completer = create_repl_session(
        keys=keys,
        theme=theme,
        editing_mode=editing_mode,
        suggestions_fn=suggestions_fn,
    )

    def set_keys(new_keys: list[str]) -> None:
        nonlocal keys
        keys = new_keys
        completer.set_keys(new_keys)

    while True:
        try:
            line = session.prompt(
                repl_prompt_message(theme),
                complete_style=CompleteStyle.MULTI_COLUMN,
            )
        except EOFError:
            # domesti-bot parity: both Ctrl-D and Ctrl-C leave the REPL.
            click.echo()
            break
        except KeyboardInterrupt:
            click.echo()
            break
        stripped = line.strip()
        if not stripped:
            continue
        if not _dispatch_repl_line(
            stripped,
            keys=keys,
            base_url=base_url,
            theme=theme,
            print_url=print_url,
            open_browser=open_browser,
            opener=opener,
            fzf_picker=fzf_picker,
            session=session,
            set_keys=set_keys,
        ):
            break


def _dispatch_repl_line(
    line: str,
    *,
    keys: list[str],
    base_url: str,
    theme: Theme,
    print_url: bool,
    open_browser: bool,
    opener: Callable[[str], bool] | None,
    fzf_picker: Callable[..., str | None],
    session: object | None,
    set_keys: Callable[[list[str]], None] | None,
) -> bool:
    """Handle one REPL line. Returns False when the REPL should exit."""
    parts = line.split(None, 1)
    head = parts[0]
    rest = parts[1] if len(parts) > 1 else ""
    lowered = head.lower()
    key_set = {key.lower() for key in keys}

    # Meta commands only when they do not collide with a real shortcut key.
    if lowered in {"quit", "exit"} and lowered not in key_set:
        return False
    if lowered == "help" and "help" not in key_set:
        _print_repl_help(theme)
        return True
    if lowered == "keys" and "keys" not in key_set:
        for key in keys:
            click.echo(f"  {theme.cmd(key)}")
        click.echo(theme.meta(f"{len(keys)} keys"))
        return True
    if lowered == "refresh" and "refresh" not in key_set:
        try:
            new_keys = fetch_keys(base_url=base_url)
        except ClientError as exc:
            click.echo(theme.err(f"error: {exc}"), err=True)
            return True
        if set_keys is not None:
            set_keys(new_keys)
        else:
            keys[:] = new_keys
        click.echo(theme.ok(f"refreshed · {len(new_keys)} shortcuts"))
        return True
    if lowered == "edit-mode" and "edit-mode" not in key_set:
        _apply_edit_mode(session, rest, theme=theme)
        return True

    try:
        query = _expand_query(line, keys=keys, fzf_picker=fzf_picker)
        _handle_resolved(
            query,
            base_url=base_url,
            theme=theme,
            print_url=print_url,
            open_browser=open_browser,
            opener=opener,
        )
    except ClientError as exc:
        click.echo(theme.err(f"error: {exc}"), err=True)
    return True


def _run(
    *,
    shortcut_args: tuple[str, ...],
    base_url: str,
    list_keys: bool,
    use_fzf: bool,
    fzf_query: str,
    print_url: bool,
    open_browser: bool,
    theme: Theme | None = None,
    opener: Callable[[str], bool] | None = None,
    input_fn: Callable[[str], str] | None = None,
    fzf_picker: Callable[..., str | None] | None = None,
    editing_mode: EditingMode = EditingMode.VI,
) -> None:
    active_theme = theme or Theme(enabled=False)
    picker = fzf_picker or pick_key_with_fzf

    if list_keys:
        for key in fetch_keys(base_url=base_url):
            click.echo(key)
        return

    query = build_query_from_args(shortcut_args)

    if use_fzf:
        keys = fetch_keys(base_url=base_url)
        selected = picker(keys, query=fzf_query)
        if selected is None:
            raise ClientError("No shortcut selected")
        query = f"{selected} {query}".strip()
        _handle_resolved(
            query,
            base_url=base_url,
            theme=active_theme,
            print_url=print_url,
            open_browser=open_browser,
            opener=opener,
        )
        return

    if not query:
        _run_repl(
            base_url=base_url,
            theme=active_theme,
            print_url=print_url,
            open_browser=open_browser,
            opener=opener,
            input_fn=input_fn,
            fzf_picker=picker,
            editing_mode=editing_mode,
        )
        return

    keys = fetch_keys(base_url=base_url)
    query = _expand_query(query, keys=keys, fzf_picker=picker)
    _handle_resolved(
        query,
        base_url=base_url,
        theme=active_theme,
        print_url=print_url,
        open_browser=open_browser,
        opener=opener,
    )


@click.command(
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.argument("shortcut_args", nargs=-1)
@click.option(
    "--base-url",
    "base_url_option",
    default=None,
    help=(
        "Base URL of the local Bunnify server. "
        f"Falls back to {ENV_VAR} / bunnify.env; prompts and persists if unset."
    ),
)
@click.option(
    "--list-keys",
    is_flag=True,
    help="Print shortcut keys (one per line) for fzf / shell completion.",
)
@click.option(
    "--fzf",
    "use_fzf",
    is_flag=True,
    help="Fuzzy-pick a shortcut with fzf, then open it (optional params follow).",
)
@click.option(
    "--query",
    "fzf_query",
    default="",
    help="Seed the fzf picker in --fzf mode without consuming shortcut params.",
)
@click.option(
    "--print-url",
    is_flag=True,
    help="Print the resolved URL instead of opening a browser.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Resolve and print the URL without opening a browser.",
)
@click.option(
    "--color",
    "color_mode",
    type=click.Choice(["auto", "always", "never"], case_sensitive=False),
    default="auto",
    show_default=True,
    help="ANSI color output (disabled when NO_COLOR is set).",
)
@click.option(
    "--edit-mode",
    "edit_mode",
    type=click.Choice(["emacs", "vim"], case_sensitive=False),
    default=None,
    help=(
        "REPL line-editing bindings (default: vim; BUNNIFY_EDIT_MODE can set "
        "emacs / e / vim / vi / v). Switch mid-session with `edit-mode`."
    ),
)
@click.option(
    "--env-file",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to bunnify.env (default: repo-root bunnify.env).",
)
def main(
    shortcut_args: tuple[str, ...],
    base_url_option: str | None,
    list_keys: bool,
    use_fzf: bool,
    fzf_query: str,
    print_url: bool,
    dry_run: bool,
    color_mode: str,
    edit_mode: str | None,
    env_file: Path | None,
) -> None:
    """
    Open a Bunnify shortcut in your default browser.

    \b
    Interactive REPL (loop with fuzzy Tab completion + history):
      ./scripts/bunnify

    \b
    Direct:
      ./scripts/bunnify vault
      ./scripts/bunnify pr 12345

    \b
    Fuzzy pick (fzf) for argv / shell completion workflows:
      ./scripts/bunnify --fzf
      ./scripts/bunnify --list-keys | fzf
    """
    theme = Theme(enabled=stdout_color_enabled(color_mode.lower()))
    mode_name = (
        normalize_edit_mode_choice(edit_mode)
        if edit_mode is not None
        else default_edit_mode_from_environ()
    )
    try:
        resolved_url = resolve_base_url(
            cli_value=base_url_option,
            persist=base_url_option is None,
            env_path=env_file or env_file_path(),
            prompt_fn=lambda message: click.prompt(
                message.rstrip(": "),
                default="",
                show_default=False,
            ),
        )
        _run(
            shortcut_args=shortcut_args,
            base_url=resolved_url,
            list_keys=list_keys,
            use_fzf=use_fzf,
            fzf_query=fzf_query,
            print_url=print_url or dry_run,
            open_browser=not (print_url or dry_run),
            theme=theme,
            editing_mode=editing_mode_enum(mode_name),
        )
    except (ClientError, ValueError, OSError) as exc:
        click.echo(theme.err(f"error: {exc}"), err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

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
    DEFAULT_BASE_URL,
    ClientError,
    HealthStatus,
    KeyEntry,
    check_health,
    fetch_health,
    fetch_key_entries,
    fetch_keys,
    fetch_suggestions,
    resolve_shortcut,
)
from app.config import (
    ENV_VAR,
    LOCAL_PORT_FILE_NAME,
    MIN_LOCAL_PORT,
    ServerPreferences,
    default_bookmarks_path,
    ensure_user_bookmarks,
    env_file_path,
    legacy_env_file_path,
    load_preferences,
    read_base_url_from_env_file,
    resolve_base_url,
    run_dir,
    save_preferences,
)
from app.github_complete import (
    bootstrap_github_completion_cache,
    ensure_github_authenticated,
)
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
from app.local_server import ensure_local_server, port_is_free, stop_local_server
from app.theme import Theme, stdout_color_enabled
from app.usage import format_key_usage_lines
from app.version import build_info, get_build_info

BUILD_INFO = build_info()


def ensure_ready_base_url(
    *,
    cli_value: str | None = None,
    environ: dict[str, str] | None = None,
    env_path: Path | None = None,
    prompt_fn: Callable[[str], str] | None = None,
    allow_prompt: bool | None = None,
    print_fn: Callable[[str], None] | None = None,
) -> str:
    """Resolve preferences and return a verified or explicitly overridden URL."""
    ask = prompt_fn or input
    log = print_fn or click.echo
    interactive = (
        allow_prompt
        if allow_prompt is not None
        else sys.stdin.isatty() and sys.stdout.isatty()
    )
    if cli_value is not None and cli_value.strip():
        base_url = resolve_base_url(cli_value=cli_value, persist=False)
        if not check_health(base_url):
            log(f"warning: Bunnify health check failed for {base_url}")
        return base_url

    preferences = load_preferences(environ=environ, env_path=env_path)
    if preferences is None and env_path is None:
        legacy_base_url = read_base_url_from_env_file(legacy_env_file_path())
        if legacy_base_url:
            preferences = ServerPreferences(
                mode="remote",
                base_url=resolve_base_url(
                    cli_value=legacy_base_url,
                    persist=False,
                ),
                local_port=None,
            )
    if preferences is None:
        if interactive:
            return run_setup(
                prompt_fn=ask,
                environ=environ,
                env_path=env_path,
                print_fn=log,
            )
        return DEFAULT_BASE_URL

    if preferences.mode == "remote":
        if not preferences.base_url:
            raise ClientError("Remote mode requires BUNNIFY_BASE_URL")
        return _wait_for_healthy_remote(
            preferences.base_url,
            prompt_fn=ask,
            interactive=interactive,
            print_fn=log,
        )

    bookmarks = ensure_user_bookmarks(
        environ=environ,
        prompt_fn=ask,
        allow_prompt=interactive,
        print_fn=log,
    )
    preferred_port = preferences.local_port
    while True:
        try:
            base_url, actual_port = ensure_local_server(
                port=preferred_port,
                pid_dir=run_dir(environ=environ),
                bookmarks=bookmarks,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            if not interactive or not _retry_requested(
                ask, f"Local server failed: {exc}\nRetry? [Y/n]: "
            ):
                raise ClientError(str(exc)) from exc
            preferred_port = None
            continue
        if not check_health(base_url):
            message = f"Local server health check failed for {base_url}"
            if not interactive or not _retry_requested(
                ask, f"{message}\nRetry? [Y/n]: "
            ):
                raise ClientError(message)
            continue
        if actual_port != preferences.local_port or base_url != preferences.base_url:
            path = env_path if env_path is not None else env_file_path(environ=environ)
            save_preferences(
                ServerPreferences(
                    mode="local",
                    base_url=base_url,
                    local_port=actual_port,
                ),
                env_path=path,
                environ=environ,
            )
        return base_url


def format_browser_setup_text(base_url: str) -> str:
    """Return Chrome/Edge OpenSearch instructions for ``base_url``."""
    normalized = base_url.rstrip("/")
    search_url = f"{normalized}/search/?q=%s"
    return "\n".join(
        [
            "Configure Chrome or Edge for address-bar shortcuts",
            "(use this exact URL — it must match the server you just set up):",
            "",
            "1. Open search-engine settings:",
            "     Chrome → chrome://settings/searchEngines",
            "     Edge   → edge://settings/searchEngines",
            "2. Add (or edit) a site search entry:",
            "     Search engine name: Bunnify",
            "     Shortcut / keyword: b",
            f"     URL: {search_url}",
            "3. Save, then in the address bar type: b gh",
            "",
            f"Saved server base URL: {normalized}",
            "Guide: https://github.com/the-hcma/bunnify/blob/main/CHROME_SETUP.md",
        ]
    )


def format_onboarding_text() -> str:
    """Return post-install / post-upgrade next steps for the terminal."""
    bookmarks = default_bookmarks_path()
    config = env_file_path()
    return "\n".join(
        [
            "Bunnify — next steps after install or upgrade",
            "",
            "1. Create your bookmarks file (required before the server starts):",
            f"     mkdir -p {bookmarks.parent}",
            "     curl -fsSL \\",
            "       https://raw.githubusercontent.com/the-hcma/bunnify/"
            "main/bunnify.json.example \\",
            f"       -o {bookmarks}",
            f"     # edit {bookmarks}",
            "",
            "2. Configure and start the server (local on a laptop; remote for a",
            "   home/always-on host):",
            "     bunnify setup",
            "   Guide: https://github.com/the-hcma/bunnify/blob/main/docs/LOCAL.md",
            "",
            "3. Configure Chrome or Edge using BUNNIFY_BASE_URL from:",
            f"     {config}",
            "   Guide: https://github.com/the-hcma/bunnify/blob/main/CHROME_SETUP.md",
            "",
            "4. Try it:  bunnify gh   (or address-bar keyword, e.g. b gh)",
            "",
            "Upgrade later:",
            "     pipx upgrade bunnify",
            "     bunnify --version",
            "   Bookmarks and config.env are kept across upgrades.",
            "",
            "Docs: https://github.com/the-hcma/bunnify",
            "Re-print this message anytime:  bunnify onboard",
        ]
    )


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


def run_setup(
    *,
    prompt_fn: Callable[[str], str] | None = None,
    environ: dict[str, str] | None = None,
    env_path: Path | None = None,
    print_fn: Callable[[str], None] | None = None,
    theme: Theme | None = None,
) -> str:
    """Interactively configure a verified local or remote Bunnify server."""
    ask = prompt_fn or input
    log = print_fn or click.echo
    colors = theme if theme is not None else Theme(enabled=False)
    path = env_path if env_path is not None else env_file_path(environ=environ)
    existing = load_preferences(environ=environ, env_path=path)

    log(colors.header("Bunnify setup"))
    log(colors.dim("Press Enter to accept the value in [brackets]."))

    while True:
        try:
            answer = ask(
                colors.brand("Server mode")
                + colors.dim(" [local]")
                + colors.dim(" (Enter accepts)")
                + ": "
            )
        except EOFError as exc:
            raise ClientError("Setup aborted") from exc
        mode = answer.strip().lower() or "local"
        if mode in {"l", "local"}:
            mode = "local"
            break
        if mode in {"r", "remote"}:
            mode = "remote"
            break
        log(colors.warn("Please enter 'local' or 'remote'."))

    if mode == "local":
        bookmarks = ensure_user_bookmarks(
            environ=environ,
            prompt_fn=ask,
            allow_prompt=True,
            print_fn=log,
        )
        pid_dir = run_dir(environ=environ)
        preferred_port = _prompt_local_port(
            ask,
            existing_port=(
                existing.local_port
                if existing is not None and existing.mode == "local"
                else None
            ),
            pid_dir=pid_dir,
            print_fn=log,
            theme=colors,
        )
        while True:
            try:
                base_url, actual_port = ensure_local_server(
                    port=preferred_port,
                    pid_dir=pid_dir,
                    bookmarks=bookmarks,
                )
            except (OSError, RuntimeError, ValueError) as exc:
                if _retry_requested(
                    ask,
                    colors.warn(f"Local server failed: {exc}\n") + "Retry? [Y/n]: ",
                ):
                    preferred_port = None
                    continue
                raise ClientError("Setup aborted; settings were not changed") from exc
            health = fetch_health(base_url)
            if health.ok:
                preferences = ServerPreferences(
                    mode="local",
                    base_url=base_url,
                    local_port=actual_port,
                )
                save_preferences(preferences, env_path=path, environ=environ)
                build_label = _format_running_build(health)
                if build_label == "unknown build":
                    local_version, local_commit = get_build_info()
                    log(
                        colors.ok(
                            "✓ Local Bunnify is healthy (unknown build; "
                            f"this CLI is {local_version} ({local_commit}))"
                        )
                    )
                else:
                    log(colors.ok(f"✓ Local Bunnify is healthy ({build_label})"))
                log(colors.ok(f"✓ Configured local Bunnify server at {base_url}"))
                log("")
                log(colors.header("Browser"))
                for line in format_browser_setup_text(base_url).splitlines():
                    log(line)
                return base_url
            if not _retry_requested(
                ask,
                colors.warn(f"Health check failed for {base_url}.\n")
                + "Retry? [Y/n]: ",
            ):
                raise ClientError("Setup aborted; settings were not changed")

    suggestion = (
        existing.base_url
        if existing is not None and existing.mode == "remote" and existing.base_url
        else DEFAULT_BASE_URL
    )
    while True:
        try:
            answer = ask(
                colors.brand("Remote Bunnify URL")
                + colors.dim(f" [{suggestion}]")
                + colors.dim(" (Enter accepts)")
                + ": "
            )
        except EOFError as exc:
            raise ClientError("Setup aborted; settings were not changed") from exc
        base_url = resolve_base_url(
            cli_value=answer.strip() or suggestion,
            persist=False,
        )
        if check_health(base_url):
            preferences = ServerPreferences(
                mode="remote",
                base_url=base_url,
                local_port=None,
            )
            save_preferences(preferences, env_path=path, environ=environ)
            log(colors.ok(f"✓ Health check passed for {base_url}"))
            log(colors.ok(f"✓ Configured remote Bunnify server at {base_url}"))
            log("")
            log(colors.header("Browser"))
            for line in format_browser_setup_text(base_url).splitlines():
                log(line)
            return base_url
        if not _retry_requested(
            ask,
            colors.warn(f"Health check failed for {base_url}.\n")
            + "Try another URL? [Y/n]: ",
        ):
            raise ClientError("Setup aborted; settings were not changed")


def matching_keys(keys: list[str], prefix: str) -> list[str]:
    """Return keys that start with ``prefix`` (case-insensitive)."""
    needle = prefix.lower()
    return [key for key in keys if key.lower().startswith(needle)]


def build_query_from_args(args: tuple[str, ...]) -> str:
    return " ".join(args).strip()


def _builds_match(health: HealthStatus) -> bool:
    """Return whether a healthy remote build matches this CLI install."""
    if health.version is None or health.commit is None:
        return False
    local_version, local_commit = get_build_info()
    return health.version == local_version and health.commit == local_commit


def _confirm_explicit_yes(prompt_fn: Callable[[str], str], message: str) -> bool:
    """Return True only for an explicit yes (empty input is no)."""
    try:
        answer = prompt_fn(message)
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


def _find_usable_local_port(start: int) -> int:
    """Return the next free port or healthy Bunnify at or above ``start``."""
    candidate = max(start, MIN_LOCAL_PORT)
    while candidate <= 65535:
        if port_is_free(candidate):
            return candidate
        if check_health(f"http://127.0.0.1:{candidate}"):
            return candidate
        candidate += 1
    raise ClientError(f"No free local port found between {MIN_LOCAL_PORT} and 65535")


def _format_running_build(health: HealthStatus) -> str:
    """Human-readable version/commit from a health probe."""
    if health.version and health.commit:
        return f"{health.version} ({health.commit})"
    if health.version:
        return health.version
    if health.commit:
        return f"commit {health.commit}"
    return "unknown build"


def _managed_local_port(pid_dir: Path) -> int | None:
    """Return the port recorded for this CLI run dir, if any."""
    try:
        return int((pid_dir / LOCAL_PORT_FILE_NAME).read_text(encoding="utf-8").strip())
    except OSError, ValueError:
        return None


def _offer_restart_mismatched_server(
    prompt_fn: Callable[[str], str],
    *,
    port: int,
    health: HealthStatus,
    pid_dir: Path,
    print_fn: Callable[[str], None],
    theme: Theme,
) -> int | None:
    """Offer a restart when a busy port serves a different Bunnify build.

    Returns the port when the caller should reuse or restart into it, or
    ``None`` when the prompt loop should continue (stop failed / still busy).

    Restart is only offered when ``pid_dir`` records this same ``port``, so we
    do not SIGTERM an unrelated managed server or loop when stop is a no-op.
    """
    local_version, local_commit = get_build_info()
    local_label = f"{local_version} ({local_commit})"
    running_label = _format_running_build(health)
    print_fn(theme.ok(f"✓ Port {port} is already serving Bunnify {running_label}"))
    if _builds_match(health):
        return port
    if health.version is None or health.commit is None:
        print_fn(
            theme.warn(
                f"Could not determine the running build (this CLI is {local_label})."
            )
        )
    else:
        print_fn(theme.warn(f"Running build differs from this CLI ({local_label})."))
    if _managed_local_port(pid_dir) != port:
        print_fn(
            theme.warn(
                "Not managed by this CLI run directory; reusing the running server. "
                "Stop it yourself (or choose another port) to start a fresh build."
            )
        )
        return port
    if not _confirm_explicit_yes(
        prompt_fn,
        "Restart the managed local server with this CLI? [y/N]: ",
    ):
        return port
    try:
        stop_local_server(pid_dir)
    except RuntimeError as exc:
        print_fn(theme.warn(f"Could not stop the managed server: {exc}"))
        return None
    if port_is_free(port):
        print_fn(theme.ok(f"✓ Stopped previous server; port {port} is free"))
        return port
    print_fn(
        theme.warn(
            f"Port {port} is still busy after stop. "
            "Choose another port, or stop the other process."
        )
    )
    return None


def _prompt_local_port(
    prompt_fn: Callable[[str], str],
    *,
    existing_port: int | None,
    pid_dir: Path,
    print_fn: Callable[[str], None] | None = None,
    theme: Theme | None = None,
) -> int:
    """Ask for a free non-privileged local server port."""
    log = print_fn or (lambda _message: None)
    colors = theme if theme is not None else Theme(enabled=False)
    default_port = existing_port if existing_port is not None else 8000
    if default_port != 0 and not MIN_LOCAL_PORT <= default_port <= 65535:
        default_port = 8000

    while True:
        try:
            answer = prompt_fn(
                colors.brand("Local server port")
                + colors.dim(f" [{default_port}]")
                + colors.dim(" (Enter accepts)")
                + ": "
            )
        except EOFError as exc:
            raise ClientError("Setup aborted") from exc
        stripped = answer.strip()
        port = default_port if not stripped else None
        if not stripped:
            pass
        else:
            try:
                port = int(stripped)
            except ValueError:
                log(colors.warn(f"Invalid port: {stripped!r}. Try again."))
                continue
        assert port is not None
        if port == 0:
            log(colors.dim("Using an OS-assigned ephemeral port (0)."))
            return 0
        if not MIN_LOCAL_PORT <= port <= 65535:
            log(
                colors.warn(
                    f"Port must be {MIN_LOCAL_PORT}-65535 "
                    "(or 0 for an OS-assigned port). Try again."
                )
            )
            continue
        if port_is_free(port):
            log(colors.ok(f"✓ Port {port} is free"))
            return port
        health = fetch_health(f"http://127.0.0.1:{port}")
        if health.ok:
            chosen = _offer_restart_mismatched_server(
                prompt_fn,
                port=port,
                health=health,
                pid_dir=pid_dir,
                print_fn=log,
                theme=colors,
            )
            if chosen is not None:
                return chosen
            continue
        log(colors.warn(f"Port {port} is already in use. Searching for a free port…"))
        found = _find_usable_local_port(port + 1)
        if port_is_free(found):
            log(colors.ok(f"✓ Found free port {found}"))
        else:
            found_health = fetch_health(f"http://127.0.0.1:{found}")
            log(
                colors.ok(
                    f"✓ Found healthy Bunnify on port {found} "
                    f"({_format_running_build(found_health)})"
                )
            )
        return found


def _retry_requested(prompt_fn: Callable[[str], str], message: str) -> bool:
    try:
        answer = prompt_fn(message)
    except EOFError:
        return False
    return answer.strip().lower() not in {"abort", "n", "no", "q", "quit"}


def _wait_for_healthy_remote(
    base_url: str,
    *,
    prompt_fn: Callable[[str], str],
    interactive: bool,
    print_fn: Callable[[str], None],
) -> str:
    while not check_health(base_url):
        message = f"Cannot reach a healthy Bunnify server at {base_url}"
        if not interactive:
            raise ClientError(message)
        print_fn(message)
        if not _retry_requested(prompt_fn, "Retry connection? [Y/n]: "):
            raise ClientError("Connection aborted")
    return base_url


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
    entries = fetch_key_entries(base_url=base_url)
    keys = [entry.key for entry in entries]
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
                set_entries=None,
            ):
                break
        return

    interactive_auth = sys.stdin.isatty() and sys.stdout.isatty()
    github_token = ensure_github_authenticated(interactive=interactive_auth)
    if github_token:
        bootstrapped = bootstrap_github_completion_cache(
            url_templates=[entry.url for entry in entries],
            token=github_token,
        )
        status = (
            f"GitHub completion · {bootstrapped['orgs']} orgs · "
            f"{bootstrapped['repos']} repos"
        )
        if bootstrapped.get("entries"):
            status += " (loaded from disk"
            if bootstrapped.get("refreshing"):
                status += ", refreshing…"
            status += ")"
        elif bootstrapped.get("refreshing"):
            status += " (warming in background…)"
        click.echo(theme.dim(status))
    else:
        click.echo(
            theme.meta(
                "GitHub not authenticated — set GITHUB_TOKEN / GH_TOKEN "
                "or run `gh auth login` for repo Tab completion"
            )
        )

    def suggestions_fn(query: str) -> list[str]:
        return fetch_suggestions(query, base_url=base_url)

    session, completer = create_repl_session(
        keys=keys,
        theme=theme,
        editing_mode=editing_mode,
        suggestions_fn=suggestions_fn,
        entries=entries,
    )

    def set_keys(new_keys: list[str]) -> None:
        nonlocal keys
        keys = new_keys
        completer.set_keys(new_keys)

    def set_entries(new_entries: list[KeyEntry]) -> None:
        completer.set_entries(new_entries)
        set_keys([entry.key for entry in new_entries])

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
            set_entries=set_entries,
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
    set_entries: Callable[[list[KeyEntry]], None] | None = None,
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
        try:
            entries = fetch_key_entries(base_url=base_url)
        except ClientError as exc:
            click.echo(theme.err(f"error: {exc}"), err=True)
            return True
        for usage_line in format_key_usage_lines(entries, theme=theme):
            click.echo(usage_line)
        click.echo(theme.meta(f"{len(entries)} keys"))
        return True
    if lowered == "refresh" and "refresh" not in key_set:
        try:
            new_entries = fetch_key_entries(base_url=base_url)
        except ClientError as exc:
            click.echo(theme.err(f"error: {exc}"), err=True)
            return True
        new_keys = [entry.key for entry in new_entries]
        if set_entries is not None:
            set_entries(new_entries)
        elif set_keys is not None:
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
    list_usage: bool = False,
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

    if list_usage:
        entries = fetch_key_entries(base_url=base_url)
        for usage_line in format_key_usage_lines(entries, theme=active_theme):
            click.echo(usage_line)
        return

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
@click.version_option(
    version=BUILD_INFO.removeprefix("bunnify "),
    prog_name="bunnify",
    message="%(prog)s %(version)s",
)
@click.argument("shortcut_args", nargs=-1)
@click.option(
    "--base-url",
    "base_url_option",
    default=None,
    help=(
        "Base URL of the local Bunnify server. "
        f"Falls back to {ENV_VAR}, ~/.config/bunnify/config.env, then legacy "
        "bunnify.env; prompts and persists to the XDG config if unset."
    ),
)
@click.option(
    "--list-keys",
    is_flag=True,
    help="Print shortcut keys (one per line) for fzf / shell completion.",
)
@click.option(
    "--list-usage",
    is_flag=True,
    help="Print short usage for each shortcut (params, description, target).",
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
    help=(
        "Path to the environment file (default: ~/.config/bunnify/config.env, "
        "XDG-aware; legacy repo-root bunnify.env is a fallback)."
    ),
)
@click.option(
    "--onboard",
    "onboard_requested",
    is_flag=True,
    help="Print post-install / upgrade next steps (also: `bunnify onboard`).",
)
@click.option(
    "--setup",
    "setup_requested",
    is_flag=True,
    help="Configure a verified local or remote server (also: `bunnify setup`).",
)
def main(
    shortcut_args: tuple[str, ...],
    base_url_option: str | None,
    list_keys: bool,
    list_usage: bool,
    use_fzf: bool,
    fzf_query: str,
    print_url: bool,
    dry_run: bool,
    color_mode: str,
    edit_mode: str | None,
    env_file: Path | None,
    onboard_requested: bool,
    setup_requested: bool,
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
    After pipx install or upgrade (`onboard` is a reserved shortcut name):
      bunnify onboard
      bunnify --onboard

    \b
    Server setup (`setup` is a reserved shortcut name):
      ./scripts/bunnify setup
      ./scripts/bunnify --setup

    \b
    Build identity (`version` is a reserved shortcut name):
      ./scripts/bunnify version
      ./scripts/bunnify --version

    \b
    Fuzzy pick (fzf) for argv / shell completion workflows:
      ./scripts/bunnify --fzf
      ./scripts/bunnify --list-keys | fzf
      ./scripts/bunnify --list-usage
    """
    if shortcut_args == ("version",):
        click.echo(BUILD_INFO)
        return

    if onboard_requested or shortcut_args == ("onboard",):
        click.echo(format_onboarding_text())
        return

    theme = Theme(enabled=stdout_color_enabled(color_mode.lower()))

    def prompt_fn(message: str) -> str:
        return click.prompt(
            message.rstrip(": "),
            default="",
            show_default=False,
        )

    mode_name = (
        normalize_edit_mode_choice(edit_mode)
        if edit_mode is not None
        else default_edit_mode_from_environ()
    )
    try:
        if setup_requested or shortcut_args == ("setup",):
            run_setup(
                prompt_fn=prompt_fn,
                env_path=env_file,
                print_fn=click.echo,
                theme=theme,
            )
            return
        resolved_url = ensure_ready_base_url(
            cli_value=base_url_option,
            env_path=env_file,
            prompt_fn=prompt_fn,
        )
        _run(
            shortcut_args=shortcut_args,
            base_url=resolved_url,
            list_keys=list_keys,
            list_usage=list_usage,
            use_fzf=use_fzf,
            fzf_query=fzf_query,
            print_url=print_url or dry_run,
            open_browser=not (print_url or dry_run),
            theme=theme,
            editing_mode=editing_mode_enum(mode_name),
        )
    except (ClientError, FileNotFoundError, ValueError, OSError, RuntimeError) as exc:
        click.echo(theme.err(f"error: {exc}"), err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

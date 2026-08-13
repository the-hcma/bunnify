"""User configuration: XDG paths, bookmarks seed/migration, base URL persistence."""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Literal

import click

from app.client import DEFAULT_BASE_URL

BOOKMARKS_ENV_VAR = "BUNNIFY_BOOKMARKS"
BOOKMARKS_FILE_NAME = "bookmarks.json"
DATA_DIR_ENV_VAR = "BUNNIFY_DATA_DIR"
ENV_FILE_NAME = "config.env"
ENV_VAR = "BUNNIFY_BASE_URL"
EXAMPLE_BOOKMARKS_NAME = "bunnify.json.example"
LEGACY_ENV_FILE_NAME = "bunnify.env"
LEGACY_BOOKMARKS_PATH = Path.home() / "work" / "bunnify" / "bunnify.json"
LOCAL_PORT_ENV_VAR = "BUNNIFY_LOCAL_PORT"
MODE_ENV_VAR = "BUNNIFY_MODE"


@dataclass(frozen=True)
class ServerPreferences:
    mode: Literal["local", "remote"]
    base_url: str
    local_port: int | None


def repo_root() -> Path:
    """Return the repository root (parent of the ``app`` package) when developing."""
    return Path(__file__).resolve().parent.parent


def xdg_config_home(*, environ: dict[str, str] | None = None) -> Path:
    """Return the XDG config home (``$XDG_CONFIG_HOME`` or ``~/.config``).

    Intentionally Unix/XDG-style on macOS as well (not Application Support),
    matching other CLI tools.
    """
    env = environ if environ is not None else os.environ
    raw = (env.get("XDG_CONFIG_HOME") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".config"


def xdg_data_home(*, environ: dict[str, str] | None = None) -> Path:
    """Return ``$XDG_DATA_HOME`` or the Unix default ``~/.local/share``."""
    env = environ if environ is not None else os.environ
    raw = (env.get("XDG_DATA_HOME") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".local" / "share"


def config_dir(*, environ: dict[str, str] | None = None) -> Path:
    """Return ``$XDG_CONFIG_HOME/bunnify`` or ``~/.config/bunnify``."""
    return xdg_config_home(environ=environ) / "bunnify"


def data_dir(*, environ: dict[str, str] | None = None) -> Path:
    """Return Bunnify's writable data directory, honoring ``BUNNIFY_DATA_DIR``."""
    env = environ if environ is not None else os.environ
    override = (env.get(DATA_DIR_ENV_VAR) or "").strip()
    if override:
        return Path(override).expanduser()
    return xdg_data_home(environ=env) / "bunnify"


def env_file_path(*, environ: dict[str, str] | None = None) -> Path:
    """User config env file under the XDG bunnify directory."""
    return config_dir(environ=environ) / ENV_FILE_NAME


def legacy_env_file_path(*, root: Path | None = None) -> Path:
    """Repository-local ``bunnify.env`` (legacy / developer checkout)."""
    return (root or repo_root()) / LEGACY_ENV_FILE_NAME


def default_bookmarks_path(*, environ: dict[str, str] | None = None) -> Path:
    """Default bookmarks JSON path (honors ``BUNNIFY_BOOKMARKS`` when set)."""
    env = environ if environ is not None else os.environ
    override = (env.get(BOOKMARKS_ENV_VAR) or "").strip()
    if override:
        return Path(override).expanduser()
    return config_dir(environ=environ) / BOOKMARKS_FILE_NAME


def legacy_bookmarks_path() -> Path:
    return LEGACY_BOOKMARKS_PATH


def load_preferences(
    *,
    environ: dict[str, str] | None = None,
    env_path: Path | None = None,
) -> ServerPreferences | None:
    """Load server preferences from the process environment and XDG config."""
    env = environ if environ is not None else os.environ
    path = env_path if env_path is not None else env_file_path(environ=env)

    def value(key: str) -> str | None:
        from_environment = (env.get(key) or "").strip()
        return from_environment or read_env_value(path, key)

    mode_raw = value(MODE_ENV_VAR)
    base_url_raw = value(ENV_VAR)
    local_port_raw = value(LOCAL_PORT_ENV_VAR)
    if not any((mode_raw, base_url_raw, local_port_raw)):
        return None

    if mode_raw:
        mode = mode_raw.lower()
        if mode not in {"local", "remote"}:
            raise ValueError(f"{MODE_ENV_VAR} must be 'local' or 'remote'")
    else:
        mode = "local" if local_port_raw else "remote"

    local_port = None
    if local_port_raw:
        try:
            local_port = int(local_port_raw)
        except ValueError as exc:
            raise ValueError(f"{LOCAL_PORT_ENV_VAR} must be an integer") from exc
        if not 1 <= local_port <= 65535:
            raise ValueError(f"{LOCAL_PORT_ENV_VAR} must be between 1 and 65535")

    base_url = normalize_base_url(base_url_raw or "")
    if base_url:
        base_url = _ensure_http_scheme(base_url)
    elif mode == "local" and local_port is not None:
        base_url = f"http://127.0.0.1:{local_port}"

    return ServerPreferences(
        mode=mode,
        base_url=base_url,
        local_port=local_port,
    )


def normalize_base_url(value: str) -> str:
    return value.strip().rstrip("/")


def read_env_value(path: Path, key: str) -> str | None:
    """Return one value from an env file, or ``None`` when missing or empty."""
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = _env_line_pattern(key).search(text)
    if match is None:
        return None
    raw = match.group(1).strip()
    raw = re.sub(r"\s+#.*$", "", raw).strip().strip("'").strip('"')
    return raw or None


def run_dir(*, environ: dict[str, str] | None = None) -> Path:
    """Return the XDG directory used for managed server PID and port files."""
    return data_dir(environ=environ) / "run"


LOCAL_PORT_FILE_NAME = ".bunnify.port"
MIN_LOCAL_PORT = 1024


def read_persisted_local_port(*, environ: dict[str, str] | None = None) -> int | None:
    """Return a saved local port from config.env or the run-directory port file."""
    preferences = load_preferences(environ=environ)
    if preferences is not None and preferences.local_port is not None:
        return preferences.local_port
    port_file = run_dir(environ=environ) / LOCAL_PORT_FILE_NAME
    try:
        port = int(port_file.read_text(encoding="utf-8").strip())
    except OSError, ValueError:
        return None
    if 0 <= port <= 65535:
        return port
    return None


def persist_local_port(port: int, *, environ: dict[str, str] | None = None) -> None:
    """Write ``port`` to the managed run directory for later rediscovery."""
    if port <= 0:
        return
    directory = run_dir(environ=environ)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / LOCAL_PORT_FILE_NAME).write_text(f"{port}\n", encoding="utf-8")


def save_preferences(
    preferences: ServerPreferences,
    *,
    env_path: Path | None = None,
    environ: dict[str, str] | None = None,
) -> None:
    """Persist a complete, verified server preference set."""
    path = env_path if env_path is not None else env_file_path()
    write_env_value(path, ENV_VAR, normalize_base_url(preferences.base_url))
    write_env_value(
        path,
        LOCAL_PORT_ENV_VAR,
        str(preferences.local_port) if preferences.local_port is not None else "",
    )
    write_env_value(path, MODE_ENV_VAR, preferences.mode)
    if preferences.mode == "local" and preferences.local_port is not None:
        persist_local_port(preferences.local_port, environ=environ)


def write_env_value(path: Path, key: str, value: str) -> None:
    """Create or update one env value while preserving all other lines."""
    if "\n" in key or "=" in key or not key.strip():
        raise ValueError("Environment key must be a non-empty single name")
    if "\n" in value:
        raise ValueError(f"{key} cannot contain a newline")
    pattern = _env_line_pattern(key)
    line = f"{key}={value}\n"
    if path.is_file():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise OSError(f"Cannot read {path}: {exc}") from exc
        if pattern.search(text):
            text = pattern.sub(lambda _match: f"{key}={value}", text, count=1)
            if not text.endswith("\n"):
                text += "\n"
        else:
            if text and not text.endswith("\n"):
                text += "\n"
            text += line
    else:
        text = (
            "# Bunnify user settings (not committed).\n"
            f"# Default location: ~/.config/bunnify/{ENV_FILE_NAME}\n"
            f"{line}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_base_url_from_env_file(path: Path) -> str | None:
    """Return ``BUNNIFY_BASE_URL`` from ``path``, or ``None`` if unset/missing."""
    value = read_env_value(path, ENV_VAR)
    return normalize_base_url(value) if value else None


def write_base_url_to_env_file(path: Path, base_url: str) -> None:
    """Create or update ``BUNNIFY_BASE_URL`` in ``path`` (preserves other lines)."""
    normalized = normalize_base_url(base_url)
    if not normalized:
        raise ValueError(f"{ENV_VAR} cannot be empty")
    write_env_value(path, ENV_VAR, normalized)


def example_bookmarks_bytes() -> bytes | None:
    """Load seed bookmarks bytes from the packaged resource or repo example."""
    try:
        packaged = resources.files("app").joinpath("data", "bookmarks.example.json")
        return packaged.read_bytes()
    except (
        FileNotFoundError,
        ModuleNotFoundError,
        OSError,
        TypeError,
        AttributeError,
    ):
        pass

    repo_example = repo_root() / EXAMPLE_BOOKMARKS_NAME
    if repo_example.is_file():
        return repo_example.read_bytes()
    return None


def seed_bookmarks_from_example(dest: Path) -> Path:
    """Copy the example bookmarks file to ``dest`` (parent dirs created).

    Raises ``FileExistsError`` if ``dest`` already exists, and ``FileNotFoundError``
    if no example template can be found.
    """
    if dest.exists():
        raise FileExistsError(str(dest))
    payload = example_bookmarks_bytes()
    if payload is None:
        raise FileNotFoundError(
            f"No bookmarks example found (expected packaged "
            f"app/data/bookmarks.example.json or {EXAMPLE_BOOKMARKS_NAME})"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(payload)
    return dest


def ensure_user_bookmarks(
    *,
    environ: dict[str, str] | None = None,
    dest: Path | None = None,
    legacy: Path | None = None,
    prompt_fn: Callable[[str], str] | None = None,
    allow_prompt: bool | None = None,
    print_fn: Callable[[str], None] | None = None,
) -> Path:
    """Return the user bookmarks file path, or raise when it is missing.

    When the file is absent and prompting is allowed, offer to install the
    packaged example bookmarks at the default path (used by ``bunnify setup``).
    """
    _ = legacy
    target = dest if dest is not None else default_bookmarks_path(environ=environ)
    if target.is_file():
        return target

    should_prompt = allow_prompt if allow_prompt is not None else sys.stdin.isatty()
    if should_prompt and _offer_example_bookmarks(
        target,
        prompt_fn=prompt_fn,
        print_fn=print_fn,
    ):
        try:
            seeded = seed_bookmarks_from_example(target)
        except FileExistsError:
            # Another process created the file while we were prompting.
            return target
        except FileNotFoundError:
            # Example template missing; fall through to friendly guidance below.
            pass
        else:
            log = print_fn if print_fn is not None else print
            log(f"Installed example bookmarks at {seeded}.")
            log(
                "Edit that file to personalize shortcuts; the local server watches "
                "it and reloads automatically (CLI resolves via the server)."
            )
            log(
                "In the interactive REPL, run `refresh` after edits to update "
                "Tab completion."
            )
            return seeded

    raise FileNotFoundError(
        "Bookmarks file not found: "
        f"{target}\n"
        "Create it manually before starting the server, for example:\n"
        f"  mkdir -p {target.parent}\n"
        "  curl -fsSL https://raw.githubusercontent.com/the-hcma/bunnify/main/"
        "bunnify.json.example \\\n"
        f"    -o {target}\n"
        "Or run `bunnify setup` and accept installing the example bookmarks.\n"
        "Or set BUNNIFY_BOOKMARKS to an existing file path.\n"
        "Full checklist: bunnify onboard"
    )


def resolve_base_url(
    *,
    cli_value: str | None = None,
    environ: dict[str, str] | None = None,
    env_path: Path | None = None,
    prompt_fn: Callable[[str], str] | None = None,
    persist: bool = True,
    default_suggestion: str = DEFAULT_BASE_URL,
    allow_prompt: bool | None = None,
) -> str:
    """
    Resolve the Bunnify server base URL.

    Precedence: explicit CLI value → process env → user XDG ``config.env`` →
    legacy repo ``bunnify.env`` → interactive prompt (persisted to the XDG
    config file when ``persist`` is true). When prompting is not allowed
    (non-TTY / ``allow_prompt=False``) or the prompt is cancelled via EOF,
    fall back to ``default_suggestion`` without writing the config file.
    """
    if cli_value is not None and cli_value.strip():
        return _ensure_http_scheme(normalize_base_url(cli_value))

    env = environ if environ is not None else os.environ
    from_env = (env.get(ENV_VAR) or "").strip()
    if from_env:
        return _ensure_http_scheme(normalize_base_url(from_env))

    primary = env_path if env_path is not None else env_file_path(environ=env)
    from_file = read_base_url_from_env_file(primary)
    if from_file:
        return _ensure_http_scheme(from_file)

    # Fall back to legacy checkout env file (read-only unless user re-prompts).
    if env_path is None:
        legacy = read_base_url_from_env_file(legacy_env_file_path())
        if legacy:
            return _ensure_http_scheme(legacy)

    suggestion = _ensure_http_scheme(
        normalize_base_url(default_suggestion) or DEFAULT_BASE_URL
    )
    should_prompt = allow_prompt if allow_prompt is not None else sys.stdin.isatty()
    if not should_prompt:
        return suggestion

    ask = prompt_fn or input
    try:
        answer = ask(f"Bunnify server base URL [{suggestion}]: ")
    except EOFError:
        return suggestion
    chosen = (
        _ensure_http_scheme(normalize_base_url(answer))
        if answer.strip()
        else suggestion
    )
    if not chosen:
        raise ValueError(f"{ENV_VAR} cannot be empty")
    if persist:
        write_base_url_to_env_file(primary, chosen)
    return chosen


def _ensure_http_scheme(url: str) -> str:
    """Require or prepend an http(s) scheme for CLI base URLs."""
    lowered = url.lower()
    if lowered.startswith(("http://", "https://")):
        return url
    if "://" in url:
        raise ValueError(f"Base URL must use http:// or https:// (got {url!r})")
    return f"http://{url}"


def _env_line_pattern(key: str) -> re.Pattern[str]:
    return re.compile(
        rf"^[^\S\r\n]*{re.escape(key)}[^\S\r\n]*=[^\S\r\n]*(.*)$",
        re.MULTILINE,
    )


def _offer_example_bookmarks(
    target: Path,
    *,
    prompt_fn: Callable[[str], str] | None,
    print_fn: Callable[[str], None] | None,
) -> bool:
    """Prompt whether to install example bookmarks at ``target``.

    On a TTY, Enter accepts (default yes). On non-TTY stdin (pipes), require an
    explicit ``y``/``yes``. ``click.prompt`` raises ``Abort`` on EOF (not
    ``EOFError``); treat that like a decline so setup falls through to the
    missing-bookmarks guidance instead of printing ``Aborted!``.
    """
    log = print_fn if print_fn is not None else print
    ask = prompt_fn or input
    log(f"No bookmarks found at {target}.")
    try:
        answer = ask("Install the example bookmarks there? [Y/n]: ")
    except EOFError, click.Abort:
        return False
    normalized = answer.strip().lower()
    if normalized in {"y", "yes"}:
        return True
    if normalized == "" and sys.stdin.isatty():
        return True
    return False

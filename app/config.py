"""Local CLI configuration (base URL) loaded from a gitignored env file."""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable
from pathlib import Path

from app.client import DEFAULT_BASE_URL

ENV_VAR = "BUNNIFY_BASE_URL"
ENV_FILE_NAME = "bunnify.env"
_BASE_URL_LINE = re.compile(
    rf"^\s*{re.escape(ENV_VAR)}\s*=\s*(.*)$",
    re.MULTILINE,
)


def repo_root() -> Path:
    """Return the repository root (parent of the ``app`` package)."""
    return Path(__file__).resolve().parent.parent


def env_file_path(*, root: Path | None = None) -> Path:
    return (root or repo_root()) / ENV_FILE_NAME


def normalize_base_url(value: str) -> str:
    return value.strip().rstrip("/")


def _ensure_http_scheme(url: str) -> str:
    """Require or prepend an http(s) scheme for CLI base URLs."""
    lowered = url.lower()
    if lowered.startswith(("http://", "https://")):
        return url
    if "://" in url:
        raise ValueError(f"Base URL must use http:// or https:// (got {url!r})")
    return f"http://{url}"


def read_base_url_from_env_file(path: Path) -> str | None:
    """Return ``BUNNIFY_BASE_URL`` from ``path``, or ``None`` if unset/missing."""
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = _BASE_URL_LINE.search(text)
    if match is None:
        return None
    raw = match.group(1).strip()
    # Drop unquoted inline comments (``.env`` style: ``URL  # note``).
    # Require whitespace before ``#`` so URL fragments are preserved.
    raw = re.sub(r"\s+#.*$", "", raw).strip().strip("'").strip('"')
    return normalize_base_url(raw) if raw else None


def write_base_url_to_env_file(path: Path, base_url: str) -> None:
    """Create or update ``BUNNIFY_BASE_URL`` in ``path`` (preserves other lines)."""
    normalized = normalize_base_url(base_url)
    if not normalized:
        raise ValueError(f"{ENV_VAR} cannot be empty")
    line = f"{ENV_VAR}={normalized}\n"
    if path.is_file():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise OSError(f"Cannot read {path}: {exc}") from exc
        if _BASE_URL_LINE.search(text):
            text = _BASE_URL_LINE.sub(f"{ENV_VAR}={normalized}", text, count=1)
            if not text.endswith("\n"):
                text += "\n"
        else:
            if text and not text.endswith("\n"):
                text += "\n"
            text += line
    else:
        text = (
            "# Local Bunnify CLI settings (not committed).\n"
            f"# Copy from {ENV_FILE_NAME}.example and adjust as needed.\n"
            f"{line}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


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

    Precedence: explicit CLI value → process env → env file → interactive prompt
    (persisted to the env file when ``persist`` is true). When prompting is not
    allowed (non-TTY / ``allow_prompt=False``) or the prompt is cancelled via
    EOF, fall back to ``default_suggestion`` without writing the env file.
    """
    if cli_value is not None and cli_value.strip():
        return _ensure_http_scheme(normalize_base_url(cli_value))

    env = environ if environ is not None else os.environ
    from_env = (env.get(ENV_VAR) or "").strip()
    if from_env:
        return _ensure_http_scheme(normalize_base_url(from_env))

    path = env_path if env_path is not None else env_file_path()
    from_file = read_base_url_from_env_file(path)
    if from_file:
        return _ensure_http_scheme(from_file)

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
        write_base_url_to_env_file(path, chosen)
    return chosen

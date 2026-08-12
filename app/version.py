"""Bunnify package and source revision information."""

from __future__ import annotations

import os
import subprocess
import tomllib
from collections.abc import Mapping
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from app import _build_metadata

PACKAGE_NAME = "bunnify"


def build_info() -> str:
    """Return a human-readable package version and source revision."""
    return format_cli_version_line(prog=PACKAGE_NAME)


def build_version() -> str:
    """Return the package version and source revision without a program name."""
    package, commit = get_build_info()
    return f"{package} ({commit})"


def format_cli_version_line(*, prog: str) -> str:
    """One-line version string for ``--version`` on console entry points."""
    package, commit = get_build_info()
    return f"{prog} {package} ({commit})"


@lru_cache(maxsize=1)
def get_build_info() -> tuple[str, str]:
    """Return ``(package_version, commit_short_or_unknown)`` once per process."""
    return (package_version(), git_commit())


def git_commit(
    *,
    environ: Mapping[str, str] | None = None,
    repository: Path | None = None,
) -> str:
    """Return the configured or checkout Git commit, shortened for display."""
    environment = os.environ if environ is None else environ
    for key in ("BUNNIFY_GIT_SHA", "GITHUB_SHA"):
        configured_sha = environment.get(key, "").strip()
        if configured_sha:
            return _normalize_commit(configured_sha)

    embedded = getattr(_build_metadata, "EMBEDDED_COMMIT", "")
    if isinstance(embedded, str) and embedded.strip():
        return _normalize_commit(embedded)

    checkout = repository or Path(__file__).resolve().parents[1]
    if not (checkout / ".git").exists():
        return "unknown"

    try:
        result = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "--short=12", "HEAD"],
            capture_output=True,
            check=True,
            text=True,
            timeout=2,
        )
    except OSError, subprocess.SubprocessError:
        return "unknown"
    return result.stdout.strip() or "unknown"


def package_version(*, pyproject_path: Path | None = None) -> str:
    """Return the distribution version, with a source-checkout fallback."""
    embedded = getattr(_build_metadata, "EMBEDDED_VERSION", "")
    if isinstance(embedded, str) and embedded.strip():
        return embedded.strip()
    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:
        path = pyproject_path or Path(__file__).resolve().parents[1] / "pyproject.toml"
        return _pyproject_version(path)


def _normalize_commit(token: str) -> str:
    stripped = token.strip()
    if not stripped:
        return "unknown"
    if len(stripped) > 12:
        return stripped[:12]
    return stripped


def _pyproject_version(path: Path) -> str:
    try:
        with path.open("rb") as pyproject_file:
            project = tomllib.load(pyproject_file).get("project", {})
    except OSError, tomllib.TOMLDecodeError:
        return "unknown"

    version_value = project.get("version")
    return version_value if isinstance(version_value, str) else "unknown"

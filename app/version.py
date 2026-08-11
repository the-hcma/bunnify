"""Bunnify package and source revision information."""

from __future__ import annotations

import os
import subprocess
import tomllib
from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

PACKAGE_NAME = "bunnify"


def build_info() -> str:
    """Return a human-readable package version and source revision."""
    return f"{PACKAGE_NAME} {build_version()}"


def build_version() -> str:
    """Return the package version and source revision without a program name."""
    return f"{package_version()} (commit {git_commit()})"


def git_commit(
    *,
    environ: Mapping[str, str] | None = None,
    repository: Path | None = None,
) -> str:
    """Return the configured or checkout Git commit, shortened for display."""
    environment = os.environ if environ is None else environ
    configured_sha = environment.get("BUNNIFY_GIT_SHA", "").strip()
    if configured_sha:
        return configured_sha[:7]

    checkout = repository or Path(__file__).resolve().parents[1]
    try:
        result = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "--short=7", "HEAD"],
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
    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:
        path = pyproject_path or Path(__file__).resolve().parents[1] / "pyproject.toml"
        return _pyproject_version(path)


def _pyproject_version(path: Path) -> str:
    try:
        with path.open("rb") as pyproject_file:
            project = tomllib.load(pyproject_file).get("project", {})
    except OSError, tomllib.TOMLDecodeError:
        return "unknown"

    version_value = project.get("version")
    return version_value if isinstance(version_value, str) else "unknown"

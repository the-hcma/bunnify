"""Bunnify package and source revision information."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Mapping
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, distribution, version
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
        # Not a checkout: a pip/pipx install straight from a VCS URL has no
        # embedded metadata, but pip records the commit it built.
        return _direct_url_commit() or "unknown"

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


def is_source_checkout(*, repository: Path | None = None) -> bool:
    """Return whether this process is running from a git checkout of bunnify."""
    checkout = repository or Path(__file__).resolve().parents[1]
    return (checkout / ".git").exists()


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


def installed_package_version(*, pyproject_path: Path | None = None) -> str:
    """Return the version actually installed on disk right now.

    Unlike :func:`package_version`, this never returns the baked-in
    ``EMBEDDED_VERSION`` a long-running process resolved at import time — it
    re-reads distribution metadata (or, in a source checkout, ``pyproject.toml``)
    on every call, so an in-place upgrade underneath an already-running process
    is visible without restarting it.
    """
    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:
        path = pyproject_path or Path(__file__).resolve().parents[1] / "pyproject.toml"
        return _pyproject_version(path)


def installed_package_commit(
    *,
    environ: Mapping[str, str] | None = None,
    repository: Path | None = None,
) -> str:
    """Return the commit actually installed on disk right now.

    Distribution metadata has no standard commit field, so (unlike
    :func:`installed_package_version`) this cannot lean on
    :mod:`importlib.metadata`. Instead it re-reads the on-disk
    ``_build_metadata`` module file fresh — bypassing the copy already
    imported into this process, which an in-place upgrade (pipx reinstall,
    sdist rebuild at the same version) leaves stale — falling back to a
    live ``git`` lookup exactly like :func:`git_commit`.
    """
    environment = os.environ if environ is None else environ
    for key in ("BUNNIFY_GIT_SHA", "GITHUB_SHA"):
        configured_sha = environment.get(key, "").strip()
        if configured_sha:
            return _normalize_commit(configured_sha)

    fresh_embedded = _reread_build_metadata_attr("EMBEDDED_COMMIT")
    if fresh_embedded:
        return _normalize_commit(fresh_embedded)

    return git_commit(environ=environment, repository=repository)


def _reread_build_metadata_attr(name: str) -> str:
    """Re-read *name* from ``_build_metadata``'s current on-disk file.

    Loaded as a throwaway module (never registered in ``sys.modules``) so a
    file an in-place upgrade replaced on disk is reflected immediately,
    instead of the already-imported ``app._build_metadata`` object's frozen
    values.
    """
    path = getattr(_build_metadata, "__file__", None)
    if not path:
        return ""
    try:
        spec = importlib.util.spec_from_file_location(
            "_bunnify_fresh_build_metadata", path
        )
        if spec is None or spec.loader is None:
            return ""
        fresh = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fresh)
    except OSError, SyntaxError:
        return ""
    value = getattr(fresh, name, "")
    return value.strip() if isinstance(value, str) else ""


def running_command_path() -> Path:
    """Return the path of the command that started this process.

    The path is made absolute without following console-script symlinks so a
    pipx or uv-tool install prints the PATH entry (``~/.local/bin/bunnify``)
    rather than the venv target. Bare names such as ``bunnify`` are looked up
    with ``shutil.which`` so PATH launches do not report ``$PWD/bunnify``.
    """
    argv0 = Path(sys.argv[0]).expanduser()
    if not argv0.is_absolute():
        located = shutil.which(os.fspath(argv0))
        if located:
            argv0 = Path(located)
    try:
        return argv0.absolute()
    except OSError:
        return argv0


def vcs_install_spec() -> str | None:
    """Return the pip spec this package was installed from, if it is a VCS install.

    For ``pipx install git+https://github.com/the-hcma/bunnify@main`` that is
    ``git+https://github.com/the-hcma/bunnify@main`` (the requested revision
    when pip recorded one, otherwise the resolved commit). None for index,
    editable and local-directory installs, and when nothing was recorded.

    This describes the *running* distribution; for the pipx app that
    ``bunnify upgrade`` acts on, see ``pipx_install.pipx_vcs_install_spec``.
    """
    try:
        raw = distribution(PACKAGE_NAME).read_text("direct_url.json")
    except PackageNotFoundError, OSError:
        return None
    return vcs_install_spec_from(raw)


def vcs_install_spec_from(raw: str | None) -> str | None:
    """Parse the text of a ``direct_url.json`` into a pip VCS spec, or None."""
    try:
        record = json.loads(raw or "")
        url = record["url"]
        info = record["vcs_info"]
        vcs = info.get("vcs", "git")
        revision = info.get("requested_revision") or info.get("commit_id")
    except ValueError, KeyError, TypeError, AttributeError:
        return None
    if not (isinstance(url, str) and url and isinstance(vcs, str) and vcs):
        return None
    if isinstance(revision, str) and revision:
        return f"{vcs}+{url}@{revision}"
    return f"{vcs}+{url}"


def _direct_url_commit() -> str:
    """Return the commit pip recorded for a VCS install, or "" if there is none.

    ``pip install git+https://...`` (and so ``pipx install git+...``) writes
    ``direct_url.json`` into the distribution with ``vcs_info.commit_id``.
    Editable/local-directory and index installs have no ``vcs_info``.
    """
    try:
        raw = distribution(PACKAGE_NAME).read_text("direct_url.json")
        commit = json.loads(raw or "")["vcs_info"]["commit_id"]
    except PackageNotFoundError, ValueError, KeyError, TypeError, OSError:
        return ""
    return _normalize_commit(commit) if isinstance(commit, str) else ""


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

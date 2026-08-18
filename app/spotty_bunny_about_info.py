"""Cocoa-free About panel facts: bookmarks path, GitHub remote, server mode."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlparse

from app.config import (
    default_bookmarks_path,
    load_preferences,
    resolve_base_url,
)


@dataclass(frozen=True)
class AboutRuntimeInfo:
    """Bookmarks, optional GitHub remote, and local/remote server for About."""

    bookmarks_display: str
    bookmarks_uri: str
    github_display: str | None
    github_url: str | None
    server_display: str
    server_url: str


OriginUrlFor = Callable[[Path], str | None]


def display_user_path(path: Path) -> str:
    """Return *path* with the home directory replaced by ``~`` when possible."""
    expanded = path.expanduser()
    home = Path.home()
    if expanded == home:
        return "~"
    try:
        return f"~/{expanded.relative_to(home)}"
    except ValueError:
        return str(expanded)


def github_https_url(remote: str) -> str | None:
    """Return ``https://github.com/owner/repo`` when *remote* points at GitHub."""
    raw = remote.strip()
    if raw.endswith(".git"):
        raw = raw[: -len(".git")]
    raw = raw.rstrip("/")
    patterns = (
        re.compile(r"^git@github\.com:([^/]+)/(.+)$"),
        re.compile(r"^git://github\.com/([^/]+)/(.+)$"),
        re.compile(r"^https?://(?:www\.)?github\.com/([^/]+)/(.+)$"),
        re.compile(r"^ssh://(?:git@)?github\.com/([^/]+)/(.+)$"),
    )
    for pattern in patterns:
        match = pattern.match(raw)
        if match is None:
            continue
        owner, rest = match.group(1), match.group(2)
        repo = rest.split("/", maxsplit=1)[0]
        if not owner or not repo:
            return None
        return f"https://github.com/{owner}/{repo}"
    return None


def github_repo_url_for_path(
    path: Path,
    *,
    origin_url_for: OriginUrlFor | None = None,
) -> str | None:
    """Return the GitHub HTTPS URL for the git checkout that contains *path*."""
    workdir = _workdir_containing_git(path)
    if workdir is None:
        return None
    reader = origin_url_for if origin_url_for is not None else _git_origin_url
    remote = reader(workdir)
    if not remote:
        return None
    return github_https_url(remote)


def load_about_runtime_info(
    *,
    bookmarks_path: Path | None = None,
    environ: dict[str, str] | None = None,
    origin_url_for: OriginUrlFor | None = None,
) -> AboutRuntimeInfo:
    """Resolve bookmarks, GitHub, and server rows from config (no Cocoa)."""
    path = (
        bookmarks_path
        if bookmarks_path is not None
        else default_bookmarks_path(environ=environ)
    )
    expanded = path.expanduser()
    bookmarks_uri = expanded.resolve(strict=False).as_uri()
    github_url = github_repo_url_for_path(expanded, origin_url_for=origin_url_for)
    github_display = None
    if github_url is not None:
        github_display = github_url.removeprefix("https://")
    prefs = load_preferences(environ=environ)
    mode: Literal["local", "remote"] | None = None
    base_url = ""
    if prefs is not None:
        mode = prefs.mode
        base_url = prefs.base_url
    if not base_url:
        base_url = resolve_base_url(
            environ=environ,
            persist=False,
            allow_prompt=False,
        )
    if mode is None:
        mode = "local" if _is_loopback_url(base_url) else "remote"
    label = "Local server" if mode == "local" else "Remote server"
    return AboutRuntimeInfo(
        bookmarks_display=display_user_path(path),
        bookmarks_uri=bookmarks_uri,
        github_display=github_display,
        github_url=github_url,
        server_display=f"{label} · {base_url}",
        server_url=base_url,
    )


def open_path_in_text_editor(
    path: Path,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> bool:
    """Open *path* in the default text editor (``open -t`` on macOS)."""
    runner = run if run is not None else subprocess.run
    try:
        completed = runner(
            ["open", "-t", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except OSError, subprocess.TimeoutExpired:
        return False
    return completed.returncode == 0


def path_from_file_uri(uri: str) -> Path | None:
    """Return a filesystem path for a ``file:`` URI, or None."""
    parsed = urlparse(uri.strip())
    if parsed.scheme != "file" or not parsed.path:
        return None
    return Path(unquote(parsed.path))


_GIT_REMOTE_TIMEOUT_S = 2
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _git_origin_url(workdir: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(workdir), "remote", "get-url", "origin"],
            capture_output=True,
            check=False,
            text=True,
            timeout=_GIT_REMOTE_TIMEOUT_S,
        )
    except OSError, subprocess.TimeoutExpired:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def _is_loopback_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in _LOOPBACK_HOSTS


def _workdir_containing_git(path: Path) -> Path | None:
    current = path.expanduser()
    try:
        current = current.resolve(strict=False)
    except OSError, RuntimeError:
        pass
    if not current.is_dir():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None

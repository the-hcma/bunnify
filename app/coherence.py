"""Version coherence between CLI, server /health, and Spotty Bunny."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass

from packaging.version import InvalidVersion, Version

from app.client import HealthStatus, fetch_health
from app.theme import Theme
from app.version import get_build_info

RestartFn = Callable[[str | None, str], bool]


@dataclass(frozen=True)
class LocalCoherenceReport:
    """Local CLI vs server and Spotty overlay build alignment."""

    local_commit: str
    local_version: str
    server: HealthStatus | None
    spotty_commit: str | None
    spotty_running: bool

    @property
    def coherent(self) -> bool:
        if self.server is not None and self.server.ok and not builds_match(self.server):
            return False
        if self.spotty_running and self.spotty_commit != self.local_commit:
            return False
        return True


def assess_local_coherence(*, base_url: str) -> LocalCoherenceReport:
    """Compare this process to *base_url* /health and a running Spotty overlay."""
    local_version, local_commit = get_build_info()
    server = fetch_health(base_url)
    spotty_running, spotty_commit = _spotty_runtime_commit()
    return LocalCoherenceReport(
        local_commit=local_commit,
        local_version=local_version,
        server=server,
        spotty_commit=spotty_commit,
        spotty_running=spotty_running,
    )


def builds_match(health: HealthStatus) -> bool:
    """Return whether *health* matches this CLI install."""
    local_version, local_commit = get_build_info()
    return builds_match_values(
        health,
        local_commit=local_commit,
        local_version=local_version,
    )


def builds_match_values(
    health: HealthStatus,
    *,
    local_commit: str,
    local_version: str,
) -> bool:
    """Return whether *health* matches explicit local version/commit."""
    if health.version is None or health.commit is None:
        return False
    return health.version == local_version and health.commit == local_commit


def parse_build_label(label: str) -> tuple[str, str] | None:
    """Return ``(version, commit)`` parsed from ``0.10.0 (abc1234)``."""
    token = label.strip()
    if not token or " (" not in token or not token.endswith(")"):
        return None
    version, _, rest = token.partition(" (")
    commit = rest.removesuffix(")").strip()
    if not version or not commit:
        return None
    return version, commit


def cli_is_newer_than(health: HealthStatus) -> bool:
    """Return whether this CLI's package version is newer than *health*."""
    if health.version is None:
        return False
    local_version, _local_commit = get_build_info()
    try:
        return Version(health.version) < Version(local_version)
    except InvalidVersion:
        return False


def ensure_local_spotty_aligned(
    *,
    force_restart: bool = False,
    print_fn: Callable[[str], None] | None = None,
    restart: RestartFn | None = None,
) -> bool:
    """Start or restart Spotty Bunny so its running commit matches this CLI."""
    if sys.platform != "darwin":
        return True
    from app.spotty_bunny_launch import ensure_spotty_bunny_running

    log = print_fn or (lambda _message: None)

    def offer_restart(recorded: str | None, current: str) -> bool:
        if force_restart:
            return True
        if restart is not None:
            return restart(recorded, current)
        running = recorded or "unknown"
        log(f"Spotty Bunny is running commit {running}; this CLI is {current}.")
        return _confirm_explicit_yes(
            input,
            "Restart Spotty Bunny with this CLI? [y/N]: ",
        )

    return ensure_spotty_bunny_running(
        force_restart=force_restart,
        restart=offer_restart,
    )


def format_build_label(health: HealthStatus) -> str:
    """Human-readable version/commit from a health probe."""
    if health.version and health.commit:
        return f"{health.version} ({health.commit})"
    if health.version:
        return health.version
    if health.commit:
        return f"commit {health.commit}"
    return "unknown build"


def offer_remote_build_mismatch(
    prompt_fn: Callable[[str], str],
    *,
    base_url: str,
    health: HealthStatus,
    print_fn: Callable[[str], None],
    theme: Theme,
) -> bool:
    """Warn when *health* differs from this CLI; return True to continue anyway."""
    if not health.ok or builds_match(health):
        return True
    if health.version is None or health.commit is None:
        return True
    local_version, local_commit = get_build_info()
    local_label = f"{local_version} ({local_commit})"
    remote_label = format_build_label(health)
    print_fn(
        theme.warn(
            f"Remote server at {base_url} is {remote_label}; this Mac is {local_label}."
        )
    )
    if cli_is_newer_than(health):
        print_fn(
            theme.dim(
                "Upgrade the remote host (merge latest release, redeploy, or "
                "run `bunnify upgrade` there) so both sides match."
            )
        )
    else:
        print_fn(
            theme.dim(
                "Upgrade this Mac with `bunnify upgrade` or align the remote "
                "host to the same release."
            )
        )
    return _confirm_explicit_yes(
        prompt_fn,
        "Continue with this client/server version skew? [y/N]: ",
    )


def _confirm_explicit_yes(prompt_fn: Callable[[str], str], message: str) -> bool:
    try:
        answer = prompt_fn(message)
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


def running_spotty_commit() -> tuple[bool, str | None]:
    """Return ``(running, commit)`` for the Spotty Bunny overlay."""
    return _spotty_runtime_commit()


def _spotty_runtime_commit() -> tuple[bool, str | None]:
    if sys.platform != "darwin":
        return False, None
    from app.spotty_bunny_launch import (
        read_spotty_bunny_runtime,
        spotty_bunny_is_running,
    )

    if not spotty_bunny_is_running():
        return False, None
    runtime = read_spotty_bunny_runtime()
    if runtime is None:
        return True, None
    _pid, commit = runtime
    return True, commit

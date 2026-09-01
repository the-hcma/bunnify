"""Runtime health snapshot for Spotty Bunny's CGEventTap (macOS)."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.config import data_dir

HEALTH_FILE_NAME = ".spotty-bunny-health"
MAX_TAP_REINSTALL_FAILURES = 3
TAP_HEALTH_CHECK_INTERVAL_S = 60.0
TAP_STATE_DISABLED = "disabled"
TAP_STATE_MISSING = "missing"
TAP_STATE_OK = "ok"
TAP_STATE_REINSTALLING = "reinstalling"


@dataclass(frozen=True)
class SpottyBunnyHealth:
    """Persisted tap activity written by the overlay process."""

    last_chord_at: float | None
    last_event_at: float | None
    reinstall_failures: int
    tap: str
    updated_at: float


def clear_spotty_bunny_health(*, health_dir: Path | None = None) -> None:
    """Remove the health snapshot (overlay exit)."""
    spotty_bunny_health_path(health_dir=health_dir).unlink(missing_ok=True)


def format_activity_timestamp(epoch: float | None) -> str:
    """Format *epoch* for ``status`` output, or ``never`` when unset."""
    if epoch is None:
        return "never"
    when = datetime.fromtimestamp(epoch, tz=UTC).astimezone()
    return when.strftime("%Y-%m-%d %H:%M:%S %Z")


def read_spotty_bunny_health(
    *, health_dir: Path | None = None
) -> SpottyBunnyHealth | None:
    """Return the latest health snapshot, or None when missing/unreadable."""
    path = spotty_bunny_health_path(health_dir=health_dir)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    fields: dict[str, str] = {}
    for line in lines:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()
    tap = fields.get("tap")
    if tap is None:
        return None
    return SpottyBunnyHealth(
        last_chord_at=_parse_optional_float(fields.get("last_chord_at")),
        last_event_at=_parse_optional_float(fields.get("last_event_at")),
        reinstall_failures=_parse_int(fields.get("reinstall_failures"), default=0),
        tap=tap,
        updated_at=_parse_float(fields.get("updated_at"), default=0.0),
    )


def should_exit_after_reinstall_failures(failures: int) -> bool:
    """Return whether KeepAlive should restart after repeated reinstall failures."""
    return failures >= MAX_TAP_REINSTALL_FAILURES


def spotty_bunny_health_path(*, health_dir: Path | None = None) -> Path:
    """Path to the overlay health snapshot under the data directory."""
    directory = data_dir() if health_dir is None else health_dir
    return directory / HEALTH_FILE_NAME


def write_spotty_bunny_health(
    *,
    health_dir: Path | None = None,
    last_chord_at: float | None = None,
    last_event_at: float | None = None,
    previous: SpottyBunnyHealth | None = None,
    reinstall_failures: int | None = None,
    tap: str,
    time_fn: Callable[[], float] | None = None,
) -> SpottyBunnyHealth:
    """Persist tap health for ``status`` and external diagnostics."""
    now = time.time if time_fn is None else time_fn
    updated_at = now()
    prior = previous or read_spotty_bunny_health(health_dir=health_dir)
    chord = last_chord_at
    if chord is None and prior is not None:
        chord = prior.last_chord_at
    event = last_event_at
    if event is None and prior is not None:
        event = prior.last_event_at
    failures = reinstall_failures
    if failures is None:
        failures = prior.reinstall_failures if prior is not None else 0
    snapshot = SpottyBunnyHealth(
        last_chord_at=chord,
        last_event_at=event,
        reinstall_failures=failures,
        tap=tap,
        updated_at=updated_at,
    )
    path = spotty_bunny_health_path(health_dir=health_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_format_health(snapshot), encoding="utf-8")
    return snapshot


def _format_health(health: SpottyBunnyHealth) -> str:
    lines = (
        f"last_chord_at: {_format_optional_float(health.last_chord_at)}",
        f"last_event_at: {_format_optional_float(health.last_event_at)}",
        f"reinstall_failures: {health.reinstall_failures}",
        f"tap: {health.tap}",
        f"updated_at: {health.updated_at:.3f}",
    )
    return "\n".join(lines) + "\n"


def _format_optional_float(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.3f}"


def _parse_float(raw: str | None, *, default: float) -> float:
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _parse_int(raw: str | None, *, default: int) -> int:
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _parse_optional_float(raw: str | None) -> float | None:
    if raw is None or not raw.strip():
        return None
    try:
        return float(raw)
    except ValueError:
        return None

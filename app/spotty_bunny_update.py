"""Daily PyPI update check and cache for Spotty Bunny."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from packaging.version import InvalidVersion, Version

from app.config import data_dir
from app.pypi import pypi_latest_version
from app.version import package_version

CACHE_FILE_NAME = "pypi-latest.json"
CHECK_INTERVAL_S = 24 * 60 * 60
FetchLatest = Callable[[], str | None]


@dataclass(frozen=True)
class UpdateStatus:
    """Installed version compared to the last successful PyPI lookup."""

    checked_at: float | None
    current: str
    latest: str | None
    outdated: bool


def cache_is_stale(checked_at: float | None, *, now: float | None = None) -> bool:
    """True when there is no check yet, or the last check is older than a day."""
    if checked_at is None:
        return True
    moment = time.time() if now is None else now
    return moment - checked_at >= CHECK_INTERVAL_S


def is_version_outdated(current: str, latest: str | None) -> bool:
    """True when *latest* is a newer package version than *current*."""
    if not latest:
        return False
    try:
        return Version(current) < Version(latest)
    except InvalidVersion:
        return False


def read_cached_update_status(
    *,
    cache_path: Path | None = None,
    current: str | None = None,
) -> UpdateStatus:
    """Compare this install to the on-disk cache without hitting the network."""
    version = current if current is not None else package_version()
    path = cache_path if cache_path is not None else update_cache_path()
    cached = _read_cache(path)
    if cached is None:
        return UpdateStatus(
            checked_at=None,
            current=version,
            latest=None,
            outdated=False,
        )
    return UpdateStatus(
        checked_at=cached.checked_at,
        current=version,
        latest=cached.latest,
        outdated=is_version_outdated(version, cached.latest),
    )


def refresh_update_status(
    *,
    cache_path: Path | None = None,
    current: str | None = None,
    fetch: FetchLatest | None = None,
    force: bool = False,
    now: float | None = None,
) -> UpdateStatus:
    """Return update status, fetching PyPI when the daily cache is stale."""
    moment = time.time() if now is None else now
    version = current if current is not None else package_version()
    path = cache_path if cache_path is not None else update_cache_path()
    cached = _read_cache(path)
    if (
        not force
        and cached is not None
        and not cache_is_stale(cached.checked_at, now=moment)
    ):
        return UpdateStatus(
            checked_at=cached.checked_at,
            current=version,
            latest=cached.latest,
            outdated=is_version_outdated(version, cached.latest),
        )
    getter = fetch if fetch is not None else pypi_latest_version
    latest = getter()
    previous_latest = cached.latest if cached is not None else None
    if latest is None:
        _write_cache(path, checked_at=moment, latest=previous_latest)
        return UpdateStatus(
            checked_at=moment,
            current=version,
            latest=previous_latest,
            outdated=is_version_outdated(version, previous_latest),
        )
    _write_cache(path, checked_at=moment, latest=latest)
    return UpdateStatus(
        checked_at=moment,
        current=version,
        latest=latest,
        outdated=is_version_outdated(version, latest),
    )


def update_cache_path(*, environ: dict[str, str] | None = None) -> Path:
    """JSON cache under Bunnify's data directory."""
    return data_dir(environ=environ) / CACHE_FILE_NAME


@dataclass(frozen=True)
class _CacheRecord:
    checked_at: float
    latest: str | None


def _read_cache(path: Path) -> _CacheRecord | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError, json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    checked_at = payload.get("checked_at")
    if not isinstance(checked_at, int | float):
        return None
    latest_raw = payload.get("latest")
    if latest_raw is None:
        latest: str | None = None
    elif isinstance(latest_raw, str) and latest_raw:
        latest = latest_raw
    else:
        return None
    return _CacheRecord(checked_at=float(checked_at), latest=latest)


def _write_cache(path: Path, *, checked_at: float, latest: str | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {"checked_at": checked_at, "latest": latest},
        indent=2,
        sort_keys=True,
    )
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(payload + "\n", encoding="utf-8")
    tmp.replace(path)

"""Latest bunnify version on PyPI."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

PYPI_JSON_URL = "https://pypi.org/pypi/bunnify/json"
PYPI_TIMEOUT_S = 8

UrlOpen = Callable[..., Any]


def pypi_latest_version(*, urlopen: UrlOpen | None = None) -> str | None:
    """Return the latest bunnify version on PyPI, or None on failure."""
    opener = urllib.request.urlopen if urlopen is None else urlopen
    try:
        with opener(PYPI_JSON_URL, timeout=PYPI_TIMEOUT_S) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (
        OSError,
        TimeoutError,
        ValueError,
        json.JSONDecodeError,
        urllib.error.URLError,
    ):
        return None
    version = payload.get("info", {}).get("version")
    return version if isinstance(version, str) and version else None

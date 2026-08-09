"""HTTP client for talking to a running Bunnify server."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = 5.0


class ClientError(Exception):
    """Raised when the local Bunnify server cannot fulfill a CLI request."""


@dataclass(frozen=True)
class ResolvedShortcut:
    url: str
    kind: str | None
    key: str | None


def _request_json(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Any:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "bunnify-cli"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            payload = json.loads(exc.read().decode("utf-8"))
            detail = str(payload.get("error") or payload)
        except json.JSONDecodeError:
            detail = exc.reason or str(exc)
        except UnicodeDecodeError:
            detail = exc.reason or str(exc)
        raise ClientError(detail or f"HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ClientError(
            f"Cannot reach Bunnify server at {url!r}: {exc.reason}. "
            "Is `./bunnify-server` running?"
        ) from exc
    except TimeoutError as exc:
        raise ClientError(f"Timed out contacting Bunnify server at {url!r}") from exc


def resolve_shortcut(
    query: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    strict: bool = True,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> ResolvedShortcut:
    """Resolve a shortcut via ``/api/resolve/`` (strict by default for the CLI)."""
    params = urllib.parse.urlencode(
        {"q": query, "strict": "1" if strict else "0"},
    )
    payload = _request_json(
        f"{base_url.rstrip('/')}/api/resolve/?{params}",
        timeout=timeout,
    )
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise ClientError(
            str(payload.get("error") if isinstance(payload, dict) else payload)
        )
    url = payload.get("url")
    if not isinstance(url, str) or not url:
        raise ClientError("Resolve response missing url")
    return ResolvedShortcut(
        url=url,
        kind=payload.get("kind") if isinstance(payload.get("kind"), str) else None,
        key=payload.get("key") if isinstance(payload.get("key"), str) else None,
    )


def fetch_keys(
    *,
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[str]:
    """Fetch bookmark keys (plus specials) from ``/api/keys/``."""
    payload = _request_json(
        f"{base_url.rstrip('/')}/api/keys/",
        timeout=timeout,
    )
    if not isinstance(payload, dict):
        raise ClientError("Keys response was not a JSON object")
    keys = payload.get("keys")
    if not isinstance(keys, list):
        raise ClientError("Keys response missing keys list")
    return [str(key) for key in keys]


def fetch_suggestions(
    query: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[str]:
    """Fetch OpenSearch-style suggestions for interactive tab completion."""
    params = urllib.parse.urlencode({"q": query})
    payload = _request_json(
        f"{base_url.rstrip('/')}/api/suggestions/?{params}",
        timeout=timeout,
    )
    if not isinstance(payload, list) or len(payload) < 2:
        return []
    suggestions = payload[1]
    if not isinstance(suggestions, list):
        return []
    return [str(item) for item in suggestions]

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


@dataclass(frozen=True)
class KeyEntry:
    """Shortcut metadata from ``/api/keys/`` (short usage / completion)."""

    key: str
    description: str = ""
    url: str = ""
    params: tuple[str, ...] = ()


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
            raw = exc.read()
        except OSError:
            raw = b""
        try:
            payload = json.loads(raw.decode("utf-8"))
            detail = str(payload.get("error") or payload)
        except json.JSONDecodeError:
            detail = exc.reason or str(exc)
        except UnicodeDecodeError:
            detail = exc.reason or str(exc)
        raise ClientError(detail or f"HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ClientError(
            f"Cannot reach Bunnify server at {url!r}: {exc.reason}. "
            "Is `./scripts/bunnify-server` running?"
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


def parse_key_entry(raw: Any) -> KeyEntry | None:
    """Parse one structured keys API entry; ignore malformed objects."""
    if not isinstance(raw, dict):
        return None
    key = raw.get("key")
    if not isinstance(key, str) or not key:
        return None
    description = raw.get("description", "")
    url = raw.get("url", "")
    params_raw = raw.get("params", [])
    if not isinstance(description, str):
        description = "" if description is None else str(description)
    if not isinstance(url, str):
        url = "" if url is None else str(url)
    params: tuple[str, ...] = ()
    if isinstance(params_raw, list):
        params = tuple(str(item) for item in params_raw)
    return KeyEntry(key=key, description=description, url=url, params=params)


def parse_keys_payload(payload: Any) -> list[KeyEntry]:
    """Normalize ``/api/keys/`` JSON into ``KeyEntry`` rows."""
    if not isinstance(payload, dict):
        raise ClientError("Keys response was not a JSON object")

    entries_raw = payload.get("entries")
    if isinstance(entries_raw, list) and entries_raw:
        parsed = [entry for item in entries_raw if (entry := parse_key_entry(item))]
        if parsed:
            return parsed

    keys = payload.get("keys")
    if not isinstance(keys, list):
        raise ClientError("Keys response missing keys list")
    result: list[KeyEntry] = []
    for item in keys:
        if isinstance(item, str) and item:
            result.append(KeyEntry(key=item))
        else:
            entry = parse_key_entry(item)
            if entry is not None:
                result.append(entry)
    return result


def fetch_key_entries(
    *,
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[KeyEntry]:
    """Fetch structured shortcut entries from ``/api/keys/``."""
    payload = _request_json(
        f"{base_url.rstrip('/')}/api/keys/",
        timeout=timeout,
    )
    return parse_keys_payload(payload)


def fetch_keys(
    *,
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[str]:
    """Fetch bookmark keys (plus specials) from ``/api/keys/``."""
    return [
        entry.key for entry in fetch_key_entries(base_url=base_url, timeout=timeout)
    ]


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

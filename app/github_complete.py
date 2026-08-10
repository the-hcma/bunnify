"""GitHub-backed parameter completions via the REST API (fail-soft)."""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 60.0
_DEFAULT_TIMEOUT_SECONDS = 8.0
_REPO_PARAM_NAMES = frozenset({"repo", "repository", "org_repo"})
_PR_PARAM_NAMES = frozenset(
    {"pr_number", "pr_id", "pr", "pull", "pull_number", "number"}
)
_API_ROOT = "https://api.github.com"

_cache: dict[str, tuple[float, list[str]]] = {}

_GITHUB_ORG_REPO = re.compile(
    r"(?:github\.com|graphite\.com/github/pr)/([^/#{}]+)/#\{repo\}",
    re.IGNORECASE,
)


def infer_fixed_github_org(url_template: str) -> str | None:
    """Return a fixed org/owner when the template is ``…/ORG/#{repo}…``."""
    match = _GITHUB_ORG_REPO.search(url_template)
    if match is None:
        return None
    return match.group(1)


def _cache_get(key: str) -> list[str] | None:
    hit = _cache.get(key)
    if hit is None:
        return None
    expires_at, values = hit
    if time.monotonic() >= expires_at:
        _cache.pop(key, None)
        return None
    return list(values)


def _cache_set(key: str, values: list[str]) -> None:
    _cache[key] = (time.monotonic() + _CACHE_TTL_SECONDS, list(values))


def clear_github_completion_cache() -> None:
    """Test helper: drop in-process completion cache."""
    _cache.clear()


def github_token_from_environ(
    environ: dict[str, str] | None = None,
) -> str | None:
    """Return a GitHub token from standard env vars, if set."""
    env = environ if environ is not None else os.environ
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        value = (env.get(name) or "").strip()
        if value:
            return value
    return None


def _github_get_json(
    path: str,
    *,
    query: dict[str, str] | None = None,
    token: str | None = None,
    timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    opener: Any | None = None,
) -> Any | None:
    """GET a GitHub REST path. Return parsed JSON, or ``None`` on failure."""
    auth = token if token is not None else github_token_from_environ()
    if not auth:
        return None
    params = urllib.parse.urlencode(query or {})
    url = f"{_API_ROOT}{path}"
    if params:
        url = f"{url}?{params}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {auth}",
            "User-Agent": "bunnify-cli",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return json.loads(body)
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
        OSError,
    ) as exc:
        logger.debug("GitHub REST GET %s failed: %s", path, exc, exc_info=True)
        return None


def list_github_repos(
    *,
    org: str | None = None,
    prefix: str = "",
    limit: int = 100,
    token: str | None = None,
    opener: Any | None = None,
) -> list[str]:
    """List repo names (short when ``org`` set, else ``owner/name``)."""
    cache_key = f"repos:{org or '*'}:{limit}"
    cached = _cache_get(cache_key)
    if cached is None:
        per_page = min(max(limit, 1), 100)
        if org:
            payload = _github_get_json(
                f"/orgs/{urllib.parse.quote(org)}/repos",
                query={
                    "per_page": str(per_page),
                    "type": "all",
                    "sort": "full_name",
                },
                token=token,
                opener=opener,
            )
            if payload is None:
                return []
            names: list[str] = []
            if isinstance(payload, list):
                for item in payload:
                    if isinstance(item, dict) and isinstance(item.get("name"), str):
                        names.append(item["name"])
            cached = names[:limit]
        else:
            payload = _github_get_json(
                "/user/repos",
                query={
                    "per_page": str(per_page),
                    "affiliation": "owner,collaborator,organization_member",
                    "sort": "full_name",
                },
                token=token,
                opener=opener,
            )
            if payload is None:
                return []
            names = []
            if isinstance(payload, list):
                for item in payload:
                    if isinstance(item, dict) and isinstance(
                        item.get("full_name"), str
                    ):
                        names.append(item["full_name"])
            cached = names[:limit]
        _cache_set(cache_key, cached)

    needle = prefix.lower()
    return [name for name in cached if name.lower().startswith(needle)]


def list_open_pull_requests(
    repo: str,
    *,
    prefix: str = "",
    limit: int = 50,
    token: str | None = None,
    opener: Any | None = None,
) -> list[str]:
    """List open PR numbers (as strings) for ``owner/name``."""
    if not repo or "/" not in repo:
        return []
    owner, name = repo.split("/", 1)
    if not owner or not name:
        return []
    cache_key = f"prs:{repo}:{limit}"
    cached = _cache_get(cache_key)
    if cached is None:
        per_page = min(max(limit, 1), 100)
        payload = _github_get_json(
            f"/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}/pulls",
            query={
                "state": "open",
                "per_page": str(per_page),
                "sort": "updated",
                "direction": "desc",
            },
            token=token,
            opener=opener,
        )
        if payload is None:
            return []
        numbers: list[str] = []
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict) and isinstance(item.get("number"), int):
                    numbers.append(str(item["number"]))
        cached = numbers[:limit]
        _cache_set(cache_key, cached)

    needle = prefix.lower()
    return [num for num in cached if num.startswith(needle)]


def resolve_repo_for_pr(
    *,
    url_template: str,
    repo_arg: str,
) -> str | None:
    """Build ``owner/name`` for PR listing from the template + typed repo token."""
    repo_arg = repo_arg.strip()
    if not repo_arg:
        return None
    if "/" in repo_arg:
        return repo_arg
    org = infer_fixed_github_org(url_template)
    if org:
        return f"{org}/{repo_arg}"
    return None


def suggest_param_values(
    *,
    param_name: str,
    url_template: str,
    filled_args: list[str],
    prefix: str,
    token: str | None = None,
    opener: Any | None = None,
) -> list[str]:
    """Return completion candidates for the next unresolved placeholder."""
    name = param_name.lower()
    if name in _REPO_PARAM_NAMES:
        org = infer_fixed_github_org(url_template)
        return list_github_repos(org=org, prefix=prefix, token=token, opener=opener)
    if name in _PR_PARAM_NAMES:
        repo_token = filled_args[-1] if filled_args else ""
        full_repo = resolve_repo_for_pr(url_template=url_template, repo_arg=repo_token)
        if full_repo is None:
            return []
        return list_open_pull_requests(
            full_repo, prefix=prefix, token=token, opener=opener
        )
    return []

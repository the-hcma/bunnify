"""GitHub-backed parameter completions via the REST API (fail-soft)."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Sequence
from typing import Any

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 300.0
_DEFAULT_TIMEOUT_SECONDS = 8.0
_GH_TOKEN_TIMEOUT_SECONDS = 8.0
_GH_LOGIN_TIMEOUT_SECONDS = 600.0
_REPO_PARAM_NAMES = frozenset({"repo", "repository", "org_repo"})
_PR_PARAM_NAMES = frozenset(
    {"pr_number", "pr_id", "pr", "pull", "pull_number", "number"}
)
_API_ROOT = "https://api.github.com"
_UNSET = object()

_cache: dict[str, tuple[float, list[str]]] = {}
_token_cache: Any = _UNSET

_GITHUB_ORG_REPO = re.compile(
    r"(?:github\.com|graphite\.com/github/pr)/([^/#{}]+)/#\{repo\}",
    re.IGNORECASE,
)

GhRunner = Callable[..., subprocess.CompletedProcess[str]]


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
    """Test helper: drop in-process completion + token caches."""
    global _token_cache
    _cache.clear()
    _token_cache = _UNSET


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


def _run_gh(
    args: Sequence[str],
    *,
    timeout: float,
    runner: GhRunner | None = None,
    capture_output: bool = True,
) -> subprocess.CompletedProcess[str]:
    run = runner or subprocess.run
    kwargs: dict[str, Any] = {
        "args": ["gh", *args],
        "text": True,
        "timeout": timeout,
        "check": False,
    }
    if capture_output:
        kwargs["capture_output"] = True
    return run(**kwargs)


def github_token_from_gh(
    *,
    runner: GhRunner | None = None,
    timeout: float = _GH_TOKEN_TIMEOUT_SECONDS,
) -> str | None:
    """Return the token from ``gh auth token`` when the CLI is logged in."""
    try:
        completed = _run_gh(
            ["auth", "token"],
            timeout=timeout,
            runner=runner,
            capture_output=True,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("gh auth token failed: %s", exc, exc_info=True)
        return None
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        logger.debug("gh auth token exited %s: %s", completed.returncode, stderr)
        return None
    token = (completed.stdout or "").strip()
    return token or None


def resolve_github_token(
    *,
    environ: dict[str, str] | None = None,
    runner: GhRunner | None = None,
    use_cache: bool = True,
) -> str | None:
    """
    Resolve a GitHub token for completion API calls.

    Precedence: ``GITHUB_TOKEN`` / ``GH_TOKEN`` → ``gh auth token``.
    """
    global _token_cache
    env_token = github_token_from_environ(environ)
    if env_token:
        return env_token
    if use_cache and _token_cache is not _UNSET:
        return _token_cache if isinstance(_token_cache, str) else None
    token = github_token_from_gh(runner=runner)
    if use_cache:
        _token_cache = token
    return token


def ensure_github_authenticated(
    *,
    interactive: bool = False,
    environ: dict[str, str] | None = None,
    runner: GhRunner | None = None,
) -> str | None:
    """
    Return a usable GitHub token, optionally running ``gh auth login`` first.

    When ``interactive`` is true and no token is available, launches the
    browser-oriented ``gh auth login`` flow (stdin/stdout inherited).
    """
    global _token_cache
    token = resolve_github_token(environ=environ, runner=runner)
    if token:
        return token
    if not interactive:
        return None
    logger.info("No GitHub token found; starting gh auth login")
    try:
        completed = _run_gh(
            [
                "auth",
                "login",
                "--hostname",
                "github.com",
                "--git-protocol",
                "https",
                "--web",
            ],
            timeout=_GH_LOGIN_TIMEOUT_SECONDS,
            runner=runner,
            capture_output=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("gh auth login failed: %s", exc, exc_info=True)
        return None
    if completed.returncode != 0:
        logger.debug("gh auth login exited %s", completed.returncode)
        return None
    _token_cache = _UNSET
    return resolve_github_token(environ=environ, runner=runner, use_cache=True)


def _github_get_json(
    path: str,
    *,
    query: dict[str, str] | None = None,
    token: str | None = None,
    timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    opener: Any | None = None,
    runner: GhRunner | None = None,
) -> Any | None:
    """GET a GitHub REST path. Return parsed JSON, or ``None`` on failure."""
    auth = token if token is not None else resolve_github_token(runner=runner)
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


def list_github_orgs(
    *,
    prefix: str = "",
    limit: int = 100,
    token: str | None = None,
    opener: Any | None = None,
    runner: GhRunner | None = None,
) -> list[str]:
    """List organization logins visible to the authenticated user."""
    cache_key = f"orgs:{limit}"
    cached = _cache_get(cache_key)
    if cached is None:
        per_page = min(max(limit, 1), 100)
        payload = _github_get_json(
            "/user/orgs",
            query={"per_page": str(per_page)},
            token=token,
            opener=opener,
            runner=runner,
        )
        if payload is None:
            return []
        names: list[str] = []
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict) and isinstance(item.get("login"), str):
                    names.append(item["login"])
        cached = names[:limit]
        _cache_set(cache_key, cached)

    needle = prefix.lower()
    return [name for name in cached if name.lower().startswith(needle)]


def list_github_repos(
    *,
    org: str | None = None,
    prefix: str = "",
    limit: int = 100,
    token: str | None = None,
    opener: Any | None = None,
    runner: GhRunner | None = None,
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
                runner=runner,
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
                runner=runner,
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
    runner: GhRunner | None = None,
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
            runner=runner,
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


def orgs_from_url_templates(url_templates: Iterable[str]) -> list[str]:
    """Unique fixed orgs inferred from bookmark URL templates."""
    seen: set[str] = set()
    ordered: list[str] = []
    for template in url_templates:
        org = infer_fixed_github_org(template)
        if org is None or org.lower() in seen:
            continue
        seen.add(org.lower())
        ordered.append(org)
    return ordered


def warm_github_completion_cache(
    *,
    url_templates: Iterable[str] | None = None,
    token: str | None = None,
    opener: Any | None = None,
    runner: GhRunner | None = None,
) -> dict[str, int]:
    """
    Prefetch orgs/repos the authenticated user can see.

    Warms:
    - ``/user/orgs``
    - ``/user/repos``
    - ``/orgs/{org}/repos`` for bookmark-fixed orgs and visible memberships
    """
    auth = token if token is not None else resolve_github_token(runner=runner)
    if not auth:
        return {"orgs": 0, "repos": 0}

    orgs = list_github_orgs(token=auth, opener=opener, runner=runner)
    fixed = orgs_from_url_templates(url_templates or ())
    targets: list[str] = []
    seen: set[str] = set()
    for org in [*fixed, *orgs]:
        key = org.lower()
        if key in seen:
            continue
        seen.add(key)
        targets.append(org)

    repo_count = 0
    # Always warm the cross-org user repo list (owner/name form).
    repo_count += len(
        list_github_repos(org=None, token=auth, opener=opener, runner=runner)
    )
    for org in targets:
        repo_count += len(
            list_github_repos(org=org, token=auth, opener=opener, runner=runner)
        )
    return {"orgs": len(orgs), "repos": repo_count}


def suggest_param_values(
    *,
    param_name: str,
    url_template: str,
    filled_args: list[str],
    prefix: str,
    token: str | None = None,
    opener: Any | None = None,
    runner: GhRunner | None = None,
) -> list[str]:
    """Return completion candidates for the next unresolved placeholder."""
    name = param_name.lower()
    if name in _REPO_PARAM_NAMES:
        org = infer_fixed_github_org(url_template)
        return list_github_repos(
            org=org, prefix=prefix, token=token, opener=opener, runner=runner
        )
    if name in _PR_PARAM_NAMES:
        repo_token = filled_args[-1] if filled_args else ""
        full_repo = resolve_repo_for_pr(url_template=url_template, repo_arg=repo_token)
        if full_repo is None:
            return []
        return list_open_pull_requests(
            full_repo, prefix=prefix, token=token, opener=opener, runner=runner
        )
    return []

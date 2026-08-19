"""Bookmark placeholder completion specs (Cocoa-free; parsed from bookmarks JSON)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_PLACEHOLDER_PATTERN = re.compile(r"#\{(\w+)\}")

COMPLETION_KINDS = frozenset(
    {
        "github_issue",
        "github_org",
        "github_pull_request",
        "github_repo",
    }
)


@dataclass(frozen=True)
class ParamCompleteSpec:
    """Declared Tab-completion behavior for one URL placeholder."""

    kind: str
    org: str | None = None
    repo_param: str | None = None


def parse_complete_map(raw: Any) -> dict[str, ParamCompleteSpec] | None:
    """Return a validated ``complete`` map, or ``None`` when *raw* is absent/invalid."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return None
    parsed: dict[str, ParamCompleteSpec] = {}
    for param_name, spec_raw in raw.items():
        if not isinstance(param_name, str) or not param_name:
            continue
        spec = parse_param_complete_spec(spec_raw)
        if spec is None:
            return None
        parsed[param_name] = spec
    return parsed


def parse_param_complete_spec(raw: Any) -> ParamCompleteSpec | None:
    """Parse one ``complete.<param>`` object."""
    if not isinstance(raw, dict):
        return None
    kind = raw.get("kind")
    if not isinstance(kind, str) or kind not in COMPLETION_KINDS:
        return None
    org = raw.get("org")
    if org is not None and not isinstance(org, str):
        return None
    repo_param = raw.get("repo_param")
    if repo_param is not None and not isinstance(repo_param, str):
        return None
    if kind in {"github_pull_request", "github_issue"} and not repo_param:
        return None
    return ParamCompleteSpec(kind=kind, org=org, repo_param=repo_param)


def validate_complete_map(
    complete: dict[str, ParamCompleteSpec],
    *,
    url: str,
) -> list[str]:
    """Return human-readable validation errors for *complete* vs *url* placeholders."""
    placeholders = set(_PLACEHOLDER_PATTERN.findall(url))
    errors: list[str] = []
    for param_name, spec in sorted(complete.items()):
        if param_name not in placeholders:
            errors.append(
                f"complete.{param_name} is not a placeholder in url ({url!r})"
            )
        if spec.repo_param is not None and spec.repo_param not in placeholders:
            errors.append(
                f"complete.{param_name}.repo_param {spec.repo_param!r} "
                f"is not a placeholder in url ({url!r})"
            )
    return errors

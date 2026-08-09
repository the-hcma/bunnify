"""Shared bookmark query resolution used by HTTP views and the CLI API."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote

from .models import Bookmark

PLACEHOLDER_PATTERN = re.compile(r"#\{(\w+)\}")
GOOGLE_SEARCH_URL = "https://www.google.com/search?q=#{search_terms}"

ResolveKind = Literal["bookmark", "special", "direct_url", "google_fallback"]


@dataclass(frozen=True)
class ResolveResult:
    """Outcome of resolving a shortcut query string."""

    ok: bool
    url: str | None = None
    error: str | None = None
    kind: ResolveKind | None = None
    key: str | None = None


def encode_placeholder_value(url_template: str, placeholder: str, value: str) -> str:
    """Encode placeholder values while preserving path separators when needed."""
    token = f"#{{{placeholder}}}"
    placeholder_start = url_template.index(token)
    query_start = url_template.rfind("?", 0, placeholder_start)
    last_ampersand = url_template.rfind("&", 0, placeholder_start)
    last_equals = url_template.rfind("=", 0, placeholder_start)

    if last_equals > max(query_start, last_ampersand):
        return quote(value, safe="")

    return quote(value, safe="/:@-._~")


def substitute_placeholder_values(
    url_template: str, param_mapping: dict[str, str]
) -> str:
    """Replace URL placeholders with encoded values."""
    substituted_url = url_template

    for placeholder, value in param_mapping.items():
        encoded_value = encode_placeholder_value(url_template, placeholder, value)
        substituted_url = substituted_url.replace(f"#{{{placeholder}}}", encoded_value)

    return substituted_url


def google_search_url(query: str) -> str:
    """Build a Google search URL for the given query string."""
    return substitute_placeholder_values(GOOGLE_SEARCH_URL, {"search_terms": query})


def resolve_query(query: str, *, strict: bool = False) -> ResolveResult:
    """
    Resolve a shortcut query (``key [params...]``) to a URL.

    Special keys ``h`` / ``help`` / ``cmd`` return site-relative paths (``/list/``,
    ``/cmd/``). When ``strict`` is true, unknown keys are errors instead of a
    Google search fallback.
    """
    query = query.strip()
    if not query:
        return ResolveResult(ok=False, error="No search query provided")

    if query.lower().startswith("htt"):
        return ResolveResult(ok=True, url=query, kind="direct_url")

    parts = query.split(None, 1)
    if not parts:
        return ResolveResult(ok=False, error="Empty search query")

    key = parts[0]
    param_string = parts[1] if len(parts) > 1 else ""

    if key in ("h", "help"):
        return ResolveResult(ok=True, url="/list/", kind="special", key=key)

    if key == "cmd":
        return ResolveResult(ok=True, url="/cmd/", kind="special", key=key)

    try:
        bookmark = Bookmark.objects.get(key=key)
    except Bookmark.DoesNotExist:
        if strict:
            return ResolveResult(
                ok=False,
                error=f"Unknown shortcut: {key}",
                key=key,
            )
        return ResolveResult(
            ok=True,
            url=google_search_url(query),
            kind="google_fallback",
            key=key,
        )

    url = bookmark.url
    placeholders = PLACEHOLDER_PATTERN.findall(url)

    if not placeholders:
        return ResolveResult(ok=True, url=url, kind="bookmark", key=key)

    param_mapping: dict[str, str] = {}

    if len(placeholders) == 1:
        if param_string or (bookmark.defaults and placeholders[0] in bookmark.defaults):
            param_mapping[placeholders[0]] = (
                param_string if param_string else bookmark.defaults[placeholders[0]]
            )
        else:
            return ResolveResult(
                ok=False,
                error=(f"Bookmark '{key}' requires a parameter.\nUsage: {key} <value>"),
                key=key,
            )
    else:
        param_values = param_string.split() if param_string else []

        if len(param_values) > len(placeholders):
            return ResolveResult(
                ok=False,
                error=f"Too many parameters for bookmark '{key}'.",
                key=key,
            )

        arg_offset = len(placeholders) - len(param_values)
        for i, placeholder in enumerate(placeholders):
            arg_idx = i - arg_offset
            if arg_idx >= 0:
                param_mapping[placeholder] = param_values[arg_idx]
            elif placeholder in (bookmark.defaults or {}):
                param_mapping[placeholder] = bookmark.defaults[placeholder]
            else:
                required_params = [
                    p for p in placeholders if p not in (bookmark.defaults or {})
                ]
                optional_params = [
                    p for p in placeholders if p in (bookmark.defaults or {})
                ]
                required = ", ".join(required_params)
                usage_args = " ".join(f"<{p}>" for p in required_params)
                optional_suffix = (
                    f" [{' '.join(optional_params)}]" if optional_params else ""
                )
                return ResolveResult(
                    ok=False,
                    error=(
                        f"Bookmark '{key}' requires parameter(s): {required}\n"
                        f"Usage: {key} {usage_args}{optional_suffix}"
                    ),
                    key=key,
                )

    return ResolveResult(
        ok=True,
        url=substitute_placeholder_values(url, param_mapping),
        kind="bookmark",
        key=key,
    )

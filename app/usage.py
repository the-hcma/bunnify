"""Format structured shortcut entries for CLI short-usage listings."""

from __future__ import annotations

from collections.abc import Iterable

from app.client import KeyEntry
from app.theme import Theme


def format_param_token(name: str, *, optional: bool) -> str:
    """Render one arg as ``<name>`` (required) or ``[name]`` (optional)."""
    if optional:
        return f"[{name}]"
    return f"<{name}>"


def format_params(
    params: tuple[str, ...] | list[str],
    *,
    optional_params: Iterable[str] | None = None,
) -> str:
    optional = frozenset(optional_params or ())
    return " ".join(
        format_param_token(name, optional=name in optional) for name in params
    )


_COMPLETION_META_DESC_MAX = 40


def format_completion_meta(
    *,
    params: tuple[str, ...] | list[str] = (),
    optional_params: Iterable[str] | None = None,
    description: str = "",
    fallback: str = "shortcut",
    desc_max: int = _COMPLETION_META_DESC_MAX,
) -> str:
    """
    Tab-completion sidebar text: args and/or help blurb.

    Examples: ``<repo> — Open org PRs``, ``[query]``, or a truncated description.
    """
    args = format_params(params, optional_params=optional_params)
    blurb = description.strip()
    if len(blurb) > desc_max > 0:
        blurb = (blurb[: desc_max - 1] + "…")[:desc_max]
    if args and blurb:
        return f"{args} — {blurb}"
    if args:
        return args
    if blurb:
        return blurb
    return fallback


def format_key_usage_lines(
    entries: list[KeyEntry],
    *,
    theme: Theme | None = None,
) -> list[str]:
    """Aligned short-usage rows: key · params · description · target."""
    active = theme or Theme(enabled=False)
    if not entries:
        return []

    rendered = [
        format_params(entry.params, optional_params=entry.optional_params)
        for entry in entries
    ]
    key_width = max(len(entry.key) for entry in entries)
    params_width = max((len(text) for text in rendered), default=0)
    # Cap description column so long blurbs do not dominate the terminal.
    desc_width = min(
        40,
        max((len(entry.description) for entry in entries), default=0),
    )

    lines: list[str] = []
    for entry, params in zip(entries, rendered, strict=True):
        description = entry.description
        if len(description) > desc_width > 0:
            description = (description[: desc_width - 1] + "…")[:desc_width]
        key_col = entry.key.ljust(key_width)
        params_col = params.ljust(params_width) if params_width else ""
        desc_col = description.ljust(desc_width) if desc_width else ""
        gap_params = f"  {params_col}" if params_width else ""
        gap_desc = f"  {desc_col}" if desc_width else ""
        target = entry.url
        lines.append(
            f"  {active.cmd(key_col)}{gap_params}{gap_desc}  {active.dim(target)}"
        )
    return lines

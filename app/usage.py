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

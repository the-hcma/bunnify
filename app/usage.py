"""Format structured shortcut entries for CLI short-usage listings."""

from __future__ import annotations

from app.client import KeyEntry
from app.theme import Theme


def format_params(params: tuple[str, ...] | list[str]) -> str:
    return " ".join(params)


def format_key_usage_lines(
    entries: list[KeyEntry],
    *,
    theme: Theme | None = None,
) -> list[str]:
    """Aligned short-usage rows: key · params · description · target."""
    active = theme or Theme(enabled=False)
    if not entries:
        return []

    key_width = max(len(entry.key) for entry in entries)
    params_width = max(
        (len(format_params(entry.params)) for entry in entries),
        default=0,
    )
    # Cap description column so long blurbs do not dominate the terminal.
    desc_width = min(
        40,
        max((len(entry.description) for entry in entries), default=0),
    )

    lines: list[str] = []
    for entry in entries:
        params = format_params(entry.params)
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

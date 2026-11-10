"""Per-shortcut browser/profile pin (``browser`` block of a bookmark)."""

from __future__ import annotations

from dataclasses import dataclass

BROWSER_APPS: tuple[str, ...] = ("edge", "chrome")


@dataclass(frozen=True)
class BrowserSpec:
    """Browser and/or profile a shortcut must open in.

    ``app`` of ``None`` means "the system default browser" (a profile alone
    is applied to it, which only works when it is Edge or Chrome).
    """

    app: str | None = None
    profile: str | None = None


def parse_browser_spec(raw: object) -> BrowserSpec | None:
    """Parse a server ``browser`` payload; ``None`` when absent or malformed."""
    if not isinstance(raw, dict):
        return None
    app = raw.get("app")
    profile = raw.get("profile")
    if app is not None and (not isinstance(app, str) or app not in BROWSER_APPS):
        return None
    if profile is not None and (not isinstance(profile, str) or not profile):
        return None
    if app is None and profile is None:
        return None
    return BrowserSpec(app=app, profile=profile)

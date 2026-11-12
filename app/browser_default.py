"""Machine-wide default browser/profile for shortcuts that do not pin one.

Stored in the per-user ``config.toml`` (profile names differ per machine, so
this never lives in the shared bookmarks). An explicit per-shortcut ``browser``
block always wins; with no setting, shortcuts open in the system default
browser exactly as before.
"""

from __future__ import annotations

import sys
from pathlib import Path

from app.browser_launch import BrowserLaunchError
from app.browser_spec import BROWSER_APPS, BrowserSpec
from app.config import (
    get_config_value,
    get_config_values,
    set_config_value,
    unset_config_value,
    update_config_values,
)

DEFAULT_BROWSER_KEY = "default_browser"
DEFAULT_BROWSER_PROFILE_KEY = "default_browser_profile"
# ``false`` means the user opted out of being asked to pick a default profile.
DEFAULT_BROWSER_PROMPT_KEY = "default_browser_prompt"


def load_default_browser(
    *,
    env_path: Path | None = None,
    environ: dict[str, str] | None = None,
) -> BrowserSpec | None:
    """The configured default browser/profile, or ``None`` when unset.

    Raises :class:`BrowserLaunchError` for an invalid ``default_browser`` (so a
    typo never silently falls back to a different browser) and for a
    ``config.toml`` that cannot be read or parsed.
    """
    try:
        values = get_config_values(
            (DEFAULT_BROWSER_KEY, DEFAULT_BROWSER_PROFILE_KEY),
            env_path=env_path,
            environ=environ,
        )
    except (ValueError, OSError) as exc:
        # An unreadable or malformed config.toml (ConfigParseError is a
        # ValueError) must surface like every other launch problem. Falling
        # back silently would open shortcuts in the wrong profile and hide the
        # mistake; every command already stops on the same file for base_url.
        raise BrowserLaunchError(f"Cannot read the default browser: {exc}") from exc
    app = values[DEFAULT_BROWSER_KEY]
    if app is not None:
        app = app.strip()
    profile = values[DEFAULT_BROWSER_PROFILE_KEY]
    if app is not None:
        app = app.lower()
        if app not in BROWSER_APPS:
            raise BrowserLaunchError(
                f"{DEFAULT_BROWSER_KEY} in config.toml must be one of "
                f"{', '.join(BROWSER_APPS)} (got {app!r})"
            )
    if app is None and profile is None:
        return None
    return BrowserSpec(app=app, profile=profile)


def save_default_browser(
    spec: BrowserSpec | None,
    *,
    env_path: Path | None = None,
    environ: dict[str, str] | None = None,
) -> None:
    """Persist (or, with ``None``, clear) the default browser/profile.

    Both keys are written in a single update so a reader never sees a browser
    paired with another selection's profile.
    """
    update_config_values(
        {
            DEFAULT_BROWSER_KEY: spec.app if spec else None,
            DEFAULT_BROWSER_PROFILE_KEY: spec.profile if spec else None,
        },
        env_path=env_path,
        environ=environ,
    )


def default_browser_prompt_enabled(
    *,
    env_path: Path | None = None,
    environ: dict[str, str] | None = None,
) -> bool:
    """False once the user opted out of the installer's profile question."""
    value = get_config_value(
        DEFAULT_BROWSER_PROMPT_KEY, env_path=env_path, environ=environ
    )
    return value is None or value.lower() != "false"


def save_default_browser_prompt(
    enabled: bool,
    *,
    env_path: Path | None = None,
    environ: dict[str, str] | None = None,
) -> None:
    """Persist whether the installer may ask for a default profile."""
    if enabled:
        unset_config_value(
            DEFAULT_BROWSER_PROMPT_KEY, env_path=env_path, environ=environ
        )
    else:
        set_config_value(
            DEFAULT_BROWSER_PROMPT_KEY, False, env_path=env_path, environ=environ
        )


def apply_default_browser(
    pinned: BrowserSpec | None,
    *,
    default: BrowserSpec | None = None,
    env_path: Path | None = None,
    environ: dict[str, str] | None = None,
) -> BrowserSpec | None:
    """The browser/profile to open with: the pin, filled in from the default.

    - no pin: the default (so every unpinned shortcut opens there);
    - pin naming a browser only: the default's profile when it is the same
      browser, so a Chrome pin never receives an Edge profile name;
    - pin naming a profile (with or without a browser): used as written, without
      even reading the default;
    - a browser-only pin is still opened when the default is invalid.

    Only macOS and Windows can honor a browser/profile; elsewhere the default
    is ignored so ordinary shortcuts keep working.
    """
    if sys.platform not in ("darwin", "win32"):
        return pinned
    if pinned is not None and pinned.profile is not None:
        # A profile pin (with or without a browser) is complete: it never
        # needs the default, so a broken default must not stop it opening.
        return pinned
    if default is None:
        try:
            default = load_default_browser(env_path=env_path, environ=environ)
        except BrowserLaunchError:
            if pinned is not None and pinned.app is not None:
                # The pin already says which browser to open; an invalid
                # default must not stop it (it still fails unpinned shortcuts).
                return pinned
            raise
    if default is None:
        return pinned
    if pinned is None:
        return default
    if pinned.app == default.app and default.profile:
        return BrowserSpec(app=pinned.app, profile=default.profile)
    return pinned

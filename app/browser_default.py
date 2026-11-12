"""Machine-wide default browser/profile for shortcuts that do not pin one.

Stored in the per-user ``config.toml`` (profile names differ per machine, so
this never lives in the shared bookmarks). A per-shortcut ``browser`` block that
names a profile always wins; a block naming only the same browser as the
default is opened in the default's profile (see :func:`apply_default_browser`).
With no setting, shortcuts open in the system default browser exactly as
before.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.browser_launch import BrowserLaunchError
from app.browser_spec import BROWSER_APPS, BrowserSpec
from app.config import (
    ScopedValues,
    current_host,
    read_scoped_config_values,
    update_config_values,
)

DEFAULT_BROWSER_KEY = "default_browser"
DEFAULT_BROWSER_PROFILE_KEY = "default_browser_profile"
# ``false`` means the user opted out of being asked to pick a default profile.
DEFAULT_BROWSER_PROMPT_KEY = "default_browser_prompt"
_KEYS = (DEFAULT_BROWSER_KEY, DEFAULT_BROWSER_PROFILE_KEY, DEFAULT_BROWSER_PROMPT_KEY)


Scope = Literal["host", "global"]


@dataclass(frozen=True)
class DefaultBrowser:
    """The effective default and where it came from.

    ``host`` is this machine's label (what ``[hosts.<label>]`` must be named).
    ``everywhere`` is the top-level (all hosts) value alone and ``this_host``
    this host's own table value alone, whatever the other one says.
    ``everywhere_error`` is set when the all-hosts value is invalid but this
    host's own valid default made it harmless here, so it can still be shown
    and cleared; ``this_host_error`` is the same for this host's own invalid
    value, which ``strict=False`` reports instead of raising.
    """

    spec: BrowserSpec | None
    source: Literal["host", "global", "none"]
    host: str
    everywhere: BrowserSpec | None = None
    this_host: BrowserSpec | None = None
    everywhere_error: str | None = None
    this_host_error: str | None = None


def _read_scoped(env_path: Path | None, environ: dict[str, str] | None) -> ScopedValues:
    try:
        return read_scoped_config_values(_KEYS, env_path=env_path, environ=environ)
    except (ValueError, OSError) as exc:
        # An unreadable or malformed config.toml (ConfigParseError is a
        # ValueError) must surface like every other launch problem. Falling
        # back silently would open shortcuts in the wrong profile and hide the
        # mistake; every command already stops on the same file for base_url.
        raise BrowserLaunchError(f"Cannot read the default browser: {exc}") from exc


def _spec_from(values: dict[str, str | None]) -> BrowserSpec | None:
    app = values[DEFAULT_BROWSER_KEY]
    profile = values[DEFAULT_BROWSER_PROFILE_KEY]
    if app is not None:
        app = app.strip().lower()
        if app not in BROWSER_APPS:
            raise BrowserLaunchError(
                f"{DEFAULT_BROWSER_KEY} in config.toml must be one of "
                f"{', '.join(BROWSER_APPS)} (got {app!r})"
            )
    if app is None and profile is None:
        return None
    return BrowserSpec(app=app, profile=profile)


def resolve_default_browser(
    *,
    env_path: Path | None = None,
    environ: dict[str, str] | None = None,
    need_host: bool = True,
    strict: bool = True,
) -> DefaultBrowser:
    """The effective default browser/profile for this machine, and its source.

    A ``[hosts.<this machine>]`` table that sets ``default_browser`` and/or
    ``default_browser_profile`` replaces the top-level pair as a whole (a host
    never inherits half a pair, so a browser can't be paired with another
    machine's profile); otherwise the top-level values apply to every host.

    Raises :class:`BrowserLaunchError` for an invalid ``default_browser`` that
    this machine would use (so a typo never silently falls back to a different
    browser) and for a ``config.toml`` that cannot be read or parsed. An invalid
    all-hosts value is only tolerated when this host has its own valid default
    (it is then reported through ``everywhere_error``, and ``bunnify browsers``
    shows it); with ``strict=False`` an invalid all-hosts or this-host value is
    tolerated and reported (``everywhere_error`` / ``this_host_error``) in every
    case, so the ``browsers`` command can show and clear it.
    """
    scoped = _read_scoped(env_path, environ)
    # The machine's name is only needed for messages and saving, so the hot
    # "open a shortcut" path (need_host=False) never looks it up.
    host = (scoped.host or current_host(environ=environ)) if need_host else ""
    this_host_error: str | None = None
    try:
        mine = _spec_from(scoped.this_host)
    except BrowserLaunchError as exc:
        if strict:
            raise
        mine = None
        this_host_error = str(exc)
    everywhere_error: str | None = None
    try:
        everywhere = _spec_from(scoped.everywhere)
    except BrowserLaunchError as exc:
        if mine is None and strict:
            raise
        # This host's own default is valid and wins, so a typo in the all-hosts
        # one must not stop its shortcuts (it still fails hosts that need it).
        # It is kept so ``bunnify browsers`` can report and clear it.
        everywhere = None
        everywhere_error = str(exc)
    source: Literal["host", "global", "none"] = (
        "host" if mine is not None else "global" if everywhere is not None else "none"
    )
    return DefaultBrowser(
        spec=mine if mine is not None else everywhere,
        source=source,
        host=host,
        everywhere=everywhere,
        this_host=mine,
        everywhere_error=everywhere_error,
        this_host_error=this_host_error,
    )


def load_default_browser(
    *,
    env_path: Path | None = None,
    environ: dict[str, str] | None = None,
) -> BrowserSpec | None:
    """The configured default browser/profile for this machine, or ``None``."""
    return resolve_default_browser(
        env_path=env_path, environ=environ, need_host=False
    ).spec


def save_default_browser(
    spec: BrowserSpec | None,
    *,
    env_path: Path | None = None,
    environ: dict[str, str] | None = None,
    scope: Scope = "host",
) -> None:
    """Persist (or, with ``None``, clear) the default browser/profile.

    ``scope="host"`` writes this machine's ``[hosts.<label>]`` table, so a
    config shared between machines keeps each machine's own choice;
    ``scope="global"`` writes the top-level keys every host falls back to.
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
        host=current_host(environ=environ) if scope == "host" else None,
    )


def default_browser_prompt_enabled(
    *,
    env_path: Path | None = None,
    environ: dict[str, str] | None = None,
) -> bool:
    """False once the user opted out of the installer's profile question.

    This machine's ``[hosts.<label>]`` value wins over the top-level one.
    """
    scoped = _read_scoped(env_path, environ)
    value = scoped.this_host[DEFAULT_BROWSER_PROMPT_KEY]
    if value is None:
        value = scoped.everywhere[DEFAULT_BROWSER_PROMPT_KEY]
    return value is None or value.strip().lower() != "false"


def save_default_browser_prompt(
    enabled: bool,
    *,
    env_path: Path | None = None,
    environ: dict[str, str] | None = None,
    scope: Scope = "host",
) -> None:
    """Persist whether the installer may ask for a default profile.

    Re-enabling on a host whose all-hosts value opted out writes an explicit
    ``true`` for the host, because deleting its key would let the top-level
    ``false`` apply again.
    """
    value: bool | None = None if enabled else False
    if scope == "host" and enabled:
        everywhere = _read_scoped(env_path, environ).everywhere
        if (everywhere[DEFAULT_BROWSER_PROMPT_KEY] or "").strip().lower() == "false":
            value = True
    update_config_values(
        {DEFAULT_BROWSER_PROMPT_KEY: value},
        env_path=env_path,
        environ=environ,
        host=current_host(environ=environ) if scope == "host" else None,
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

"""``bunnify browsers``: list Edge/Chrome profiles and choose the default one."""

from __future__ import annotations

import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from app.browser_default import (
    DEFAULT_BROWSER_KEY,
    DEFAULT_BROWSER_PROFILE_KEY,
    apply_default_browser,
    default_browser_prompt_enabled,
    load_default_browser,
    save_default_browser,
    save_default_browser_prompt,
)
from app.browser_launch import (
    BrowserLaunchError,
    ProfileInfo,
    browser_from_identifier,
    detect_default_browser_id,
    display_name,
    installed_browser_profiles,
)
from app.browser_spec import BrowserSpec
from app.theme import Theme

SUPPORTED_PLATFORMS = ("darwin", "win32")
BROWSERS_USAGE = "usage: bunnify browsers [default]"
CHOOSE_PROMPT = (
    "Choose a default profile [1-{count}], Enter to decide later, n to never ask: "
)
CHANGE_PROMPT = "Choose a default profile [1-{count}], c to clear, Enter to keep: "
NO_PROFILES_PROMPT = "c to clear the saved default, Enter to keep it: "
PICK_PROMPT = "Choose a default profile [1-{count}], Enter to cancel: "
CLEARABLE_PROMPTS = (CHANGE_PROMPT, NO_PROFILES_PROMPT)
ABORTED = "aborted"

Choice = tuple[str, ProfileInfo]


def _flatten(found: dict[str, list[ProfileInfo]]) -> list[Choice]:
    return [(app, info) for app, profiles in found.items() for info in profiles]


def _describe(spec: BrowserSpec | None) -> str:
    if spec is None:
        return "not set"
    parts = []
    if spec.app:
        parts.append(display_name(spec.app))
    if spec.profile:
        parts.append(f'profile "{spec.profile}"')
    return ", ".join(parts)


def _is_default(spec: BrowserSpec | None, app: str, info: ProfileInfo) -> bool:
    return spec is not None and spec.app == app and spec.profile == info.name


def _format_choice(
    index: int | None, app: str, info: ProfileInfo, colors: Theme, marker: str
) -> str:
    lead = f"{index:>3}) " if index is not None else "     "
    account = f"  {colors.dim(info.account)}" if info.account else ""
    return (
        f"{lead}{display_name(app)}  {info.name}{account}  "
        f"{colors.dim(f'[{info.directory}]')}{marker}"
    )


def _unsupported(log: Callable[[str], None], colors: Theme) -> int:
    log(
        colors.warn(
            "Browser profiles are only supported on macOS and Windows "
            f"(this is {sys.platform})."
        )
    )
    return 1


def run_browsers(
    args: list[str],
    *,
    env_path: Path | None = None,
    print_fn: Callable[[str], None] | None = None,
    prompt_fn: Callable[[str], str] | None = None,
    theme: Theme | None = None,
    found: dict[str, list[ProfileInfo]] | None = None,
    interactive: bool | None = None,
) -> int:
    """List profiles (no args) or choose the default (``default``). Exit code.

    ``interactive`` says whether a person can answer prompts; the CLI always
    supplies a ``prompt_fn``, so it passes the real terminal state. Left as
    ``None`` (tests) an injected ``prompt_fn`` counts as interactive.
    """
    log = print_fn or print
    colors = theme if theme is not None else Theme(enabled=False)
    if args not in ([], ["default"]):
        log(BROWSERS_USAGE)
        return 2
    if sys.platform not in SUPPORTED_PLATFORMS:
        return _unsupported(log, colors)
    try:
        current = load_default_browser(env_path=env_path)
    except (BrowserLaunchError, ValueError, OSError) as exc:
        log(colors.err(f"error: {exc}"))
        return 1
    discovery_failed = False
    try:
        profiles = (
            found
            if found is not None
            else installed_browser_profiles(
                on_error=lambda exc: log(colors.warn(f"warning: {exc}"))
            )
        )
    except (BrowserLaunchError, ValueError, OSError) as exc:
        log(colors.err(f"error: {exc}"))
        if args != ["default"]:
            if current is not None:
                log(f"Default for unpinned shortcuts: {_describe(current)}")
            return 1
        if current is None:
            return 1
        # The saved default may be the very thing that no longer opens, so
        # still offer to clear it even though discovery failed.
        profiles = {}
        discovery_failed = True
    if args == ["default"] and (profiles or current is not None):
        # With a saved default we still offer "clear", so an unusable default
        # (its browser or profile is gone) can always be removed.
        return _choose_default(
            profiles,
            current,
            env_path=env_path,
            log=log,
            prompt_fn=prompt_fn,
            colors=colors,
            interactive=interactive,
            discovery_failed=discovery_failed,
        )
    if not profiles:
        log("No Edge or Chrome profiles found (is a browser installed and run once?).")
        return 1
    system_default = browser_from_identifier(detect_default_browser_id())
    log(colors.header("Browser profiles"))
    for app, infos in profiles.items():
        suffix = "  (system default browser)" if app == system_default else ""
        log(f"{display_name(app)}{suffix}")
        for info in infos:
            marker = (
                colors.ok("  ← default for unpinned shortcuts")
                if _is_default(current, app, info)
                else ""
            )
            log(_format_choice(None, app, info, colors, marker))
    log("")
    log(f"Default for unpinned shortcuts: {_describe(current)}")
    log(
        "Pin one shortcut with "
        '"browser": {"app": "edge", "profile": "<name>"} in its bookmark; '
        "use the profile name exactly as listed. Change the default with: "
        "bunnify browsers default"
    )
    return 0


def _choose_default(
    profiles: dict[str, list[ProfileInfo]],
    current: BrowserSpec | None,
    *,
    env_path: Path | None,
    log: Callable[[str], None],
    prompt_fn: Callable[[str], str] | None,
    colors: Theme,
    interactive: bool | None = None,
    discovery_failed: bool = False,
) -> int:
    if interactive is None:
        interactive = prompt_fn is not None or (
            sys.stdin.isatty() and sys.stdout.isatty()
        )
    if not interactive:
        log(
            colors.err(
                "error: choosing a default profile needs a terminal; set "
                f"{DEFAULT_BROWSER_KEY} and {DEFAULT_BROWSER_PROFILE_KEY} in "
                "config.toml instead"
            )
        )
        return 1
    ask = prompt_fn or input
    answer = _ask_for_profile(
        profiles,
        current,
        ask=ask,
        log=log,
        colors=colors,
        prompt=CHANGE_PROMPT if current is not None else PICK_PROMPT,
        discovery_failed=discovery_failed,
    )
    try:
        return _apply_answer(answer, current, env_path=env_path, log=log, colors=colors)
    except (ValueError, OSError) as exc:
        log(colors.err(f"error: could not save the default browser profile: {exc}"))
        return 1


def _ask_for_profile(
    profiles: dict[str, list[ProfileInfo]],
    current: BrowserSpec | None,
    *,
    ask: Callable[[str], str],
    log: Callable[[str], None],
    colors: Theme,
    prompt: str,
    discovery_failed: bool = False,
) -> str | Choice:
    """Show the numbered list and return the user's answer: a choice or a letter."""
    choices = _flatten(profiles)
    if not choices:
        log(
            colors.warn(
                f"Could not list profiles to check the saved default "
                f"({_describe(current)}); see the error above."
                if discovery_failed
                else "No profiles found for the saved default "
                f"({_describe(current)}); it may have been removed."
            )
        )
        prompt = NO_PROFILES_PROMPT
    names = Counter((app, info.name) for app, info in choices)
    for number, (app, info) in enumerate(choices, start=1):
        marker = (
            colors.ok("  ← current default") if _is_default(current, app, info) else ""
        )
        if names[(app, info.name)] > 1:
            marker += colors.warn("  (name shared; rename it in the browser first)")
        log(_format_choice(number, app, info, colors, marker))
    while True:
        try:
            raw = ask(prompt.format(count=len(choices))).strip().lower()
        except EOFError, KeyboardInterrupt:
            return ABORTED  # an abort is not the same answer as "decide later"
        if choices and raw.isdecimal() and 1 <= int(raw) <= len(choices):
            app, info = choices[int(raw) - 1]
            if names[(app, info.name)] > 1:
                log(
                    colors.warn(
                        f'"{info.name}" names {names[(app, info.name)]} '
                        f"{display_name(app)} profiles; rename one in the "
                        "browser so Bunnify can tell them apart."
                    )
                )
                continue
            return (app, info)
        if raw == "" or (raw == "c" and prompt in CLEARABLE_PROMPTS):
            return raw
        if raw == "n" and prompt == CHOOSE_PROMPT:
            return raw
        log(
            colors.warn(
                f"Enter a number from 1 to {len(choices)}."
                if choices
                else "Enter c to clear or press Enter to keep."
            )
        )


def _apply_answer(
    answer: str | Choice,
    current: BrowserSpec | None,
    *,
    env_path: Path | None,
    log: Callable[[str], None],
    colors: Theme,
) -> int:
    if answer == ABORTED:
        log("Cancelled; nothing was changed.")
        return 1
    if isinstance(answer, tuple):
        app, info = answer
        save_default_browser(BrowserSpec(app=app, profile=info.name), env_path=env_path)
        log(
            colors.ok(
                "✓ Default for unpinned shortcuts: "
                f'{display_name(app)}, profile "{info.name}"'
            )
        )
        return 0
    if answer == "c" and current is None:
        log("There is no saved default to clear.")
        return 0
    if answer == "c":
        save_default_browser(None, env_path=env_path)
        log(
            colors.ok(
                "✓ Cleared the default profile; shortcuts use the system default."
            )
        )
        return 0
    if answer == "n":
        save_default_browser_prompt(False, env_path=env_path)
        log(
            "OK, the installer will not ask again. "
            "Change it any time: bunnify browsers default"
        )
        return 0
    if current is None:
        log("OK, no default chosen. Pick one any time: bunnify browsers default")
    else:
        log(f"Default for unpinned shortcuts: {_describe(current)} (unchanged)")
    return 0


def offer_default_profile(
    *,
    ask: Callable[[str], str],
    log: Callable[[str], None],
    colors: Theme,
    env_path: Path | None = None,
    found: dict[str, list[ProfileInfo]] | None = None,
) -> None:
    """Installer step: show profiles and let the user pick, defer, or opt out.

    Silent when the user opted out; when a default is already chosen it only
    reports it. Never fails the install (a macOS privacy denial is reported
    with its fix and skipped).
    """
    if sys.platform not in SUPPORTED_PLATFORMS:
        return
    try:
        if not default_browser_prompt_enabled(env_path=env_path):
            return
        current = load_default_browser(env_path=env_path)
        if current is not None:
            log(f"Default browser profile: {_describe(current)} (bunnify browsers)")
            return
        profiles = (
            found
            if found is not None
            else installed_browser_profiles(
                on_error=lambda exc: log(colors.warn(f"warning: {exc}"))
            )
        )
    except (BrowserLaunchError, ValueError, OSError) as exc:
        log(colors.warn(f"Skipping the default browser profile step: {exc}"))
        return
    if not profiles:
        return
    log("")
    log(colors.header("Default browser profile"))
    log(
        "Shortcuts without their own browser setting can open in one Edge/Chrome "
        "profile instead of whichever the browser picks. Profiles found:"
    )
    answer = _ask_for_profile(
        profiles,
        None,
        ask=ask,
        log=log,
        colors=colors,
        prompt=CHOOSE_PROMPT,
    )
    try:
        _apply_answer(answer, None, env_path=env_path, log=log, colors=colors)
    except (ValueError, OSError) as exc:
        log(
            colors.warn(
                f"Could not save the default browser profile ({exc}); "
                "set it later with: bunnify browsers default"
            )
        )


__all__ = [
    "apply_default_browser",
    "offer_default_profile",
    "run_browsers",
]

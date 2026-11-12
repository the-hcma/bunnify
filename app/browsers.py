"""``bunnify browsers``: list Edge/Chrome profiles and choose the default one."""

from __future__ import annotations

import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import click

from app.browser_default import (
    DEFAULT_BROWSER_KEY,
    DEFAULT_BROWSER_PROFILE_KEY,
    DefaultBrowser,
    Scope,
    apply_default_browser,
    default_browser_prompt_enabled,
    resolve_default_browser,
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
BROWSERS_USAGE = "usage: bunnify browsers [default [global]]"
CHOOSE_PROMPT = (
    "Choose a default profile [1-{count}], Enter to decide later, n to never ask: "
)
CHANGE_PROMPT = "Choose a default profile [1-{count}], c to clear, Enter to keep: "
NO_PROFILES_PROMPT = "c to clear the saved default, Enter to keep it: "
PICK_PROMPT = "Choose a default profile [1-{count}], Enter to cancel: "
CLEARABLE_PROMPTS = (CHANGE_PROMPT, NO_PROFILES_PROMPT)
ABORTED = "aborted"
MAX_INVALID_ANSWERS = 5

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


def _where(resolved: DefaultBrowser) -> str:
    """Where the effective default comes from, for messages."""
    if resolved.source == "host":
        return f"this host, {resolved.host}"
    if resolved.source == "global":
        return "all hosts"
    return ""


# Stands for an all-hosts default that is saved but invalid, so it can be cleared.
_INVALID_GLOBAL = BrowserSpec(profile="(invalid setting)")


def _scope_current(resolved: DefaultBrowser, scope: Scope) -> BrowserSpec | None:
    """The value saved in *scope*: what a choice or a clear there would change."""
    if scope == "global":
        if resolved.everywhere is None and resolved.everywhere_error is not None:
            return _INVALID_GLOBAL
        return resolved.everywhere
    if resolved.this_host is None and resolved.this_host_error is not None:
        return _INVALID_GLOBAL
    return resolved.this_host


def _scope_label(scope: Scope, resolved: DefaultBrowser) -> str:
    return "all hosts" if scope == "global" else f"this host, {resolved.host}"


def _is_default(spec: BrowserSpec | None, app: str, info: ProfileInfo) -> bool:
    # A profile-only default (no browser named) matches the name in any browser.
    return (
        spec is not None
        and spec.app in (None, app)
        and spec.profile is not None
        and spec.profile == info.name
    )


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
    if args not in ([], ["default"], ["default", "global"]):
        log(BROWSERS_USAGE)
        return 2
    if sys.platform not in SUPPORTED_PLATFORMS:
        return _unsupported(log, colors)
    scope: Scope = "global" if args == ["default", "global"] else "host"
    choosing = args[:1] == ["default"]
    try:
        resolved = resolve_default_browser(env_path=env_path, strict=False)
    except (BrowserLaunchError, ValueError, OSError) as exc:
        log(colors.err(f"error: {exc}"))
        return 1
    current = resolved.spec
    # What is saved in the scope being edited (an invalid value counts), so it
    # can always be cleared even when no profile can be listed.
    saved = _scope_current(resolved, scope)
    if resolved.everywhere_error is not None:
        log(
            colors.warn(
                "warning: the all-hosts default is invalid "
                f"({resolved.everywhere_error}); "
                + (
                    "this host's own default is used instead. "
                    if resolved.this_host is not None
                    else "shortcuts on hosts without their own default fail until "
                    "it is fixed. "
                )
                + "Fix it in config.toml or clear it with: "
                "bunnify browsers default global"
            )
        )
    if resolved.this_host_error is not None:
        log(
            colors.warn(
                "warning: this host's default is invalid "
                f"({resolved.this_host_error}). Fix it in config.toml or clear it "
                "with: bunnify browsers default"
            )
        )
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
        if not choosing:
            if current is not None:
                log(
                    f"Default for unpinned shortcuts: {_describe(current)} "
                    f"({_where(resolved)})"
                )
            return 1
        if saved is None:
            return 1
        # The saved default may be the very thing that no longer opens, so
        # still offer to clear it even though discovery failed.
        profiles = {}
        discovery_failed = True
    if choosing and (profiles or saved is not None):
        # With a saved default we still offer "clear", so an unusable default
        # (its browser or profile is gone, or the value is invalid) can always
        # be removed.
        return _choose_default(
            profiles,
            resolved,
            scope,
            env_path=env_path,
            log=log,
            prompt_fn=prompt_fn,
            colors=colors,
            interactive=interactive,
            discovery_failed=discovery_failed,
        )
    if not profiles:
        log("No Edge or Chrome profiles found (is a browser installed and run once?).")
        if current is not None:
            log(
                f"Default for unpinned shortcuts: {_describe(current)} "
                f"({_where(resolved)}). Change or clear it with: "
                "bunnify browsers default"
            )
        return 1
    system_default = browser_from_identifier(detect_default_browser_id())
    log(colors.header("Browser profiles"))
    log(f"This host: {resolved.host}")
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
    where = f" ({_where(resolved)})" if current is not None else ""
    log(f"Default for unpinned shortcuts: {_describe(current)}{where}")
    log(
        "Pin one shortcut with "
        '"browser": {"app": "edge", "profile": "<name>"} in its bookmark; '
        "use the profile name exactly as listed. Set this host's default with: "
        "bunnify browsers default (or all hosts: bunnify browsers default global)"
    )
    return 0


def _choose_default(
    profiles: dict[str, list[ProfileInfo]],
    resolved: DefaultBrowser,
    scope: Scope,
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
    # Mark and compare against the value this scope would change, not the
    # effective one (a host's own table overrides the all-hosts value).
    current = _scope_current(resolved, scope)
    log(f"Setting the default for: {_scope_label(scope, resolved)}")
    if scope == "host" and resolved.source == "global":
        log(
            f"Inherited from all hosts now: {_describe(resolved.spec)} "
            "(a choice here overrides it on this host only)."
        )
    if scope == "global" and resolved.this_host is not None:
        log(
            colors.warn(
                f"Note: this host ({resolved.host}) has its own default "
                f"({_describe(resolved.this_host)}), which keeps overriding the "
                "all-hosts one here."
            )
        )
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
        return _apply_answer(
            answer,
            resolved,
            scope,
            env_path=env_path,
            log=log,
            colors=colors,
        )
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
    invalid = 0
    while True:
        if invalid >= MAX_INVALID_ANSWERS:
            # Bounded retries: a prompt that keeps returning unusable answers
            # (a stuck wrapper, piped input) must not spin forever.
            log(colors.warn("Too many invalid answers; nothing was changed."))
            return ABORTED
        try:
            raw = ask(prompt.format(count=len(choices))).strip().lower()
        except EOFError, KeyboardInterrupt, click.Abort:
            # click.prompt turns Ctrl-C and EOF into click.Abort. An abort is
            # not the same answer as "decide later".
            return ABORTED
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
                invalid += 1
                continue
            return (app, info)
        if raw == "" or (raw == "c" and prompt in CLEARABLE_PROMPTS):
            return raw
        if raw == "n" and prompt == CHOOSE_PROMPT:
            return raw
        invalid += 1
        log(
            colors.warn(
                f"Enter a number from 1 to {len(choices)}."
                if choices
                else "Enter c to clear or press Enter to keep."
            )
        )


def _apply_answer(
    answer: str | Choice,
    resolved: DefaultBrowser,
    scope: Scope,
    *,
    env_path: Path | None,
    log: Callable[[str], None],
    colors: Theme,
) -> int:
    current = _scope_current(resolved, scope)
    if answer == ABORTED:
        log("Cancelled; nothing was changed.")
        return 1
    if isinstance(answer, tuple):
        app, info = answer
        save_default_browser(
            BrowserSpec(app=app, profile=info.name), env_path=env_path, scope=scope
        )
        log(
            colors.ok(
                f"✓ Default for unpinned shortcuts ({_scope_label(scope, resolved)}): "
                f'{display_name(app)}, profile "{info.name}"'
            )
        )
        return 0
    if answer == "c" and current is None:
        log(f"There is no saved default to clear for {_scope_label(scope, resolved)}.")
        return 0
    if (
        answer == "c"
        and scope == "host"
        and resolved.source != "host"
        and resolved.this_host_error is None
    ):
        log(
            f"This host ({resolved.host}) has no default of its own; the all-hosts "
            "default stays. Clear that one with: bunnify browsers default global"
        )
        return 0
    if answer == "c":
        save_default_browser(None, env_path=env_path, scope=scope)
        if scope == "host":
            after = "it follows the all-hosts default again, if there is one."
        elif resolved.this_host is not None:
            after = (
                f"this host ({resolved.host}) still uses its own default "
                f"({_describe(resolved.this_host)})."
            )
        else:
            after = "shortcuts use the system default."
        log(
            colors.ok(
                f"✓ Cleared the default for {_scope_label(scope, resolved)}; {after}"
            )
        )
        return 0
    if answer == "n":
        save_default_browser_prompt(False, env_path=env_path, scope=scope)
        where = (
            f"the [hosts.{resolved.host}] table (and the top level too, if it is "
            "set there)"
            if scope == "host"
            else "the top level of config.toml"
        )
        log(
            "OK, the installer will not ask again on "
            f"{_scope_label(scope, resolved)}. You can still choose a default any "
            "time with: bunnify browsers default. To be asked again, remove "
            f"default_browser_prompt from {where}."
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
        resolved = resolve_default_browser(env_path=env_path, strict=False)
        if resolved.spec is not None:
            log(
                f"Default browser profile: {_describe(resolved.spec)} "
                f"({_where(resolved)}; see bunnify browsers)"
            )
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
    log(f"Saving for this host ({resolved.host}); other machines keep their own.")
    answer = _ask_for_profile(
        profiles,
        None,
        ask=ask,
        log=log,
        colors=colors,
        prompt=CHOOSE_PROMPT,
    )
    try:
        _apply_answer(
            answer, resolved, "host", env_path=env_path, log=log, colors=colors
        )
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

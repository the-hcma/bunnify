"""Interactive and static onboarding after pipx install or upgrade."""

from __future__ import annotations

import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from packaging.version import InvalidVersion, Version

from app.client import ClientError
from app.config import default_bookmarks_path, env_file_path, load_preferences
from app.pipx_install import (
    install_macos_extra,
    macos_extra_installed,
    pipx_bunnify_path,
)
from app.pypi import pypi_latest_version
from app.theme import Theme
from app.version import get_build_info, is_source_checkout, running_command_path


@dataclass(frozen=True)
class InstallState:
    """Detected install / upgrade context for onboarding."""

    bookmarks_ready: bool
    command_path: str
    macos_extra: bool
    macos_platform: bool
    pipx_app_path: str | None
    pipx_version_label: str | None
    preferences_ready: bool
    pypi_latest: str | None
    server_agent_installed: bool
    source_checkout: bool
    spotty_agent_installed: bool
    upgrade_available: bool
    version_label: str


def detect_install_state(
    *,
    read_executable_build: Callable[[Path], str | None],
) -> InstallState:
    """Gather pipx, PyPI, macOS, and config state for onboarding."""
    package, commit = get_build_info()
    version_label = f"{package} ({commit})"
    command_path = running_command_path()
    pipx_app = pipx_bunnify_path()
    pipx_label = read_executable_build(pipx_app) if pipx_app is not None else None
    pypi_latest = pypi_latest_version()
    upgrade_available = _upgrade_available(package, pypi_latest)
    bookmarks = default_bookmarks_path()
    preferences = load_preferences()
    spotty_installed = False
    server_installed = False
    if sys.platform == "darwin":
        from app.server_agent import is_agent_installed as server_agent_installed
        from app.spotty_bunny_agent import is_agent_installed as spotty_agent_installed

        spotty_installed = spotty_agent_installed()
        server_installed = server_agent_installed()
    return InstallState(
        bookmarks_ready=bookmarks.is_file(),
        command_path=command_path,
        macos_extra=macos_extra_installed(),
        macos_platform=sys.platform == "darwin",
        pipx_app_path=str(pipx_app) if pipx_app is not None else None,
        pipx_version_label=pipx_label,
        preferences_ready=preferences is not None,
        pypi_latest=pypi_latest,
        server_agent_installed=server_installed,
        source_checkout=is_source_checkout(),
        spotty_agent_installed=spotty_installed,
        upgrade_available=upgrade_available,
        version_label=version_label,
    )


def format_onboarding_text(
    state: InstallState | None = None,
    *,
    read_executable_build: Callable[[Path], str | None] | None = None,
) -> str:
    """Return post-install / post-upgrade next steps for the terminal."""
    if state is None:
        reader = read_executable_build
        if reader is None:
            from app.cli import _read_executable_build as reader  # noqa: PLC0415

        state = detect_install_state(read_executable_build=reader)
    bookmarks = default_bookmarks_path()
    config = env_file_path()
    lines = ["Bunnify — next steps after install or upgrade", ""]
    lines.extend(_format_install_summary(state))
    lines.append("")
    step = 1
    if not state.bookmarks_ready:
        lines.extend(
            [
                f"{step}. Bookmarks (required before the server starts):",
                "     bunnify setup   # offers to install the example shortcuts",
                f"     # or create {bookmarks} yourself from bunnify.json.example",
                "",
            ]
        )
        step += 1
    if not state.preferences_ready:
        lines.extend(
            [
                f"{step}. Configure and start the server (local on a laptop;",
                "   remote for a home/always-on host):",
                "     bunnify setup",
                "   Guide: https://github.com/the-hcma/bunnify/blob/main/docs/LOCAL.md",
                "",
            ]
        )
        step += 1
    lines.extend(
        [
            f"{step}. Configure Chrome or Edge using BUNNIFY_BASE_URL from:",
            f"     {config}",
            "   Guide: https://github.com/the-hcma/bunnify/blob/main/CHROME_SETUP.md",
            "",
        ]
    )
    step += 1
    lines.extend(
        [
            f"{step}. Try it:  bunnify gh   (or address-bar keyword, e.g. b gh)",
            "",
        ]
    )
    if state.macos_platform:
        step += 1
        lines.extend(_format_spotty_bunny_section(state, step))
    lines.extend(
        [
            "Upgrade later (preferred):",
            "     bunnify upgrade   # shows from/to versions, then pipx upgrade",
            "   Bookmarks and config.env are kept across upgrades.",
            "   If --version still shows a checkout SHA, PATH is using",
            "   ./scripts/bunnify or a repo .venv — the pipx app lives in",
            "   ~/.local/bin/bunnify.",
            "",
            "Docs: https://github.com/the-hcma/bunnify",
            "Re-print this message anytime:  bunnify onboard",
        ]
    )
    return "\n".join(lines)


def run_onboard(
    *,
    confirm_yes: Callable[[Callable[[str], str], str], bool] | None = None,
    print_fn: Callable[[str], None] | None = None,
    prompt_fn: Callable[[str], str] | None = None,
    read_executable_build: Callable[[Path], str | None] | None = None,
    run_upgrade: Callable[..., None] | None = None,
    theme: Theme | None = None,
) -> None:
    """Print onboarding guidance; interactively upgrade and install macOS extras."""
    from app.cli import _command_banner, _read_executable_build  # noqa: PLC0415

    log = print_fn or print
    ask = prompt_fn or input
    colors = theme if theme is not None else Theme(enabled=False)
    reader = read_executable_build or _read_executable_build
    state = detect_install_state(read_executable_build=reader)
    yes = confirm_yes
    if yes is None:
        from app.cli import _confirm_explicit_yes as yes  # noqa: PLC0415

    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    log(colors.header(_command_banner("onboard")))
    for line in _format_install_summary(state):
        log(line)
    log("")

    if interactive and state.upgrade_available and state.pypi_latest is not None:
        if yes(
            ask,
            colors.brand(f"Upgrade pipx install to {state.pypi_latest} now? [y/N]: "),
        ):
            upgrade = run_upgrade
            if upgrade is None:
                from app.cli import run_upgrade as upgrade  # noqa: PLC0415

            try:
                upgrade(print_fn=log, theme=colors)
            except ClientError as exc:
                log(colors.err(f"error: {exc}"))
            else:
                state = detect_install_state(read_executable_build=reader)

    if interactive and state.macos_platform and not state.macos_extra:
        if yes(
            ask,
            colors.brand(
                "Install macOS dependencies for Spotty Bunny (PyObjC)? [y/N]: "
            ),
        ):
            pipx = shutil.which("pipx")
            if pipx is None:
                log(colors.warn("pipx not found on PATH; install PyObjC manually:"))
                log("  pipx install --force 'bunnify[macos]'")
            elif install_macos_extra(pipx):
                log(colors.ok("✓ Installed bunnify[macos] (PyObjC) via pipx"))
                state = detect_install_state(read_executable_build=reader)
            else:
                log(colors.warn("pipx install --force 'bunnify[macos]' failed."))

    if interactive and state.macos_platform and state.macos_extra:
        preferences = load_preferences()
        if preferences is not None and preferences.mode == "local":
            if not state.server_agent_installed or yes(
                ask,
                colors.brand(
                    "Install or refresh the local Bunnify server LaunchAgent? [y/N]: "
                ),
            ):
                from app.server_agent import install_agent as install_server_agent

                port = preferences.local_port or 8000
                code = install_server_agent(
                    port=port,
                    print_err=lambda message: log(message),
                )
                if code == 0:
                    log(colors.ok("✓ Local Bunnify server LaunchAgent is installed."))
                    state = detect_install_state(read_executable_build=reader)
                else:
                    log(
                        colors.warn(
                            "Server LaunchAgent install did not finish; "
                            "see messages above."
                        )
                    )
        if not _confirm_server_reachable_for_install(
            preferences,
            ask=ask,
            log=log,
            colors=colors,
            yes=yes,
        ):
            log(colors.warn("Skipping Spotty Bunny install (server not confirmed)."))
        else:
            prompt = (
                "Install or refresh Spotty Bunny (LaunchAgent + Control chord test)? "
                "[y/N]: "
            )
            if not state.spotty_agent_installed or yes(ask, colors.brand(prompt)):
                from app.spotty_bunny_agent import install_agent

                code = install_agent(
                    print_err=lambda message: log(message), prompt_fn=ask
                )
                if code == 0:
                    log(
                        colors.ok(
                            "✓ Spotty Bunny is installed and the Control chord works."
                        )
                    )
                    state = detect_install_state(read_executable_build=reader)
                else:
                    log(
                        colors.warn(
                            "Spotty Bunny install did not finish; see messages above."
                        )
                    )

    log("")
    log(format_onboarding_text(state))


def _confirm_server_reachable_for_install(
    preferences: object | None,
    *,
    ask: Callable[[str], str],
    log: Callable[[str], None],
    colors: Theme,
    yes: Callable[[Callable[[str], str], str], bool],
) -> bool:
    """Return True when healthy, or when the user confirms continuing anyway."""
    from app.client import check_health
    from app.config import ServerPreferences

    if preferences is None or not isinstance(preferences, ServerPreferences):
        return True
    base_url = preferences.base_url
    if not base_url:
        return True
    if check_health(base_url):
        return True
    kind = "Remote" if preferences.mode == "remote" else "Local"
    log(colors.warn(f"{kind} Bunnify at {base_url} is not reachable."))
    return yes(
        ask,
        colors.warn("Continue installing Spotty Bunny anyway? [y/N]: "),
    )


def _format_install_summary(state: InstallState) -> list[str]:
    lines = [f"Already installed: {state.version_label}", f"  {state.command_path}"]
    if state.pipx_app_path is not None:
        lines.append("pipx app:")
        if state.pipx_version_label is not None:
            lines.append(f"  {state.pipx_version_label}")
        lines.append(f"  {state.pipx_app_path}")
    elif not state.source_checkout:
        lines.append("pipx app: not found (~/.local/bin/bunnify)")
    if state.source_checkout:
        lines.append(
            "Note: this process is a git checkout; `bunnify upgrade` updates the "
            "pipx app, not this tree."
        )
    if state.pypi_latest is not None:
        if state.upgrade_available:
            lines.append(f"PyPI latest: {state.pypi_latest} (upgrade available)")
        else:
            lines.append(f"PyPI latest: {state.pypi_latest} (up to date)")
    if state.macos_platform:
        extra = "installed" if state.macos_extra else "not installed"
        lines.append(f"macOS Spotty Bunny dependencies (PyObjC): {extra}")
        if state.server_agent_installed:
            lines.append("Bunnify server LaunchAgent: installed")
        else:
            lines.append("Bunnify server LaunchAgent: not installed")
        if state.spotty_agent_installed:
            lines.append("Spotty Bunny LaunchAgent: installed")
        else:
            lines.append("Spotty Bunny LaunchAgent: not installed")
    return lines


def _format_spotty_bunny_section(state: InstallState, step: int) -> list[str]:
    if state.macos_extra and state.spotty_agent_installed:
        return [
            f"{step}. macOS Spotty Bunny (optional search box): installed",
            "     bunnify spotty-bunny status",
            "     bunnify upgrade && bunnify spotty-bunny upgrade",
            "     bunnify spotty-bunny uninstall",
            "   Guide: https://github.com/the-hcma/bunnify/blob/main/docs/LOCAL.md",
            "",
        ]
    if state.macos_extra:
        return [
            f"{step}. macOS Spotty Bunny (optional search box):",
            "     bunnify spotty-bunny install    # LaunchAgent + chord test",
            "     bunnify spotty-bunny status",
            "   Guide: https://github.com/the-hcma/bunnify/blob/main/docs/LOCAL.md",
            "",
        ]
    return [
        f"{step}. macOS Spotty Bunny (optional search box):",
        "     bunnify onboard                 # offers macOS deps + install",
        "     pipx install --force 'bunnify[macos]'",
        "     bunnify spotty-bunny install",
        "   Guide: https://github.com/the-hcma/bunnify/blob/main/docs/LOCAL.md",
        "",
    ]


def _upgrade_available(package: str, pypi_latest: str | None) -> bool:
    if pypi_latest is None:
        return False
    try:
        return Version(package) < Version(pypi_latest)
    except InvalidVersion:
        return False

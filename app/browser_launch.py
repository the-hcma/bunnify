"""Launch a URL in a specific Edge/Chrome profile (macOS and Windows).

Only used when a shortcut carries a ``browser`` block; shortcuts without one
keep opening through ``webbrowser.open`` (default browser, default profile).
There is deliberately no fallback: if the requested browser or profile cannot
be found, :class:`BrowserLaunchError` is raised and nothing is opened.
"""

from __future__ import annotations

import errno
import json
import os
import plistlib
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from xml.parsers.expat import ExpatError

from app.browser_spec import BROWSER_APPS, BrowserSpec
from app.client import ClientError
from app.config import current_host

LAUNCH_TIMEOUT_SECONDS = 10.0

_MAC_APP_NAMES = {"edge": "Microsoft Edge", "chrome": "Google Chrome"}
_MAC_BUNDLE_IDS = {
    "com.microsoft.edgemac": "edge",
    "com.google.chrome": "chrome",
}
_MAC_USER_DATA = {
    "edge": Path("Library/Application Support/Microsoft Edge"),
    "chrome": Path("Library/Application Support/Google/Chrome"),
}
_WIN_EXECUTABLES = {"edge": "msedge.exe", "chrome": "chrome.exe"}
_WIN_USER_DATA = {
    "edge": Path("Microsoft") / "Edge" / "User Data",
    "chrome": Path("Google") / "Chrome" / "User Data",
}
_WIN_PROG_ID_PREFIXES = (("MSEdgeHTM", "edge"), ("ChromeHTML", "chrome"))
_DISPLAY_NAMES = {"edge": "Edge", "chrome": "Chrome"}

_WIN_DETACHED_PROCESS = 0x00000008
_WIN_CREATE_NEW_PROCESS_GROUP = 0x00000200


class BrowserLaunchError(ClientError):
    """The requested browser/profile cannot be used; nothing was opened."""


class BrowserProfilesAccessError(BrowserLaunchError):
    """The OS denied reading the browser's profile list (macOS privacy)."""


class BrowserProfileNotFoundError(BrowserLaunchError):
    """A shortcut names a profile that does not exist on this machine.

    Usually the shortcut was set up on another machine (a work laptop, say)
    that shares the same bookmarks, so nothing is opened and the message says
    so instead of just failing.
    """


class BrowserProfilesMissingError(BrowserLaunchError):
    """The browser has no ``Local State`` yet (never run, or not installed)."""


@dataclass(frozen=True)
class ProfileInfo:
    """One browser profile as listed in the browser's ``Local State``."""

    directory: str
    name: str
    account: str | None = None


@dataclass(frozen=True)
class LaunchPlan:
    """A validated, ready-to-run browser launch."""

    app: str
    profile_name: str | None
    profile_dir: str | None
    argv: tuple[str, ...]

    def describe(self) -> str:
        """One-line human description (``Edge, profile "Work"``)."""
        text = _DISPLAY_NAMES[self.app]
        if self.profile_name:
            text += f', profile "{self.profile_name}"'
        return text


FindAppFn = Callable[[str], str | None]
DefaultBrowserFn = Callable[[], str | None]
RunFn = Callable[[tuple[str, ...]], int]


def browser_from_identifier(identifier: str | None) -> str | None:
    """Map a macOS bundle id or Windows ProgId to ``edge``/``chrome``."""
    if not identifier:
        return None
    mac = _MAC_BUNDLE_IDS.get(identifier.lower())
    if mac:
        return mac
    for prefix, app in _WIN_PROG_ID_PREFIXES:
        if identifier.startswith(prefix):
            return app
    return None


def _mac_launch_services_plist(home: Path) -> Path:
    return (
        home
        / "Library"
        / "Preferences"
        / "com.apple.LaunchServices"
        / "com.apple.launchservices.secure.plist"
    )


def detect_default_browser_id(
    *, platform: str | None = None, home: Path | None = None
) -> str | None:
    """Return the raw default-browser identifier for ``https`` links, if known."""
    platform = platform or sys.platform
    if platform == "darwin":
        path = _mac_launch_services_plist(home or Path.home())
        try:
            with path.open("rb") as handle:
                data = plistlib.load(handle)
        except OSError, plistlib.InvalidFileException, ValueError, ExpatError:
            return None
        handlers = data.get("LSHandlers") if isinstance(data, dict) else None
        if not isinstance(handlers, list):
            return None
        for handler in handlers:
            if not isinstance(handler, dict):
                continue
            if str(handler.get("LSHandlerURLScheme", "")).lower() != "https":
                continue
            role = handler.get("LSHandlerRoleAll") or handler.get("LSHandlerRoleViewer")
            return role if isinstance(role, str) else None
        return None
    if platform == "win32":
        try:
            import winreg

            key_path = (
                r"Software\Microsoft\Windows\Shell\Associations"
                r"\UrlAssociations\https\UserChoice"
            )
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                value, _kind = winreg.QueryValueEx(key, "ProgId")
        except ImportError, OSError:
            return None
        return value if isinstance(value, str) else None
    return None


def find_installed_app(
    app: str,
    *,
    platform: str | None = None,
    home: Path | None = None,
    system_apps: Path = Path("/Applications"),
) -> str | None:
    """Return the macOS app bundle path / Windows executable path, or ``None``."""
    platform = platform or sys.platform
    if platform == "darwin":
        bundle = f"{_MAC_APP_NAMES[app]}.app"
        for root in (system_apps, (home or Path.home()) / "Applications"):
            candidate = root / bundle
            if candidate.is_dir():
                return str(candidate)
        return None
    if platform == "win32":
        exe = _WIN_EXECUTABLES[app]
        try:
            import winreg

            key_path = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}"
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(hive, key_path) as key:
                        value, _kind = winreg.QueryValueEx(key, "")
                except OSError:
                    continue
                if isinstance(value, str) and Path(value).is_file():
                    return value
        except ImportError:
            return None
        return None
    return None


def user_data_dir(
    app: str,
    *,
    platform: str | None = None,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Path | None:
    """Return the browser's user-data directory (holds ``Local State``)."""
    platform = platform or sys.platform
    if platform == "darwin":
        return (home or Path.home()) / _MAC_USER_DATA[app]
    if platform == "win32":
        env = env if env is not None else os.environ
        local = env.get("LOCALAPPDATA")
        if not local:
            return None
        return Path(local) / _WIN_USER_DATA[app]
    return None


def _is_profile_dir_name(name: object) -> bool:
    """True for a plain single-component directory name (no paths, drives, ``..``)."""
    return (
        isinstance(name, str)
        and name not in ("", ".", "..")
        and "/" not in name
        and ":" not in name  # drive-relative (D:Profile 1) / NTFS stream names
        and "\\" not in name
        and "\x00" not in name
    )


def macos_profile_access_hint(executable: str | None = None) -> str:
    """How to grant macOS access to the browser's profile list.

    TCC attributes the read to the process that started this one: the
    terminal app for a command run from a terminal, or the executable launchd
    started (the real ``python`` behind a venv, not the ``Python.app`` it hands
    off to) for Spotty Bunny. The hint names both so neither path is misled.
    """
    exe = os.path.realpath(executable or sys.executable)
    return (
        "macOS blocked access to the browser's profile data. Under System "
        "Settings → Privacy & Security → Full Disk Access, add the app that "
        "started this: your terminal app when you ran it from a terminal, or, "
        f"for Spotty Bunny (launchd), this executable: {exe} "
        "(run `spotty-bunny doctor` for steps). Then restart the process"
    )


def list_profile_details(user_data: Path) -> list[ProfileInfo]:
    """List profiles (directory, display name, account) from ``Local State``.

    Entries whose directory is missing on disk are stale cache and ignored, so
    a pin to one is an error rather than a silently created fresh profile.
    Malformed state raises :class:`BrowserLaunchError`; a macOS privacy denial
    raises :class:`BrowserProfilesAccessError` with the fix.
    """
    state_path = user_data / "Local State"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except PermissionError as exc:
        detail = f"Cannot read browser profiles from {state_path}: {exc}"
        if exc.errno != errno.EPERM:
            # EACCES is an ordinary file-mode problem; Full Disk Access would
            # not fix it, so do not send the user there.
            raise BrowserLaunchError(detail) from exc
        if sys.platform == "darwin":
            detail += f". {macos_profile_access_hint()}"
        raise BrowserProfilesAccessError(detail) from exc
    except FileNotFoundError as exc:
        raise BrowserProfilesMissingError(
            f"Cannot read browser profiles from {state_path}: {exc}"
        ) from exc
    except (OSError, ValueError) as exc:
        raise BrowserLaunchError(
            f"Cannot read browser profiles from {state_path}: {exc}"
        ) from exc
    section = state.get("profile") if isinstance(state, dict) else None
    cache = section.get("info_cache") if isinstance(section, dict) else None
    if not isinstance(cache, dict):
        raise BrowserLaunchError(
            f"Unexpected profile data in {state_path}: no profile.info_cache"
        )
    profiles: list[ProfileInfo] = []
    for directory, info in cache.items():
        name = info.get("name") if isinstance(info, dict) else None
        if (
            isinstance(name, str)
            and _is_profile_dir_name(directory)
            and (user_data / directory).is_dir()
        ):
            account = info.get("user_name") if isinstance(info, dict) else None
            profiles.append(
                ProfileInfo(
                    directory=directory,
                    name=name,
                    account=account if isinstance(account, str) and account else None,
                )
            )
    return profiles


def list_profiles(user_data: Path) -> dict[str, str]:
    """Map profile directory name to display name from ``Local State``."""
    return {info.directory: info.name for info in list_profile_details(user_data)}


def installed_browser_profiles(
    *,
    platform: str | None = None,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
    find_app: FindAppFn | None = None,
    on_error: Callable[[BrowserLaunchError], None] | None = None,
) -> dict[str, list[ProfileInfo]]:
    """Profiles of every installed Edge/Chrome, keyed by ``edge``/``chrome``.

    A browser that is not installed or has never been run (no ``Local State``)
    is omitted. A browser whose state is malformed or denied is skipped while
    another yields profiles, and its error is passed to ``on_error`` so the
    caller can still tell the user (for example the Full Disk Access fix);
    when no browser yields profiles, the first error propagates as
    :class:`BrowserLaunchError`.
    """
    platform = platform or sys.platform
    locate = find_app or (
        lambda name: find_installed_app(name, platform=platform, home=home)
    )
    found: dict[str, list[ProfileInfo]] = {}
    errors: list[BrowserLaunchError] = []
    for app in BROWSER_APPS:
        if locate(app) is None:
            continue
        data_dir = user_data_dir(app, platform=platform, home=home, env=env)
        if data_dir is None:
            continue
        try:
            # Read, don't stat: a macOS privacy denial must surface as an
            # access error, not look like "no profiles".
            profiles = list_profile_details(data_dir)
        except BrowserProfilesMissingError:
            continue
        except BrowserLaunchError as exc:
            # One broken browser must not hide a working one.
            errors.append(exc)
            continue
        if profiles:
            found[app] = profiles
    if errors and not found:
        raise errors[0]
    if on_error is not None:
        for error in errors:
            on_error(error)
    return found


def display_name(app: str) -> str:
    """``Edge`` / ``Chrome`` for a browser key."""
    return _DISPLAY_NAMES[app]


def resolve_profile_dir(app: str, profile: str, profiles: Mapping[str, str]) -> str:
    """Return the directory of the profile named exactly ``profile``."""
    matches = sorted(d for d, name in profiles.items() if name == profile)
    if len(matches) == 1:
        return matches[0]
    label = _DISPLAY_NAMES[app]
    if len(matches) > 1:
        raise BrowserLaunchError(
            f'{label} has {len(matches)} profiles named "{profile}" '
            f"({', '.join(matches)}); rename one so the shortcut is unambiguous"
        )
    available = ", ".join(f'"{n}"' for n in sorted(profiles.values())) or "none"
    raise BrowserProfileNotFoundError(
        f'{label} has no profile named "{profile}" on this machine ({current_host()}). '
        "This shortcut was probably set up for a different machine (for example a "
        "work laptop), so nothing was opened. "
        f"Profiles here: {available}. To use it here, create or rename a profile "
        "with that exact name, or point the shortcut at one of these."
    )


def plan_launch(
    url: str,
    spec: BrowserSpec,
    *,
    platform: str | None = None,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
    find_app: FindAppFn | None = None,
    default_browser: DefaultBrowserFn | None = None,
) -> LaunchPlan:
    """Validate ``spec`` against this machine and build the launch command.

    Raises :class:`BrowserLaunchError` for every unsatisfiable request.
    """
    platform = platform or sys.platform
    if platform not in ("darwin", "win32"):
        raise BrowserLaunchError(
            "Per-shortcut browser selection is supported on macOS and Windows only"
        )
    app = spec.app
    if app is None:
        detect = default_browser or (
            lambda: detect_default_browser_id(platform=platform, home=home)
        )
        identifier = detect()
        app = browser_from_identifier(identifier)
        if app is None:
            raise BrowserLaunchError(
                f'Profile "{spec.profile}" needs the default browser to be Edge '
                f"or Chrome, but it is {identifier or 'unknown'}; set "
                '"app" on the shortcut to choose a browser explicitly'
            )
    locate = find_app or (
        lambda name: find_installed_app(name, platform=platform, home=home)
    )
    app_path = locate(app)
    if app_path is None:
        raise BrowserLaunchError(f"{_DISPLAY_NAMES[app]} is not installed")

    profile_dir: str | None = None
    if spec.profile is not None:
        data_dir = user_data_dir(app, platform=platform, home=home, env=env)
        if data_dir is None:
            raise BrowserLaunchError(
                f"Cannot locate {_DISPLAY_NAMES[app]} profile data on this machine"
            )
        profile_dir = resolve_profile_dir(app, spec.profile, list_profiles(data_dir))

    if platform == "darwin":
        argv: list[str] = ["open"]
        if profile_dir is None:
            argv += ["-a", app_path, url]
        else:
            argv += [
                "-na",
                app_path,
                "--args",
                f"--profile-directory={profile_dir}",
                url,
            ]
    else:
        argv = [app_path]
        if profile_dir is not None:
            argv.append(f"--profile-directory={profile_dir}")
        argv.append(url)
    return LaunchPlan(
        app=app,
        profile_name=spec.profile,
        profile_dir=profile_dir,
        argv=tuple(argv),
    )


def _default_run(argv: tuple[str, ...]) -> int:
    if sys.platform == "win32":
        subprocess.Popen(
            argv,
            close_fds=True,
            creationflags=_WIN_DETACHED_PROCESS | _WIN_CREATE_NEW_PROCESS_GROUP,
        )
        return 0
    completed = subprocess.run(
        argv, check=False, timeout=LAUNCH_TIMEOUT_SECONDS, capture_output=True
    )
    return completed.returncode


def launch(plan: LaunchPlan, *, run: RunFn | None = None) -> None:
    """Run a validated plan; raises :class:`BrowserLaunchError` on failure."""
    runner = run or _default_run
    try:
        code = runner(plan.argv)
    except (OSError, subprocess.SubprocessError) as exc:
        raise BrowserLaunchError(f"Failed to launch {plan.describe()}: {exc}") from exc
    if code != 0:
        raise BrowserLaunchError(f"Failed to launch {plan.describe()} (exit {code})")

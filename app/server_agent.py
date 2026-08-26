"""Bunnify server macOS LaunchAgent (install, uninstall, status, upgrade)."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from app.client import check_health
from app.config import run_dir
from app.local_server import stop_local_server
from app.version import build_version

AGENT_COMMANDS = frozenset({"install", "status", "uninstall", "upgrade"})
AGENT_LABEL = "com.thehcma.bunnify"
AGENT_PLIST_NAME = f"{AGENT_LABEL}.plist"
COMMAND_NAME = "bunnify-server"
DEFAULT_PORT = 8000
HEALTH_TIMEOUT_S = 60.0
LAUNCHCTL_TIMEOUT_S = 10
NOT_MACOS_MESSAGE = f"{COMMAND_NAME}: this command is only available on macOS."
UNKNOWN_COMMAND_MESSAGE = (
    f"{COMMAND_NAME}: unknown command '{{command}}'. "
    "Use install, uninstall, status, or upgrade; "
    "or run without a subcommand to start the managed server."
)

LaunchctlFn = Callable[..., subprocess.CompletedProcess[str]]


def agent_plist_path(*, home: Path | None = None) -> Path:
    """Installed LaunchAgent path under *home*."""
    root = home if home is not None else Path.home()
    return root / "Library" / "LaunchAgents" / AGENT_PLIST_NAME


def bootout_loaded_agent(
    *,
    launchctl: LaunchctlFn | None = None,
    uid: int | None = None,
) -> bool:
    """Unload the LaunchAgent when loaded so KeepAlive cannot respawn.

    Returns True when a bootout was issued.
    """
    if not is_agent_loaded(launchctl=launchctl, uid=uid):
        return False
    _bootout_agent(launchctl=launchctl, uid=uid)
    return True


def format_agent_plist(*, home: Path, program_arguments: Sequence[str]) -> str:
    """Return the LaunchAgent plist for *program_arguments* and *home*."""
    args_xml = "\n".join(
        f"    <string>{escape(arg)}</string>" for arg in program_arguments
    )
    return _PLIST_TEMPLATE.replace("__PROGRAM_ARGUMENTS__", args_xml).replace(
        "__HOME__", escape(str(home))
    )


def install_agent(
    *,
    bookmarks: Path | None = None,
    home: Path | None = None,
    launchctl: LaunchctlFn | None = None,
    pid_dir: Path | None = None,
    platform: str | None = None,
    port: int = DEFAULT_PORT,
    print_err: Callable[[str], None] | None = None,
    program: Path | Sequence[str] | None = None,
    timeout_s: float = HEALTH_TIMEOUT_S,
) -> int:
    """Write the LaunchAgent, bootstrap it, and wait until /health succeeds."""
    err = print_err or _print_err
    if not _is_darwin(platform):
        err(NOT_MACOS_MESSAGE)
        return 1
    if not 1 <= port <= 65535:
        err(f"{COMMAND_NAME}: port must be between 1 and 65535")
        return 1
    program_argv = _resolve_program_arguments(program)
    if program_argv is None:
        err(f"{COMMAND_NAME}: could not find the bunnify-server binary on PATH.")
        return 1
    launch_binary = Path(program_argv[0])
    if not _program_launch_target_ok(launch_binary):
        err(
            f"{COMMAND_NAME}: binary missing or not executable: "
            f"{launch_binary.expanduser()}"
        )
        return 1
    root = home if home is not None else Path.home()
    agent_pid_dir = pid_dir if pid_dir is not None else launchd_pid_dir()
    agent_pid_dir.mkdir(parents=True, exist_ok=True)
    argv = [
        *program_argv,
        "--foreground",
        "--noninteractive",
        "--port",
        str(port),
        "--pid-dir",
        str(agent_pid_dir),
    ]
    if bookmarks is not None:
        argv.extend(["--bookmarks", str(bookmarks.expanduser().resolve())])
    # Stop a non-launchd managed server that may still hold the port.
    try:
        stop_local_server(run_dir(), port=port, port_timeout_s=5)
    except OSError, RuntimeError, ValueError:
        pass
    plist = agent_plist_path(home=root)
    _write_plist(plist, home=root, program_arguments=argv)
    if not _reload_agent(plist, launchctl=launchctl, pid_dir=agent_pid_dir):
        _rollback_failed_install(
            plist, launchctl=launchctl, pid_dir=agent_pid_dir, port=port
        )
        err(f"{COMMAND_NAME}: launchctl bootstrap failed for {plist}.")
        return 1
    base_url = f"http://127.0.0.1:{port}"
    if not _wait_for_health(base_url, timeout_s=timeout_s):
        _rollback_failed_install(
            plist, launchctl=launchctl, pid_dir=agent_pid_dir, port=port
        )
        err(f"{COMMAND_NAME}: server at {base_url} did not become healthy.")
        return 1
    err(f"{COMMAND_NAME}: installed LaunchAgent {AGENT_LABEL}")
    err(f"{COMMAND_NAME}: plist {plist}")
    err(f"{COMMAND_NAME}: listening at {base_url}")
    return 0


def is_agent_installed(*, home: Path | None = None) -> bool:
    """True when the LaunchAgent plist is present under *home*."""
    return agent_plist_path(home=home).is_file()


def is_agent_loaded(
    *,
    launchctl: LaunchctlFn | None = None,
    uid: int | None = None,
) -> bool:
    """True when launchd has the server agent in the gui domain."""
    completed = _launchctl(
        ["print", f"{_gui_domain(uid)}/{AGENT_LABEL}"],
        launchctl=launchctl,
    )
    return completed.returncode == 0


def launchd_pid_dir(*, environ: dict[str, str] | None = None) -> Path:
    """PID/port directory used by the LaunchAgent-managed server."""
    return run_dir(environ=environ) / "launchd"


def run_agent_command(
    command: str,
    rest: Sequence[str] = (),
    **kwargs: object,
) -> int:
    """Dispatch a LaunchAgent subcommand."""
    if command == "install":
        try:
            options = _parse_install_args(rest)
        except ValueError as exc:
            print(f"{COMMAND_NAME} install: {exc}", file=sys.stderr)
            return 2
        return install_agent(
            bookmarks=options.bookmarks,
            port=options.port,
            **kwargs,
        )
    if rest:
        print(
            f"{COMMAND_NAME} {command}: unexpected arguments.",
            file=sys.stderr,
        )
        return 2
    if command == "status":
        return status_agent(**kwargs)
    if command == "uninstall":
        return uninstall_agent(**kwargs)
    if command == "upgrade":
        return upgrade_agent(**kwargs)
    print(UNKNOWN_COMMAND_MESSAGE.format(command=command), file=sys.stderr)
    return 2


def server_program() -> Path | None:
    """Primary executable path for status display (first ProgramArguments entry)."""
    argv = server_program_arguments()
    if not argv:
        return None
    return Path(argv[0])


def server_program_arguments() -> list[str] | None:
    """Absolute argv launchd should use as the program prefix."""
    found = shutil.which(COMMAND_NAME)
    if found:
        return [found]
    module = Path(sys.executable).resolve()
    if module.is_file() and os.access(module, os.X_OK):
        return [str(module), "-m", "app.server_cli"]
    return None


def status_agent(
    *,
    home: Path | None = None,
    launchctl: LaunchctlFn | None = None,
    platform: str | None = None,
    print_err: Callable[[str], None] | None = None,
    print_fn: Callable[[str], None] | None = None,
    program: Path | Sequence[str] | None = None,
) -> int:
    """Print agent and health state. Exit 0 when installed, loaded, and healthy."""
    err = print_err or _print_err
    out = print_fn or print
    if not _is_darwin(platform):
        err(NOT_MACOS_MESSAGE)
        return 1
    root = home if home is not None else Path.home()
    plist = agent_plist_path(home=root)
    installed = plist.is_file()
    loaded = is_agent_loaded(launchctl=launchctl) if installed else False
    plist_argv = _plist_program_arguments(plist) if installed else None
    if program is not None:
        binary = Path(program[0] if isinstance(program, Sequence) else program)
    elif plist_argv:
        binary = Path(plist_argv[0])
    else:
        binary = server_program()
    binary_ok = binary is not None and _program_launch_target_ok(Path(binary))
    port = _port_from_argv(plist_argv) if plist_argv else None
    base_url = f"http://127.0.0.1:{port}" if port else None
    healthy = bool(base_url and check_health(base_url))
    stdout_path, stderr_path = _launchd_log_paths(plist)
    out(f"healthy: {'yes' if healthy else 'no'}")
    if base_url is None:
        out("url: none")
    else:
        out(f"url: {base_url}")
    if not installed:
        out("launchd: not installed")
    else:
        out(f"launchd: {'loaded' if loaded else 'not loaded'}")
    if binary is None:
        out("binary: none")
    elif binary_ok:
        out(f"binary: {binary}")
    else:
        out(f"binary: {binary} (missing or not executable)")
    out(f"launchd_stdout: {stdout_path or 'none'}")
    out(f"launchd_stderr: {stderr_path or 'none'}")
    out(f"version: {build_version()}")
    ok = installed and loaded and binary_ok and healthy
    return 0 if ok else 1


def uninstall_agent(
    *,
    home: Path | None = None,
    launchctl: LaunchctlFn | None = None,
    pid_dir: Path | None = None,
    platform: str | None = None,
    print_err: Callable[[str], None] | None = None,
) -> int:
    """Remove the plist, boot out, and stop the launchd-managed server."""
    err = print_err or _print_err
    if not _is_darwin(platform):
        err(NOT_MACOS_MESSAGE)
        return 1
    root = home if home is not None else Path.home()
    plist = agent_plist_path(home=root)
    agent_pid_dir = pid_dir if pid_dir is not None else launchd_pid_dir()
    port = None
    if plist.is_file():
        port = _port_from_argv(_plist_program_arguments(plist))
    loaded = is_agent_loaded(launchctl=launchctl)
    plist.unlink(missing_ok=True)
    if loaded:
        _bootout_agent(launchctl=launchctl)
    try:
        stop_local_server(agent_pid_dir, port=port, port_timeout_s=5)
    except OSError, RuntimeError, ValueError:
        pass
    err(f"{COMMAND_NAME}: uninstalled LaunchAgent {AGENT_LABEL}")
    return 0


def upgrade_agent(
    *,
    bookmarks: Path | None = None,
    home: Path | None = None,
    launchctl: LaunchctlFn | None = None,
    pid_dir: Path | None = None,
    platform: str | None = None,
    port: int | None = None,
    print_err: Callable[[str], None] | None = None,
    program: Path | Sequence[str] | None = None,
    timeout_s: float = HEALTH_TIMEOUT_S,
) -> int:
    """Rewrite the plist for the current binary and bounce launchd."""
    err = print_err or _print_err
    if not _is_darwin(platform):
        err(NOT_MACOS_MESSAGE)
        return 1
    root = home if home is not None else Path.home()
    plist = agent_plist_path(home=root)
    if not plist.is_file():
        err(
            f"{COMMAND_NAME}: LaunchAgent is not installed. Run: {COMMAND_NAME} install"
        )
        return 1
    chosen_port = port
    if chosen_port is None:
        chosen_port = _port_from_argv(_plist_program_arguments(plist))
    if chosen_port is None:
        chosen_port = DEFAULT_PORT
    return install_agent(
        bookmarks=bookmarks,
        home=root,
        launchctl=launchctl,
        pid_dir=pid_dir,
        platform=platform,
        port=chosen_port,
        print_err=err,
        program=program,
        timeout_s=timeout_s,
    )


@dataclass(frozen=True)
class _InstallOptions:
    bookmarks: Path | None
    port: int


def _bootstrap_agent(
    plist: Path, *, launchctl: LaunchctlFn | None = None, uid: int | None = None
) -> bool:
    completed = _launchctl(
        ["bootstrap", _gui_domain(uid), str(plist)],
        launchctl=launchctl,
    )
    return completed.returncode == 0


def _bootout_agent(
    *, launchctl: LaunchctlFn | None = None, uid: int | None = None
) -> None:
    _launchctl(
        ["bootout", f"{_gui_domain(uid)}/{AGENT_LABEL}"],
        launchctl=launchctl,
    )


def _gui_domain(uid: int | None = None) -> str:
    return f"gui/{os.getuid() if uid is None else uid}"


def _is_darwin(platform: str | None) -> bool:
    return (sys.platform if platform is None else platform) == "darwin"


def _launchctl(
    args: Sequence[str],
    *,
    launchctl: LaunchctlFn | None = None,
) -> subprocess.CompletedProcess[str]:
    argv = ["launchctl", *args]
    runner = launchctl or subprocess.run
    try:
        return runner(
            argv,
            capture_output=True,
            check=False,
            text=True,
            timeout=LAUNCHCTL_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(argv, 1, "", str(exc))


def _launchd_log_paths(plist: Path) -> tuple[str | None, str | None]:
    if not plist.is_file():
        return None, None
    try:
        text = plist.read_text(encoding="utf-8")
    except OSError:
        return None, None
    return (
        _plist_string(text, "StandardOutPath"),
        _plist_string(text, "StandardErrorPath"),
    )


def _parse_install_args(rest: Sequence[str]) -> _InstallOptions:
    parser = argparse.ArgumentParser(prog=f"{COMMAND_NAME} install", add_help=True)
    parser.add_argument(
        "-f",
        "--bookmarks",
        type=Path,
        default=None,
        help="Bookmarks JSON file passed to the LaunchAgent.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"TCP port for the LaunchAgent server (default: {DEFAULT_PORT}).",
    )
    try:
        namespace = parser.parse_args(list(rest))
    except SystemExit as exc:
        code = 0 if exc.code is None else int(exc.code)
        if code == 0:
            raise
        raise ValueError("invalid arguments") from None
    if not 1 <= namespace.port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    return _InstallOptions(bookmarks=namespace.bookmarks, port=namespace.port)


def _plist_program_arguments(plist: Path) -> list[str] | None:
    if not plist.is_file():
        return None
    try:
        text = plist.read_text(encoding="utf-8")
    except OSError:
        return None
    marker = "<key>ProgramArguments</key>"
    start = text.find(marker)
    if start < 0:
        return None
    chunk = text[start:]
    array_start = chunk.find("<array>")
    array_end = chunk.find("</array>")
    if array_start < 0 or array_end < 0 or array_end <= array_start:
        return None
    body = chunk[array_start + len("<array>") : array_end]
    args: list[str] = []
    while True:
        open_tag = body.find("<string>")
        if open_tag < 0:
            break
        close_tag = body.find("</string>", open_tag)
        if close_tag < 0:
            break
        args.append(body[open_tag + len("<string>") : close_tag])
        body = body[close_tag + len("</string>") :]
    return args or None


def _plist_string(text: str, key: str) -> str | None:
    marker = f"<key>{key}</key>"
    start = text.find(marker)
    if start < 0:
        return None
    chunk = text[start:]
    open_tag = chunk.find("<string>")
    close_tag = chunk.find("</string>")
    if open_tag < 0 or close_tag < 0 or close_tag <= open_tag:
        return None
    return chunk[open_tag + len("<string>") : close_tag]


def _port_from_argv(argv: Sequence[str] | None) -> int | None:
    if not argv:
        return None
    for index, part in enumerate(argv):
        if part == "--port" and index + 1 < len(argv):
            try:
                port = int(argv[index + 1])
            except ValueError:
                return None
            if 1 <= port <= 65535:
                return port
            return None
    return None


def _print_err(message: str) -> None:
    print(message, file=sys.stderr)


def _program_launch_target_ok(path: Path) -> bool:
    try:
        resolved = path.expanduser().resolve(strict=False)
    except OSError:
        return False
    return resolved.is_file() and os.access(resolved, os.X_OK)


def _reload_agent(
    plist: Path,
    *,
    launchctl: LaunchctlFn | None = None,
    pid_dir: Path | None = None,
) -> bool:
    """Boot out, stop a stale managed server, and bootstrap the LaunchAgent."""
    _bootout_agent(launchctl=launchctl)
    if pid_dir is not None:
        try:
            stop_local_server(pid_dir, port_timeout_s=5)
        except OSError, RuntimeError, ValueError:
            pass
    if _bootstrap_agent(plist, launchctl=launchctl):
        return True
    _bootout_agent(launchctl=launchctl)
    return _bootstrap_agent(plist, launchctl=launchctl)


def _resolve_program_arguments(
    program: Path | Sequence[str] | None,
) -> list[str] | None:
    if program is None:
        return server_program_arguments()
    if isinstance(program, (str, Path)):
        return [str(Path(program).expanduser().resolve())]
    return [str(part) for part in program]


def _rollback_failed_install(
    plist: Path,
    *,
    launchctl: LaunchctlFn | None,
    pid_dir: Path,
    port: int,
) -> None:
    """Boot out and remove a plist that never became healthy."""
    _bootout_agent(launchctl=launchctl)
    plist.unlink(missing_ok=True)
    try:
        stop_local_server(pid_dir, port=port, port_timeout_s=5)
    except OSError, RuntimeError, ValueError:
        pass


def _wait_for_health(base_url: str, *, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if check_health(base_url):
            return True
        time.sleep(0.1)
    return check_health(base_url)


def _write_plist(plist: Path, *, home: Path, program_arguments: Sequence[str]) -> None:
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_text(
        format_agent_plist(home=home, program_arguments=program_arguments),
        encoding="utf-8",
    )


_PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.thehcma.bunnify</string>

  <key>ProgramArguments</key>
  <array>
__PROGRAM_ARGUMENTS__
  </array>

  <key>KeepAlive</key>
  <true/>
  <key>RunAtLoad</key>
  <true/>

  <key>StandardErrorPath</key>
  <string>__HOME__/Library/Logs/bunnify.err.log</string>
  <key>StandardOutPath</key>
  <string>__HOME__/Library/Logs/bunnify.out.log</string>
</dict>
</plist>
"""

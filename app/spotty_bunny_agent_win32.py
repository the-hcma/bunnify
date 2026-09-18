"""Spotty Bunny Windows autostart (install, uninstall, status, upgrade).

Windows sibling of ``app/spotty_bunny_agent.py``, backed by a Scheduled
Task (``app.spotty_bunny_task_win32``) instead of a LaunchAgent. There is
no TCC equivalent on Windows, so the biggest simplification versus macOS
is that this module has no permission-probe/prompt flow at all -- install/
upgrade only ever fail on the Scheduled Task itself or the overlay not
coming up.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from app.spotty_bunny_agent import (
    AGENT_COMMANDS,
    UNKNOWN_COMMAND_MESSAGE,
    _program_launch_target_ok,
    hotkey_command,
    spotty_bunny_program,
    spotty_bunny_program_arguments,
)
from app.spotty_bunny_cli import COMMAND_NAME, _spotty_bunny_log_file
from app.spotty_bunny_launch import (
    clear_spotty_bunny_pid,
    spotty_bunny_is_running,
    stop_spotty_bunny,
)
from app.spotty_bunny_tap_health import (
    TAP_STATE_OK,
    format_activity_timestamp,
    read_spotty_bunny_health,
)
from app.spotty_bunny_task_win32 import (
    TASK_NAME,
    SchtasksFn,
    create_or_update_task,
    format_task_xml,
    is_task_installed,
    is_task_running,
    remove_task,
    run_task_once,
    task_program_arguments,
    task_xml,
)
from app.version import build_version

__all__ = [
    "AGENT_COMMANDS",
    "UNKNOWN_COMMAND_MESSAGE",
    "install_agent",
    "is_agent_installed",
    "run_win32_agent_command",
    "status_agent",
    "uninstall_agent",
    "upgrade_agent",
]

INSTALL_WAIT_TIMEOUT_S = 15.0
NOT_WINDOWS_MESSAGE = f"{COMMAND_NAME}: this command is only available on Windows."
ROLLBACK_WAIT_TIMEOUT_S = 15.0


def install_agent(
    *,
    pid_dir: Path | None = None,
    platform: str | None = None,
    print_err: Callable[[str], None] | None = None,
    program: Path | None = None,
    schtasks: SchtasksFn | None = None,
    timeout_s: float = INSTALL_WAIT_TIMEOUT_S,
) -> int:
    """Register the Scheduled Task, run it once, and wait for the overlay."""
    err = print_err or _print_err
    if not _is_win32(platform):
        err(NOT_WINDOWS_MESSAGE)
        return 1
    binary = program if program is not None else spotty_bunny_program()
    program_argv = (
        [str(program.resolve())]
        if program is not None
        else spotty_bunny_program_arguments()
    )
    if program_argv is None or binary is None:
        err(f"{COMMAND_NAME}: could not find the spotty-bunny binary on PATH.")
        return 1
    launch_binary = Path(program_argv[0])
    if not _program_launch_target_ok(launch_binary):
        err(
            f"{COMMAND_NAME}: binary missing or not executable: "
            f"{launch_binary.expanduser()}"
        )
        return 1
    previous_xml = task_xml(schtasks=schtasks)
    xml = format_task_xml(program_arguments=program_argv)
    if not create_or_update_task(xml, schtasks=schtasks):
        restored = _rollback_failed_install(
            previous_xml, pid_dir=pid_dir, schtasks=schtasks
        )
        err(f"{COMMAND_NAME}: {_rollback_outcome_message(restored, schtasks=schtasks)}")
        err(f"{COMMAND_NAME}: schtasks /Create failed for '{TASK_NAME}'.")
        return 1
    run_task_once(schtasks=schtasks)
    if not _wait_for_managed_overlay(pid_dir=pid_dir, timeout_s=timeout_s):
        restored = _rollback_failed_install(
            previous_xml, pid_dir=pid_dir, schtasks=schtasks
        )
        err(f"{COMMAND_NAME}: {_rollback_outcome_message(restored, schtasks=schtasks)}")
        err(f"{COMMAND_NAME}: overlay did not start within {timeout_s:.0f}s.")
        return 1
    err(f"{COMMAND_NAME}: installed Scheduled Task '{TASK_NAME}'")
    err(f"{COMMAND_NAME}: binary {binary}")
    return 0


def is_agent_installed(*, schtasks: SchtasksFn | None = None) -> bool:
    """True when the Scheduled Task is registered."""
    return is_task_installed(schtasks=schtasks)


def run_win32_agent_command(
    command: str,
    rest: Sequence[str] = (),
    **kwargs: object,
) -> int:
    """Dispatch a Scheduled-Task subcommand. Extra argv is an error."""
    if command == "hotkey":
        return hotkey_command(rest)
    if rest:
        print(
            f"{COMMAND_NAME} {command}: unexpected arguments.",
            file=sys.stderr,
        )
        return 2
    if command == "install":
        return install_agent(**kwargs)
    if command == "status":
        return status_agent(**kwargs)
    if command == "uninstall":
        return uninstall_agent(**kwargs)
    if command == "upgrade":
        return upgrade_agent(**kwargs)
    print(UNKNOWN_COMMAND_MESSAGE.format(command=command), file=sys.stderr)
    return 2


def status_agent(
    *,
    pid_dir: Path | None = None,
    platform: str | None = None,
    print_err: Callable[[str], None] | None = None,
    print_fn: Callable[[str], None] | None = None,
    program: Path | None = None,
    schtasks: SchtasksFn | None = None,
) -> int:
    """Print task, process, log, and version state. Exit 0 if healthy."""
    err = print_err or _print_err
    out = print_fn or print
    if not _is_win32(platform):
        err(NOT_WINDOWS_MESSAGE)
        return 1
    installed = is_task_installed(schtasks=schtasks)
    if program is not None:
        binary = program
    elif installed:
        task_argv = task_program_arguments(schtasks=schtasks)
        binary = Path(task_argv[0]) if task_argv else spotty_bunny_program()
    else:
        binary = spotty_bunny_program()
    task_running = is_task_running(schtasks=schtasks) if installed else False
    running = spotty_bunny_is_running(pid_dir=pid_dir)
    pid_text = _pid_text(pid_dir=pid_dir) if running else "none"
    binary_ok = binary is not None and _program_launch_target_ok(Path(binary))
    app_log = _spotty_bunny_log_file(None)
    out(f"running: {'yes' if running else 'no'}")
    out(f"pid: {pid_text}")
    if not installed:
        out("task: not installed")
    else:
        out(f"task: {'running' if task_running else 'registered'}")
    if binary is None:
        out("binary: none")
    elif binary_ok:
        out(f"binary: {binary}")
    else:
        out(f"binary: {binary} (missing or not executable)")
    out(f"application_log: {app_log}")
    out(f'follow_logs: Get-Content -Path "{app_log}" -Wait -Tail 20')
    out(f'follow_logs_alt: type "{app_log}"')
    out(f"version: {build_version()}")
    health = read_spotty_bunny_health()
    if health is None:
        out("tap: unknown")
        out("last_chord: unknown")
    else:
        out(f"tap: {health.tap}")
        out(f"last_chord: {format_activity_timestamp(health.last_chord_at)}")
    tap_ok = health is not None and health.tap == TAP_STATE_OK
    if running and not tap_ok:
        healthy = False
    else:
        healthy = installed and running and binary_ok
    return 0 if healthy else 1


def uninstall_agent(
    *,
    pid_dir: Path | None = None,
    platform: str | None = None,
    print_err: Callable[[str], None] | None = None,
    schtasks: SchtasksFn | None = None,
) -> int:
    """Delete the Scheduled Task, stop leftovers, and clear the pid."""
    err = print_err or _print_err
    if not _is_win32(platform):
        err(NOT_WINDOWS_MESSAGE)
        return 1
    remove_task(schtasks=schtasks)
    stop_spotty_bunny(pid_dir=pid_dir)
    clear_spotty_bunny_pid(pid_dir=pid_dir)
    err(f"{COMMAND_NAME}: uninstalled Scheduled Task '{TASK_NAME}'")
    return 0


def upgrade_agent(
    *,
    pid_dir: Path | None = None,
    platform: str | None = None,
    print_err: Callable[[str], None] | None = None,
    program: Path | None = None,
    schtasks: SchtasksFn | None = None,
    timeout_s: float = INSTALL_WAIT_TIMEOUT_S,
) -> int:
    """Rewrite the Scheduled Task for the current binary and re-run it.

    Delegates to :func:`install_agent` -- there is no TCC/interpreter
    check to differentiate the two on Windows, matching
    ``app.server_agent.upgrade_agent``'s own delegation for the same
    reason, rather than macOS's ``spotty_bunny_agent.upgrade_agent``
    duplication (which exists there only to thread TCC re-verification
    through).
    """
    err = print_err or _print_err
    if not _is_win32(platform):
        err(NOT_WINDOWS_MESSAGE)
        return 1
    if not is_task_installed(schtasks=schtasks):
        err(
            f"{COMMAND_NAME}: Scheduled Task is not installed. "
            f"Run: {COMMAND_NAME} install"
        )
        return 1
    return install_agent(
        pid_dir=pid_dir,
        platform=platform,
        print_err=err,
        program=program,
        schtasks=schtasks,
        timeout_s=timeout_s,
    )


def _is_win32(platform: str | None) -> bool:
    return (sys.platform if platform is None else platform) == "win32"


def _pid_text(*, pid_dir: Path | None) -> str:
    from app.spotty_bunny_launch import read_spotty_bunny_runtime

    runtime = read_spotty_bunny_runtime(pid_dir=pid_dir)
    if runtime is None:
        return "none"
    return str(runtime[0])


def _print_err(message: str) -> None:
    print(message, file=sys.stderr)


def _rollback_failed_install(
    previous_xml: str | None,
    *,
    pid_dir: Path | None,
    schtasks: SchtasksFn | None,
) -> bool:
    """Undo a failed install/upgrade attempt.

    Mirrors ``app.server_agent._rollback_failed_install``: when
    *previous_xml* names a previously-working configuration (the upgrade
    case), restore and re-run it, then confirm the overlay comes back up,
    so a failed upgrade doesn't leave Spotty Bunny fully uninstalled.
    Returns True when that restore succeeded.
    """
    stop_spotty_bunny(pid_dir=pid_dir)
    clear_spotty_bunny_pid(pid_dir=pid_dir)
    if previous_xml is None:
        remove_task(schtasks=schtasks)
        return False
    if not create_or_update_task(previous_xml, schtasks=schtasks):
        return False
    run_task_once(schtasks=schtasks)
    return _wait_for_managed_overlay(pid_dir=pid_dir, timeout_s=ROLLBACK_WAIT_TIMEOUT_S)


def _rollback_outcome_message(restored: bool, *, schtasks: SchtasksFn | None) -> str:
    if restored:
        return "restored the previous Scheduled Task configuration."
    if is_task_installed(schtasks=schtasks):
        return (
            "kept the previous Scheduled Task configuration registered "
            f"for retry; the overlay is now down. Run: {COMMAND_NAME} install"
        )
    return (
        "removed the non-functional Scheduled Task; "
        f"the overlay is now down. Run: {COMMAND_NAME} install"
    )


def _wait_for_managed_overlay(*, pid_dir: Path | None, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if spotty_bunny_is_running(pid_dir=pid_dir):
            return True
        time.sleep(0.05)
    return spotty_bunny_is_running(pid_dir=pid_dir)

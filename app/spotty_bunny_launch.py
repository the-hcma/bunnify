"""Start and detect the Spotty Bunny overlay process (macOS)."""

from __future__ import annotations

import ctypes
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from app.config import run_dir
from app.process_marker import (
    SPOTTY_BUNNY_COMPONENT,
    build_marker_arguments,
    marker_from_command,
)
from app.version import git_commit

logger = logging.getLogger(__name__)

RestartFn = Callable[[str | None, str], bool]
SPOTTY_BUNNY_LAUNCHD_WAIT_S = 2.0
SPOTTY_BUNNY_LOCAL_BIN_NAME = (
    "spotty-bunny.exe" if sys.platform == "win32" else "spotty-bunny"
)
SPOTTY_BUNNY_PID_FILE = ".spotty-bunny.pid"
SPOTTY_BUNNY_STARTUP_WAIT_S = 0.05


def clear_spotty_bunny_pid(
    *,
    only_pid: int | None = None,
    pid_dir: Path | None = None,
) -> None:
    """Remove the recorded Spotty Bunny PID file.

    When *only_pid* is set, the file is left in place if it records a
    different process (so a successor overlay's pid is not erased).
    """
    if only_pid is not None:
        runtime = read_spotty_bunny_runtime(pid_dir=pid_dir)
        if runtime is None or runtime[0] != only_pid:
            return
    spotty_bunny_pid_path(pid_dir=pid_dir).unlink(missing_ok=True)


def ensure_spotty_bunny_running(
    *,
    cli_commit: str | None = None,
    force_restart: bool = False,
    installed: bool | None = None,
    loaded: bool | None = None,
    pid_dir: Path | None = None,
    restart: RestartFn | None = None,
    spawn: Callable[[Sequence[str]], int] | None = None,
) -> bool:
    """Start Spotty Bunny in the background when it is not already running.

    When an overlay is already running on a different commit, *restart* is
    asked whether to stop it and spawn this CLI's build. Returns ``True``
    when a process was already running or was started successfully.
    """
    if sys.platform != "darwin":
        return False
    directory = pid_dir if pid_dir is not None else run_dir()
    current = cli_commit if cli_commit is not None else git_commit()
    if loaded is None or installed is None:
        if pid_dir is None:
            from app.spotty_bunny_agent import is_agent_installed, is_agent_loaded

            if loaded is None:
                loaded = is_agent_loaded()
            if installed is None:
                installed = is_agent_installed()
        else:
            if loaded is None:
                loaded = False
            if installed is None:
                installed = False
    runtime = read_spotty_bunny_runtime(pid_dir=directory)
    pid_alive = runtime is not None and _spotty_bunny_process_alive(runtime[0])
    if pid_alive or loaded:
        running_commit = runtime[1] if runtime is not None else None
        if running_commit == current and not force_restart:
            logger.debug("spotty-bunny already running (pid file %s)", directory)
            return True
        if running_commit is None and not force_restart and restart is None:
            logger.debug(
                "spotty-bunny running without recorded commit (pid file %s)",
                directory,
            )
            return True
        should_restart = force_restart
        if not should_restart and restart is not None:
            should_restart = restart(running_commit, current)
        if not should_restart:
            logger.debug(
                "spotty-bunny already running with commit %s (cli %s)",
                running_commit,
                current,
            )
            return True
        if loaded:
            from app.spotty_bunny_agent import bootout_loaded_agent

            bootout_loaded_agent()
        stop_spotty_bunny(pid_dir=directory)
    elif runtime is not None:
        spotty_bunny_pid_path(pid_dir=directory).unlink(missing_ok=True)
    if installed:
        from app.spotty_bunny_agent import install_agent

        if install_agent(skip_chord_confirm=True) == 0:
            deadline = time.monotonic() + SPOTTY_BUNNY_LAUNCHD_WAIT_S
            while True:
                if spotty_bunny_is_running(pid_dir=directory):
                    logger.info("started spotty-bunny via LaunchAgent")
                    return True
                if time.monotonic() >= deadline:
                    break
                time.sleep(SPOTTY_BUNNY_STARTUP_WAIT_S)
            logger.warning(
                "LaunchAgent bootstrap did not produce a live overlay; "
                "not spawning a second one"
            )
            return False
        logger.warning("LaunchAgent install failed; falling back to spawn")
    command = spotty_bunny_launch_arguments(commit=current)
    spawn_fn = spawn or _spawn_detached
    try:
        pid = spawn_fn(command)
    except OSError as exc:
        logger.warning("could not start spotty-bunny: %s", exc)
        return False
    if pid <= 0:
        logger.warning("spotty-bunny spawn returned invalid pid %s", pid)
        return False
    time.sleep(SPOTTY_BUNNY_STARTUP_WAIT_S)
    if not _spotty_bunny_process_alive(pid):
        logger.warning("spotty-bunny exited immediately after spawn (pid %s)", pid)
        return False
    write_spotty_bunny_pid(pid, pid_dir=directory, commit=current)
    logger.info("started spotty-bunny (pid %s)", pid)
    return True


def read_spotty_bunny_runtime(
    *,
    pid_dir: Path | None = None,
) -> tuple[int, str | None] | None:
    """Return ``(pid, commit)`` from the pid file, or None if missing/invalid."""
    path = spotty_bunny_pid_path(pid_dir=pid_dir)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        pid = int(lines[0].strip())
    except OSError, ValueError, IndexError:
        return None
    commit = lines[1].strip() if len(lines) > 1 and lines[1].strip() else None
    return pid, commit


def spotty_bunny_command() -> list[str]:
    """Return the argv used to launch Spotty Bunny."""
    local = Path.home() / ".local" / "bin" / SPOTTY_BUNNY_LOCAL_BIN_NAME
    if local.is_file() and os.access(local, os.X_OK):
        return [str(local)]
    binary = shutil.which("spotty-bunny")
    if binary:
        return [binary]
    return [sys.executable, "-m", "app.spotty_bunny_cli"]


def spotty_bunny_is_running(*, pid_dir: Path | None = None) -> bool:
    """True when the pid file points at a live Spotty Bunny process."""
    runtime = read_spotty_bunny_runtime(pid_dir=pid_dir)
    if runtime is None:
        return False
    pid, _commit = runtime
    if not _spotty_bunny_process_alive(pid):
        spotty_bunny_pid_path(pid_dir=pid_dir).unlink(missing_ok=True)
        return False
    return True


def spotty_bunny_launch_arguments(*, commit: str | None = None) -> list[str]:
    """Return the argv used to spawn Spotty Bunny, stamped with its build."""
    return [
        *spotty_bunny_command(),
        *build_marker_arguments(SPOTTY_BUNNY_COMPONENT, commit=commit),
    ]


def spotty_bunny_pid_path(*, pid_dir: Path | None = None) -> Path:
    """Path to the Spotty Bunny PID file under the runtime directory."""
    directory = pid_dir if pid_dir is not None else run_dir()
    return directory / SPOTTY_BUNNY_PID_FILE


def stop_spotty_bunny(*, pid_dir: Path | None = None) -> bool:
    """SIGTERM (then SIGKILL) a leftover overlay. Returns True if signaled."""
    runtime = read_spotty_bunny_runtime(pid_dir=pid_dir)
    path = spotty_bunny_pid_path(pid_dir=pid_dir)
    if runtime is None:
        path.unlink(missing_ok=True)
        return False
    pid, _commit = runtime
    if not _spotty_bunny_process_alive(pid):
        path.unlink(missing_ok=True)
        return False
    _terminate_pid(pid)
    path.unlink(missing_ok=True)
    return True


def write_spotty_bunny_pid(
    pid: int,
    *,
    commit: str | None = None,
    pid_dir: Path | None = None,
) -> None:
    """Record *pid* and build commit for later ``spotty_bunny_is_running`` checks."""
    path = spotty_bunny_pid_path(pid_dir=pid_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    recorded = commit if commit is not None else git_commit()
    path.write_text(f"{pid}\n{recorded}\n", encoding="utf-8")


class _UnicodeString(ctypes.Structure):
    """winternl.h ``UNICODE_STRING`` (``Length`` is in bytes, not characters)."""

    _fields_ = (
        ("Length", ctypes.c_ushort),
        ("MaximumLength", ctypes.c_ushort),
        ("Buffer", ctypes.c_void_p),
    )


def _is_spotty_bunny_command(command: str) -> bool:
    """Match the overlay by name, then let a build marker rule out a sibling."""
    if "spotty-bunny" not in command and "spotty_bunny_cli" not in command:
        return False
    marker = marker_from_command(command)
    return marker is None or marker.component == SPOTTY_BUNNY_COMPONENT


def _process_command(pid: int) -> str | None:
    try:
        completed = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except OSError, subprocess.TimeoutExpired:
        return None
    command = completed.stdout.strip()
    return command or None


def _process_exists(pid: int) -> bool:
    if sys.platform == "win32":
        return _win32_process_alive(pid)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _spotty_bunny_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if not _process_exists(pid):
        return False
    if sys.platform == "win32":
        # #427 wires a live Windows stop path (uninstall/rollback), so a
        # stale/reused PID being treated as "our overlay" is no longer
        # inert -- verify the process before trusting it.
        #
        # Match on the full command line, like the `ps -o command=` check
        # below. The image name alone is not enough: the pipx/pip
        # `spotty-bunny.exe` is a launcher that starts a child python.exe,
        # and the overlay records *its own* pid (os.getpid()), whose image is
        # `...\Scripts\python.exe` -- so an image-name check rejected the real
        # overlay, `status` reported "running: no", and the stale-pid cleanup
        # deleted the pid file (#494). The command line of that python
        # process still names `spotty-bunny.exe` (or `app.spotty_bunny_cli`
        # for a `-m` launch). Fall back to the image name when the command
        # line cannot be read.
        command = _win32_process_command_line(pid)
        if command is not None:
            return _is_spotty_bunny_command(command)
        image = _win32_process_image_name(pid)
        return image is not None and _is_spotty_bunny_command(image)
    command = _process_command(pid)
    return command is not None and _is_spotty_bunny_command(command)


_WIN32_ERROR_ACCESS_DENIED = 5
_WIN32_FILETIME_TO_UNIX_100NS = 116_444_736_000_000_000  # 1601 -> 1970, in 100 ns
_WIN32_PROCESS_COMMAND_LINE_INFORMATION = 60  # ProcessCommandLineInformation
_WIN32_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_WIN32_PROCESS_TERMINATE = 0x0001
_WIN32_STILL_ACTIVE = 259


def _win32_process_command_line(pid: int) -> str | None:
    """Return the full command line of *pid*, or None if it cannot be read.

    ``NtQueryInformationProcess(ProcessCommandLineInformation)`` returns a
    ``UNICODE_STRING`` and works with ``PROCESS_QUERY_LIMITED_INFORMATION``
    for a same-user process (Windows 8.1+), so no WMI or PowerShell is needed.
    None covers "gone", "denied" and "unsupported": callers fall back to the
    image name.
    """
    import ctypes

    kernel32 = _win32_kernel32()
    ntdll = ctypes.WinDLL("ntdll")
    handle = kernel32.OpenProcess(_WIN32_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        needed = ctypes.c_ulong(0)
        # The first call only reports the required size (it "fails" with
        # STATUS_INFO_LENGTH_MISMATCH by design).
        ntdll.NtQueryInformationProcess(
            handle,
            _WIN32_PROCESS_COMMAND_LINE_INFORMATION,
            None,
            0,
            ctypes.byref(needed),
        )
        if needed.value == 0:
            return None
        buffer = ctypes.create_string_buffer(needed.value)
        status = ntdll.NtQueryInformationProcess(
            handle,
            _WIN32_PROCESS_COMMAND_LINE_INFORMATION,
            buffer,
            needed.value,
            ctypes.byref(needed),
        )
        if status != 0:
            return None
        header = ctypes.cast(buffer, ctypes.POINTER(_UnicodeString))[0]
        if not header.Buffer or not header.Length:
            return None
        return ctypes.wstring_at(header.Buffer, header.Length // 2)
    finally:
        kernel32.CloseHandle(handle)


def _win32_process_image_name(pid: int) -> str | None:
    """Return the running executable's path for *pid*, or None if unknown.

    None covers both "process is gone" and "denied" -- either way, the
    caller cannot confirm identity, so it must not treat *pid* as our
    overlay.
    """
    import ctypes

    kernel32 = _win32_kernel32()
    handle = kernel32.OpenProcess(_WIN32_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = ctypes.c_ulong(len(buf))
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return None
        return buf.value
    finally:
        kernel32.CloseHandle(handle)


def _win32_kernel32():
    import ctypes

    # use_last_error=True so a failed OpenProcess's GetLastError() is
    # captured correctly by ctypes.get_last_error() below -- ctypes.windll's
    # convenience objects don't do this reliably (see
    # spotty_bunny_hook_win32.install_chord_hook, same pattern).
    return ctypes.WinDLL("kernel32", use_last_error=True)


def _win32_process_alive(pid: int) -> bool:
    """Existence check via OpenProcess/GetExitCodeProcess.

    Deliberately not ``os.kill(pid, 0)``: on Windows, ``os.kill`` with any
    signal other than the two console-control events calls
    ``TerminateProcess(handle, sig)`` -- ``os.kill(pid, 0)`` would actually
    terminate a live process (with exit code 0) instead of merely probing
    it.

    ``OpenProcess`` failing doesn't necessarily mean the pid is gone: it
    also fails with ``ERROR_ACCESS_DENIED`` for a live process we lack
    rights to (e.g. started elevated, or as another user) -- treat that as
    "alive" rather than "not found", since concluding "not running" here
    feeds ``stop_spotty_bunny()`` unlinking the pid file out from under a
    process that is, in fact, still running.
    """
    import ctypes

    kernel32 = _win32_kernel32()
    handle = kernel32.OpenProcess(_WIN32_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ctypes.get_last_error() == _WIN32_ERROR_ACCESS_DENIED
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == _WIN32_STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _win32_process_start_time(pid: int) -> float | None:
    """Epoch seconds at which *pid* started, or None if it cannot be read.

    ``GetProcessTimes`` needs only ``PROCESS_QUERY_LIMITED_INFORMATION``;
    None covers "gone" and "denied".
    """
    import ctypes
    from ctypes import wintypes

    kernel32 = _win32_kernel32()
    handle = kernel32.OpenProcess(_WIN32_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            return None
        ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
        return (ticks - _WIN32_FILETIME_TO_UNIX_100NS) / 10_000_000
    finally:
        kernel32.CloseHandle(handle)


def _win32_terminate_pid(pid: int) -> bool:
    """Return whether ``TerminateProcess`` was actually issued.

    A ``False`` return (most commonly ``ERROR_ACCESS_DENIED``, same
    caveat as :func:`_win32_process_alive`) tells :func:`_terminate_pid`
    not to sit through a pointless wait for an exit that was never
    requested.
    """
    kernel32 = _win32_kernel32()
    handle = kernel32.OpenProcess(_WIN32_PROCESS_TERMINATE, False, pid)
    if not handle:
        logger.warning(
            "could not open pid %s to terminate it (denied or already gone)", pid
        )
        return False
    try:
        return bool(kernel32.TerminateProcess(handle, 1))
    finally:
        kernel32.CloseHandle(handle)


def _spawn_detached(command: Sequence[str]) -> int:
    proc = subprocess.Popen(
        list(command),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return int(proc.pid)


def _terminate_pid(pid: int) -> None:
    if sys.platform == "win32":
        if not _win32_terminate_pid(pid):
            # Nothing was actually requested (see _win32_terminate_pid) --
            # waiting here would just stall for the full timeout on a
            # termination that was never issued.
            return
        _wait_for_exit(pid, timeout_s=10)
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    if _wait_for_exit(pid, timeout_s=10):
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    _wait_for_exit(pid, timeout_s=2)


def _wait_for_exit(pid: int, *, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not _process_exists(pid):
            return True
        time.sleep(0.05)
    return False

"""Start and detect the Spotty Bunny overlay process (macOS)."""

from __future__ import annotations

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
from app.version import git_commit

logger = logging.getLogger(__name__)

RestartFn = Callable[[str | None, str], bool]
SPOTTY_BUNNY_LAUNCHD_WAIT_S = 2.0
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
    current = git_commit()
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
        if running_commit is None or running_commit == current:
            logger.debug("spotty-bunny already running (pid file %s)", directory)
            return True
        if restart is None or not restart(running_commit, current):
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

        if install_agent() == 0:
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
    command = spotty_bunny_command()
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


def _is_spotty_bunny_command(command: str) -> bool:
    return "spotty-bunny" in command or "spotty_bunny_cli" in command


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


def _spotty_bunny_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    command = _process_command(pid)
    return command is not None and _is_spotty_bunny_command(command)


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
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        time.sleep(0.05)
    return False

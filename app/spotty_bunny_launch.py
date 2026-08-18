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

logger = logging.getLogger(__name__)

SPOTTY_BUNNY_PID_FILE = ".spotty-bunny.pid"
SPOTTY_BUNNY_STARTUP_WAIT_S = 0.05


def clear_spotty_bunny_pid(*, pid_dir: Path | None = None) -> None:
    """Remove the recorded Spotty Bunny PID file."""
    spotty_bunny_pid_path(pid_dir=pid_dir).unlink(missing_ok=True)


def ensure_spotty_bunny_running(
    *,
    pid_dir: Path | None = None,
    spawn: Callable[[Sequence[str]], int] | None = None,
) -> bool:
    """Start Spotty Bunny in the background when it is not already running.

    Returns ``True`` when a process was already running or was started successfully.
    """
    if sys.platform != "darwin":
        return False
    directory = pid_dir if pid_dir is not None else run_dir()
    if spotty_bunny_is_running(pid_dir=directory):
        logger.debug("spotty-bunny already running (pid file %s)", directory)
        return True
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
    write_spotty_bunny_pid(pid, pid_dir=directory)
    logger.info("started spotty-bunny (pid %s)", pid)
    return True


def spotty_bunny_command() -> list[str]:
    """Return the argv used to launch Spotty Bunny."""
    binary = shutil.which("spotty-bunny")
    if binary:
        return [binary]
    return [sys.executable, "-m", "app.spotty_bunny_cli"]


def spotty_bunny_is_running(*, pid_dir: Path | None = None) -> bool:
    """True when the pid file points at a live Spotty Bunny process."""
    path = spotty_bunny_pid_path(pid_dir=pid_dir)
    try:
        raw = path.read_text(encoding="utf-8").strip()
        pid = int(raw)
    except OSError, ValueError:
        return False
    if not _spotty_bunny_process_alive(pid):
        path.unlink(missing_ok=True)
        return False
    return True


def spotty_bunny_pid_path(*, pid_dir: Path | None = None) -> Path:
    """Path to the Spotty Bunny PID file under the runtime directory."""
    directory = pid_dir if pid_dir is not None else run_dir()
    return directory / SPOTTY_BUNNY_PID_FILE


def stop_spotty_bunny(*, pid_dir: Path | None = None) -> bool:
    """SIGTERM (then SIGKILL) a leftover overlay. Returns True if signaled."""
    path = spotty_bunny_pid_path(pid_dir=pid_dir)
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except OSError, ValueError:
        return False
    if not _spotty_bunny_process_alive(pid):
        path.unlink(missing_ok=True)
        return False
    _terminate_pid(pid)
    path.unlink(missing_ok=True)
    return True


def write_spotty_bunny_pid(pid: int, *, pid_dir: Path | None = None) -> None:
    """Record *pid* for later ``spotty_bunny_is_running`` checks."""
    path = spotty_bunny_pid_path(pid_dir=pid_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{pid}\n", encoding="utf-8")


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

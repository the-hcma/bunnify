"""Remember which interpreter was granted Input Monitoring (macOS TCC).

macOS ties Accessibility / Input Monitoring grants to one specific
executable (its path and code identity). When a Homebrew Python upgrade,
a pipx reinstall, or a venv rebuild changes that executable, the old grant
silently stops applying and the global hotkey dies with no error. Recording
the interpreter at grant time lets ``bunnify doctor`` name that cause
unambiguously instead of leaving the operator to guess.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from app.config import data_dir

ACCESSIBILITY_PANE = "Accessibility (“Device Control and Data Access” on macOS 27+)"
GRANT_FILE_NAME = ".spotty-bunny-tcc-grant"
INTERPRETER_VERSION_TIMEOUT_S = 15
PROCESS_EXECUTABLE_TIMEOUT_S = 5
RUNTIME_GRANT_FILE_NAME = ".spotty-bunny-runtime-grant"
RUNTIME_GRANT_HEARTBEAT_S = 300.0
RUNTIME_GRANT_MAX_AGE_S = 900.0

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GrantDiagnosis:
    """Outcome of comparing the recorded grant with the interpreter now in use."""

    healthy: bool
    lines: tuple[str, ...]
    state: str


@dataclass(frozen=True)
class InterpreterIdentity:
    """What macOS keys a privacy grant on: the real path and the binary itself."""

    path: str
    sha256: str | None
    version: str | None
    app_path: str | None = None
    app_sha256: str | None = None

    def label(self) -> str:
        version = self.version or "unknown version"
        return f"{self.path} ({version})"


@dataclass(frozen=True)
class RuntimeGrant:
    """Privacy grants as seen by the running overlay itself.

    Only a launchd-started overlay is its own responsible process; one started
    from a terminal (foreground run or spawn fallback) reports the terminal's
    grants, so ``launchd`` records which case this is.
    """

    accessibility: bool
    executable: str
    input_monitoring: bool
    launchd: bool
    pid: int
    updated_at: float


def app_bundle_path(identity: InterpreterIdentity) -> str | None:
    """Return the ``Python.app`` bundle a framework interpreter runs as, if any."""
    if identity.app_path is None:
        return None
    for parent in Path(identity.app_path).parents:
        if parent.suffix == ".app":
            return str(parent)
    return None


def describe_interpreter(
    interpreter: Path,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> InterpreterIdentity:
    """Return the current identity of *interpreter* (resolved real path)."""
    real = interpreter.resolve()
    app_path = _framework_app_binary(real)
    return InterpreterIdentity(
        app_path=app_path,
        app_sha256=_file_sha256(Path(app_path)) if app_path else None,
        path=str(real),
        sha256=_file_sha256(real),
        version=_interpreter_version(real, run=run),
    )


def diagnose_grant(
    *,
    accessibility: bool,
    agent_installed: bool = True,
    current: InterpreterIdentity,
    input_monitoring: bool,
    recorded: InterpreterIdentity | None,
) -> GrantDiagnosis:
    """Explain, as specifically as the evidence allows, what to re-authorize."""
    if accessibility and input_monitoring:
        lines = [
            f"Accessibility and Input Monitoring are granted for {current.label()}."
        ]
        if recorded is not None and recorded != current:
            lines.append(
                f"Note: the recorded authorized interpreter was {recorded.label()}; "
                "the grants are present for the current one. The record is left "
                "unchanged; `install` / `upgrade` refresh it."
            )
        return GrantDiagnosis(healthy=True, lines=tuple(lines), state="ok")
    if recorded is not None and recorded.path != current.path:
        return GrantDiagnosis(
            healthy=False,
            lines=(
                "Accessibility and Input Monitoring were authorized for a "
                "different interpreter than the one spotty-bunny runs now.",
                f"  authorized: {recorded.label()}",
                f"  running:    {current.label()}",
                "macOS grants Input Monitoring per executable, so the old "
                "grant no longer applies. This (typically a Python upgrade "
                "or reinstall) is why the hotkey stopped working.",
                *_reauthorize_steps(current, agent_installed),
            ),
            state="interpreter_moved",
        )
    if recorded is not None and _binary_changed(recorded, current):
        return GrantDiagnosis(
            healthy=False,
            lines=(
                "The interpreter at the authorized path was replaced in place.",
                f"  authorized: {recorded.label()} sha256 {_short(recorded.sha256)}",
                f"  running:    {current.label()} sha256 {_short(current.sha256)}",
                "macOS ties the grant to the binary's identity, so an "
                "in-place update (for example `brew upgrade python`) "
                "invalidates it even though the path is unchanged.",
                *_reauthorize_steps(current, agent_installed),
            ),
            state="interpreter_modified",
        )
    absent = [
        name
        for name, granted in (
            ("Accessibility", accessibility),
            ("Input Monitoring", input_monitoring),
        )
        if not granted
    ]
    missing = " and ".join(absent)
    was, wasnt = ("were", "are") if len(absent) > 1 else ("was", "is")
    if recorded is not None:
        reason = (
            f"{missing} {was} authorized for this exact interpreter before but "
            "macOS no longer reports it: the entry was removed, toggled off, "
            "or reset."
        )
        state = "revoked"
    else:
        reason = (
            f"{missing} {wasnt} not granted for this interpreter, and no earlier "
            "grant is on record (it was never granted, or was granted before "
            "bunnify began recording it)."
        )
        state = "unrecorded"
    return GrantDiagnosis(
        healthy=False,
        lines=(reason, *_reauthorize_steps(current, agent_installed)),
        state=state,
    )


def diagnose_running_agent(
    *,
    current: InterpreterIdentity,
    executable: str | None,
    pid: int,
) -> tuple[str, ...]:
    """Problem lines when the live overlay runs a different binary than launchd would.

    A grant follows the process that holds it, so an overlay started before a
    Python upgrade keeps working on the old (possibly deleted) binary; the next
    launch uses the new one, which has no grant of its own.
    """
    if executable is None or "/" not in executable:
        return ()
    expected = launched_executable(current)
    if os.path.realpath(executable) == os.path.realpath(expected):
        return ()
    removed = "" if Path(executable).exists() else ", which has been removed"
    return (
        f"problem: the running spotty-bunny (pid {pid}) is still the old "
        f"interpreter {executable}{removed}.",
        "The hotkey keeps working only until it restarts (log out, reboot, "
        "or `bunnify spotty-bunny upgrade`); launchd will then start "
        f"{expected}, which needs its own Accessibility and Input Monitoring "
        "grants.",
    )


def launched_executable(identity: InterpreterIdentity) -> str:
    """The binary macOS actually runs (and attributes grants to) for *identity*."""
    return identity.app_path or identity.path


def process_executable(
    pid: int,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> str | None:
    """Return the executable image of *pid* (still reported after it is deleted)."""
    runner = run or subprocess.run
    try:
        completed = runner(
            ["ps", "-p", str(pid), "-o", "comm="],
            capture_output=True,
            check=False,
            text=True,
            timeout=PROCESS_EXECUTABLE_TIMEOUT_S,
        )
    except OSError, subprocess.SubprocessError:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def read_recorded_grant(*, grant_dir: Path | None = None) -> InterpreterIdentity | None:
    """Return the interpreter last recorded as authorized, or None."""
    try:
        payload = json.loads(_grant_path(grant_dir).read_text(encoding="utf-8"))
        return InterpreterIdentity(
            app_path=payload.get("app_path"),
            app_sha256=payload.get("app_sha256"),
            path=str(payload["path"]),
            sha256=payload.get("sha256"),
            version=payload.get("version"),
        )
    except OSError, KeyError, TypeError, ValueError:
        return None


def read_runtime_grant(*, grant_dir: Path | None = None) -> RuntimeGrant | None:
    """Return the grants the overlay last reported for itself, or None."""
    directory = data_dir() if grant_dir is None else grant_dir
    try:
        payload = json.loads(
            (directory / RUNTIME_GRANT_FILE_NAME).read_text(encoding="utf-8")
        )
        return RuntimeGrant(
            accessibility=bool(payload["accessibility"]),
            executable=str(payload["executable"]),
            input_monitoring=bool(payload["input_monitoring"]),
            launchd=bool(payload.get("launchd", False)),
            pid=int(payload["pid"]),
            updated_at=float(payload["updated_at"]),
        )
    except OSError, KeyError, TypeError, ValueError:
        return None


def record_grant(
    identity: InterpreterIdentity, *, grant_dir: Path | None = None
) -> bool:
    """Persist *identity* as the authorized interpreter; False if not writable."""
    path = _grant_path(grant_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(identity)) + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("could not record the TCC grant identity: %s", exc)
        return False
    return True


def runtime_grant_due(previous: RuntimeGrant | None, current: RuntimeGrant) -> bool:
    """True when *current* changed since *previous* or a heartbeat is due."""
    if previous is None:
        return True
    if asdict(previous) | {"updated_at": 0} != asdict(current) | {"updated_at": 0}:
        return True
    return current.updated_at - previous.updated_at >= RUNTIME_GRANT_HEARTBEAT_S


def runtime_grant_rejection(
    report: RuntimeGrant | None,
    *,
    now: float | None = None,
    pid: int,
) -> str | None:
    """Why *report* cannot stand in for the live overlay's grants, or None."""
    if report is None:
        return "no report from the running spotty-bunny"
    if report.pid != pid:
        return f"report is from pid {report.pid}, not the running pid {pid}"
    if not report.launchd:
        return "running spotty-bunny was not started by launchd"
    age = (time.time() if now is None else now) - report.updated_at
    if age > RUNTIME_GRANT_MAX_AGE_S:
        return f"report is stale ({int(age)}s old)"
    return None


def write_runtime_grant(grant: RuntimeGrant, *, grant_dir: Path | None = None) -> bool:
    """Persist the overlay's own view of its grants; False if not writable."""
    directory = data_dir() if grant_dir is None else grant_dir
    path = directory / RUNTIME_GRANT_FILE_NAME
    temp = path.with_name(f"{path.name}.tmp")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        temp.write_text(json.dumps(asdict(grant)) + "\n", encoding="utf-8")
        temp.replace(path)
    except OSError as exc:
        logger.warning("could not record the runtime TCC grant: %s", exc)
        return False
    return True


def _binary_changed(
    recorded: InterpreterIdentity, current: InterpreterIdentity
) -> bool:
    if (
        recorded.app_sha256 is not None
        and current.app_sha256 is not None
        and recorded.app_sha256 != current.app_sha256
    ):
        return True
    if recorded.sha256 is not None and current.sha256 is not None:
        return recorded.sha256 != current.sha256
    return (
        recorded.version is not None
        and current.version is not None
        and recorded.version != current.version
    )


def _file_sha256(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _framework_app_binary(real: Path) -> str | None:
    """Return the ``Python.app`` binary a framework build's launcher execs."""
    candidate = real.parent.parent / "Resources/Python.app/Contents/MacOS/Python"
    return str(candidate) if candidate.is_file() else None


def _grant_path(grant_dir: Path | None) -> Path:
    return (data_dir() if grant_dir is None else grant_dir) / GRANT_FILE_NAME


def _interpreter_version(
    interpreter: Path,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> str | None:
    runner = run or subprocess.run
    try:
        completed = runner(
            [str(interpreter), "--version"],
            capture_output=True,
            check=False,
            text=True,
            timeout=INTERPRETER_VERSION_TIMEOUT_S,
        )
    except OSError, subprocess.SubprocessError:
        return None
    if completed.returncode != 0:
        return None
    return (completed.stdout or completed.stderr).strip() or None


def _reauthorize_steps(
    current: InterpreterIdentity, agent_installed: bool = True
) -> tuple[str, ...]:
    bundle = app_bundle_path(current)
    steps = [
        "To re-authorize, in System Settings → Privacy & Security, for BOTH "
        f"Input Monitoring and {ACCESSIBILITY_PANE}:",
        "  1. Select any stale Python / python3 entry and remove it with the − button.",
        "  2. Click +, press ⌘⇧G, paste this path, and click Open:",
        f"       {bundle or current.path}",
    ]
    if bundle is not None:
        steps.append(
            "     (this framework Python runs as that app bundle, so macOS "
            "lists the entry as “Python”, not as a python3 path)"
        )
    steps.append("  3. Make sure the new entry's toggle is on.")
    steps.append(
        "Then run: bunnify spotty-bunny upgrade"
        if agent_installed
        else "Then run: bunnify spotty-bunny install"
    )
    return tuple(steps)


def _short(digest: str | None) -> str:
    return digest[:12] if digest else "unknown"

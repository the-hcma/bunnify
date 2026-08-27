"""Spotty Bunny macOS LaunchAgent (install, uninstall, status, upgrade)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from app.process_marker import SPOTTY_BUNNY_COMPONENT, build_marker_arguments
from app.spotty_bunny_cli import (
    COMMAND_NAME,
    MACOS_EXTRA_HINT,
    NOT_MACOS_MESSAGE,
    _spotty_bunny_log_file,
)
from app.spotty_bunny_launch import (
    clear_spotty_bunny_pid,
    spotty_bunny_command,
    spotty_bunny_is_running,
    stop_spotty_bunny,
)
from app.version import build_version

AGENT_COMMANDS = frozenset({"install", "status", "uninstall", "upgrade"})
AGENT_LABEL = "com.thehcma.bunnify.spotty-bunny"
AGENT_PLIST_NAME = f"{AGENT_LABEL}.plist"
LAUNCHCTL_TIMEOUT_S = 10
LAUNCHD_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
CHORD_RETRY_HINT = f"""\
{COMMAND_NAME}: the overlay may need a fresh launchd process after granting
Accessibility / Input Monitoring. Restarting the agent — test again when ready.
"""
CHORD_TEST_PROMPT = f"{COMMAND_NAME}: did the search box appear? [y/N]: "
POST_INSTALL_HINT = (
    f"{COMMAND_NAME}: hold one Control and press the other to test the overlay."
)
TCC_INSTRUCTIONS = f"""\
{COMMAND_NAME}: Accessibility and Input Monitoring must be granted to the
Python interpreter launchd will exec (the pipx/venv interpreter behind
spotty-bunny), not only Terminal.app.

System Settings → Privacy & Security → Accessibility
System Settings → Privacy & Security → Input Monitoring
"""
TCC_RECHECK_PROMPT = (
    "Press Enter after granting Accessibility/Input Monitoring to re-check "
    "(or Ctrl-C to cancel)."
)
TCC_PROBE_TIMEOUT_S = 15
UNKNOWN_COMMAND_MESSAGE = (
    f"{COMMAND_NAME}: unknown command '{{command}}'. "
    "Use install, uninstall, status, or upgrade; "
    "or run with no subcommand for the foreground overlay."
)

LaunchctlFn = Callable[..., subprocess.CompletedProcess[str]]
TccFn = Callable[[Path], "TccStatus"]


@dataclass(frozen=True)
class TccStatus:
    """Current Accessibility and Input Monitoring grants for one interpreter."""

    accessibility: bool
    input_monitoring: bool

    @property
    def ok(self) -> bool:
        return self.accessibility and self.input_monitoring


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
    path = launchd_path_for_home(home)
    return (
        _PLIST_TEMPLATE.replace("__PROGRAM_ARGUMENTS__", args_xml)
        .replace("__HOME__", escape(str(home)))
        .replace("__LAUNCHD_PATH__", escape(path))
    )


def install_agent(
    *,
    home: Path | None = None,
    launchctl: LaunchctlFn | None = None,
    pid_dir: Path | None = None,
    platform: str | None = None,
    print_err: Callable[[str], None] | None = None,
    probe_tcc: TccFn | None = None,
    program: Path | None = None,
    prompt_fn: Callable[[str], str] | None = None,
    request_tcc: TccFn | None = None,
    skip_chord_confirm: bool = False,
) -> int:
    """Write the LaunchAgent, verify TCC, and bootstrap it."""
    err = print_err or _print_err
    if not _is_darwin(platform):
        err(NOT_MACOS_MESSAGE)
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
    prepared = _prepare_program_launch(
        program_argv=program_argv,
        binary=binary,
        err=err,
        plist=None,
    )
    if prepared is None:
        return 1
    program_argv, binary, interpreter = prepared
    status = _require_current_tcc(
        interpreter,
        err=err,
        probe_tcc=probe_tcc,
        prompt_fn=prompt_fn,
        request_tcc=request_tcc,
    )
    if status is None:
        return 1
    root = home if home is not None else Path.home()
    plist = agent_plist_path(home=root)
    _write_plist(plist, home=root, program_arguments=program_argv)
    if not _reload_agent(
        plist,
        launchctl=launchctl,
        pid_dir=pid_dir,
    ):
        err(f"{COMMAND_NAME}: launchctl bootstrap failed for {plist}.")
        return 1
    err(f"{COMMAND_NAME}: installed LaunchAgent {AGENT_LABEL}")
    err(f"{COMMAND_NAME}: plist {plist}")
    err(f"{COMMAND_NAME}: interpreter {interpreter_realpath(interpreter)}")
    if skip_chord_confirm or _confirm_chord_works(
        plist,
        err=err,
        launchctl=launchctl,
        pid_dir=pid_dir,
        prompt_fn=prompt_fn,
    ):
        return 0
    return 1


def interpreter_for_program(program: Path) -> Path:
    """Return the interpreter launchd will exec for a console-script *program*."""
    try:
        raw = program.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return program

    # pipx console-script wrappers are typically `#!/bin/sh` that `exec` a
    # concrete venv python. For TCC probing we must use that real python,
    # not the shell.
    pipx_exec = re.search(
        r"exec'\s*['\"](?P<python>[^'\"]*?/bin/python[^'\"]*)['\"]\s+\"\$0\"",
        raw,
    )
    if pipx_exec:
        return Path(pipx_exec.group("python"))

    shell_exec = _shell_exec_python_from_wrapper(raw)
    if shell_exec is not None:
        return shell_exec

    first_line = raw.splitlines()[:1]
    if not first_line or not first_line[0].startswith("#!"):
        return program

    line = first_line[0][2:].strip()
    parts = line.split()
    if not parts:
        return program

    executable = Path(parts[0])
    if executable.name == "env" and len(parts) >= 2:
        resolved = shutil.which(parts[1], path=LAUNCHD_PATH)
        if resolved is None:
            return Path(parts[1])
        return Path(resolved)
    return executable


def interpreter_realpath(interpreter: Path) -> Path:
    """Return the canonical interpreter path for TCC display and comparisons."""
    try:
        return Path(os.path.realpath(interpreter))
    except OSError:
        return interpreter


def is_agent_installed(*, home: Path | None = None) -> bool:
    """True when the LaunchAgent plist is present under *home*."""
    return agent_plist_path(home=home).is_file()


def is_agent_loaded(
    *,
    launchctl: LaunchctlFn | None = None,
    uid: int | None = None,
) -> bool:
    """True when launchd has the Spotty Bunny agent in the gui domain."""
    completed = _launchctl(
        ["print", f"{_gui_domain(uid)}/{AGENT_LABEL}"],
        launchctl=launchctl,
    )
    return completed.returncode == 0


def launchd_path_for_home(home: Path) -> str:
    """PATH for the Spotty Bunny LaunchAgent (Homebrew + ``~/.local/bin``)."""
    local_bin = str((home / ".local" / "bin").resolve())
    return f"{local_bin}:{LAUNCHD_PATH}"


def refresh_agent_plist(
    *,
    home: Path | None = None,
    platform: str | None = None,
    print_err: Callable[[str], None] | None = None,
    program: Path | None = None,
) -> int:
    """Rewrite the LaunchAgent plist for this binary without bouncing launchd."""
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
    binary = program if program is not None else spotty_bunny_program()
    program_argv = (
        [str(program.resolve())]
        if program is not None
        else spotty_bunny_program_arguments()
    )
    if program_argv is None or binary is None:
        err(f"{COMMAND_NAME}: could not find the spotty-bunny binary on PATH.")
        return 1
    _write_plist(plist, home=root, program_arguments=program_argv)
    err(f"{COMMAND_NAME}: refreshed LaunchAgent plist {plist}")
    err(f"{COMMAND_NAME}: binary {binary}")
    return 0


def run_agent_command(
    command: str,
    rest: Sequence[str] = (),
    **kwargs: object,
) -> int:
    """Dispatch a LaunchAgent subcommand. Extra argv is an error."""
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


def spotty_bunny_program() -> Path | None:
    """Primary executable path for status display (first ProgramArguments entry)."""
    argv = spotty_bunny_program_arguments()
    if not argv:
        return None
    return Path(argv[0])


def spotty_bunny_program_arguments() -> list[str] | None:
    """Absolute argv launchd should use in ProgramArguments."""
    command = spotty_bunny_command()
    if not command:
        return None
    resolved: list[str] = []
    for index, part in enumerate(command):
        if index == 0:
            path = Path(part).expanduser()
            if path.is_absolute():
                resolved.append(str(path))
                continue
            found = shutil.which(part)
            resolved.append(found if found else str(path.resolve()))
            continue
        resolved.append(part)
    resolved.extend(build_marker_arguments(SPOTTY_BUNNY_COMPONENT))
    return resolved


def status_agent(
    *,
    home: Path | None = None,
    launchctl: LaunchctlFn | None = None,
    pid_dir: Path | None = None,
    platform: str | None = None,
    print_err: Callable[[str], None] | None = None,
    print_fn: Callable[[str], None] | None = None,
    probe_tcc: TccFn | None = None,
    program: Path | None = None,
) -> int:
    """Print agent, process, log, version, and TCC state. Exit 0 if healthy."""
    err = print_err or _print_err
    out = print_fn or print
    if not _is_darwin(platform):
        err(NOT_MACOS_MESSAGE)
        return 1
    root = home if home is not None else Path.home()
    plist = agent_plist_path(home=root)
    installed = plist.is_file()
    if program is not None:
        binary = program
    elif installed:
        plist_argv = _plist_program_arguments(plist)
        binary = Path(plist_argv[0]) if plist_argv else spotty_bunny_program()
    else:
        binary = spotty_bunny_program()
    loaded = is_agent_loaded(launchctl=launchctl) if installed else False
    running = spotty_bunny_is_running(pid_dir=pid_dir)
    pid_text = "none"
    if running:
        pid_text = _pid_text(pid_dir=pid_dir)
    interpreter = interpreter_for_program(binary) if binary is not None else None
    binary_ok = binary is not None and _program_launch_target_ok(Path(binary))
    tcc = _probe_tcc_for_status(
        interpreter,
        err=err,
        probe_tcc=probe_tcc,
    )
    stdout_path, stderr_path = _launchd_log_paths(plist)
    app_log = _spotty_bunny_log_file(None)
    out(f"running: {'yes' if running else 'no'}")
    out(f"pid: {pid_text}")
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
    if interpreter is None:
        out("interpreter: none")
    else:
        out(f"interpreter: {interpreter_realpath(interpreter)}")
    out(f"application_log: {app_log}")
    out(f'follow_logs: tail --follow=name --retry "{app_log}"')
    out(f'follow_logs_alt: tail -f "{app_log}"')
    out(f"launchd_stdout: {stdout_path or 'none'}")
    out(f"launchd_stderr: {stderr_path or 'none'}")
    out(f"version: {build_version()}")
    out(f"accessibility: {'yes' if tcc.accessibility else 'no'}")
    out(f"input_monitoring: {'yes' if tcc.input_monitoring else 'no'}")
    healthy = installed and loaded and running and binary_ok
    return 0 if healthy else 1


def uninstall_agent(
    *,
    home: Path | None = None,
    launchctl: LaunchctlFn | None = None,
    pid_dir: Path | None = None,
    platform: str | None = None,
    print_err: Callable[[str], None] | None = None,
) -> int:
    """Remove the plist, then boot out, stop leftovers, and clear the pid."""
    err = print_err or _print_err
    if not _is_darwin(platform):
        err(NOT_MACOS_MESSAGE)
        return 1
    root = home if home is not None else Path.home()
    plist = agent_plist_path(home=root)
    loaded = is_agent_loaded(launchctl=launchctl)
    # Unlink first so an in-process bootout cannot leave the plist behind.
    plist.unlink(missing_ok=True)
    if loaded:
        _bootout_agent(launchctl=launchctl)
    stop_spotty_bunny(pid_dir=pid_dir)
    clear_spotty_bunny_pid(pid_dir=pid_dir)
    err(f"{COMMAND_NAME}: uninstalled LaunchAgent {AGENT_LABEL}")
    return 0


def upgrade_agent(
    *,
    home: Path | None = None,
    launchctl: LaunchctlFn | None = None,
    pid_dir: Path | None = None,
    platform: str | None = None,
    print_err: Callable[[str], None] | None = None,
    probe_tcc: TccFn | None = None,
    program: Path | None = None,
    prompt_fn: Callable[[str], str] | None = None,
    request_tcc: TccFn | None = None,
    skip_chord_confirm: bool = False,
) -> int:
    """Rewrite the plist for the current binary, re-check TCC, and bounce."""
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
    binary = program if program is not None else spotty_bunny_program()
    program_argv = (
        [str(program.resolve())]
        if program is not None
        else spotty_bunny_program_arguments()
    )
    if program_argv is None or binary is None:
        err(f"{COMMAND_NAME}: could not find the spotty-bunny binary on PATH.")
        return 1
    prepared = _prepare_program_launch(
        program_argv=program_argv,
        binary=binary,
        err=err,
        plist=plist,
    )
    if prepared is None:
        return 1
    program_argv, binary, interpreter = prepared
    status = _require_current_tcc(
        interpreter,
        err=err,
        probe_tcc=probe_tcc,
        prompt_fn=prompt_fn,
        request_tcc=request_tcc,
    )
    if status is None:
        return 1
    _write_plist(plist, home=root, program_arguments=program_argv)
    if not _reload_agent(
        plist,
        launchctl=launchctl,
        pid_dir=pid_dir,
    ):
        err(f"{COMMAND_NAME}: launchctl bootstrap failed for {plist}.")
        return 1
    err(f"{COMMAND_NAME}: refreshed LaunchAgent {AGENT_LABEL}")
    err(f"{COMMAND_NAME}: binary {binary}")
    err(f"{COMMAND_NAME}: interpreter {interpreter_realpath(interpreter)}")
    if skip_chord_confirm or _confirm_chord_works(
        plist,
        err=err,
        launchctl=launchctl,
        pid_dir=pid_dir,
        prompt_fn=prompt_fn,
    ):
        return 0
    return 1


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


def _expand_shell_vars(token: str, assignments: Mapping[str, str]) -> str:
    """Expand ``$HOME`` / ``$name`` / ``${name}`` with longest-name-first passes."""
    home = str(Path.home())
    values: dict[str, str] = {"HOME": home}
    for name in sorted(assignments, key=len, reverse=True):
        values[name] = _substitute_shell_vars(
            assignments[name].replace("${HOME}", home).replace("$HOME", home),
            values,
        )
    return _substitute_shell_vars(
        token.replace("${HOME}", home).replace("$HOME", home),
        values,
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


def _pid_text(*, pid_dir: Path | None) -> str:
    from app.spotty_bunny_launch import read_spotty_bunny_runtime

    runtime = read_spotty_bunny_runtime(pid_dir=pid_dir)
    if runtime is None:
        return "none"
    return str(runtime[0])


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


def _prepare_program_launch(
    *,
    program_argv: list[str],
    binary: Path,
    err: Callable[[str], None],
    plist: Path | None,
) -> tuple[list[str], Path, Path] | None:
    launch_binary = Path(program_argv[0])
    if not _program_launch_target_ok(launch_binary):
        err(
            f"{COMMAND_NAME}: binary missing or not executable: "
            f"{launch_binary.expanduser()}"
        )
        return None
    interpreter = interpreter_for_program(launch_binary)
    if plist is not None and plist.is_file():
        old_argv = _plist_program_arguments(plist)
        if old_argv:
            old_interp = interpreter_realpath(
                interpreter_for_program(Path(old_argv[0]))
            )
            new_interp = interpreter_realpath(interpreter)
            if old_interp != new_interp:
                err(
                    f"{COMMAND_NAME}: Python interpreter changed "
                    f"({old_interp} → {new_interp})."
                )
                err(
                    f"{COMMAND_NAME}: re-grant Accessibility and Input Monitoring "
                    f"to {new_interp} in System Settings → Privacy & Security, "
                    f"then re-run: {COMMAND_NAME} upgrade"
                )
    return program_argv, binary, interpreter


def _program_launch_target_ok(path: Path) -> bool:
    try:
        resolved = path.expanduser().resolve(strict=False)
    except OSError:
        return False
    return resolved.is_file() and os.access(resolved, os.X_OK)


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


def _print_err(message: str) -> None:
    print(message, file=sys.stderr)


def _confirm_chord_works(
    plist: Path,
    *,
    err: Callable[[str], None],
    launchctl: LaunchctlFn | None,
    pid_dir: Path | None,
    prompt_fn: Callable[[str], str] | None,
) -> bool:
    """Prompt until the user confirms the Control chord works, bouncing on retry."""
    ask = prompt_fn or input
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        err(POST_INSTALL_HINT)
        return True
    while True:
        err(POST_INSTALL_HINT)
        try:
            answer = ask(CHORD_TEST_PROMPT)
        except EOFError, KeyboardInterrupt:
            return False
        if answer.strip().lower() in {"y", "yes"}:
            return True
        err(CHORD_RETRY_HINT)
        if not _reload_agent(plist, launchctl=launchctl, pid_dir=pid_dir):
            err(f"{COMMAND_NAME}: could not restart the LaunchAgent.")
            return False


def _probe_tcc(interpreter: Path) -> TccStatus:
    return _run_tcc_probe(interpreter, prompt=False)


def _request_tcc(interpreter: Path) -> TccStatus:
    return _run_tcc_probe(interpreter, prompt=True)


def _require_current_tcc(
    interpreter: Path,
    *,
    err: Callable[[str], None],
    probe_tcc: TccFn | None,
    prompt_fn: Callable[[str], str] | None = None,
    request_tcc: TccFn | None,
) -> TccStatus | None:
    probe = probe_tcc or _probe_tcc
    request = request_tcc or _request_tcc
    try:
        status = probe(interpreter)
        if not status.ok:
            request(interpreter)
            status = probe(interpreter)
    except ImportError:
        err(MACOS_EXTRA_HINT)
        return None
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        err(f"{COMMAND_NAME}: could not verify TCC for {interpreter}: {exc}")
        return None
    if not status.ok:
        err(TCC_INSTRUCTIONS)
        err(f"{COMMAND_NAME}: interpreter {interpreter}")
        err(
            f"{COMMAND_NAME}: accessibility="
            f"{'yes' if status.accessibility else 'no'} "
            f"input_monitoring={'yes' if status.input_monitoring else 'no'}"
        )
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            err(f"Then re-run: {COMMAND_NAME} install")
            return None
        while not status.ok:
            try:
                (prompt_fn or input)(TCC_RECHECK_PROMPT)
            except EOFError, KeyboardInterrupt:
                return None
            try:
                status = probe(interpreter)
            except ImportError:
                err(MACOS_EXTRA_HINT)
                return None
            except (OSError, subprocess.SubprocessError, ValueError) as exc:
                err(f"{COMMAND_NAME}: could not verify TCC for {interpreter}: {exc}")
                return None
            if status.ok:
                return status
            err(
                f"{COMMAND_NAME}: accessibility="
                f"{'yes' if status.accessibility else 'no'} "
                f"input_monitoring={'yes' if status.input_monitoring else 'no'}"
            )
        return status
    return status


def _reload_agent(
    plist: Path,
    *,
    launchctl: LaunchctlFn | None = None,
    pid_dir: Path | None = None,
) -> bool:
    """Boot out, stop stale overlays, and bootstrap the LaunchAgent."""
    _bootout_agent(launchctl=launchctl)
    stop_spotty_bunny(pid_dir=pid_dir)
    clear_spotty_bunny_pid(pid_dir=pid_dir)
    if _bootstrap_agent(plist, launchctl=launchctl):
        return True
    _bootout_agent(launchctl=launchctl)
    return _bootstrap_agent(plist, launchctl=launchctl)


def _run_tcc_probe(interpreter: Path, *, prompt: bool) -> TccStatus:
    completed = subprocess.run(
        [str(interpreter), "-c", _TCC_PROBE, "1" if prompt else "0"],
        capture_output=True,
        check=False,
        text=True,
        timeout=TCC_PROBE_TIMEOUT_S,
    )
    if completed.returncode == 2:
        raise ImportError("PyObjC is required to probe TCC")
    if completed.returncode != 0:
        raise OSError(
            completed.stderr.strip() or completed.stdout.strip() or "tcc probe failed"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise OSError(f"tcc probe returned invalid JSON: {exc}") from exc
    try:
        return TccStatus(
            accessibility=bool(payload["accessibility"]),
            input_monitoring=bool(payload["input_monitoring"]),
        )
    except (KeyError, TypeError) as exc:
        raise OSError(f"tcc probe returned invalid JSON: {exc}") from exc


def _probe_tcc_for_status(
    interpreter: Path | None,
    *,
    err: Callable[[str], None],
    probe_tcc: TccFn | None,
) -> TccStatus:
    if interpreter is None:
        return TccStatus(False, False)
    try:
        return (probe_tcc or _probe_tcc)(interpreter)
    except ImportError:
        err(MACOS_EXTRA_HINT)
        return TccStatus(False, False)
    except OSError, subprocess.SubprocessError, ValueError:
        return TccStatus(False, False)


def _shell_exec_python_from_wrapper(raw: str) -> Path | None:
    """Return the python path from a bash ``exec`` line, ignoring comments."""
    assignments: dict[str, str] = {}
    assign_pattern = re.compile(
        r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>[\"']?)(?P<body>[^\"'\n]*)(?P=value)$"
    )
    pattern = re.compile(
        r"^exec\s+(?:\"|\')?(?P<python>[^\"'\n]+?/bin/python(?:3(?:\.\d+)?)?)",
    )
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        assign = assign_pattern.match(stripped)
        if assign is not None:
            assignments[assign.group("name")] = assign.group("body")
            continue
        match = pattern.match(stripped)
        if match is None:
            continue
        token = match.group("python").strip("\"'")
        expanded = _expand_shell_vars(token, assignments)
        # Prefer a partially expanded exec path over falling through to the
        # shebang shell (which misleads TCC probing).
        return Path(expanded).expanduser()
    return None


def _substitute_shell_vars(text: str, values: Mapping[str, str]) -> str:
    """Replace ``$name`` / ``${name}`` until stable (longest names first)."""
    expanded = text
    for _ in range(len(values) + 2):
        previous = expanded
        for name in sorted(values, key=len, reverse=True):
            value = values[name]
            expanded = expanded.replace(f"${{{name}}}", value).replace(
                f"${name}", value
            )
        if expanded == previous:
            break
    return expanded


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
  <string>com.thehcma.bunnify.spotty-bunny</string>

  <key>ProgramArguments</key>
  <array>
__PROGRAM_ARGUMENTS__
  </array>

  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>__LAUNCHD_PATH__</string>
  </dict>

  <key>KeepAlive</key>
  <true/>
  <key>RunAtLoad</key>
  <true/>

  <key>StandardErrorPath</key>
  <string>__HOME__/Library/Logs/bunnify.spotty-bunny.err.log</string>
  <key>StandardOutPath</key>
  <string>__HOME__/Library/Logs/bunnify.spotty-bunny.out.log</string>
</dict>
</plist>
"""

_TCC_PROBE = r"""
import json
import sys

try:
    from ApplicationServices import AXIsProcessTrusted, AXIsProcessTrustedWithOptions
    from Foundation import NSDictionary
    from Quartz import CGPreflightListenEventAccess, CGRequestListenEventAccess
except ImportError:
    raise SystemExit(2)

if sys.argv[1] == "1":
    AXIsProcessTrustedWithOptions(
        NSDictionary.dictionaryWithObject_forKey_(True, "AXTrustedCheckOptionPrompt")
    )
    CGRequestListenEventAccess()
print(
    json.dumps(
        {
            "accessibility": bool(AXIsProcessTrusted()),
            "input_monitoring": bool(CGPreflightListenEventAccess()),
        }
    )
)
"""

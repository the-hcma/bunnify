"""Spotty Bunny macOS LaunchAgent (install, uninstall, status, upgrade)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

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
TCC_INSTRUCTIONS = f"""\
{COMMAND_NAME}: Accessibility and Input Monitoring must be granted to the
Python interpreter launchd will exec (the pipx/venv interpreter behind
spotty-bunny), not only Terminal.app.

System Settings → Privacy & Security → Accessibility
System Settings → Privacy & Security → Input Monitoring

Then re-run: {COMMAND_NAME} install
"""
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


def format_agent_plist(*, program: Path, home: Path) -> str:
    """Return the LaunchAgent plist for *program* and *home*."""
    return _PLIST_TEMPLATE.replace("__SPOTTY_BUNNY__", escape(str(program))).replace(
        "__HOME__", escape(str(home))
    )


def install_agent(
    *,
    home: Path | None = None,
    launchctl: LaunchctlFn | None = None,
    platform: str | None = None,
    print_err: Callable[[str], None] | None = None,
    probe_tcc: TccFn | None = None,
    program: Path | None = None,
    request_tcc: TccFn | None = None,
) -> int:
    """Write the LaunchAgent, verify TCC, and bootstrap it."""
    err = print_err or _print_err
    if not _is_darwin(platform):
        err(NOT_MACOS_MESSAGE)
        return 1
    binary = program if program is not None else spotty_bunny_program()
    if binary is None:
        err(f"{COMMAND_NAME}: could not find the spotty-bunny binary on PATH.")
        return 1
    interpreter = interpreter_for_program(binary)
    status = _require_current_tcc(
        interpreter,
        err=err,
        probe_tcc=probe_tcc,
        request_tcc=request_tcc,
    )
    if status is None:
        return 1
    root = home if home is not None else Path.home()
    plist = agent_plist_path(home=root)
    _write_plist(plist, program=binary, home=root)
    _bootout_agent(launchctl=launchctl)
    if not _bootstrap_agent(plist, launchctl=launchctl):
        err(f"{COMMAND_NAME}: launchctl bootstrap failed for {plist}.")
        return 1
    err(f"{COMMAND_NAME}: installed LaunchAgent {AGENT_LABEL}")
    err(f"{COMMAND_NAME}: plist {plist}")
    return 0


def interpreter_for_program(program: Path) -> Path:
    """Return the interpreter launchd will exec for a console-script *program*."""
    try:
        first = program.read_bytes().splitlines()[:1]
    except OSError:
        return program
    if not first or not first[0].startswith(b"#!"):
        return program
    line = first[0][2:].decode("utf-8", errors="replace").strip()
    parts = line.split()
    if not parts:
        return program
    executable = Path(parts[0])
    if executable.name == "env" and len(parts) >= 2:
        resolved = shutil.which(parts[1])
        return Path(resolved) if resolved else Path(parts[1])
    return executable


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
    """Absolute path launchd should exec (`command -v spotty-bunny`)."""
    command = spotty_bunny_command()
    if not command:
        return None
    path = Path(command[0]).expanduser()
    if path.is_absolute():
        return path
    resolved = shutil.which(command[0])
    return Path(resolved) if resolved else path.resolve()


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
    binary = program if program is not None else spotty_bunny_program()
    loaded = is_agent_loaded(launchctl=launchctl) if plist.is_file() else False
    running = spotty_bunny_is_running(pid_dir=pid_dir)
    pid_text = "none"
    if running:
        pid_text = _pid_text(pid_dir=pid_dir)
    installed = plist.is_file()
    interpreter = interpreter_for_program(binary) if binary is not None else None
    tcc = (
        (probe_tcc or _probe_tcc)(interpreter)
        if interpreter is not None
        else TccStatus(False, False)
    )
    stdout_path, stderr_path = _launchd_log_paths(plist)
    out(f"running: {'yes' if running else 'no'}")
    out(f"pid: {pid_text}")
    if not installed:
        out("launchd: not installed")
    else:
        out(f"launchd: {'loaded' if loaded else 'not loaded'}")
    out(f"binary: {binary if binary is not None else 'none'}")
    out(f"application_log: {_spotty_bunny_log_file(None)}")
    out(f"launchd_stdout: {stdout_path or 'none'}")
    out(f"launchd_stderr: {stderr_path or 'none'}")
    out(f"version: {build_version()}")
    out(f"accessibility: {'yes' if tcc.accessibility else 'no'}")
    out(f"input_monitoring: {'yes' if tcc.input_monitoring else 'no'}")
    return 0 if installed and loaded and running else 1


def uninstall_agent(
    *,
    home: Path | None = None,
    launchctl: LaunchctlFn | None = None,
    pid_dir: Path | None = None,
    platform: str | None = None,
    print_err: Callable[[str], None] | None = None,
) -> int:
    """Boot out the agent, remove the plist, stop the process, clear the pid."""
    err = print_err or _print_err
    if not _is_darwin(platform):
        err(NOT_MACOS_MESSAGE)
        return 1
    root = home if home is not None else Path.home()
    plist = agent_plist_path(home=root)
    if plist.is_file() or is_agent_loaded(launchctl=launchctl):
        _bootout_agent(launchctl=launchctl)
    plist.unlink(missing_ok=True)
    stop_spotty_bunny(pid_dir=pid_dir)
    clear_spotty_bunny_pid(pid_dir=pid_dir)
    err(f"{COMMAND_NAME}: uninstalled LaunchAgent {AGENT_LABEL}")
    return 0


def upgrade_agent(
    *,
    home: Path | None = None,
    launchctl: LaunchctlFn | None = None,
    platform: str | None = None,
    print_err: Callable[[str], None] | None = None,
    probe_tcc: TccFn | None = None,
    program: Path | None = None,
    request_tcc: TccFn | None = None,
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
    if binary is None:
        err(f"{COMMAND_NAME}: could not find the spotty-bunny binary on PATH.")
        return 1
    interpreter = interpreter_for_program(binary)
    status = _require_current_tcc(
        interpreter,
        err=err,
        probe_tcc=probe_tcc,
        request_tcc=request_tcc,
    )
    if status is None:
        return 1
    _write_plist(plist, program=binary, home=root)
    if is_agent_loaded(launchctl=launchctl):
        _kickstart_agent(launchctl=launchctl)
    elif not _bootstrap_agent(plist, launchctl=launchctl):
        err(f"{COMMAND_NAME}: launchctl bootstrap failed for {plist}.")
        return 1
    err(f"{COMMAND_NAME}: refreshed LaunchAgent {AGENT_LABEL}")
    err(f"{COMMAND_NAME}: binary {binary}")
    return 0


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


def _kickstart_agent(
    *, launchctl: LaunchctlFn | None = None, uid: int | None = None
) -> None:
    _launchctl(
        ["kickstart", "-k", f"{_gui_domain(uid)}/{AGENT_LABEL}"],
        launchctl=launchctl,
    )


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
    from app.spotty_bunny_launch import spotty_bunny_pid_path

    path = spotty_bunny_pid_path(pid_dir=pid_dir)
    try:
        return path.read_text(encoding="utf-8").strip() or "none"
    except OSError:
        return "none"


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


def _probe_tcc(interpreter: Path) -> TccStatus:
    return _run_tcc_probe(interpreter, prompt=False)


def _request_tcc(interpreter: Path) -> TccStatus:
    return _run_tcc_probe(interpreter, prompt=True)


def _require_current_tcc(
    interpreter: Path,
    *,
    err: Callable[[str], None],
    probe_tcc: TccFn | None,
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
    except (OSError, subprocess.SubprocessError) as exc:
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
        return None
    return status


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
    payload = json.loads(completed.stdout)
    return TccStatus(
        accessibility=bool(payload["accessibility"]),
        input_monitoring=bool(payload["input_monitoring"]),
    )


def _write_plist(plist: Path, *, program: Path, home: Path) -> None:
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_text(format_agent_plist(program=program, home=home), encoding="utf-8")


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
    <string>__SPOTTY_BUNNY__</string>
  </array>

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

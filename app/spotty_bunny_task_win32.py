"""Windows Scheduled Task backing Spotty Bunny autostart.

Wraps ``schtasks.exe`` via subprocess rather than ``win32com``/
``ITaskDefinition`` -- avoids COM lifetime concerns and reuses the same
fake-injection test pattern as ``app.spotty_bunny_agent._launchctl``. The
task's ``LogonTrigger`` approximates launchd's ``RunAtLoad`` and its
``RestartOnFailure`` setting approximates ``KeepAlive`` -- a bounded
approximation (999 restarts, 1-minute apart), not identical semantics to
launchd's unconditional respawn.
"""

from __future__ import annotations

import getpass
import logging
import os
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from xml.sax.saxutils import escape

logger = logging.getLogger(__name__)

SCHTASKS_TIMEOUT_S = 15
TASK_NAME = "Bunnify Spotty Bunny"
TASK_STATUS_RUNNING = "Running"

SchtasksFn = Callable[..., subprocess.CompletedProcess[str]]

_TASK_XML_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>__USER_ID__</UserId>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>__USER_ID__</UserId>
      <LogonType>InteractiveToken</LogonType>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>999</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>__COMMAND__</Command>
      <Arguments>__ARGUMENTS__</Arguments>
    </Exec>
  </Actions>
</Task>
"""


def format_task_xml(
    *, program_arguments: Sequence[str], user_id: str | None = None
) -> str:
    """Return the Scheduled Task XML for *program_arguments*.

    The ``LogonTrigger`` and ``Principal`` are scoped to *user_id* (default:
    the current ``DOMAIN\\user``). A ``LogonTrigger`` with no ``UserId``
    means "when any user logs on", which Windows only lets an elevated
    account register -- scoping it to the current user lets a standard
    account install Spotty Bunny without "Access is denied".

    ``program_arguments[0]`` becomes the Action's ``Command`` (the raw
    executable path, unquoted -- Task Scheduler treats ``Command`` as a
    single path, not a command line); the rest become ``Arguments``,
    quoted with :func:`subprocess.list2cmdline` -- the same escaping rules
    ``CommandLineToArgvW`` expects, so :func:`_split_windows_command_line`
    can parse them back out of :func:`task_program_arguments`. (Command is
    written unquoted even when it contains a space -- deliberately not
    read back from ``schtasks /Query``'s free-text "Task To Run" field,
    which concatenates Command+Arguments into one display string and would
    need its own re-quoting heuristic to round-trip a spaced path; reading
    ``<Command>``/``<Arguments>`` straight out of the XML avoids that.)
    """
    command, *rest = program_arguments
    account = user_id if user_id is not None else _current_user_id()
    return (
        _TASK_XML_TEMPLATE.replace("__COMMAND__", escape(command))
        .replace("__ARGUMENTS__", escape(subprocess.list2cmdline(rest)))
        .replace("__USER_ID__", escape(account))
    )


def create_or_update_task(
    xml: str,
    *,
    on_error: Callable[[str], None] | None = None,
    schtasks: SchtasksFn | None = None,
) -> bool:
    """Register (or replace) the Scheduled Task from *xml*. Returns success.

    On failure, ``schtasks``' own message (for example ``ERROR: Access is
    denied.``) is logged and passed to *on_error* so callers can show why.
    """
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".xml",
        encoding="utf-16",
        delete=False,
    )
    try:
        handle.write(xml)
        handle.close()
        completed = _schtasks(
            ["/Create", "/TN", TASK_NAME, "/XML", handle.name, "/F"],
            schtasks=schtasks,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            logger.warning("schtasks /Create failed: %s", detail)
            if on_error is not None and detail:
                on_error(detail)
        return completed.returncode == 0
    finally:
        Path(handle.name).unlink(missing_ok=True)


def remove_task(*, schtasks: SchtasksFn | None = None) -> bool:
    """Delete the Scheduled Task. Returns True when gone (already-gone is success)."""
    completed = _schtasks(
        ["/Delete", "/TN", TASK_NAME, "/F"],
        schtasks=schtasks,
    )
    if completed.returncode == 0:
        return True
    return _task_not_found(completed)


def is_task_installed(*, schtasks: SchtasksFn | None = None) -> bool:
    """True when the Scheduled Task is registered."""
    completed = _schtasks(["/Query", "/TN", TASK_NAME], schtasks=schtasks)
    return completed.returncode == 0


def is_task_running(*, schtasks: SchtasksFn | None = None) -> bool:
    """True when Task Scheduler itself reports the task as ``Running``."""
    completed = _schtasks(
        ["/Query", "/TN", TASK_NAME, "/FO", "LIST", "/V"],
        schtasks=schtasks,
    )
    if completed.returncode != 0:
        return False
    return _status_from_query_output(completed.stdout) == TASK_STATUS_RUNNING


def run_task_once(*, schtasks: SchtasksFn | None = None) -> bool:
    """Trigger an immediate run of the registered task."""
    completed = _schtasks(["/Run", "/TN", TASK_NAME], schtasks=schtasks)
    return completed.returncode == 0


def task_xml(*, schtasks: SchtasksFn | None = None) -> str | None:
    """Return the currently-registered task's XML, or None if not installed."""
    completed = _schtasks(["/Query", "/TN", TASK_NAME, "/XML"], schtasks=schtasks)
    if completed.returncode != 0:
        return None
    return completed.stdout


def task_program_arguments(*, schtasks: SchtasksFn | None = None) -> list[str] | None:
    """Argv Task Scheduler will exec, read from the registered task's XML."""
    xml = task_xml(schtasks=schtasks)
    if xml is None:
        return None
    return _program_arguments_from_xml(xml)


def _current_user_id() -> str:
    """The logged-on account as ``DOMAIN\\user`` (bare ``user`` without a domain)."""
    user = getpass.getuser()
    domain = os.environ.get("USERDOMAIN")
    return f"{domain}\\{user}" if domain else user


def _program_arguments_from_xml(xml: str) -> list[str] | None:
    command = _xml_tag_text(xml, "Command")
    if not command:
        return None
    arguments = _xml_tag_text(xml, "Arguments")
    return [command, *_split_windows_command_line(arguments)]


def _xml_tag_text(xml: str, tag: str) -> str:
    from html import unescape

    start = xml.find(f"<{tag}>")
    end = xml.find(f"</{tag}>")
    if start < 0 or end < 0 or end <= start:
        return ""
    return unescape(xml[start + len(tag) + 2 : end])


def _field_from_query_output(text: str, field: str) -> str | None:
    prefix = f"{field.lower()}:"
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith(prefix):
            return stripped[len(prefix) :].strip()
    return None


def _status_from_query_output(text: str) -> str | None:
    return _field_from_query_output(text, "Status")


def _split_windows_command_line(command: str) -> list[str]:
    """Split a command line using ``CommandLineToArgvW``'s quoting rules.

    Deliberately reimplemented in pure Python (not
    ``ctypes.windll.shell32.CommandLineToArgvW``) so it can be
    fixture-tested against realistic ``schtasks`` output on any host OS,
    not only real Windows.
    """
    args: list[str] = []
    current: list[str] = []
    in_quotes = False
    i = 0
    n = len(command)
    while i < n:
        char = command[i]
        if char == "\\":
            num_backslashes = 0
            while i < n and command[i] == "\\":
                num_backslashes += 1
                i += 1
            if i < n and command[i] == '"':
                current.append("\\" * (num_backslashes // 2))
                if num_backslashes % 2 == 1:
                    current.append('"')
                else:
                    in_quotes = not in_quotes
                i += 1
            else:
                current.append("\\" * num_backslashes)
            continue
        if char == '"':
            in_quotes = not in_quotes
            i += 1
            continue
        if char in (" ", "\t") and not in_quotes:
            if current:
                args.append("".join(current))
                current = []
            i += 1
            while i < n and command[i] in (" ", "\t"):
                i += 1
            continue
        current.append(char)
        i += 1
    if current:
        args.append("".join(current))
    return args


def _task_not_found(completed: subprocess.CompletedProcess[str]) -> bool:
    combined = f"{completed.stdout}\n{completed.stderr}".lower()
    return "cannot find" in combined


def _schtasks(
    args: Sequence[str],
    *,
    schtasks: SchtasksFn | None = None,
) -> subprocess.CompletedProcess[str]:
    argv = ["schtasks", *args]
    runner = schtasks or subprocess.run
    try:
        return runner(
            argv,
            capture_output=True,
            check=False,
            text=True,
            timeout=SCHTASKS_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(argv, 1, "", str(exc))

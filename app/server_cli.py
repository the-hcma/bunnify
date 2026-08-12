"""Installed command-line entry point for the managed Bunnify server."""

from __future__ import annotations

import argparse
import logging
import os
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from app.client import check_health
from app.config import data_dir, ensure_user_bookmarks, run_dir
from app.version import build_version

LOG_LEVELS = ("CRITICAL", "DEBUG", "ERROR", "INFO", "WARNING")


@dataclass(frozen=True)
class ServerOptions:
    bookmarks: Path | None
    console: bool
    foreground: bool
    listen_all: bool
    log_file: Path
    log_level: str
    noninteractive: bool
    pid_dir: Path
    port: int
    stop: bool


def build_parser() -> argparse.ArgumentParser:
    """Build the ``bunnify-server`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="bunnify-server",
        description=(
            "Start the Bunnify Django server and reload bookmarks when their "
            "JSON file changes."
        ),
    )
    parser.add_argument(
        "-f",
        "--bookmarks",
        type=Path,
        help="Bookmarks JSON file (default: XDG config bookmarks.json).",
    )
    parser.add_argument(
        "--console",
        action="store_true",
        help="Run in the foreground and enable console logging.",
    )
    parser.add_argument(
        "--foreground",
        action="store_true",
        help="Run in the foreground instead of starting a background process.",
    )
    parser.add_argument(
        "--listen-all",
        action="store_true",
        help="Listen on all IPv4 interfaces instead of localhost only.",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Log file (default: BUNNIFY_DATA_DIR/bunnify.log).",
    )
    parser.add_argument(
        "--log-level",
        type=str.upper,
        choices=LOG_LEVELS,
        default="WARNING",
        help="Application log level (default: WARNING).",
    )
    parser.add_argument(
        "-y",
        "--noninteractive",
        action="store_true",
        help="Never prompt and apply pending database migrations.",
    )
    parser.add_argument(
        "--pid-dir",
        type=Path,
        default=None,
        help="Directory for managed PID and port files.",
    )
    parser.add_argument(
        "--port",
        type=_port_value,
        default=8000,
        help="TCP port, or 0 for an OS-selected ephemeral port (default: 8000).",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Stop the server identified by files under --pid-dir.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {build_version()}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the installed server command."""
    options = _parse_options(argv)
    options.pid_dir.mkdir(parents=True, exist_ok=True)
    if options.stop:
        return _stop_managed_server(options.pid_dir)

    try:
        bookmarks = _ensure_bookmarks(options)
        _stop_managed_server(options.pid_dir, quiet=True)
        port = _resolve_port(options.port)
        if options.foreground or options.console:
            return _run_foreground(options, bookmarks, port)
        return _start_background(options, bookmarks, port)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"bunnify-server: error: {exc}", file=sys.stderr)
        return 1


def _background_command(
    options: ServerOptions,
    bookmarks: Path,
    port: int,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "app.server_cli",
        "--bookmarks",
        str(bookmarks),
        "--foreground",
        "--log-file",
        str(options.log_file),
        "--log-level",
        options.log_level,
        "--noninteractive",
        "--pid-dir",
        str(options.pid_dir),
        "--port",
        str(port),
    ]
    if options.listen_all:
        command.append("--listen-all")
    return command


def _cleanup_files(pid_dir: Path, *, owner_pid: int | None = None) -> None:
    pid_file, port_file, watcher_pid_file = _pid_paths(pid_dir)
    if owner_pid is not None and _read_pid(pid_file) not in {None, owner_pid}:
        return
    pid_file.unlink(missing_ok=True)
    port_file.unlink(missing_ok=True)
    watcher_pid_file.unlink(missing_ok=True)


def _configure_environment(options: ServerOptions) -> None:
    options.log_file.parent.mkdir(parents=True, exist_ok=True)
    os.environ["BUNNIFY_LOG_CONSOLE"] = "true" if options.console else "false"
    os.environ["BUNNIFY_LOG_FILE"] = str(options.log_file)
    os.environ["BUNNIFY_LOG_LEVEL"] = options.log_level
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")


def _ensure_bookmarks(options: ServerOptions) -> Path:
    if options.bookmarks is None:
        try:
            return ensure_user_bookmarks(
                allow_prompt=not options.noninteractive,
                print_fn=print,
            ).resolve()
        except FileNotFoundError as exc:
            raise RuntimeError(str(exc)) from exc
    bookmarks = options.bookmarks.expanduser().resolve()
    if not bookmarks.is_file():
        raise RuntimeError(f"bookmarks file not found: {bookmarks}")
    return bookmarks


def _initialize_database(*, bookmarks: Path, noninteractive: bool) -> None:
    import django
    from django.core.management import call_command
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    django.setup()
    executor = MigrationExecutor(connection)
    pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
    if pending:
        should_migrate = noninteractive
        if not should_migrate and sys.stdin.isatty():
            answer = input(
                f"Database has {len(pending)} pending migration(s). Apply them? [y/N]: "
            )
            should_migrate = answer.strip().lower() in {"y", "yes"}
        if not should_migrate:
            raise RuntimeError(
                "database needs migrations; rerun with --noninteractive or migrate it"
            )
        call_command("migrate", interactive=False, verbosity=0)
    call_command("load_bookmarks", file=str(bookmarks), verbosity=0)


def _is_bunnify_command(command: str) -> bool:
    try:
        arguments = shlex.split(command)
    except ValueError:
        return False
    if not arguments:
        return False

    if len(arguments) >= 3 and arguments[1:3] == ["-m", "app.server_cli"]:
        return True
    executable_names = {Path(argument).name for argument in arguments[:2]}
    return "bunnify-server" in executable_names


def _is_bunnify_process(pid: int) -> bool:
    command = _process_command(pid)
    return command is not None and _is_bunnify_command(command)


def _is_process_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _listener_pids(port: int) -> list[int]:
    """Return PIDs listening on TCP ``port`` (best-effort via ``lsof``)."""
    try:
        completed = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except OSError, subprocess.TimeoutExpired:
        return []
    pids: list[int] = []
    for line in completed.stdout.splitlines():
        try:
            pids.append(int(line.strip()))
        except ValueError:
            continue
    return pids


def _parse_options(argv: list[str] | None) -> ServerOptions:
    namespace = build_parser().parse_args(argv)
    console = bool(namespace.console)
    default_log_file = (os.environ.get("BUNNIFY_LOG_FILE") or "").strip()
    log_file = namespace.log_file or (
        Path(default_log_file) if default_log_file else data_dir() / "bunnify.log"
    )
    return ServerOptions(
        bookmarks=namespace.bookmarks,
        console=console,
        foreground=bool(namespace.foreground) or console,
        listen_all=bool(namespace.listen_all),
        log_file=log_file.expanduser(),
        log_level=namespace.log_level,
        noninteractive=bool(namespace.noninteractive),
        pid_dir=(namespace.pid_dir or run_dir()).expanduser(),
        port=namespace.port,
        stop=bool(namespace.stop),
    )


def _pid_dir_from_command(command: str) -> Path | None:
    """Return ``--pid-dir`` from a process command line, if present."""
    try:
        arguments = shlex.split(command)
    except ValueError:
        return None
    try:
        index = arguments.index("--pid-dir")
    except ValueError:
        return None
    if index + 1 >= len(arguments):
        return None
    return Path(arguments[index + 1]).expanduser()


def _pid_paths(pid_dir: Path) -> tuple[Path, Path, Path]:
    return (
        pid_dir / ".bunnify.pid",
        pid_dir / ".bunnify.port",
        pid_dir / ".bunnify_watcher.pid",
    )


def _port_from_command(command: str) -> int | None:
    """Return ``--port`` from a process command line when it is a fixed port."""
    try:
        arguments = shlex.split(command)
    except ValueError:
        return None
    try:
        index = arguments.index("--port")
    except ValueError:
        return None
    if index + 1 >= len(arguments):
        return None
    try:
        port = int(arguments[index + 1])
    except ValueError:
        return None
    if not 1 <= port <= 65535:
        return None
    return port


def _port_is_free(port: int) -> bool:
    """Return whether ``port`` can be bound with ``SO_REUSEADDR``.

    Matches Django's runserver reuse behavior so a draining listen socket after
    SIGTERM is not mistaken for an active occupant.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            candidate.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _port_value(raw: str) -> int:
    try:
        port = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("must be between 0 and 65535")
    return port


def _process_command(pid: int) -> str | None:
    """Return the ``ps`` command line for ``pid``, or ``None`` on failure."""
    if not _is_process_running(pid):
        return None
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


def _process_managed_by_pid_dir(pid: int, pid_dir: Path) -> bool:
    """Return whether ``pid`` is a Bunnify server for this ``pid_dir``.

    Processes started without an explicit ``--pid-dir`` use the default
    :func:`run_dir` (same as ``_parse_options``), so treat a missing flag as
    that default rather than as a mismatch.
    """
    command = _process_command(pid)
    if command is None or not _is_bunnify_command(command):
        return False
    recorded = _pid_dir_from_command(command)
    if recorded is None:
        recorded = run_dir()
    try:
        return recorded.resolve() == pid_dir.expanduser().resolve()
    except OSError:
        return recorded.expanduser() == pid_dir.expanduser()


def _read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except OSError, ValueError:
        return None


def _read_port(path: Path) -> int | None:
    try:
        port = int(path.read_text(encoding="utf-8").strip())
    except OSError, ValueError:
        return None
    if not 1 <= port <= 65535:
        return None
    return port


def _resolve_port(requested_port: int) -> int:
    if requested_port:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
            candidate.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                candidate.bind(("127.0.0.1", requested_port))
            except OSError as exc:
                raise RuntimeError(f"port {requested_port} is already in use") from exc
        return requested_port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


def _run_foreground(
    options: ServerOptions,
    bookmarks: Path,
    port: int,
) -> int:
    _configure_environment(options)
    _initialize_database(
        bookmarks=bookmarks,
        noninteractive=options.noninteractive,
    )
    from django.core.management import call_command

    _write_runtime_files(options.pid_dir, port)
    _start_watcher(bookmarks)

    def handle_signal(signum: int, _frame: object) -> None:
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGHUP, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    address = "0.0.0.0" if options.listen_all else "127.0.0.1"
    print(f"Bunnify server listening at http://{address}:{port}/")
    try:
        call_command(
            "runserver",
            f"{address}:{port}",
            use_reloader=False,
        )
    except KeyboardInterrupt:
        return 130
    finally:
        _cleanup_files(options.pid_dir, owner_pid=os.getpid())
    return 0


def _start_background(
    options: ServerOptions,
    bookmarks: Path,
    port: int,
) -> int:
    _configure_environment(options)
    _initialize_database(
        bookmarks=bookmarks,
        noninteractive=options.noninteractive,
    )
    startup_log = options.pid_dir / "bunnify-startup.log"
    with startup_log.open("a", encoding="utf-8") as output:
        process = subprocess.Popen(
            _background_command(options, bookmarks, port),
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    _write_runtime_files(options.pid_dir, port, pid=process.pid)

    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        if check_health(base_url):
            print(f"Bunnify server started at {base_url} (PID {process.pid})")
            return 0
        time.sleep(0.2)

    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    _cleanup_files(options.pid_dir, owner_pid=process.pid)
    try:
        detail = startup_log.read_text(encoding="utf-8")[-4000:].strip()
    except OSError:
        detail = ""
    suffix = f"\n{detail}" if detail else ""
    raise RuntimeError(f"server did not become healthy within 30 seconds{suffix}")


def _start_watcher(bookmarks: Path) -> None:
    from django.core.management import call_command

    def watch() -> None:
        try:
            call_command("watch_bookmarks", file=str(bookmarks), verbosity=0)
        except Exception:
            logging.getLogger(__name__).exception("Bookmark watcher stopped")

    threading.Thread(
        target=watch,
        name="bunnify-bookmark-watcher",
        daemon=True,
    ).start()


def _stop_managed_server(pid_dir: Path, *, quiet: bool = False) -> int:
    """SIGTERM the managed server, wait for exit, then confirm its port is free."""
    pid_file, port_file, _watcher_pid_file = _pid_paths(pid_dir)
    pid = _read_pid(pid_file)
    port = _read_port(port_file)
    if pid == os.getpid():
        return 0

    signaled_pids: list[int] = []
    if pid is not None and _is_process_running(pid):
        if not _process_managed_by_pid_dir(pid, pid_dir):
            _cleanup_files(pid_dir)
            if not quiet:
                if _is_bunnify_process(pid):
                    print(
                        f"Refusing to stop process {pid} "
                        "(different --pid-dir); removed stale PID files."
                    )
                else:
                    print(
                        f"Refusing to stop unrelated process {pid}; "
                        "removed stale PID files."
                    )
            return 0
        if port is None:
            command = _process_command(pid)
            if command is not None:
                port = _port_from_command(command)
        _terminate_pid(pid)
        signaled_pids.append(pid)

    if port is not None and not _port_is_free(port):
        for listener_pid in _listener_pids(port):
            if listener_pid == os.getpid() or listener_pid in signaled_pids:
                continue
            if not _process_managed_by_pid_dir(listener_pid, pid_dir):
                continue
            _terminate_pid(listener_pid)
            signaled_pids.append(listener_pid)

    should_wait_for_port = bool(signaled_pids) or not quiet
    if (
        port is not None
        and should_wait_for_port
        and not _wait_for_port_free(port, timeout_s=15)
    ):
        _cleanup_files(pid_dir)
        if not quiet:
            print(f"Port {port} is still busy after stop.", file=sys.stderr)
        return 1

    _cleanup_files(pid_dir)
    if not quiet:
        if signaled_pids:
            stopped = ", ".join(str(value) for value in signaled_pids)
            print(f"Stopped Bunnify server (PID {stopped}).")
        else:
            print("Bunnify was not running.")
    return 0


def _terminate_pid(pid: int) -> None:
    """Send SIGTERM, escalate to SIGKILL if the process does not exit."""
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
        if not _is_process_running(pid):
            return True
        time.sleep(0.1)
    return not _is_process_running(pid)


def _wait_for_port_free(port: int, *, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _port_is_free(port):
            return True
        time.sleep(0.05)
    return _port_is_free(port)


def _write_runtime_files(pid_dir: Path, port: int, *, pid: int | None = None) -> None:
    pid_file, port_file, watcher_pid_file = _pid_paths(pid_dir)
    pid_dir.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(f"{pid or os.getpid()}\n", encoding="utf-8")
    port_file.write_text(f"{port}\n", encoding="utf-8")
    watcher_pid_file.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())

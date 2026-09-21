"""Windows behavior of the managed server helpers (#535)."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from app import server_cli
from bookmarks.win32_test_support import real_win32_available

_NETSTAT = """
Active Connections

  Proto  Local Address          Foreign Address        State           PID
  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       1180
  TCP    127.0.0.1:8000         0.0.0.0:0              LISTENING       4242
  TCP    127.0.0.1:8000         127.0.0.1:50122        ESTABLISHED     9999
  TCP    127.0.0.1:18000        0.0.0.0:0              LISTENING       5000
  TCP    [::]:8000              [::]:0                 LISTENING       4242
  TCP    0.0.0.0:8000           0.0.0.0:0              LISTENING       7777
  TCP    0.0.0.0:8000           0.0.0.0:0              LISTENING       notapid
  TCP    127.0.0.1:8000         0.0.0.0:0              ABHÖREN         6161
  TCP    127.0.0.1:8000         0.0.0.0:0              À L'ÉCOUTE      6262
"""

_LAUNCHER = (
    '"C:\\Users\\a b\\.local\\bin\\bunnify-server.exe" --bunnify-build '
    'server:0.15.0 --port 8123 --pid-dir "C:\\Users\\a b\\run"'
)
_MODULE = (
    '"C:\\pipx\\venvs\\bunnify\\Scripts\\python.exe" -m app.server_cli '
    "--bunnify-build server:0.15.0 --foreground --port 8123"
)


class _Win32(SimpleTestCase):
    def setUp(self) -> None:
        self.enterContext(patch("app.server_cli.sys.platform", "win32"))


class ParseNetstatTests(SimpleTestCase):
    def test_returns_the_listeners_on_the_port_once_each(self) -> None:
        self.assertEqual(
            server_cli._parse_netstat_listeners(_NETSTAT, 8000),
            [4242, 7777, 6161, 6262],
        )

    def test_ignores_other_ports_and_non_listening_rows(self) -> None:
        self.assertEqual(server_cli._parse_netstat_listeners(_NETSTAT, 18000), [5000])
        self.assertEqual(server_cli._parse_netstat_listeners(_NETSTAT, 50122), [])
        self.assertEqual(server_cli._parse_netstat_listeners("", 8000), [])

    def test_a_port_that_is_only_a_suffix_of_another_does_not_match(self) -> None:
        # ":8000" must not match ":18000".
        self.assertEqual(server_cli._parse_netstat_listeners(_NETSTAT, 800), [])


class WindowsCommandLineTests(_Win32):
    def test_quoted_paths_with_spaces_and_backslashes_split_correctly(self) -> None:
        self.assertEqual(
            server_cli._split_command(_LAUNCHER),
            [
                "C:\\Users\\a b\\.local\\bin\\bunnify-server.exe",
                "--bunnify-build",
                "server:0.15.0",
                "--port",
                "8123",
                "--pid-dir",
                "C:\\Users\\a b\\run",
            ],
        )

    def test_the_console_script_and_a_module_launch_are_recognized(self) -> None:
        self.assertTrue(server_cli._is_bunnify_command(_LAUNCHER))
        self.assertTrue(server_cli._is_bunnify_command(_MODULE))

    def test_the_server_is_recognized_whatever_case_it_was_launched_with(self) -> None:
        # Windows file names are case-insensitive; --stop must not treat a
        # running "Bunnify-Server" as an unrelated process.
        for launcher in (
            "C:\\Users\\a\\.local\\bin\\Bunnify-Server.EXE --foreground",
            "BUNNIFY-SERVER --foreground",
            "C:\\PIPX\\bunnify\\Scripts\\PYTHON.EXE -m app.server_cli --foreground",
        ):
            with self.subTest(launcher):
                self.assertTrue(server_cli._is_bunnify_command(launcher))

    def test_other_programs_are_not_the_server(self) -> None:
        for command in (
            "C:\\Windows\\System32\\notepad.exe bunnify-server.txt",
            '"C:\\Python\\python.exe" C:\\scripts\\other.py',
            '"C:\\bin\\spotty-bunny.exe" --bunnify-build spotty-bunny:0.15.0',
        ):
            with self.subTest(command):
                self.assertFalse(server_cli._is_bunnify_command(command))

    def test_a_sibling_component_marker_rules_the_launcher_out(self) -> None:
        sibling = (
            '"C:\\Users\\a\\.local\\bin\\bunnify-server.exe" --bunnify-build '
            "spotty-bunny:0.15.0+abc123"
        )
        self.assertFalse(server_cli._is_bunnify_command(sibling))

    def test_pid_dir_and_port_come_from_a_windows_command_line(self) -> None:
        self.assertEqual(
            server_cli._pid_dir_from_command(_LAUNCHER), Path("C:\\Users\\a b\\run")
        )
        self.assertEqual(server_cli._port_from_command(_LAUNCHER), 8123)

    def test_the_program_name_drops_exe_and_folds_case_only_on_windows(self) -> None:
        self.assertEqual(
            server_cli._program_name("C:\\x\\Bunnify-Server.EXE"), "bunnify-server"
        )
        with patch("app.server_cli.sys.platform", "linux"):
            self.assertEqual(
                server_cli._program_name("/x/bunnify-server"), "bunnify-server"
            )
            self.assertEqual(
                server_cli._program_name("/x/bunnify-server.exe"), "bunnify-server.exe"
            )


class WindowsProcessTests(_Win32):
    def test_liveness_uses_openprocess_never_os_kill(self) -> None:
        with (
            patch("os.kill", side_effect=OSError(87, "The parameter is incorrect")),
            patch(
                "app.spotty_bunny_launch._win32_process_alive", return_value=True
            ) as alive,
        ):
            self.assertTrue(server_cli._is_process_running(4242))
        alive.assert_called_once_with(4242)

    def test_a_non_positive_pid_is_never_running(self) -> None:
        self.assertFalse(server_cli._is_process_running(0))
        self.assertFalse(server_cli._is_process_running(-1))

    def test_the_command_line_comes_from_the_process_itself_not_ps(self) -> None:
        with (
            patch("app.server_cli._is_process_running", return_value=True),
            patch("app.server_cli.subprocess.run") as run,
            patch(
                "app.spotty_bunny_launch._win32_process_command_line",
                return_value=_LAUNCHER,
            ),
        ):
            self.assertEqual(server_cli._process_command(4242), _LAUNCHER)
        run.assert_not_called()

    def test_no_command_line_for_a_process_that_is_gone(self) -> None:
        with patch("app.server_cli._is_process_running", return_value=False):
            self.assertIsNone(server_cli._process_command(4242))

    def test_terminate_uses_terminateprocess_and_waits_for_the_exit(self) -> None:
        with (
            patch("os.kill", side_effect=AssertionError("os.kill on Windows")),
            patch(
                "app.spotty_bunny_launch._win32_terminate_pid", return_value=True
            ) as term,
            patch("app.server_cli._wait_for_exit", return_value=True) as wait,
        ):
            server_cli._terminate_pid(4242)
        term.assert_called_once_with(4242)
        wait.assert_called_once_with(4242, timeout_s=10)

    def test_a_refused_stop_of_a_live_process_is_an_error_not_a_success(self) -> None:
        # e.g. the server runs elevated: OpenProcess(PROCESS_TERMINATE) fails
        # while the process is still alive.
        with (
            patch("app.spotty_bunny_launch._win32_terminate_pid", return_value=False),
            patch("app.server_cli._is_process_running", return_value=True),
            patch("app.server_cli._wait_for_exit") as wait,
            self.assertRaises(PermissionError),
        ):
            server_cli._terminate_pid(4242)
        wait.assert_not_called()

    def test_a_process_that_is_already_gone_is_not_an_error(self) -> None:
        with (
            patch("app.spotty_bunny_launch._win32_terminate_pid", return_value=False),
            patch("app.server_cli._is_process_running", return_value=False),
            patch("app.server_cli._wait_for_exit") as wait,
        ):
            server_cli._terminate_pid(4242)  # returns quietly
        wait.assert_not_called()

    def test_stop_reports_a_refused_stop_and_exits_nonzero(self) -> None:
        from io import StringIO
        from tempfile import TemporaryDirectory

        stderr = StringIO()
        with (
            TemporaryDirectory() as tmp,
            patch(
                "app.server_cli._stop_managed_server",
                side_effect=PermissionError("could not stop process 4242"),
            ),
            patch("app.server_cli.sys.stderr", stderr),
        ):
            code = server_cli.main(["--stop", "--pid-dir", tmp])
        self.assertEqual(code, 1)
        self.assertIn("could not stop process 4242", stderr.getvalue())

    def test_listeners_come_from_netstat_not_lsof(self) -> None:
        completed = subprocess.CompletedProcess([], 0, _NETSTAT, "")
        with patch("app.server_cli.subprocess.run", return_value=completed) as run:
            self.assertEqual(server_cli._listener_pids(8000), [4242, 7777, 6161, 6262])
        self.assertEqual(run.call_args.args[0][0], "netstat")

    def test_a_missing_or_slow_netstat_means_no_listeners(self) -> None:
        for error in (OSError("no netstat"), subprocess.TimeoutExpired("netstat", 10)):
            with (
                self.subTest(type(error).__name__),
                patch("app.server_cli.subprocess.run", side_effect=error),
            ):
                self.assertEqual(server_cli._listener_pids(8000), [])


class PosixBehaviorIsUnchangedTests(SimpleTestCase):
    def setUp(self) -> None:
        self.enterContext(patch("app.server_cli.sys.platform", "linux"))

    def test_liveness_still_probes_with_signal_zero(self) -> None:
        with patch("os.kill") as kill:
            self.assertTrue(server_cli._is_process_running(4242))
        kill.assert_called_once_with(4242, 0)

    def test_listeners_still_come_from_lsof(self) -> None:
        completed = subprocess.CompletedProcess([], 0, "4242\n7777\n", "")
        with patch("app.server_cli.subprocess.run", return_value=completed) as run:
            self.assertEqual(server_cli._listener_pids(8000), [4242, 7777])
        self.assertEqual(run.call_args.args[0][0], "lsof")

    def test_terminate_still_escalates_from_sigterm_to_sigkill(self) -> None:
        import signal

        sigkill = getattr(signal, "SIGKILL", 9)
        with (
            patch("os.kill") as kill,
            patch("app.server_cli._wait_for_exit", side_effect=[False, True]),
            patch(
                "app.server_cli.signal", SimpleNamespace(SIGTERM=15, SIGKILL=sigkill)
            ),
        ):
            server_cli._terminate_pid(4242)
        self.assertEqual([call.args[1] for call in kill.call_args_list], [15, sigkill])

    def test_command_lines_still_split_the_posix_way(self) -> None:
        self.assertEqual(
            server_cli._split_command("/bin/x --pid-dir '/a b/run'"),
            ["/bin/x", "--pid-dir", "/a b/run"],
        )


class StartupStopTests(SimpleTestCase):
    """The starter records Popen.pid; on Windows that is the venv launcher stub."""

    def _stop_with_recorded_pid(self, recorded: int) -> MagicMock:
        from tempfile import TemporaryDirectory

        with (
            TemporaryDirectory() as tmp,
            patch("app.server_cli._terminate_pid") as terminate,
            patch("app.server_cli._is_process_running", return_value=True),
            patch("app.server_cli._process_managed_by_pid_dir", return_value=True),
            patch("app.server_cli._port_is_free", return_value=True),
        ):
            pid_dir = Path(tmp)
            server_cli._pid_paths(pid_dir)[0].write_text(
                f"{recorded}\n", encoding="utf-8"
            )
            self.assertEqual(server_cli._stop_managed_server(pid_dir, quiet=True), 0)
        return terminate

    def test_the_process_that_started_us_is_never_stopped(self) -> None:
        # Otherwise the new server terminates its launcher (and, through the
        # launcher's job object, itself) as its first act.
        self._stop_with_recorded_pid(os.getppid()).assert_not_called()

    def test_this_process_is_never_stopped(self) -> None:
        self._stop_with_recorded_pid(os.getpid()).assert_not_called()

    def test_another_managed_server_is_still_stopped(self) -> None:
        other = os.getpid() + os.getppid() + 12345
        self._stop_with_recorded_pid(other).assert_called_once_with(other)


class PortProbeTests(SimpleTestCase):
    """Whether a port is free must not be fooled by a listener that set SO_REUSEADDR."""

    def test_windows_probes_with_exclusive_use_not_reuse(self) -> None:
        candidate = MagicMock()
        with patch("app.server_cli.sys.platform", "win32"):
            server_cli._probe_socket_options(candidate)
        (call,) = candidate.setsockopt.call_args_list
        level, option, value = call.args
        self.assertEqual(level, socket.SOL_SOCKET)
        self.assertEqual(option, getattr(socket, "SO_EXCLUSIVEADDRUSE", -5))
        self.assertNotEqual(option, socket.SO_REUSEADDR)
        self.assertEqual(value, 1)

    def test_posix_still_probes_with_reuse(self) -> None:
        candidate = MagicMock()
        with patch("app.server_cli.sys.platform", "linux"):
            server_cli._probe_socket_options(candidate)
        candidate.setsockopt.assert_called_once_with(
            socket.SOL_SOCKET, socket.SO_REUSEADDR, 1
        )

    def test_a_listener_that_set_reuseaddr_makes_the_port_not_free(self) -> None:
        # How Django's server binds. On Windows a SO_REUSEADDR probe bound
        # straight onto it and called the port free.
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            self.assertFalse(server_cli._port_is_free(port))

    def test_a_port_nobody_uses_is_free(self) -> None:
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            port = reserved.getsockname()[1]
        self.assertTrue(server_cli._port_is_free(port))

    def test_local_setups_port_choice_agrees_with_the_servers_check(self) -> None:
        # bunnify setup / ensure_local_server pick the port with
        # local_server.port_is_free; it used to keep SO_REUSEADDR and call an
        # occupied port free, after which the server refused it.
        from app.local_server import port_is_free

        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            self.assertFalse(port_is_free(port))
            self.assertFalse(server_cli._port_is_free(port))
        self.assertTrue(port_is_free(port))

    def test_resolving_an_occupied_requested_port_fails(self) -> None:
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            with self.assertRaisesRegex(RuntimeError, "already in use"):
                server_cli._resolve_port(port)


class DetachOptionsTests(SimpleTestCase):
    def test_windows_detaches_with_creation_flags(self) -> None:
        with patch("app.server_cli.sys.platform", "win32"):
            options = server_cli._detach_options()
        self.assertNotIn("start_new_session", options)
        flags = options["creationflags"]
        self.assertTrue(flags & 0x00000008)  # DETACHED_PROCESS
        self.assertTrue(flags & 0x00000200)  # CREATE_NEW_PROCESS_GROUP
        self.assertTrue(flags & 0x08000000)  # CREATE_NO_WINDOW

    def test_posix_starts_a_new_session(self) -> None:
        with patch("app.server_cli.sys.platform", "linux"):
            self.assertEqual(server_cli._detach_options(), {"start_new_session": True})


class ForegroundSignalTests(SimpleTestCase):
    def _run(self, fake_signal: SimpleNamespace) -> list[int]:
        registered: list[int] = []
        fake_signal.signal = lambda signum, _handler: registered.append(signum)
        options = server_cli.ServerOptions(
            bookmarks=None,
            console=False,
            foreground=True,
            listen_all=False,
            log_file=Path("x.log"),
            log_level="WARNING",
            noninteractive=True,
            pid_dir=Path("run"),
            port=0,
            port_timeout_s=1.0,
            replace_on_port=None,
            stop=False,
        )
        with (
            patch("app.server_cli.signal", fake_signal),
            patch("app.server_cli._configure_environment"),
            patch("app.server_cli._initialize_database"),
            patch("app.server_cli._write_runtime_files"),
            patch("app.server_cli._start_watcher"),
            patch("app.server_cli._cleanup_files"),
            patch("django.core.management.call_command"),
        ):
            server_cli._run_foreground(options, Path("b.json"), 8000)
        return registered

    def test_registers_only_the_signals_that_exist(self) -> None:
        # Windows: no SIGHUP (this crashed startup), but SIGBREAK.
        windows = SimpleNamespace(SIGINT=2, SIGTERM=15, SIGBREAK=21)
        self.assertEqual(self._run(windows), [2, 15, 21])

    def test_registers_sighup_where_it_exists(self) -> None:
        posix = SimpleNamespace(SIGHUP=1, SIGINT=2, SIGTERM=15)
        self.assertEqual(self._run(posix), [1, 2, 15])


class BackgroundStartTests(SimpleTestCase):
    def test_the_background_server_is_started_detached(self) -> None:
        options = server_cli.ServerOptions(
            bookmarks=None,
            console=False,
            foreground=False,
            listen_all=False,
            log_file=Path("x.log"),
            log_level="WARNING",
            noninteractive=True,
            pid_dir=Path(os.devnull).parent,
            port=0,
            port_timeout_s=1.0,
            replace_on_port=None,
            stop=False,
        )
        process = MagicMock(pid=999)
        process.poll.return_value = None
        from tempfile import TemporaryDirectory

        with (
            TemporaryDirectory() as tmp,
            patch("app.server_cli._configure_environment"),
            patch("app.server_cli._initialize_database"),
            patch("app.server_cli._write_runtime_files"),
            # Popen is patched below on the shared subprocess module, which
            # git_commit() also uses; keep the command builder out of it.
            patch("app.server_cli._background_command", return_value=["server"]),
            patch("app.server_cli.check_health", return_value=True),
            patch(
                "app.server_cli._detach_options", return_value={"creationflags": 0x208}
            ),
            patch("app.server_cli.subprocess.Popen", return_value=process) as popen,
        ):
            code = server_cli._start_background(
                server_cli.ServerOptions(**{**options.__dict__, "pid_dir": Path(tmp)}),
                Path("b.json"),
                8000,
            )
        self.assertEqual(code, 0)
        self.assertEqual(popen.call_args.kwargs["creationflags"], 0x208)
        self.assertNotIn("start_new_session", popen.call_args.kwargs)


@skipUnless(real_win32_available(), "needs Windows")
class RealWindowsProcessTests(SimpleTestCase):
    def test_this_process_is_alive_and_a_bogus_pid_is_not(self) -> None:
        self.assertTrue(server_cli._is_process_running(os.getpid()))
        self.assertFalse(server_cli._is_process_running(0x7FFFFFF0))

    def test_the_command_line_of_a_real_process_is_readable(self) -> None:
        command = server_cli._process_command(os.getpid())
        self.assertIsNotNone(command)
        assert command is not None
        self.assertIn(os.path.basename(sys.executable).lower(), command.lower())

    def test_a_real_listener_is_found_by_netstat(self) -> None:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            self.assertIn(os.getpid(), server_cli._listener_pids(port))

    def test_a_real_process_is_terminated(self) -> None:
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            self.assertTrue(server_cli._is_process_running(child.pid))
            started = time.monotonic()
            server_cli._terminate_pid(child.pid)
            self.assertFalse(server_cli._is_process_running(child.pid))
            self.assertLess(time.monotonic() - started, 10)
        finally:
            child.kill()
            child.wait()

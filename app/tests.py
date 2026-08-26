from __future__ import annotations

import io
import socket
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from unittest import mock

from click.testing import CliRunner
from django.test import SimpleTestCase

from app import settings
from app.cli import main as cli_main
from app.config import data_dir
from app.local_server import ensure_local_server, stop_local_server
from app.server_cli import _is_bunnify_command
from app.server_cli import main as server_main
from app.version import (
    build_info,
    build_version,
    format_cli_version_line,
    get_build_info,
    git_commit,
    package_version,
    running_command_path,
)


class BuildInfoTests(SimpleTestCase):
    def tearDown(self) -> None:
        get_build_info.cache_clear()

    @mock.patch("app.version.git_commit", return_value="abcdef1")
    @mock.patch("app.version.package_version", return_value="0.2.3")
    def test_build_info_formats_version_and_commit(
        self,
        _package_version: mock.Mock,
        _git_commit: mock.Mock,
    ) -> None:
        get_build_info.cache_clear()
        self.assertEqual(build_info(), "bunnify 0.2.3 (abcdef1)")
        self.assertEqual(build_version(), "0.2.3 (abcdef1)")
        self.assertEqual(
            format_cli_version_line(prog="bunnify-server"),
            "bunnify-server 0.2.3 (abcdef1)",
        )

    def test_git_commit_prefers_environment(self) -> None:
        self.assertEqual(
            git_commit(environ={"BUNNIFY_GIT_SHA": "abcdef1234567890"}),
            "abcdef123456",
        )

    def test_git_commit_uses_embedded_metadata(self) -> None:
        with mock.patch(
            "app.version._build_metadata.EMBEDDED_COMMIT",
            "fedcba9876543210",
        ):
            self.assertEqual(git_commit(environ={}), "fedcba987654")

    def test_package_version_prefers_embedded(self) -> None:
        with mock.patch(
            "app.version._build_metadata.EMBEDDED_VERSION",
            "9.9.9",
        ):
            self.assertEqual(package_version(), "9.9.9")

    def test_package_version_falls_back_to_pyproject(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            pyproject_path = Path(temporary_directory) / "pyproject.toml"
            pyproject_path.write_text(
                '[project]\nname = "bunnify"\nversion = "1.2.3"\n'
            )

            with (
                mock.patch(
                    "app.version._build_metadata.EMBEDDED_VERSION",
                    "",
                ),
                mock.patch(
                    "app.version.version",
                    side_effect=PackageNotFoundError,
                ),
            ):
                self.assertEqual(
                    package_version(pyproject_path=pyproject_path),
                    "1.2.3",
                )

    def test_is_source_checkout_detects_git_dir(self) -> None:
        from app.version import is_source_checkout

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.assertFalse(is_source_checkout(repository=root))
            (root / ".git").mkdir()
            self.assertTrue(is_source_checkout(repository=root))

    def test_running_command_path_keeps_console_script_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            venv_binary = root / "pipx" / "venvs" / "bunnify" / "bin" / "bunnify"
            venv_binary.parent.mkdir(parents=True)
            venv_binary.write_text("#!/bin/sh\n")
            shim = root / "bin" / "bunnify"
            shim.parent.mkdir()
            shim.symlink_to(venv_binary)
            with mock.patch("app.version.sys.argv", [str(shim)]):
                shown = running_command_path()
            self.assertEqual(shown, shim.absolute())
            self.assertNotEqual(shown, venv_binary.resolve())

    def test_running_command_path_looks_up_bare_command_on_path(self) -> None:
        located = Path("/Users/me/.local/bin/bunnify")
        with (
            mock.patch("app.version.sys.argv", ["bunnify-on-path"]),
            mock.patch("app.version.shutil.which", return_value=str(located)) as which,
        ):
            shown = running_command_path()
        which.assert_called_once_with("bunnify-on-path")
        self.assertEqual(shown, located)

    def test_running_command_path_prefers_path_over_cwd_file(self) -> None:
        located = Path("/Users/me/.local/bin/bunnify")
        with tempfile.TemporaryDirectory() as temporary_directory:
            cwd_file = Path(temporary_directory) / "bunnify"
            cwd_file.write_text("not the CLI\n")
            with (
                mock.patch("app.version.sys.argv", ["bunnify"]),
                mock.patch(
                    "app.version.shutil.which",
                    return_value=str(located),
                ) as which,
            ):
                shown = running_command_path()
        which.assert_called_once_with("bunnify")
        self.assertEqual(shown, located)


class CliVersionTests(SimpleTestCase):
    def test_version_uses_distribution_metadata(self) -> None:
        result = CliRunner().invoke(cli_main, ["--version"])

        self.assertEqual(result.exit_code, 0)
        lines = result.output.splitlines()
        self.assertEqual(lines[0], build_info())
        self.assertTrue(lines[1].startswith("running from "))

    def test_version_command_prints_build_info(self) -> None:
        result = CliRunner().invoke(cli_main, ["version"])

        self.assertEqual(result.exit_code, 0)
        lines = result.output.splitlines()
        self.assertEqual(lines[0], build_info())
        self.assertTrue(lines[1].startswith("running from "))


class ConfigDataDirTests(SimpleTestCase):
    def test_data_dir_honors_override(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            expected = Path(temporary_directory) / "state"

            self.assertEqual(
                data_dir(environ={"BUNNIFY_DATA_DIR": str(expected)}),
                expected,
            )

    def test_data_dir_uses_xdg_data_home(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            expected = Path(temporary_directory) / "bunnify"

            self.assertEqual(
                data_dir(environ={"XDG_DATA_HOME": temporary_directory}),
                expected,
            )


class LocalServerTests(SimpleTestCase):
    @mock.patch("app.local_server.subprocess.run")
    @mock.patch("app.local_server.check_health", side_effect=[False, True])
    def test_start_invokes_installed_module(
        self,
        _check_health: mock.Mock,
        run: mock.Mock,
    ) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        with tempfile.TemporaryDirectory() as temporary_directory:
            pid_dir = Path(temporary_directory)

            base_url, port = ensure_local_server(
                port=8765,
                pid_dir=pid_dir,
                timeout_s=1,
            )

        self.assertEqual((base_url, port), ("http://127.0.0.1:8765", 8765))
        command = run.call_args.args[0]
        self.assertEqual(command[:3], [sys.executable, "-m", "app.server_cli"])

    @mock.patch("app.local_server.subprocess.run")
    def test_stop_invokes_installed_module(self, run: mock.Mock) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        with tempfile.TemporaryDirectory() as temporary_directory:
            pid_dir = Path(temporary_directory)

            stop_local_server(pid_dir)

        command = run.call_args.args[0]
        self.assertEqual(command[:3], [sys.executable, "-m", "app.server_cli"])
        self.assertIn("--stop", command)

    @mock.patch("app.local_server.wait_for_port_free", return_value=True)
    @mock.patch("app.local_server.subprocess.run")
    def test_stop_passes_port_timeout_to_server_cli(
        self,
        run: mock.Mock,
        wait_for_port: mock.Mock,
    ) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        with tempfile.TemporaryDirectory() as temporary_directory:
            pid_dir = Path(temporary_directory)

            stop_local_server(pid_dir, port=8123, port_timeout_s=1.5)

        command = run.call_args.args[0]
        self.assertIn("--port-timeout", command)
        self.assertEqual(command[command.index("--port-timeout") + 1], "1.5")
        wait_for_port.assert_called_once_with(8123, timeout_s=1.5)

    @mock.patch("app.local_server.wait_for_port_free", return_value=True)
    @mock.patch("app.local_server.subprocess.run")
    def test_stop_passes_replace_on_port(
        self,
        run: mock.Mock,
        wait_for_port: mock.Mock,
    ) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        with tempfile.TemporaryDirectory() as temporary_directory:
            pid_dir = Path(temporary_directory)

            stop_local_server(
                pid_dir,
                port=8123,
                replace_foreign_bunnify=True,
            )

        command = run.call_args.args[0]
        self.assertIn("--replace-on-port", command)
        self.assertEqual(command[command.index("--replace-on-port") + 1], "8123")
        wait_for_port.assert_called_once_with(8123, timeout_s=15)

    @mock.patch("app.local_server.wait_for_port_free", return_value=True)
    @mock.patch("app.local_server.subprocess.run")
    def test_stop_waits_for_requested_port(
        self,
        run: mock.Mock,
        wait_for_port: mock.Mock,
    ) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        with tempfile.TemporaryDirectory() as temporary_directory:
            pid_dir = Path(temporary_directory)

            stop_local_server(pid_dir, port=8123, port_timeout_s=1)

        wait_for_port.assert_called_once_with(8123, timeout_s=1)

    @mock.patch("app.local_server.wait_for_port_free", return_value=True)
    @mock.patch(
        "app.local_server.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["bunnify-server"], timeout=60),
    )
    def test_stop_maps_timeout_to_runtime_error(
        self,
        _run: mock.Mock,
        _wait_for_port: mock.Mock,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            pid_dir = Path(temporary_directory)

            with self.assertRaisesRegex(RuntimeError, "Timed out stopping"):
                stop_local_server(pid_dir, port=8123, port_timeout_s=1)

    @mock.patch("app.local_server.wait_for_port_free", return_value=False)
    @mock.patch("app.local_server.subprocess.run")
    def test_stop_raises_when_port_stays_busy(
        self,
        run: mock.Mock,
        _wait_for_port: mock.Mock,
    ) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        with tempfile.TemporaryDirectory() as temporary_directory:
            pid_dir = Path(temporary_directory)

            with self.assertRaisesRegex(RuntimeError, "still busy after stop"):
                stop_local_server(pid_dir, port=8123, port_timeout_s=0.1)

    def test_wait_for_port_free_returns_true_when_bindable(self) -> None:
        from app.local_server import wait_for_port_free

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
            holder.bind(("127.0.0.1", 0))
            port = int(holder.getsockname()[1])

        self.assertTrue(wait_for_port_free(port, timeout_s=1))

    def test_wait_for_port_free_times_out_while_held(self) -> None:
        from app.local_server import wait_for_port_free

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
            holder.bind(("127.0.0.1", 0))
            holder.listen()
            port = int(holder.getsockname()[1])
            self.assertFalse(wait_for_port_free(port, timeout_s=0.2))

    def test_port_is_free_uses_reuseaddr(self) -> None:
        from app.local_server import port_is_free

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
            holder.bind(("127.0.0.1", 0))
            port = int(holder.getsockname()[1])
        # Closed socket may still look busy without SO_REUSEADDR; our check must
        # match Django's runserver and treat the port as usable.
        self.assertTrue(port_is_free(port))

    def test_port_is_free_enables_reuseaddr_on_probe_socket(self) -> None:
        from app.local_server import port_is_free

        with mock.patch("app.local_server.socket.socket") as socket_cls:
            probe = socket_cls.return_value.__enter__.return_value
            probe.bind.return_value = None
            self.assertTrue(port_is_free(8123))
            probe.setsockopt.assert_called_with(
                socket.SOL_SOCKET,
                socket.SO_REUSEADDR,
                1,
            )

    def test_stop_rejects_ephemeral_wait_port(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(ValueError, "1 and 65535"):
                stop_local_server(Path(temporary_directory), port=0)

    def test_stop_rejects_non_positive_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(ValueError, "positive"):
                stop_local_server(Path(temporary_directory), port_timeout_s=0)
            with self.assertRaisesRegex(ValueError, "positive"):
                stop_local_server(
                    Path(temporary_directory), port_timeout_s=float("nan")
                )


class ServerCliVersionTests(SimpleTestCase):
    def test_version_uses_distribution_metadata(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            server_main(["--version"])

        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(output.getvalue(), f"bunnify-server {build_version()}\n")


class ServerStopTests(SimpleTestCase):
    def test_stop_returns_error_when_port_stays_busy(self) -> None:
        from app.server_cli import _stop_managed_server

        with tempfile.TemporaryDirectory() as temporary_directory:
            pid_dir = Path(temporary_directory)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
                holder.bind(("127.0.0.1", 0))
                holder.listen()
                port = int(holder.getsockname()[1])
                (pid_dir / ".bunnify.port").write_text(f"{port}\n", encoding="utf-8")

                with (
                    mock.patch("app.server_cli._listener_pids", return_value=[]),
                    mock.patch(
                        "app.server_cli._wait_for_port_free",
                        return_value=False,
                    ) as wait_for_port,
                ):
                    self.assertEqual(
                        _stop_managed_server(
                            pid_dir,
                            quiet=False,
                            port_timeout_s=0.25,
                        ),
                        1,
                    )
                wait_for_port.assert_called_once_with(port, timeout_s=0.25)

    def test_quiet_stop_skips_wait_when_nothing_signaled(self) -> None:
        from app.server_cli import _stop_managed_server

        with tempfile.TemporaryDirectory() as temporary_directory:
            pid_dir = Path(temporary_directory)
            (pid_dir / ".bunnify.port").write_text("8123\n", encoding="utf-8")

            with (
                mock.patch("app.server_cli._port_is_free", return_value=False),
                mock.patch("app.server_cli._listener_pids", return_value=[]),
                mock.patch("app.server_cli._wait_for_port_free") as wait_for_port,
            ):
                self.assertEqual(_stop_managed_server(pid_dir, quiet=True), 0)

            wait_for_port.assert_not_called()

    def test_stop_terminates_listener_when_pid_file_stale(self) -> None:
        from app.server_cli import _stop_managed_server

        with tempfile.TemporaryDirectory() as temporary_directory:
            pid_dir = Path(temporary_directory)
            (pid_dir / ".bunnify.port").write_text("8123\n", encoding="utf-8")

            with (
                mock.patch("app.server_cli._port_is_free", side_effect=[False, True]),
                mock.patch("app.server_cli._listener_pids", return_value=[4242]),
                mock.patch(
                    "app.server_cli._process_managed_by_pid_dir",
                    return_value=True,
                ),
                mock.patch("app.server_cli._terminate_pid") as terminate,
                mock.patch("app.server_cli._wait_for_port_free", return_value=True),
            ):
                self.assertEqual(_stop_managed_server(pid_dir, quiet=True), 0)

            terminate.assert_called_once_with(4242)

    def test_stop_skips_listener_for_other_pid_dir(self) -> None:
        from app.server_cli import _stop_managed_server

        with tempfile.TemporaryDirectory() as temporary_directory:
            pid_dir = Path(temporary_directory)
            (pid_dir / ".bunnify.port").write_text("8123\n", encoding="utf-8")

            with (
                mock.patch("app.server_cli._port_is_free", return_value=False),
                mock.patch("app.server_cli._listener_pids", return_value=[4242]),
                mock.patch(
                    "app.server_cli._process_managed_by_pid_dir",
                    return_value=False,
                ),
                mock.patch("app.server_cli._terminate_pid") as terminate,
                mock.patch("app.server_cli._wait_for_port_free") as wait_for_port,
            ):
                self.assertEqual(_stop_managed_server(pid_dir, quiet=True), 0)

            terminate.assert_not_called()
            wait_for_port.assert_not_called()

    def test_stop_replace_on_port_terminates_foreign_bunnify_listener(self) -> None:
        from app.server_cli import _stop_managed_server

        with tempfile.TemporaryDirectory() as temporary_directory:
            pid_dir = Path(temporary_directory)

            with (
                mock.patch("app.server_cli._port_is_free", return_value=False),
                mock.patch("app.server_cli._listener_pids", return_value=[4242]),
                mock.patch(
                    "app.server_cli._process_managed_by_pid_dir",
                    return_value=False,
                ),
                mock.patch(
                    "app.server_cli._is_bunnify_process",
                    return_value=True,
                ),
                mock.patch("app.server_cli._terminate_pid") as terminate,
                mock.patch("app.server_cli._wait_for_port_free", return_value=True),
            ):
                self.assertEqual(
                    _stop_managed_server(
                        pid_dir,
                        quiet=True,
                        replace_on_port=8123,
                    ),
                    0,
                )

            terminate.assert_called_once_with(4242)

    def test_process_managed_by_pid_dir_defaults_missing_flag(self) -> None:
        from app.server_cli import _process_managed_by_pid_dir

        default = Path("/tmp/default-run")
        with (
            mock.patch(
                "app.server_cli._process_command",
                return_value="python -m app.server_cli --port 8000 --foreground",
            ),
            mock.patch("app.server_cli.run_dir", return_value=default),
        ):
            self.assertTrue(_process_managed_by_pid_dir(1, default))
            self.assertFalse(_process_managed_by_pid_dir(1, Path("/tmp/other-run")))

        from app.server_cli import _pid_dir_from_command, _port_from_command

        self.assertEqual(
            _pid_dir_from_command(
                "python -m app.server_cli --pid-dir /tmp/bunnify-run --port 8000"
            ),
            Path("/tmp/bunnify-run"),
        )
        self.assertEqual(
            _pid_dir_from_command(
                "python -m app.server_cli --pid-dir=/tmp/bunnify-run --port=8000"
            ),
            Path("/tmp/bunnify-run"),
        )
        self.assertIsNone(_pid_dir_from_command("python -m app.server_cli --port 8000"))
        self.assertEqual(
            _port_from_command(
                "python -m app.server_cli --pid-dir /tmp/run --port 8123"
            ),
            8123,
        )
        self.assertEqual(
            _port_from_command(
                "python -m app.server_cli --pid-dir=/tmp/run --port=8123"
            ),
            8123,
        )
        self.assertIsNone(
            _port_from_command("python -m app.server_cli --pid-dir /tmp/run --port 0")
        )

    def test_stop_scopes_recorded_pid_to_pid_dir(self) -> None:
        from app.server_cli import _stop_managed_server

        with tempfile.TemporaryDirectory() as temporary_directory:
            pid_dir = Path(temporary_directory)
            (pid_dir / ".bunnify.pid").write_text("4242\n", encoding="utf-8")
            (pid_dir / ".bunnify.port").write_text("8123\n", encoding="utf-8")

            with (
                mock.patch("app.server_cli._is_process_running", return_value=True),
                mock.patch(
                    "app.server_cli._process_managed_by_pid_dir",
                    return_value=False,
                ),
                mock.patch("app.server_cli._is_bunnify_process", return_value=True),
                mock.patch("app.server_cli._terminate_pid") as terminate,
            ):
                self.assertEqual(_stop_managed_server(pid_dir, quiet=True), 0)

            terminate.assert_not_called()
            self.assertFalse((pid_dir / ".bunnify.pid").exists())

    def test_stop_recovers_port_from_command_when_port_file_missing(self) -> None:
        from app.server_cli import _stop_managed_server

        with tempfile.TemporaryDirectory() as temporary_directory:
            pid_dir = Path(temporary_directory)
            (pid_dir / ".bunnify.pid").write_text("4242\n", encoding="utf-8")

            with (
                mock.patch("app.server_cli._is_process_running", return_value=True),
                mock.patch(
                    "app.server_cli._process_managed_by_pid_dir",
                    return_value=True,
                ),
                mock.patch(
                    "app.server_cli._process_command",
                    return_value=(
                        "python -m app.server_cli --pid-dir "
                        f"{pid_dir} --port 8123 --foreground"
                    ),
                ),
                mock.patch("app.server_cli._terminate_pid") as terminate,
                mock.patch("app.server_cli._port_is_free", return_value=True),
                mock.patch(
                    "app.server_cli._wait_for_port_free",
                    return_value=True,
                ) as wait_for_port,
            ):
                self.assertEqual(_stop_managed_server(pid_dir, quiet=False), 0)

            terminate.assert_called_once_with(4242)
            wait_for_port.assert_called_once_with(8123, timeout_s=15)


LAUNCHAGENT_COMMAND = (
    "/opt/homebrew/Cellar/python@3.14/3.14.7/Frameworks/Python.framework/Versions/"
    "3.14/Resources/Python.app/Contents/MacOS/Python -E "
    "/Users/tester/.local/bin/bunnify-server --foreground --noninteractive "
    "--port 8000 --pid-dir /Users/tester/.local/share/bunnify/run/launchd"
)


class ServerProcessTests(SimpleTestCase):
    def test_accepts_abi_flagged_interpreters(self) -> None:
        for interpreter in ("python3.14t", "python3.14d", "python3.14td", "pypy3"):
            with self.subTest(interpreter=interpreter):
                self.assertTrue(
                    _is_bunnify_command(
                        f"/tmp/venv/bin/{interpreter} -E "
                        "/tmp/venv/bin/bunnify-server --port 8000"
                    )
                )

    def test_accepts_bare_console_script(self) -> None:
        self.assertTrue(_is_bunnify_command("bunnify-server --port 8000"))

    def test_accepts_bunnify_console_script(self) -> None:
        self.assertTrue(
            _is_bunnify_command(
                "/tmp/venv/bin/python /tmp/venv/bin/bunnify-server --port 8000"
            )
        )

    def test_accepts_bunnify_server_module(self) -> None:
        self.assertTrue(
            _is_bunnify_command("/tmp/venv/bin/python -m app.server_cli --port 8000")
        )

    def test_accepts_interpreter_option_taking_a_value(self) -> None:
        self.assertTrue(
            _is_bunnify_command(
                "/usr/bin/python3 -X importtime -W ignore "
                "/tmp/venv/bin/bunnify-server --port 8000"
            )
        )

    def test_accepts_launchagent_interpreter_invocation(self) -> None:
        self.assertTrue(_is_bunnify_command(LAUNCHAGENT_COMMAND))

    def test_launchagent_process_is_managed_by_its_pid_dir(self) -> None:
        from app.server_cli import _process_managed_by_pid_dir

        launchd_dir = Path("/Users/tester/.local/share/bunnify/run/launchd")
        with mock.patch(
            "app.server_cli._process_command",
            return_value=LAUNCHAGENT_COMMAND,
        ):
            self.assertTrue(_process_managed_by_pid_dir(1, launchd_dir))
            self.assertFalse(
                _process_managed_by_pid_dir(1, Path("/Users/tester/other-run"))
            )

    def test_rejects_command_containing_bunnify_name(self) -> None:
        self.assertFalse(_is_bunnify_command("grep -r bunnify-server ."))

    def test_rejects_interpreter_inline_code(self) -> None:
        self.assertFalse(
            _is_bunnify_command("/usr/bin/python3 -c 'print(\"bunnify-server\")'")
        )

    def test_rejects_unrelated_python_script(self) -> None:
        self.assertFalse(
            _is_bunnify_command("/usr/bin/python3 -E /tmp/venv/bin/other-script")
        )


class SettingsDataDirTests(SimpleTestCase):
    def test_sqlite_database_is_under_data_dir(self) -> None:
        self.assertEqual(
            settings.DATABASE_PATH,
            data_dir() / "db.sqlite3",
        )

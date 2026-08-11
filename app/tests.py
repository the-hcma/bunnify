from __future__ import annotations

import io
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from click.testing import CliRunner
from django.test import SimpleTestCase

from app import settings
from app.cli import main as cli_main
from app.config import data_dir
from app.local_server import ensure_local_server, stop_local_server
from app.server_cli import main as server_main
from app.version import package_version


class CliVersionTests(SimpleTestCase):
    def test_version_uses_distribution_metadata(self) -> None:
        result = CliRunner().invoke(cli_main, ["--version"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn(package_version(), result.output)


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


class ServerCliVersionTests(SimpleTestCase):
    def test_version_uses_distribution_metadata(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            server_main(["--version"])

        self.assertEqual(raised.exception.code, 0)
        self.assertIn(package_version(), output.getvalue())


class SettingsDataDirTests(SimpleTestCase):
    def test_sqlite_database_is_under_data_dir(self) -> None:
        self.assertEqual(
            settings.DATABASE_PATH,
            data_dir() / "db.sqlite3",
        )

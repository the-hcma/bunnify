"""Tests for pipx macOS extra helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase

from app.pipx_install import (
    install_macos_extra,
    macos_extra_installed,
    pipx_bunnify_path,
    pipx_bunnify_venv_python,
)


class PipxInstallTests(SimpleTestCase):
    def test_install_macos_extra_runs_pipx_force(self) -> None:
        completed = subprocess.CompletedProcess(["pipx"], 0, "", "")
        with patch("app.pipx_install.subprocess.run", return_value=completed) as run:
            self.assertTrue(install_macos_extra("/usr/bin/pipx"))
        self.assertEqual(
            run.call_args.args[0],
            ["/usr/bin/pipx", "install", "--force", "bunnify[macos]"],
        )

    def test_macos_extra_installed_probes_appkit(self) -> None:
        completed = subprocess.CompletedProcess(["python"], 0, "", "")
        interpreter = Path("/opt/venv/bin/python")
        with patch("app.pipx_install.subprocess.run", return_value=completed) as run:
            self.assertTrue(macos_extra_installed(interpreter=interpreter))
        self.assertEqual(run.call_args.args[0][0], str(interpreter))

    def test_macos_extra_installed_falls_back_to_sys_executable(self) -> None:
        completed = subprocess.CompletedProcess(["python"], 1, "", "")
        with (
            patch("app.pipx_install.pipx_bunnify_venv_python", return_value=None),
            patch("app.pipx_install.subprocess.run", return_value=completed) as run,
            patch("app.pipx_install.sys.executable", "/opt/fallback/bin/python"),
        ):
            self.assertFalse(macos_extra_installed())
        self.assertEqual(run.call_args.args[0][0], "/opt/fallback/bin/python")

    def test_macos_extra_installed_returns_false_when_probe_fails(self) -> None:
        completed = subprocess.CompletedProcess(["python"], 1, "", "")
        interpreter = Path("/opt/venv/bin/python")
        with patch("app.pipx_install.subprocess.run", return_value=completed):
            self.assertFalse(macos_extra_installed(interpreter=interpreter))

    def test_macos_extra_installed_returns_false_on_subprocess_error(self) -> None:
        interpreter = Path("/opt/venv/bin/python")
        with patch(
            "app.pipx_install.subprocess.run",
            side_effect=OSError("probe failed"),
        ):
            self.assertFalse(macos_extra_installed(interpreter=interpreter))

    def test_pipx_bunnify_venv_python_uses_pipx_home(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            python = root / "venvs" / "bunnify" / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text("", encoding="utf-8")
            self.assertEqual(
                pipx_bunnify_venv_python(pipx_home=root),
                python,
            )

    def test_pipx_bunnify_venv_python_checks_local_pipx_home(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / ".local" / "pipx"
            python = root / "venvs" / "bunnify" / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text("", encoding="utf-8")
            with patch.object(Path, "home", return_value=Path(tmp)):
                self.assertEqual(pipx_bunnify_venv_python(), python)

    def test_pipx_bunnify_path_honors_pipx_bin_dir(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = root / "bunnify"
            binary.write_text("#!/bin/sh\n", encoding="utf-8")
            with patch.dict("os.environ", {"PIPX_BIN_DIR": str(root)}, clear=False):
                self.assertEqual(pipx_bunnify_path(), binary.resolve())

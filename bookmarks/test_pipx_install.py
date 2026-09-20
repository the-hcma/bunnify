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
    pipx_bunnify_display,
    pipx_bunnify_path,
    pipx_bunnify_venv_python,
    pipx_vcs_install_spec,
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
        fallback = "/opt/fallback/bin/python"
        with (
            patch("app.pipx_install.pipx_bunnify_venv_python", return_value=None),
            patch("app.pipx_install.subprocess.run", return_value=completed) as run,
            patch("app.pipx_install.sys.executable", fallback),
        ):
            self.assertFalse(macos_extra_installed())
        # The SUT routes sys.executable through Path(...), which normalizes
        # separators for the host OS -- compare against that same
        # normalization instead of the raw fallback string.
        self.assertEqual(run.call_args.args[0][0], str(Path(fallback)))

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
            with patch("app.pipx_install.sys.platform", "linux"):
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
            with (
                patch("app.pipx_install.sys.platform", "linux"),
                patch.object(Path, "home", return_value=Path(tmp)),
            ):
                self.assertEqual(pipx_bunnify_venv_python(), python)

    def test_pipx_bunnify_path_honors_pipx_bin_dir(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = root / "bunnify"
            binary.write_text("#!/bin/sh\n", encoding="utf-8")
            with (
                patch("app.pipx_install.sys.platform", "linux"),
                patch.dict("os.environ", {"PIPX_BIN_DIR": str(root)}, clear=False),
            ):
                self.assertEqual(pipx_bunnify_path(), binary.resolve())


class PipxInstallWindowsLayoutTests(SimpleTestCase):
    """The Windows pipx layout: bunnify.exe and Scripts/python.exe (#509)."""

    def test_display_names_the_exe_on_windows_only(self) -> None:
        with patch("app.pipx_install.sys.platform", "win32"):
            self.assertEqual(pipx_bunnify_display(), "~/.local/bin/bunnify.exe")
        with patch("app.pipx_install.sys.platform", "linux"):
            self.assertEqual(pipx_bunnify_display(), "~/.local/bin/bunnify")

    def test_app_path_finds_bunnify_exe_in_the_default_bin_dir(self) -> None:
        with TemporaryDirectory() as tmp:
            binary = Path(tmp) / ".local" / "bin" / "bunnify.exe"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b"")
            with (
                patch("app.pipx_install.sys.platform", "win32"),
                patch.object(Path, "home", return_value=Path(tmp)),
                patch.dict("os.environ", {"PIPX_BIN_DIR": ""}),
            ):
                self.assertEqual(pipx_bunnify_path(), binary.resolve())

    def test_app_path_honors_pipx_bin_dir_on_windows(self) -> None:
        with TemporaryDirectory() as tmp:
            binary = Path(tmp) / "bunnify.exe"
            binary.write_bytes(b"")
            with (
                patch("app.pipx_install.sys.platform", "win32"),
                patch.dict("os.environ", {"PIPX_BIN_DIR": tmp}),
            ):
                self.assertEqual(pipx_bunnify_path(), binary.resolve())

    def test_app_path_ignores_the_other_platforms_name(self) -> None:
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "bunnify.exe").write_bytes(b"")
            with (
                patch("app.pipx_install.sys.platform", "linux"),
                patch.object(Path, "home", return_value=Path(tmp) / "nobody"),
                patch.dict("os.environ", {"PIPX_BIN_DIR": tmp}),
            ):
                self.assertIsNone(pipx_bunnify_path())

    def test_venv_python_found_under_localappdata_scripts(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "AppData" / "Local" / "pipx" / "pipx"
            python = root / "venvs" / "bunnify" / "Scripts" / "python.exe"
            python.parent.mkdir(parents=True)
            python.write_bytes(b"")
            with (
                patch("app.pipx_install.sys.platform", "win32"),
                patch.object(Path, "home", return_value=Path(tmp) / "nobody"),
                patch.dict(
                    "os.environ",
                    {"LOCALAPPDATA": str(Path(tmp) / "AppData" / "Local")},
                    clear=False,
                ),
                patch.dict("os.environ", {"PIPX_HOME": ""}),
            ):
                self.assertEqual(pipx_bunnify_venv_python(), python)

    def test_venv_python_found_in_the_older_home_pipx_dir(self) -> None:
        with TemporaryDirectory() as tmp:
            python = Path(tmp) / "pipx" / "venvs" / "bunnify" / "Scripts" / "python.exe"
            python.parent.mkdir(parents=True)
            python.write_bytes(b"")
            with (
                patch("app.pipx_install.sys.platform", "win32"),
                patch.object(Path, "home", return_value=Path(tmp)),
                patch.dict("os.environ", {"LOCALAPPDATA": "", "PIPX_HOME": ""}),
            ):
                self.assertEqual(pipx_bunnify_venv_python(), python)

    def test_venv_python_ignores_the_other_platforms_layout(self) -> None:
        with TemporaryDirectory() as tmp:
            python = Path(tmp) / "venvs" / "bunnify" / "Scripts" / "python.exe"
            python.parent.mkdir(parents=True)
            python.write_bytes(b"")
            with patch("app.pipx_install.sys.platform", "linux"):
                self.assertIsNone(pipx_bunnify_venv_python(pipx_home=Path(tmp)))
            with patch("app.pipx_install.sys.platform", "win32"):
                self.assertEqual(pipx_bunnify_venv_python(pipx_home=Path(tmp)), python)

    def test_onboard_summary_names_the_exe_when_the_app_is_missing(self) -> None:
        from app.onboard import InstallState, _format_install_summary

        state = InstallState(
            bookmarks_ready=True,
            command_path="C:\\x\\bunnify.exe",
            macos_extra=False,
            macos_platform=False,
            pipx_app_path=None,
            pipx_version_label=None,
            preferences_ready=True,
            pypi_latest=None,
            server_agent_installed=False,
            source_checkout=False,
            spotty_agent_installed=False,
            upgrade_available=False,
            version_label="0.15.0 (abc)",
        )
        with patch("app.pipx_install.sys.platform", "win32"):
            summary = "\n".join(_format_install_summary(state))
        self.assertIn("pipx app: not found (~/.local/bin/bunnify.exe)", summary)


_GIT_RECORD = (
    '{"url": "https://github.com/the-hcma/bunnify", "vcs_info": '
    '{"vcs": "git", "requested_revision": "main", "commit_id": "abc123"}}'
)
_GIT_SPEC = "git+https://github.com/the-hcma/bunnify@main"


class PipxVcsInstallSpecTests(SimpleTestCase):
    """The spec is read from the pipx app's own venv, not the running process."""

    @staticmethod
    def _venv(root: Path, *, platform: str, record: str | None) -> Path:
        """A pipx home holding a bunnify venv, in *platform*'s layout."""
        if platform == "win32":
            python = root / "venvs" / "bunnify" / "Scripts" / "python.exe"
            site = root / "venvs" / "bunnify" / "Lib" / "site-packages"
        else:
            python = root / "venvs" / "bunnify" / "bin" / "python"
            site = root / "venvs" / "bunnify" / "lib" / "python3.14" / "site-packages"
        python.parent.mkdir(parents=True)
        python.write_bytes(b"")
        dist_info = site / "bunnify-0.15.0.dist-info"
        dist_info.mkdir(parents=True)
        if record is not None:
            (dist_info / "direct_url.json").write_text(record, encoding="utf-8")
        return root

    def test_reads_the_record_from_a_windows_venv(self) -> None:
        with TemporaryDirectory() as tmp:
            home = self._venv(Path(tmp), platform="win32", record=_GIT_RECORD)
            with patch("app.pipx_install.sys.platform", "win32"):
                self.assertEqual(pipx_vcs_install_spec(pipx_home=home), _GIT_SPEC)

    def test_reads_the_record_from_a_posix_venv(self) -> None:
        with TemporaryDirectory() as tmp:
            home = self._venv(Path(tmp), platform="linux", record=_GIT_RECORD)
            with patch("app.pipx_install.sys.platform", "linux"):
                self.assertEqual(pipx_vcs_install_spec(pipx_home=home), _GIT_SPEC)

    def test_the_pipx_apps_record_wins_over_the_running_distribution(self) -> None:
        # Running ./scripts/bunnify from a checkout while the pipx app came
        # from PyPI: the checkout's own (editable) record must not decide.
        with TemporaryDirectory() as tmp:
            home = self._venv(Path(tmp), platform="linux", record=None)
            with (
                patch("app.pipx_install.sys.platform", "linux"),
                patch("app.pipx_install.vcs_install_spec", return_value=_GIT_SPEC),
            ):
                self.assertIsNone(pipx_vcs_install_spec(pipx_home=home))

    def test_a_git_pipx_app_is_found_even_when_the_running_one_is_editable(
        self,
    ) -> None:
        with TemporaryDirectory() as tmp:
            home = self._venv(Path(tmp), platform="linux", record=_GIT_RECORD)
            with (
                patch("app.pipx_install.sys.platform", "linux"),
                patch("app.pipx_install.vcs_install_spec", return_value=None),
            ):
                self.assertEqual(pipx_vcs_install_spec(pipx_home=home), _GIT_SPEC)

    def test_an_index_or_editable_record_is_not_a_vcs_install(self) -> None:
        with TemporaryDirectory() as tmp:
            home = self._venv(
                Path(tmp),
                platform="linux",
                record='{"url": "file:///src", "dir_info": {"editable": true}}',
            )
            with patch("app.pipx_install.sys.platform", "linux"):
                self.assertIsNone(pipx_vcs_install_spec(pipx_home=home))

    def test_an_unreadable_record_is_skipped(self) -> None:
        with TemporaryDirectory() as tmp:
            home = self._venv(Path(tmp), platform="linux", record=None)
            # A directory where the file should be: read_text raises OSError.
            unreadable = next(
                home.glob("venvs/bunnify/lib/*/site-packages/*.dist-info")
            )
            (unreadable / "direct_url.json").mkdir()
            with patch("app.pipx_install.sys.platform", "linux"):
                self.assertIsNone(pipx_vcs_install_spec(pipx_home=home))

    def test_without_a_pipx_venv_the_running_distribution_is_consulted(self) -> None:
        with TemporaryDirectory() as tmp:
            with patch(
                "app.pipx_install.vcs_install_spec", return_value=_GIT_SPEC
            ) as running:
                self.assertEqual(pipx_vcs_install_spec(pipx_home=Path(tmp)), _GIT_SPEC)
            running.assert_called_once_with()

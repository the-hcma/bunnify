"""Tests for interactive onboarding."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from django.test import SimpleTestCase

from app.cli import run_upgrade
from app.client import ClientError
from app.onboard import (
    InstallState,
    detect_install_state,
    format_onboarding_text,
    run_onboard,
)

_FIXTURE_COMMIT = "test-fixture-commit"
_FIXTURE_INSTALLED_VERSION = "0.0.0+test-fixture-installed"
_FIXTURE_PYPI_LATEST_VERSION = "0.0.0+test-fixture-pypi-latest"


class OnboardTests(SimpleTestCase):
    def setUp(self) -> None:
        # Never read this machine's real pipx install: tests that want a git
        # install patch their own spec.
        self.enterContext(patch("app.onboard.pipx_vcs_install_spec", return_value=None))

    def test_detect_install_state_marks_upgrade_when_pypi_is_newer(self) -> None:
        with (
            patch(
                "app.onboard.get_build_info",
                return_value=(_FIXTURE_INSTALLED_VERSION, _FIXTURE_COMMIT),
            ),
            patch(
                "app.onboard.pypi_latest_version",
                return_value=_FIXTURE_PYPI_LATEST_VERSION,
            ),
        ):
            state = detect_install_state(
                read_executable_build=lambda _path: (
                    f"{_FIXTURE_INSTALLED_VERSION} ({_FIXTURE_COMMIT})"
                ),
            )
        self.assertTrue(state.upgrade_available)
        self.assertEqual(state.pypi_latest, _FIXTURE_PYPI_LATEST_VERSION)

    def test_detect_install_state_skips_pypi_for_a_git_install(self) -> None:
        with (
            patch(
                "app.onboard.get_build_info",
                return_value=(_FIXTURE_INSTALLED_VERSION, _FIXTURE_COMMIT),
            ),
            patch(
                "app.onboard.pipx_vcs_install_spec",
                return_value="git+https://github.com/the-hcma/bunnify@main",
            ),
            patch(
                "app.onboard.pypi_latest_version",
                return_value=_FIXTURE_INSTALLED_VERSION,
            ) as pypi,
        ):
            state = detect_install_state(read_executable_build=lambda _path: None)
        pypi.assert_not_called()
        self.assertIsNone(state.pypi_latest)
        self.assertFalse(state.upgrade_available)
        self.assertEqual(
            state.vcs_install, "git+https://github.com/the-hcma/bunnify@main"
        )

    def test_detect_install_state_has_no_vcs_install_by_default(self) -> None:
        with (
            patch(
                "app.onboard.get_build_info",
                return_value=(_FIXTURE_INSTALLED_VERSION, _FIXTURE_COMMIT),
            ),
            patch("app.onboard.pipx_vcs_install_spec", return_value=None),
            patch(
                "app.onboard.pypi_latest_version",
                return_value=_FIXTURE_PYPI_LATEST_VERSION,
            ),
        ):
            state = detect_install_state(read_executable_build=lambda _path: None)
        self.assertIsNone(state.vcs_install)
        self.assertEqual(state.pypi_latest, _FIXTURE_PYPI_LATEST_VERSION)

    def test_summary_names_the_git_source_instead_of_pypi(self) -> None:
        state = InstallState(
            bookmarks_ready=True,
            command_path="C:\\bin\\bunnify.exe",
            macos_extra=False,
            macos_platform=False,
            pipx_app_path=None,
            pipx_version_label=None,
            preferences_ready=True,
            pypi_latest="0.15.0",
            server_agent_installed=False,
            source_checkout=False,
            spotty_agent_installed=False,
            upgrade_available=False,
            version_label="0.15.0 (0142e9ee2148)",
            vcs_install="git+https://github.com/the-hcma/bunnify@main",
        )
        text = format_onboarding_text(state)
        self.assertIn(
            "Installed from git: git+https://github.com/the-hcma/bunnify@main", text
        )
        self.assertNotIn("PyPI latest", text)

    @staticmethod
    def _state(**overrides: object) -> InstallState:
        fields: dict[str, object] = {
            "bookmarks_ready": False,
            "command_path": "C:\\bin\\bunnify.exe",
            "macos_extra": False,
            "macos_platform": False,
            "pipx_app_path": None,
            "pipx_version_label": None,
            "preferences_ready": True,
            "pypi_latest": None,
            "server_agent_installed": False,
            "source_checkout": False,
            "spotty_agent_installed": False,
            "upgrade_available": False,
            "version_label": "0.15.0 (abc)",
        }
        fields.update(overrides)
        return InstallState(**fields)  # pyright: ignore[reportArgumentType]

    def test_windows_gets_its_own_spotty_bunny_step(self) -> None:
        text = format_onboarding_text(self._state(windows_platform=True))
        self.assertIn("Windows Spotty Bunny (optional search box):", text)
        self.assertIn("bunnify spotty-bunny install", text)
        self.assertIn("Scheduled Task", text)
        self.assertNotIn("macOS", text)
        self.assertIn("Spotty Bunny Scheduled Task: not installed", text)

    def test_windows_step_reflects_an_installed_task(self) -> None:
        text = format_onboarding_text(
            self._state(windows_platform=True, spotty_agent_installed=True)
        )
        self.assertIn("Windows Spotty Bunny (optional search box): installed", text)
        self.assertIn("bunnify spotty-bunny uninstall", text)
        self.assertNotIn("spotty-bunny install ", text)
        self.assertIn("Spotty Bunny Scheduled Task: installed", text)

    def test_other_platforms_get_no_windows_step(self) -> None:
        for state in (
            self._state(),
            self._state(macos_platform=True),
        ):
            with self.subTest(macos=state.macos_platform):
                text = format_onboarding_text(state)
                self.assertNotIn("Windows Spotty Bunny", text)
                self.assertNotIn("Scheduled Task", text)

    def test_macos_step_is_unchanged(self) -> None:
        text = format_onboarding_text(self._state(macos_platform=True))
        self.assertIn("macOS Spotty Bunny (optional search box):", text)

    def test_remote_mode_does_not_ask_for_local_bookmarks(self) -> None:
        text = format_onboarding_text(self._state(remote_mode=True))
        self.assertNotIn("Bookmarks (required", text)
        self.assertNotIn("bookmarks.json", text)
        self.assertIn("Configure Chrome or Edge", text)

    def test_local_mode_still_asks_for_bookmarks(self) -> None:
        text = format_onboarding_text(self._state(remote_mode=False))
        self.assertIn("1. Bookmarks (required before the server starts):", text)

    def test_detect_install_state_reads_mode_and_the_windows_task(self) -> None:
        preferences = MagicMock(mode="remote")
        with (
            patch("app.onboard.sys.platform", "win32"),
            # sys.platform is process-global: without these, stdlib and pathlib
            # calls would take their Windows branches on a non-Windows host.
            patch("app.onboard.running_command_path", return_value=Path("bunnify")),
            patch("app.onboard.pipx_bunnify_path", return_value=None),
            patch("app.onboard.default_bookmarks_path", return_value=Path("b.json")),
            patch("app.onboard.load_preferences", return_value=preferences),
            patch("app.onboard.pypi_latest_version", return_value=None),
            patch("app.onboard.pipx_vcs_install_spec", return_value=None),
            patch("app.onboard.macos_extra_installed", return_value=False),
            patch(
                "app.spotty_bunny_agent_win32.is_agent_installed", return_value=True
            ) as installed,
        ):
            state = detect_install_state(read_executable_build=lambda _path: None)
        installed.assert_called_once_with()
        self.assertTrue(state.windows_platform)
        self.assertTrue(state.spotty_agent_installed)
        self.assertTrue(state.remote_mode)
        self.assertFalse(state.macos_platform)

    def test_detect_install_state_does_not_touch_the_task_elsewhere(self) -> None:
        with (
            patch("app.onboard.sys.platform", "linux"),
            patch("app.onboard.running_command_path", return_value=Path("bunnify")),
            patch("app.onboard.pipx_bunnify_path", return_value=None),
            patch("app.onboard.default_bookmarks_path", return_value=Path("b.json")),
            patch("app.onboard.load_preferences", return_value=None),
            patch("app.onboard.pypi_latest_version", return_value=None),
            patch("app.onboard.pipx_vcs_install_spec", return_value=None),
            patch("app.onboard.macos_extra_installed", return_value=False),
            patch("app.spotty_bunny_agent_win32.is_agent_installed") as installed,
        ):
            state = detect_install_state(read_executable_build=lambda _path: None)
        installed.assert_not_called()
        self.assertFalse(state.windows_platform)
        self.assertFalse(state.remote_mode)

    def test_format_onboarding_text_includes_install_summary(self) -> None:
        state = InstallState(
            bookmarks_ready=False,
            command_path="/usr/local/bin/bunnify",
            macos_extra=False,
            macos_platform=True,
            pipx_app_path="/Users/me/.local/bin/bunnify",
            pipx_version_label="0.8.3 (abc12345)",
            preferences_ready=False,
            pypi_latest="0.8.3",
            server_agent_installed=False,
            source_checkout=False,
            spotty_agent_installed=False,
            upgrade_available=False,
            version_label="0.8.3 (abc12345)",
        )
        text = format_onboarding_text(state)
        self.assertIn("Already installed:", text)
        self.assertIn("pipx app:", text)
        self.assertIn("bunnify onboard", text)
        self.assertIn("pipx install --force", text)

    def test_run_onboard_offers_macos_extra_install(self) -> None:
        stdout = StringIO()
        state_without_extra = InstallState(
            bookmarks_ready=True,
            command_path="/Users/me/.local/bin/bunnify",
            macos_extra=False,
            macos_platform=True,
            pipx_app_path="/Users/me/.local/bin/bunnify",
            pipx_version_label="0.8.3 (abc12345)",
            preferences_ready=True,
            pypi_latest="0.8.3",
            server_agent_installed=False,
            source_checkout=False,
            spotty_agent_installed=False,
            upgrade_available=False,
            version_label="0.8.3 (abc12345)",
        )
        state_with_extra = InstallState(
            bookmarks_ready=True,
            command_path="/Users/me/.local/bin/bunnify",
            macos_extra=True,
            macos_platform=True,
            pipx_app_path="/Users/me/.local/bin/bunnify",
            pipx_version_label="0.8.3 (abc12345)",
            preferences_ready=True,
            pypi_latest="0.8.3",
            server_agent_installed=False,
            source_checkout=False,
            spotty_agent_installed=False,
            upgrade_available=False,
            version_label="0.8.3 (abc12345)",
        )
        state_with_agent = InstallState(
            bookmarks_ready=True,
            command_path="/Users/me/.local/bin/bunnify",
            macos_extra=True,
            macos_platform=True,
            pipx_app_path="/Users/me/.local/bin/bunnify",
            pipx_version_label="0.8.3 (abc12345)",
            preferences_ready=True,
            pypi_latest="0.8.3",
            server_agent_installed=False,
            source_checkout=False,
            spotty_agent_installed=True,
            upgrade_available=False,
            version_label="0.8.3 (abc12345)",
        )

        def ask(_message: str) -> str:
            return "y"

        with (
            patch(
                "app.onboard.detect_install_state",
                side_effect=[
                    state_without_extra,
                    state_with_extra,
                    state_with_agent,
                ],
            ),
            patch("app.onboard.sys.stdin") as stdin,
            patch("app.onboard.sys.stdout") as stdout_tty,
            patch("app.onboard.shutil.which", return_value="/usr/bin/pipx"),
            patch("app.onboard.install_macos_extra", return_value=True) as install,
            patch("app.onboard.load_preferences", return_value=None),
            patch("app.spotty_bunny_agent.install_agent", return_value=0) as agent,
            patch("app.cli._confirm_explicit_yes", side_effect=[True, False]),
        ):
            stdin.isatty.return_value = True
            stdout_tty.isatty.return_value = True
            run_onboard(print_fn=stdout.write, prompt_fn=ask)
        install.assert_called_once_with("/usr/bin/pipx")
        agent.assert_called_once()
        self.assertIs(agent.call_args.kwargs.get("prompt_fn"), ask)
        output = stdout.getvalue()
        self.assertIn("Already installed:", output)
        self.assertIn("Spotty Bunny LaunchAgent: installed", output)

    def test_run_onboard_prints_the_install_summary_once(self) -> None:
        stdout = StringIO()
        state = self._state(preferences_ready=True, bookmarks_ready=True)
        with (
            patch("app.onboard.detect_install_state", return_value=state),
            patch("app.onboard.load_preferences", return_value=None),
            patch("app.onboard.sys.stdin") as stdin,
        ):
            stdin.isatty.return_value = False
            run_onboard(print_fn=stdout.write, prompt_fn=lambda _m: "n")
        output = stdout.getvalue()
        self.assertEqual(output.count("Already installed:"), 1, output)
        # ... and the rest of the guidance still follows it.
        self.assertIn("next steps after install or upgrade", output)
        self.assertIn("Upgrade later (preferred):", output)

    def test_run_onboard_repeats_the_summary_only_when_the_install_changed(
        self,
    ) -> None:
        stdout = StringIO()
        before = self._state(
            bookmarks_ready=True,
            pypi_latest="0.16.0",
            upgrade_available=True,
            version_label="0.15.0 (old)",
        )
        after = self._state(bookmarks_ready=True, version_label="0.16.0 (new)")
        with (
            patch("app.onboard.detect_install_state", side_effect=[before, after]),
            patch("app.onboard.load_preferences", return_value=None),
            patch("app.onboard.sys.stdin") as stdin,
            patch("app.onboard.sys.stdout") as stdout_tty,
        ):
            stdin.isatty.return_value = True
            stdout_tty.isatty.return_value = True
            run_onboard(
                print_fn=stdout.write,
                prompt_fn=lambda _m: "y",
                confirm_yes=lambda _ask, _msg: True,
                run_upgrade=lambda **_kwargs: None,
            )
        output = stdout.getvalue()
        self.assertEqual(output.count("Already installed: 0.15.0 (old)"), 1, output)
        self.assertEqual(output.count("Already installed: 0.16.0 (new)"), 1, output)

    def test_format_onboarding_text_can_leave_the_summary_out(self) -> None:
        state = self._state(bookmarks_ready=True)
        self.assertIn("Already installed:", format_onboarding_text(state))
        self.assertNotIn(
            "Already installed:", format_onboarding_text(state, include_summary=False)
        )

    def test_run_onboard_installs_server_agent_for_local_prefs(self) -> None:
        from app.config import ServerPreferences

        stdout = StringIO()
        before = InstallState(
            bookmarks_ready=True,
            command_path="/Users/me/.local/bin/bunnify",
            macos_extra=True,
            macos_platform=True,
            pipx_app_path="/Users/me/.local/bin/bunnify",
            pipx_version_label="0.8.3 (abc12345)",
            preferences_ready=True,
            pypi_latest="0.8.3",
            server_agent_installed=False,
            source_checkout=False,
            spotty_agent_installed=False,
            upgrade_available=False,
            version_label="0.8.3 (abc12345)",
        )
        after = InstallState(
            bookmarks_ready=True,
            command_path="/Users/me/.local/bin/bunnify",
            macos_extra=True,
            macos_platform=True,
            pipx_app_path="/Users/me/.local/bin/bunnify",
            pipx_version_label="0.8.3 (abc12345)",
            preferences_ready=True,
            pypi_latest="0.8.3",
            server_agent_installed=True,
            source_checkout=False,
            spotty_agent_installed=True,
            upgrade_available=False,
            version_label="0.8.3 (abc12345)",
        )
        prefs = ServerPreferences(
            mode="local",
            base_url="http://127.0.0.1:8123",
            local_port=8123,
        )

        with (
            patch(
                "app.onboard.detect_install_state",
                side_effect=[before, after, after],
            ),
            patch("app.onboard.sys.stdin") as stdin,
            patch("app.onboard.sys.stdout") as stdout_tty,
            patch("app.onboard.load_preferences", return_value=prefs),
            patch("app.server_agent.install_agent", return_value=0) as server,
            patch("app.spotty_bunny_agent.install_agent", return_value=0) as spotty,
            patch("app.client.check_health", return_value=True),
            patch("app.cli._confirm_explicit_yes", return_value=True),
        ):
            stdin.isatty.return_value = True
            stdout_tty.isatty.return_value = True
            run_onboard(print_fn=stdout.write, prompt_fn=lambda _m: "y")
        server.assert_called_once()
        self.assertEqual(server.call_args.kwargs["port"], 8123)
        spotty.assert_called_once()
        self.assertIn(
            "Local Bunnify server LaunchAgent is installed", stdout.getvalue()
        )

    def test_run_onboard_skips_spotty_when_remote_unreachable_declined(self) -> None:
        from app.config import ServerPreferences

        stdout = StringIO()
        state = InstallState(
            bookmarks_ready=True,
            command_path="/Users/me/.local/bin/bunnify",
            macos_extra=True,
            macos_platform=True,
            pipx_app_path="/Users/me/.local/bin/bunnify",
            pipx_version_label="0.8.3 (abc12345)",
            preferences_ready=True,
            pypi_latest="0.8.3",
            server_agent_installed=False,
            source_checkout=False,
            spotty_agent_installed=False,
            upgrade_available=False,
            version_label="0.8.3 (abc12345)",
        )
        prefs = ServerPreferences(
            mode="remote",
            base_url="https://broken.example",
            local_port=None,
        )

        with (
            patch("app.onboard.detect_install_state", return_value=state),
            patch("app.onboard.sys.stdin") as stdin,
            patch("app.onboard.sys.stdout") as stdout_tty,
            patch("app.onboard.load_preferences", return_value=prefs),
            patch("app.client.check_health", return_value=False),
            patch("app.spotty_bunny_agent.install_agent") as spotty,
            patch("app.cli._confirm_explicit_yes", return_value=False),
        ):
            stdin.isatty.return_value = True
            stdout_tty.isatty.return_value = True
            # Keep configured remote (first prompt); unreachable continue uses
            # patched _confirm_explicit_yes → False (skip Spotty).
            run_onboard(print_fn=stdout.write, prompt_fn=lambda _m: "y")
        spotty.assert_not_called()
        self.assertIn("Skipping Spotty Bunny install", stdout.getvalue())
        self.assertIn("Configured mode: remote", stdout.getvalue())

    def test_run_onboard_declined_keep_calls_setup(self) -> None:
        from app.client import ClientError
        from app.config import ServerPreferences

        stdout = StringIO()
        before = InstallState(
            bookmarks_ready=True,
            command_path="/Users/me/.local/bin/bunnify",
            macos_extra=True,
            macos_platform=False,
            pipx_app_path="/Users/me/.local/bin/bunnify",
            pipx_version_label="0.8.3 (abc12345)",
            preferences_ready=True,
            pypi_latest="0.8.3",
            server_agent_installed=False,
            source_checkout=False,
            spotty_agent_installed=False,
            upgrade_available=False,
            version_label="0.8.3 (abc12345)",
        )
        after = InstallState(
            bookmarks_ready=True,
            command_path="/Users/me/.local/bin/bunnify",
            macos_extra=True,
            macos_platform=False,
            pipx_app_path="/Users/me/.local/bin/bunnify",
            pipx_version_label="0.8.3 (abc12345)",
            preferences_ready=True,
            pypi_latest="0.8.3",
            server_agent_installed=False,
            source_checkout=False,
            spotty_agent_installed=False,
            upgrade_available=False,
            version_label="0.8.3 (abc12345)",
        )
        prefs = ServerPreferences(
            mode="remote",
            base_url="https://old.example",
            local_port=None,
        )
        setup = MagicMock(return_value="https://new.example")
        with (
            patch(
                "app.onboard.detect_install_state",
                side_effect=[before, after],
            ) as detect,
            patch("app.onboard.sys.stdin") as stdin,
            patch("app.onboard.sys.stdout") as stdout_tty,
            patch("app.onboard.load_preferences", return_value=prefs),
            patch("app.cli.run_setup", setup),
        ):
            stdin.isatty.return_value = True
            stdout_tty.isatty.return_value = True
            run_onboard(print_fn=stdout.write, prompt_fn=lambda _m: "n")
        setup.assert_called_once()
        self.assertTrue(setup.call_args.kwargs.get("skip_keep_confirmation"))
        self.assertEqual(detect.call_count, 2)
        self.assertIn("Opening setup to reconfigure", stdout.getvalue())

        setup_err = MagicMock(side_effect=ClientError("setup failed"))
        stdout_err = StringIO()
        with (
            patch("app.onboard.detect_install_state", return_value=before),
            patch("app.onboard.sys.stdin") as stdin,
            patch("app.onboard.sys.stdout") as stdout_tty,
            patch("app.onboard.load_preferences", return_value=prefs),
            patch("app.cli.run_setup", setup_err),
        ):
            stdin.isatty.return_value = True
            stdout_tty.isatty.return_value = True
            run_onboard(print_fn=stdout_err.write, prompt_fn=lambda _m: "n")
        self.assertIn("error: setup failed", stdout_err.getvalue())

    def test_run_onboard_warns_when_macos_extra_install_fails(self) -> None:
        stdout = StringIO()
        state = InstallState(
            bookmarks_ready=True,
            command_path="/Users/me/.local/bin/bunnify",
            macos_extra=False,
            macos_platform=True,
            pipx_app_path="/Users/me/.local/bin/bunnify",
            pipx_version_label="0.8.3 (abc12345)",
            preferences_ready=True,
            pypi_latest="0.8.3",
            server_agent_installed=False,
            source_checkout=False,
            spotty_agent_installed=False,
            upgrade_available=False,
            version_label="0.8.3 (abc12345)",
        )
        with (
            patch("app.onboard.detect_install_state", return_value=state),
            patch("app.onboard.sys.stdin") as stdin,
            patch("app.onboard.sys.stdout") as stdout_tty,
            patch("app.onboard.shutil.which", return_value="/usr/bin/pipx"),
            patch("app.onboard.install_macos_extra", return_value=False),
            patch("app.spotty_bunny_agent.install_agent") as agent,
            patch("app.cli._confirm_explicit_yes", return_value=True),
        ):
            stdin.isatty.return_value = True
            stdout_tty.isatty.return_value = True
            run_onboard(print_fn=stdout.write, prompt_fn=lambda _m: "y")
        output = stdout.getvalue()
        self.assertIn("pipx install --force 'bunnify[macos]' failed.", output)
        agent.assert_not_called()

    def test_run_onboard_warns_when_pipx_missing(self) -> None:
        stdout = StringIO()
        state = InstallState(
            bookmarks_ready=True,
            command_path="/Users/me/.local/bin/bunnify",
            macos_extra=False,
            macos_platform=True,
            pipx_app_path="/Users/me/.local/bin/bunnify",
            pipx_version_label="0.8.3 (abc12345)",
            preferences_ready=True,
            pypi_latest="0.8.3",
            server_agent_installed=False,
            source_checkout=False,
            spotty_agent_installed=False,
            upgrade_available=False,
            version_label="0.8.3 (abc12345)",
        )
        with (
            patch("app.onboard.detect_install_state", return_value=state),
            patch("app.onboard.sys.stdin") as stdin,
            patch("app.onboard.sys.stdout") as stdout_tty,
            patch("app.onboard.shutil.which", return_value=None),
            patch("app.onboard.install_macos_extra") as install,
            patch("app.spotty_bunny_agent.install_agent") as agent,
            patch("app.cli._confirm_explicit_yes", return_value=True),
        ):
            stdin.isatty.return_value = True
            stdout_tty.isatty.return_value = True
            run_onboard(print_fn=stdout.write, prompt_fn=lambda _m: "y")
        output = stdout.getvalue()
        self.assertIn("pipx not found on PATH", output)
        self.assertIn("pipx install --force 'bunnify[macos]'", output)
        install.assert_not_called()
        agent.assert_not_called()

    def test_run_onboard_offers_upgrade_when_available(self) -> None:
        stdout = StringIO()
        before = InstallState(
            bookmarks_ready=True,
            command_path="/Users/me/.local/bin/bunnify",
            macos_extra=True,
            macos_platform=False,
            pipx_app_path="/Users/me/.local/bin/bunnify",
            pipx_version_label="0.8.0 (abc12345)",
            preferences_ready=True,
            pypi_latest="0.9.0",
            server_agent_installed=False,
            source_checkout=False,
            spotty_agent_installed=True,
            upgrade_available=True,
            version_label="0.8.0 (abc12345)",
        )
        after = InstallState(
            bookmarks_ready=True,
            command_path="/Users/me/.local/bin/bunnify",
            macos_extra=True,
            macos_platform=False,
            pipx_app_path="/Users/me/.local/bin/bunnify",
            pipx_version_label="0.9.0 (def67890)",
            preferences_ready=True,
            pypi_latest="0.9.0",
            server_agent_installed=False,
            source_checkout=False,
            spotty_agent_installed=True,
            upgrade_available=False,
            version_label="0.9.0 (def67890)",
        )
        upgrade = MagicMock(spec=run_upgrade)
        with (
            patch(
                "app.onboard.detect_install_state",
                side_effect=[before, after],
            ),
            patch("app.onboard.sys.stdin") as stdin,
            patch("app.onboard.sys.stdout") as stdout_tty,
            patch("app.cli._confirm_explicit_yes", return_value=True),
        ):
            stdin.isatty.return_value = True
            stdout_tty.isatty.return_value = True
            run_onboard(
                print_fn=stdout.write,
                prompt_fn=lambda _m: "y",
                run_upgrade=upgrade,
            )
        upgrade.assert_called_once()
        self.assertIn("print_fn", upgrade.call_args.kwargs)
        self.assertIn("prompt_fn", upgrade.call_args.kwargs)
        self.assertIn("theme", upgrade.call_args.kwargs)

    def test_run_onboard_reports_upgrade_client_error(self) -> None:
        stdout = StringIO()
        state = InstallState(
            bookmarks_ready=True,
            command_path="/Users/me/.local/bin/bunnify",
            macos_extra=True,
            macos_platform=False,
            pipx_app_path="/Users/me/.local/bin/bunnify",
            pipx_version_label="0.8.0 (abc12345)",
            preferences_ready=True,
            pypi_latest="0.9.0",
            server_agent_installed=False,
            source_checkout=False,
            spotty_agent_installed=True,
            upgrade_available=True,
            version_label="0.8.0 (abc12345)",
        )
        upgrade = MagicMock(spec=run_upgrade, side_effect=ClientError("pipx not found"))
        with (
            patch("app.onboard.detect_install_state", return_value=state),
            patch("app.onboard.sys.stdin") as stdin,
            patch("app.onboard.sys.stdout") as stdout_tty,
            patch("app.cli._confirm_explicit_yes", return_value=True),
        ):
            stdin.isatty.return_value = True
            stdout_tty.isatty.return_value = True
            run_onboard(
                print_fn=stdout.write,
                prompt_fn=lambda _m: "y",
                run_upgrade=upgrade,
            )
        self.assertIn("error: pipx not found", stdout.getvalue())

    def test_cli_onboard_prints_install_summary(self) -> None:
        from app.cli import main

        with (
            patch(
                "app.onboard.detect_install_state",
                return_value=InstallState(
                    bookmarks_ready=False,
                    command_path="/Users/me/.local/bin/bunnify",
                    macos_extra=False,
                    macos_platform=False,
                    pipx_app_path="/Users/me/.local/bin/bunnify",
                    pipx_version_label="0.8.3 (abc12345)",
                    preferences_ready=False,
                    pypi_latest="0.8.3",
                    server_agent_installed=False,
                    source_checkout=False,
                    spotty_agent_installed=False,
                    upgrade_available=False,
                    version_label="0.8.3 (abc12345)",
                ),
            ),
            patch("app.onboard.sys.stdin") as stdin,
            patch("app.onboard.sys.stdout") as stdout_tty,
        ):
            stdin.isatty.return_value = False
            stdout_tty.isatty.return_value = False
            result = CliRunner().invoke(main, ["onboard"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Already installed:", result.output)
        self.assertIn("bunnify setup", result.output)
        self.assertIn("bunnify upgrade", result.output)

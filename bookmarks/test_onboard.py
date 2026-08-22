"""Tests for interactive onboarding."""

from __future__ import annotations

from io import StringIO
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


class OnboardTests(SimpleTestCase):
    def test_detect_install_state_marks_upgrade_when_pypi_is_newer(self) -> None:
        with patch("app.onboard.pypi_latest_version", return_value="0.9.0"):
            state = detect_install_state(
                read_executable_build=lambda _path: "0.8.0 (abc12345)",
            )
        self.assertTrue(state.upgrade_available)
        self.assertEqual(state.pypi_latest, "0.9.0")

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
            source_checkout=False,
            spotty_agent_installed=False,
            upgrade_available=False,
            version_label="0.8.3 (abc12345)",
        )

        def ask(_message: str) -> str:
            return "y"

        with (
            patch(
                "app.onboard.detect_install_state",
                side_effect=[state_without_extra, state_with_extra],
            ),
            patch("app.onboard.sys.stdin") as stdin,
            patch("app.onboard.sys.stdout") as stdout_tty,
            patch("app.onboard.shutil.which", return_value="/usr/bin/pipx"),
            patch("app.onboard.install_macos_extra", return_value=True) as install,
            patch("app.spotty_bunny_agent.install_agent", return_value=0) as agent,
            patch("app.cli._confirm_explicit_yes", side_effect=[True, False]),
        ):
            stdin.isatty.return_value = True
            stdout_tty.isatty.return_value = True
            run_onboard(print_fn=stdout.write, prompt_fn=ask)
        install.assert_called_once_with("/usr/bin/pipx")
        agent.assert_called_once()
        self.assertIs(agent.call_args.kwargs.get("prompt_fn"), ask)
        self.assertIn("Already installed:", stdout.getvalue())

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

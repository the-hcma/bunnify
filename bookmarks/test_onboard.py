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

_FIXTURE_COMMIT = "test-fixture-commit"
_FIXTURE_INSTALLED_VERSION = "0.0.0+test-fixture-installed"
_FIXTURE_PYPI_LATEST_VERSION = "0.0.0+test-fixture-pypi-latest"


class OnboardTests(SimpleTestCase):
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

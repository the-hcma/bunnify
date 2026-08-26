"""Tests for the self-identifying argv build marker."""

from __future__ import annotations

from unittest import mock

from django.test import SimpleTestCase

from app.process_marker import (
    BUILD_MARKER_FLAG,
    SERVER_COMPONENT,
    SPOTTY_BUNNY_COMPONENT,
    build_marker_arguments,
    build_marker_value,
    marker_from_arguments,
    marker_from_command,
    parse_marker_value,
)


class BuildMarkerValueTests(SimpleTestCase):
    def test_arguments_pair_flag_with_value(self) -> None:
        self.assertEqual(
            build_marker_arguments(SERVER_COMPONENT, commit="abc123", version="1.2.3"),
            [BUILD_MARKER_FLAG, "bunnify-server:1.2.3+abc123"],
        )

    def test_defaults_come_from_running_build(self) -> None:
        with mock.patch(
            "app.process_marker.get_build_info",
            return_value=("0.11.0", "2959c24e2afc"),
        ):
            self.assertEqual(
                build_marker_value(SPOTTY_BUNNY_COMPONENT),
                "spotty-bunny:0.11.0+2959c24e2afc",
            )

    def test_local_version_segment_keeps_commit_last(self) -> None:
        marker = parse_marker_value("bunnify-server:1.2.3+local+abc123")
        assert marker is not None
        self.assertEqual(marker.version, "1.2.3+local")
        self.assertEqual(marker.commit, "abc123")


class MarkerParsingTests(SimpleTestCase):
    def test_parses_attached_value_form(self) -> None:
        marker = marker_from_arguments(
            ["bunnify-server", f"{BUILD_MARKER_FLAG}=bunnify-server:1.2.3+abc123"]
        )
        assert marker is not None
        self.assertEqual(marker.component, SERVER_COMPONENT)
        self.assertEqual(marker.version, "1.2.3")

    def test_parses_separate_value_form(self) -> None:
        marker = marker_from_command(
            "/usr/bin/python3 -E /opt/bin/bunnify-server "
            f"{BUILD_MARKER_FLAG} bunnify-server:1.2.3+abc123 --port 8000"
        )
        assert marker is not None
        self.assertEqual(marker.commit, "abc123")
        self.assertEqual(marker.component, SERVER_COMPONENT)

    def test_returns_none_for_absent_or_malformed_markers(self) -> None:
        cases = (
            "bunnify-server --port 8000",
            f"bunnify-server {BUILD_MARKER_FLAG}",
            f"bunnify-server {BUILD_MARKER_FLAG} nocolon",
            f"bunnify-server {BUILD_MARKER_FLAG} missing-build:",
            f"bunnify-server {BUILD_MARKER_FLAG} bunnify-server:1.2.3",
            f"bunnify-server {BUILD_MARKER_FLAG} :1.2.3+abc123",
        )
        for command in cases:
            with self.subTest(command=command):
                self.assertIsNone(marker_from_command(command))

    def test_returns_none_for_unparsable_command(self) -> None:
        self.assertIsNone(marker_from_command("bunnify-server --bookmarks 'unclosed"))


class MarkerDetectionTests(SimpleTestCase):
    def test_marker_alone_cannot_promote_an_unrelated_command(self) -> None:
        """A match authorizes signalling the process, so the executable gates it."""
        from app.server_cli import _is_bunnify_command

        cases = (
            f"grep -r {BUILD_MARKER_FLAG} bunnify-server:1.0+abc123 .",
            f"/opt/some-wrapper --exec {BUILD_MARKER_FLAG} bunnify-server:1.0+abc123",
            f"sh -c 'echo {BUILD_MARKER_FLAG} bunnify-server:1.0+abc123'",
        )
        for command in cases:
            with self.subTest(command=command):
                self.assertFalse(_is_bunnify_command(command))

    def test_marker_distinguishes_components(self) -> None:
        from app.server_cli import _is_bunnify_command
        from app.spotty_bunny_launch import _is_spotty_bunny_command

        server = f"/opt/bin/bunnify-server {BUILD_MARKER_FLAG} bunnify-server:1+abc123"
        spotty = f"/opt/bin/spotty-bunny {BUILD_MARKER_FLAG} spotty-bunny:1+abc123"

        self.assertTrue(_is_bunnify_command(server))
        self.assertFalse(_is_bunnify_command(spotty))
        self.assertTrue(_is_spotty_bunny_command(spotty))
        self.assertFalse(_is_spotty_bunny_command(server))

    def test_marker_rules_out_a_sibling_component_on_a_matching_shape(self) -> None:
        from app.server_cli import _is_bunnify_command

        self.assertFalse(
            _is_bunnify_command(
                "/usr/bin/python3 -E /opt/bin/bunnify-server "
                f"{BUILD_MARKER_FLAG} spotty-bunny:1.0+abc123"
            )
        )

    def test_unmarked_legacy_processes_still_match_by_shape(self) -> None:
        from app.server_cli import _is_bunnify_command
        from app.spotty_bunny_launch import _is_spotty_bunny_command

        self.assertTrue(
            _is_bunnify_command("/usr/bin/python3 -E /opt/bin/bunnify-server --port 1")
        )
        self.assertTrue(_is_spotty_bunny_command("/opt/bin/spotty-bunny"))


class MarkerStampingTests(SimpleTestCase):
    def test_background_server_command_is_stamped(self) -> None:
        from pathlib import Path

        from app.server_cli import ServerOptions, _background_command

        options = ServerOptions(
            bookmarks=None,
            console=False,
            foreground=False,
            listen_all=False,
            log_file=Path("/tmp/bunnify.log"),
            log_level="INFO",
            noninteractive=True,
            pid_dir=Path("/tmp/run"),
            port=8000,
            port_timeout_s=5.0,
            replace_on_port=None,
            stop=False,
        )
        command = _background_command(options, Path("/tmp/bookmarks.json"), 8000)

        self.assertIn(BUILD_MARKER_FLAG, command)
        marker = marker_from_arguments(command)
        assert marker is not None
        self.assertEqual(marker.component, SERVER_COMPONENT)

    def test_background_server_command_parses_back_into_the_server_cli(self) -> None:
        from pathlib import Path

        from app.server_cli import ServerOptions, _background_command, build_parser

        options = ServerOptions(
            bookmarks=None,
            console=False,
            foreground=False,
            listen_all=False,
            log_file=Path("/tmp/bunnify.log"),
            log_level="INFO",
            noninteractive=True,
            pid_dir=Path("/tmp/run"),
            port=8000,
            port_timeout_s=5.0,
            replace_on_port=None,
            stop=False,
        )
        command = _background_command(options, Path("/tmp/bookmarks.json"), 8000)

        namespace = build_parser().parse_args(command[3:])
        self.assertEqual(namespace.port, 8000)

    def test_spotty_bunny_launch_arguments_are_stamped(self) -> None:
        from app.spotty_bunny_launch import spotty_bunny_launch_arguments

        with mock.patch(
            "app.spotty_bunny_launch.spotty_bunny_command",
            return_value=["/opt/bin/spotty-bunny"],
        ):
            arguments = spotty_bunny_launch_arguments(commit="abc123")
        marker = marker_from_arguments(arguments)
        assert marker is not None
        self.assertEqual(marker.commit, "abc123")
        self.assertEqual(marker.component, SPOTTY_BUNNY_COMPONENT)

    def test_spotty_bunny_launch_arguments_parse_back_into_the_cli(self) -> None:
        """Pin the console-script form; the fallback prepends ``-m <module>``."""
        from app.spotty_bunny_cli import build_parser
        from app.spotty_bunny_launch import spotty_bunny_launch_arguments

        with mock.patch(
            "app.spotty_bunny_launch.spotty_bunny_command",
            return_value=["/opt/bin/spotty-bunny"],
        ):
            arguments = spotty_bunny_launch_arguments(commit="abc123")
        namespace = build_parser().parse_args(arguments[1:])
        self.assertEqual(namespace.log_level, "INFO")

    def test_spotty_bunny_module_fallback_arguments_parse_back_into_the_cli(
        self,
    ) -> None:
        from app.spotty_bunny_cli import build_parser
        from app.spotty_bunny_launch import spotty_bunny_launch_arguments

        with mock.patch(
            "app.spotty_bunny_launch.spotty_bunny_command",
            return_value=["/usr/bin/python3", "-m", "app.spotty_bunny_cli"],
        ):
            arguments = spotty_bunny_launch_arguments(commit="abc123")
        namespace = build_parser().parse_args(arguments[3:])
        self.assertEqual(namespace.log_level, "INFO")

    def test_spotty_bunny_plist_arguments_are_stamped(self) -> None:
        from app.spotty_bunny_agent import spotty_bunny_program_arguments

        with mock.patch(
            "app.spotty_bunny_agent.spotty_bunny_command",
            return_value=["/opt/bin/spotty-bunny"],
        ):
            arguments = spotty_bunny_program_arguments()

        assert arguments is not None
        marker = marker_from_arguments(arguments)
        assert marker is not None
        self.assertEqual(marker.component, SPOTTY_BUNNY_COMPONENT)

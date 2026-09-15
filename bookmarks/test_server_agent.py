"""Tests for the Bunnify server macOS LaunchAgent."""

from __future__ import annotations

import subprocess
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import call, patch

from django.test import SimpleTestCase


class ServerAgentTests(SimpleTestCase):
    def test_format_agent_plist_matches_example_placeholders(self) -> None:
        from app.server_agent import AGENT_LABEL, format_agent_plist

        root = Path(__file__).resolve().parents[1]
        example = (
            root / "etc" / "launchd" / "com.thehcma.bunnify.plist.example"
        ).read_text(encoding="utf-8")
        home = Path("/Users/test")
        expected = example.replace(
            "    <string>__BUNNIFY_SERVER__</string>\n"
            "    <string>--foreground</string>\n"
            "    <string>--noninteractive</string>\n"
            "    <string>--port</string>\n"
            "    <string>8000</string>\n"
            "    <string>--pid-dir</string>\n"
            "    <string>__HOME__/.local/share/bunnify/run/launchd</string>",
            "    <string>/opt/bunnify-server</string>\n"
            "    <string>--foreground</string>\n"
            "    <string>--noninteractive</string>\n"
            "    <string>--port</string>\n"
            "    <string>8000</string>\n"
            "    <string>--pid-dir</string>\n"
            "    <string>/Users/test/.local/share/bunnify/run/launchd</string>",
        ).replace("__HOME__", "/Users/test")
        self.assertEqual(
            format_agent_plist(
                home=home,
                program_arguments=[
                    "/opt/bunnify-server",
                    "--foreground",
                    "--noninteractive",
                    "--port",
                    "8000",
                    "--pid-dir",
                    "/Users/test/.local/share/bunnify/run/launchd",
                ],
            ),
            expected,
        )
        self.assertIn(AGENT_LABEL, expected)
        self.assertIn("<key>KeepAlive</key>", expected)
        self.assertIn("<key>RunAtLoad</key>", expected)

    def test_install_bootstraps_and_waits_for_health(self) -> None:
        from app.server_agent import AGENT_LABEL, install_agent

        ctl = _FakeLaunchctl()
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            program = home / "bin" / "bunnify-server"
            _write_executable(program)
            pid_dir = home / "run" / "launchd"
            stderr = StringIO()
            with (
                patch("app.server_agent.stop_local_server"),
                patch("app.server_agent.port_is_free", return_value=False),
                patch("app.server_agent.check_health", return_value=True),
                patch(
                    "app.server_agent._port_served_by_pid_dir",
                    side_effect=lambda port, pid_dir: pid_dir.name == "launchd",
                ),
            ):
                code = install_agent(
                    home=home,
                    launchctl=ctl,
                    pid_dir=pid_dir,
                    platform="darwin",
                    port=8123,
                    print_err=stderr.write,
                    program=program,
                    timeout_s=1,
                )
            plist = home / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
            self.assertEqual(code, 0)
            self.assertTrue(plist.is_file())
            text = plist.read_text(encoding="utf-8")
            self.assertIn(str(program), text)
            self.assertIn("<string>8123</string>", text)
            self.assertIn(str(pid_dir), text)
            self.assertTrue(any(call[1] == "bootstrap" for call in ctl.calls))
            self.assertIn("listening at http://127.0.0.1:8123", stderr.getvalue())

    def test_install_writes_bookmarks_into_plist(self) -> None:
        from app.server_agent import AGENT_LABEL, install_agent

        ctl = _FakeLaunchctl()
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            program = home / "bin" / "bunnify-server"
            _write_executable(program)
            pid_dir = home / "run" / "launchd"
            bookmarks = home / "custom" / "bookmarks.json"
            with (
                patch("app.server_agent.stop_local_server"),
                patch("app.server_agent.port_is_free", return_value=False),
                patch("app.server_agent.check_health", return_value=True),
                patch(
                    "app.server_agent._port_served_by_pid_dir",
                    side_effect=lambda port, pid_dir: pid_dir.name == "launchd",
                ),
            ):
                code = install_agent(
                    home=home,
                    launchctl=ctl,
                    pid_dir=pid_dir,
                    platform="darwin",
                    port=8123,
                    bookmarks=bookmarks,
                    print_err=lambda _m: None,
                    program=program,
                    timeout_s=1,
                )
            plist = home / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
            self.assertEqual(code, 0)
            text = plist.read_text(encoding="utf-8")
            self.assertIn("--bookmarks", text)
            self.assertIn(str(bookmarks.resolve()), text)

    def test_install_stamps_build_marker_into_plist(self) -> None:
        from app.process_marker import BUILD_MARKER_FLAG, marker_from_arguments
        from app.server_agent import (
            AGENT_LABEL,
            _plist_program_arguments,
            install_agent,
        )

        ctl = _FakeLaunchctl()
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            program = home / "bin" / "bunnify-server"
            _write_executable(program)
            pid_dir = home / "run" / "launchd"
            with (
                patch("app.server_agent.stop_local_server"),
                patch("app.server_agent.port_is_free", return_value=False),
                patch("app.server_agent.check_health", return_value=True),
                patch(
                    "app.server_agent._port_served_by_pid_dir",
                    side_effect=lambda port, pid_dir: pid_dir.name == "launchd",
                ),
            ):
                code = install_agent(
                    home=home,
                    launchctl=ctl,
                    pid_dir=pid_dir,
                    platform="darwin",
                    port=8123,
                    print_err=lambda _m: None,
                    program=program,
                    timeout_s=1,
                )
            plist = home / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
            self.assertEqual(code, 0)
            self.assertIn(BUILD_MARKER_FLAG, plist.read_text(encoding="utf-8"))

            argv = _plist_program_arguments(plist)
            assert argv is not None
            marker = marker_from_arguments(argv)
            assert marker is not None
            self.assertEqual(marker.component, "bunnify-server")

    def test_install_rejects_non_darwin(self) -> None:
        from app.server_agent import install_agent

        stderr = StringIO()
        code = install_agent(platform="linux", print_err=stderr.write)
        self.assertEqual(code, 1)
        self.assertIn("macOS", stderr.getvalue())

    def test_uninstall_removes_plist_and_bootouts(self) -> None:
        from app.server_agent import AGENT_LABEL, format_agent_plist, uninstall_agent

        ctl = _FakeLaunchctl()
        ctl.loaded = True
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            plist = home / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
            plist.parent.mkdir(parents=True)
            program = home / "bunnify-server"
            _write_executable(program)
            plist.write_text(
                format_agent_plist(
                    home=home,
                    program_arguments=[
                        str(program),
                        "--foreground",
                        "--noninteractive",
                        "--port",
                        "8000",
                        "--pid-dir",
                        str(home / "run" / "launchd"),
                    ],
                ),
                encoding="utf-8",
            )
            with patch("app.server_agent.stop_local_server") as stop:
                code = uninstall_agent(
                    home=home,
                    launchctl=ctl,
                    pid_dir=home / "run" / "launchd",
                    platform="darwin",
                    print_err=lambda _m: None,
                )
            self.assertEqual(code, 0)
            self.assertFalse(plist.exists())
            self.assertFalse(ctl.loaded)
            self.assertTrue(any(call[1] == "bootout" for call in ctl.calls))
            stop.assert_called_once_with(
                home / "run" / "launchd",
                port=8000,
                port_timeout_s=5,
            )

    def test_run_agent_command_install_parses_port(self) -> None:
        from app.server_agent import run_agent_command

        with patch("app.server_agent.install_agent", return_value=0) as install:
            code = run_agent_command("install", ["--port", "9001"])
        self.assertEqual(code, 0)
        self.assertEqual(install.call_args.kwargs["port"], 9001)

    def test_install_rolls_back_plist_when_bootstrap_fails(self) -> None:
        from app.server_agent import AGENT_LABEL, install_agent

        ctl = _FakeLaunchctl()
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            program = home / "bin" / "bunnify-server"
            _write_executable(program)
            pid_dir = home / "run" / "launchd"
            stderr = StringIO()
            with (
                patch("app.server_agent.stop_local_server"),
                patch("app.server_agent.port_is_free", return_value=True),
                patch("app.server_agent._reload_agent", return_value=False),
            ):
                code = install_agent(
                    home=home,
                    launchctl=ctl,
                    pid_dir=pid_dir,
                    platform="darwin",
                    port=8123,
                    print_err=stderr.write,
                    program=program,
                )
            plist = home / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
            self.assertEqual(code, 1)
            self.assertFalse(plist.exists())
            self.assertIn("launchctl bootstrap failed", stderr.getvalue())

    def test_install_rolls_back_plist_when_health_fails(self) -> None:
        from app.server_agent import AGENT_LABEL, install_agent

        ctl = _FakeLaunchctl()
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            program = home / "bin" / "bunnify-server"
            _write_executable(program)
            pid_dir = home / "run" / "launchd"
            with (
                patch("app.server_agent.stop_local_server"),
                patch("app.server_agent.port_is_free", return_value=True),
                patch("app.server_agent.check_health", return_value=False),
                patch("app.server_agent._port_served_by_pid_dir", return_value=False),
            ):
                code = install_agent(
                    home=home,
                    launchctl=ctl,
                    pid_dir=pid_dir,
                    platform="darwin",
                    port=8123,
                    print_err=lambda _m: None,
                    program=program,
                    timeout_s=0.2,
                )
            plist = home / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
            self.assertEqual(code, 1)
            self.assertFalse(plist.exists())
            self.assertFalse(ctl.loaded)

    def test_install_restores_previous_plist_when_bootstrap_fails(self) -> None:
        from app.server_agent import (
            AGENT_LABEL,
            COMMAND_NAME,
            format_agent_plist,
            install_agent,
        )

        ctl = _FakeLaunchctl()
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            program = home / "bin" / "bunnify-server"
            _write_executable(program)
            pid_dir = home / "run" / "launchd"
            restored_pid_dir = home / "run" / "launchd-previous"
            plist = home / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
            plist.parent.mkdir(parents=True)
            previous_plist_text = format_agent_plist(
                home=home,
                program_arguments=[
                    str(program),
                    "--foreground",
                    "--noninteractive",
                    "--port",
                    "8000",
                    "--pid-dir",
                    str(restored_pid_dir),
                ],
            )
            plist.write_text(previous_plist_text, encoding="utf-8")
            stderr = StringIO()
            with (
                patch("app.server_agent.stop_local_server") as stop,
                patch("app.server_agent.port_is_free", return_value=True),
                patch("app.server_agent._reload_agent", return_value=False),
                patch(
                    "app.server_agent._wait_for_managed_health",
                    side_effect=lambda base_url, *, pid_dir, port, timeout_s: (
                        port == 8000 and pid_dir == restored_pid_dir
                    ),
                ),
            ):
                code = install_agent(
                    home=home,
                    launchctl=ctl,
                    pid_dir=pid_dir,
                    platform="darwin",
                    port=8123,
                    print_err=stderr.write,
                    program=program,
                )
            self.assertEqual(code, 1)
            self.assertTrue(plist.is_file())
            self.assertEqual(plist.read_text(encoding="utf-8"), previous_plist_text)
            # The restored plist must actually be re-bootstrapped into
            # launchd, not just written to disk -- otherwise local mode is
            # left uninstalled despite the "restored" message below.
            self.assertTrue(ctl.loaded)
            self.assertIn(
                "restored the previous LaunchAgent configuration",
                stderr.getvalue(),
            )
            # Callers surface messages[-1] as the reported failure detail, so
            # the root-cause line must be last -- not just present anywhere.
            self.assertTrue(
                stderr.getvalue().endswith(
                    f"{COMMAND_NAME}: launchctl bootstrap failed for {plist}."
                ),
                stderr.getvalue(),
            )
            # _wait_for_managed_health is asserted (via side_effect) to have
            # been probed on the *restored* plist's port (8000) and pid_dir
            # (restored_pid_dir, distinct from the failed attempt's pid_dir),
            # proving install_agent re-derives both from the restored plist
            # rather than reusing the failed attempt's. Only one stop against
            # this pid_dir (the initial rollback stop, before the restore)
            # should run; a second one here would target the
            # just-restored (healthy) server instead.
            pid_dir_calls = [c for c in stop.call_args_list if c.args[0] == pid_dir]
            self.assertEqual(
                pid_dir_calls, [call(pid_dir, port=8123, port_timeout_s=5)]
            )

    def test_install_preserves_previous_plist_when_restore_also_fails(self) -> None:
        """A restore whose retry never becomes healthy must not delete the
        last-known-good plist -- it stays on disk (unloaded) so a later
        `install` can retry against it instead of leaving local mode with
        nothing to fall back to. Regression test for the bug fixed alongside
        `_rollback_outcome_message`: `_rollback_failed_install` used to call
        `plist.unlink(missing_ok=True)` unconditionally, even after a restore
        attempt, silently deleting a previously-working configuration.
        """
        from app.server_agent import AGENT_LABEL, format_agent_plist, install_agent

        ctl = _FakeLaunchctl()
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            program = home / "bin" / "bunnify-server"
            _write_executable(program)
            pid_dir = home / "run" / "launchd"
            restored_pid_dir = home / "run" / "launchd-previous"
            plist = home / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
            plist.parent.mkdir(parents=True)
            previous_plist_text = format_agent_plist(
                home=home,
                program_arguments=[
                    str(program),
                    "--foreground",
                    "--noninteractive",
                    "--port",
                    "8000",
                    "--pid-dir",
                    str(restored_pid_dir),
                ],
            )
            plist.write_text(previous_plist_text, encoding="utf-8")
            stderr = StringIO()
            with (
                patch("app.server_agent.stop_local_server") as stop,
                patch("app.server_agent.port_is_free", return_value=True),
                patch("app.server_agent._reload_agent", return_value=False),
                patch("app.server_agent._wait_for_managed_health", return_value=False),
            ):
                code = install_agent(
                    home=home,
                    launchctl=ctl,
                    pid_dir=pid_dir,
                    platform="darwin",
                    port=8123,
                    print_err=stderr.write,
                    program=program,
                )
            self.assertEqual(code, 1)
            self.assertTrue(plist.is_file())
            self.assertEqual(plist.read_text(encoding="utf-8"), previous_plist_text)
            self.assertIn(
                "kept the previous LaunchAgent configuration on disk",
                stderr.getvalue(),
            )
            self.assertIn(
                "local mode is now down",
                stderr.getvalue(),
            )
            # Cleanup after a failed restore must target the *restored*
            # plist's port (8000) and pid_dir (restored_pid_dir, distinct
            # from the failed attempt's pid_dir), not the failed attempt's.
            stop.assert_any_call(restored_pid_dir, port=8000, port_timeout_s=5)

    def test_install_removes_plist_when_fresh_install_never_becomes_healthy(
        self,
    ) -> None:
        """With no previous configuration to restore (fresh install), a
        failed rollback still removes the non-functional plist."""
        from app.server_agent import AGENT_LABEL, install_agent

        ctl = _FakeLaunchctl()
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            program = home / "bin" / "bunnify-server"
            _write_executable(program)
            pid_dir = home / "run" / "launchd"
            plist = home / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
            stderr = StringIO()
            with (
                patch("app.server_agent.stop_local_server"),
                patch("app.server_agent.port_is_free", return_value=True),
                patch("app.server_agent._reload_agent", return_value=False),
            ):
                code = install_agent(
                    home=home,
                    launchctl=ctl,
                    pid_dir=pid_dir,
                    platform="darwin",
                    port=8123,
                    print_err=stderr.write,
                    program=program,
                )
            self.assertEqual(code, 1)
            self.assertFalse(plist.exists())
            self.assertIn(
                "removed the non-functional LaunchAgent configuration",
                stderr.getvalue(),
            )

    def test_install_restores_previous_plist_when_health_check_fails(self) -> None:
        from app.server_agent import (
            AGENT_LABEL,
            COMMAND_NAME,
            format_agent_plist,
            install_agent,
        )

        ctl = _FakeLaunchctl()
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            program = home / "bin" / "bunnify-server"
            _write_executable(program)
            pid_dir = home / "run" / "launchd"
            restored_pid_dir = home / "run" / "launchd-previous"
            plist = home / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
            plist.parent.mkdir(parents=True)
            previous_plist_text = format_agent_plist(
                home=home,
                program_arguments=[
                    str(program),
                    "--foreground",
                    "--noninteractive",
                    "--port",
                    "8000",
                    "--pid-dir",
                    str(restored_pid_dir),
                ],
            )
            plist.write_text(previous_plist_text, encoding="utf-8")
            stderr = StringIO()
            with (
                patch("app.server_agent.stop_local_server"),
                patch("app.server_agent.port_is_free", return_value=True),
                patch(
                    "app.server_agent._wait_for_managed_health",
                    side_effect=lambda base_url, *, pid_dir, port, timeout_s: (
                        port == 8000 and pid_dir == restored_pid_dir
                    ),
                ),
            ):
                # `_reload_agent` is left un-mocked here (unlike the
                # bootstrap-failure test above) so this exercises the
                # *second* `_rollback_failed_install` call site -- the one
                # reached when the new plist loads but its server never
                # becomes healthy, which is the more common upgrade failure.
                code = install_agent(
                    home=home,
                    launchctl=ctl,
                    pid_dir=pid_dir,
                    platform="darwin",
                    port=8123,
                    print_err=stderr.write,
                    program=program,
                    timeout_s=0.2,
                )
            self.assertEqual(code, 1)
            self.assertTrue(plist.is_file())
            self.assertEqual(plist.read_text(encoding="utf-8"), previous_plist_text)
            # The restored plist must actually be re-bootstrapped into
            # launchd, not just written to disk -- otherwise local mode is
            # left uninstalled despite the "restored" message below.
            self.assertTrue(ctl.loaded)
            self.assertIn(
                "restored the previous LaunchAgent configuration",
                stderr.getvalue(),
            )
            self.assertTrue(
                stderr.getvalue().endswith(
                    f"{COMMAND_NAME}: server at http://127.0.0.1:8123 "
                    "did not become healthy."
                ),
                stderr.getvalue(),
            )

    def test_install_rejects_foreign_server_on_port(self) -> None:
        from app.server_agent import AGENT_LABEL, install_agent

        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            program = home / "bin" / "bunnify-server"
            _write_executable(program)
            pid_dir = home / "run" / "launchd"
            stderr = StringIO()
            with (
                patch("app.server_agent.stop_local_server"),
                patch("app.server_agent.port_is_free", return_value=False),
                patch("app.server_agent.check_health", return_value=True),
                patch("app.server_agent._port_served_by_pid_dir", return_value=False),
            ):
                code = install_agent(
                    home=home,
                    pid_dir=pid_dir,
                    platform="darwin",
                    port=8123,
                    print_err=stderr.write,
                    program=program,
                )
            plist = home / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
            self.assertEqual(code, 1)
            self.assertFalse(plist.exists())
            self.assertIn("another Bunnify server", stderr.getvalue())

    def test_upgrade_agent_preserves_port_and_bookmarks(self) -> None:
        from app.server_agent import AGENT_LABEL, format_agent_plist, upgrade_agent

        ctl = _FakeLaunchctl()
        ctl.loaded = True
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            program = home / "bin" / "bunnify-server"
            _write_executable(program)
            pid_dir = home / "run" / "launchd"
            bookmarks = home / "custom" / "bookmarks.json"
            plist = home / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
            plist.parent.mkdir(parents=True)
            plist.write_text(
                format_agent_plist(
                    home=home,
                    program_arguments=[
                        str(program),
                        "--foreground",
                        "--noninteractive",
                        "--port",
                        "8123",
                        "--pid-dir",
                        str(pid_dir),
                        "--bookmarks",
                        str(bookmarks),
                    ],
                ),
                encoding="utf-8",
            )
            with patch("app.server_agent.install_agent", return_value=0) as install:
                code = upgrade_agent(
                    home=home,
                    launchctl=ctl,
                    platform="darwin",
                    print_err=lambda _m: None,
                )
            self.assertEqual(code, 0)
            install.assert_called_once()
            self.assertEqual(install.call_args.kwargs["port"], 8123)
            self.assertEqual(install.call_args.kwargs["bookmarks"], bookmarks)

    def test_upgrade_agent_unescapes_xml_entities_in_plist(self) -> None:
        from app.server_agent import AGENT_LABEL, format_agent_plist, upgrade_agent

        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            program = home / "bin" / "bunnify-server"
            _write_executable(program)
            pid_dir = home / "Smith&Co" / "run" / "launchd"
            bookmarks = home / "Smith&Co" / "bookmarks.json"
            plist = home / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
            plist.parent.mkdir(parents=True)
            plist.write_text(
                format_agent_plist(
                    home=home,
                    program_arguments=[
                        str(program),
                        "--foreground",
                        "--noninteractive",
                        "--port",
                        "8123",
                        "--pid-dir",
                        str(pid_dir),
                        "--bookmarks",
                        str(bookmarks),
                    ],
                ),
                encoding="utf-8",
            )
            with patch("app.server_agent.install_agent", return_value=0) as install:
                code = upgrade_agent(
                    home=home,
                    platform="darwin",
                    print_err=lambda _m: None,
                )
            self.assertEqual(code, 0)
            self.assertEqual(install.call_args.kwargs["bookmarks"], bookmarks)
            self.assertEqual(install.call_args.kwargs["pid_dir"], None)
            self.assertEqual(
                install.call_args.kwargs["port"],
                8123,
            )
            self.assertEqual(
                str(install.call_args.kwargs["bookmarks"]),
                str(bookmarks),
            )

    def test_status_agent_reports_loaded_healthy(self) -> None:
        from app.server_agent import AGENT_LABEL, format_agent_plist, status_agent

        ctl = _FakeLaunchctl()
        ctl.loaded = True
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            program = home / "bunnify-server"
            _write_executable(program)
            plist = home / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
            plist.parent.mkdir(parents=True)
            plist.write_text(
                format_agent_plist(
                    home=home,
                    program_arguments=[
                        str(program),
                        "--foreground",
                        "--noninteractive",
                        "--port",
                        "8123",
                        "--pid-dir",
                        str(home / "run" / "launchd"),
                    ],
                ),
                encoding="utf-8",
            )
            stdout = StringIO()
            with patch("app.server_agent.check_health", return_value=True):
                code = status_agent(
                    home=home,
                    launchctl=ctl,
                    platform="darwin",
                    print_fn=stdout.write,
                )
            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("healthy: yes", output)
            self.assertIn("launchd: loaded", output)
            self.assertIn("url: http://127.0.0.1:8123", output)

    def test_server_cli_dispatches_install(self) -> None:
        from app.server_cli import main

        with patch("app.server_agent.run_agent_command", return_value=0) as run:
            code = main(["install", "--port", "8000"])
        self.assertEqual(code, 0)
        run.assert_called_once_with("install", ["--port", "8000"])

    def test_wait_for_managed_health_accepts_port_file_match(self) -> None:
        from app.server_agent import _wait_for_managed_health

        with TemporaryDirectory() as tmp:
            pid_dir = Path(tmp)
            port_file = pid_dir / ".bunnify.port"
            port_file.write_text("8123", encoding="utf-8")
            with (
                patch("app.server_agent.check_health", return_value=True),
                patch("app.server_agent._port_served_by_pid_dir", return_value=False),
                patch("app.server_agent.time.sleep"),
            ):
                healthy = _wait_for_managed_health(
                    "http://127.0.0.1:8123",
                    pid_dir=pid_dir,
                    port=8123,
                    timeout_s=1.0,
                )
        self.assertTrue(healthy)

    def test_managed_port_file_matches_reads_recorded_port(self) -> None:
        from app.server_agent import _managed_port_file_matches

        with TemporaryDirectory() as tmp:
            port_file = Path(tmp) / ".bunnify.port"
            port_file.write_text("8123\n", encoding="utf-8")
            self.assertTrue(_managed_port_file_matches(port_file, 8123))
            self.assertFalse(_managed_port_file_matches(port_file, 9000))


class _FakeLaunchctl:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.loaded = False

    def __call__(
        self, argv: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        if len(argv) >= 2 and argv[1] == "print":
            return subprocess.CompletedProcess(argv, 0 if self.loaded else 1, "", "")
        if len(argv) >= 2 and argv[1] == "bootstrap":
            self.loaded = True
        if len(argv) >= 2 and argv[1] == "bootout":
            self.loaded = False
        return subprocess.CompletedProcess(argv, 0, "", "")


def _write_executable(path: Path, *, content: str = "#!/bin/sh\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path

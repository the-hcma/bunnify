"""Tests for the Bunnify server macOS LaunchAgent."""

from __future__ import annotations

import subprocess
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

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

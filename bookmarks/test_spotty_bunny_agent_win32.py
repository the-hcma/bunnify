"""Tests for the Spotty Bunny Windows Scheduled Task agent."""

from __future__ import annotations

import subprocess
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase

from app.spotty_bunny_task_win32 import format_task_xml


class InstallAgentTests(SimpleTestCase):
    def test_rejects_non_win32(self) -> None:
        from app.spotty_bunny_agent_win32 import install_agent

        stderr = StringIO()
        code = install_agent(platform="darwin", print_err=stderr.write)
        self.assertEqual(code, 1)
        self.assertIn("only available on Windows", stderr.getvalue())

    def test_missing_binary_reports_error(self) -> None:
        from app.spotty_bunny_agent_win32 import install_agent

        stderr = StringIO()
        with (
            patch(
                "app.spotty_bunny_agent_win32.spotty_bunny_program_arguments",
                return_value=None,
            ),
            patch(
                "app.spotty_bunny_agent_win32.spotty_bunny_program", return_value=None
            ),
        ):
            code = install_agent(
                platform="win32", print_err=stderr.write, schtasks=_FakeSchtasks()
            )
        self.assertEqual(code, 1)
        self.assertIn("could not find the spotty-bunny binary", stderr.getvalue())

    def test_binary_not_executable_reports_error(self) -> None:
        from app.spotty_bunny_agent_win32 import install_agent

        with TemporaryDirectory() as tmp:
            program = Path(tmp) / "missing-binary.exe"
            stderr = StringIO()
            code = install_agent(
                platform="win32",
                print_err=stderr.write,
                program=program,
                schtasks=_FakeSchtasks(),
            )
        self.assertEqual(code, 1)
        self.assertIn("missing or not executable", stderr.getvalue())

    def test_registers_task_runs_it_and_reports_success(self) -> None:
        from app.spotty_bunny_agent_win32 import install_agent

        fake = _FakeSchtasks()
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            program = _write_executable(home / "spotty-bunny.exe")
            pid_dir = home / "run"
            stderr = StringIO()
            with patch(
                "app.spotty_bunny_agent_win32.spotty_bunny_is_running",
                return_value=True,
            ):
                code = install_agent(
                    pid_dir=pid_dir,
                    platform="win32",
                    print_err=stderr.write,
                    program=program,
                    schtasks=fake,
                )
        self.assertEqual(code, 0)
        self.assertTrue(fake.registered)
        self.assertTrue(fake.running)
        self.assertIn("installed Scheduled Task", stderr.getvalue())

    def test_rolls_back_when_create_fails(self) -> None:
        from app.spotty_bunny_agent_win32 import install_agent

        fake = _FakeSchtasks()
        fake.create_should_fail = True
        with TemporaryDirectory() as tmp:
            program = _write_executable(Path(tmp) / "spotty-bunny.exe")
            stderr = StringIO()
            code = install_agent(
                platform="win32",
                print_err=stderr.write,
                program=program,
                schtasks=fake,
            )
        self.assertEqual(code, 1)
        self.assertIn("schtasks /Create failed", stderr.getvalue())
        self.assertIn("removed the non-functional Scheduled Task", stderr.getvalue())

    def test_removes_task_when_fresh_install_never_becomes_healthy(self) -> None:
        from app.spotty_bunny_agent_win32 import install_agent

        fake = _FakeSchtasks()
        with TemporaryDirectory() as tmp:
            program = _write_executable(Path(tmp) / "spotty-bunny.exe")
            stderr = StringIO()
            with patch(
                "app.spotty_bunny_agent_win32._wait_for_managed_overlay",
                return_value=False,
            ):
                code = install_agent(
                    platform="win32",
                    print_err=stderr.write,
                    program=program,
                    schtasks=fake,
                    timeout_s=0.01,
                )
        self.assertEqual(code, 1)
        self.assertFalse(fake.registered)
        self.assertIn("overlay did not start", stderr.getvalue())
        self.assertIn("removed the non-functional Scheduled Task", stderr.getvalue())

    def test_restores_previous_task_when_upgrade_never_becomes_healthy(self) -> None:
        from app.spotty_bunny_agent_win32 import ROLLBACK_WAIT_TIMEOUT_S, install_agent

        fake = _FakeSchtasks()
        fake.registered = True
        fake.registered_xml = format_task_xml(
            program_arguments=["C:\\bin\\old-spotty-bunny.exe"]
        )
        previous_xml = fake.registered_xml
        with TemporaryDirectory() as tmp:
            program = _write_executable(Path(tmp) / "spotty-bunny.exe")
            stderr = StringIO()
            with patch(
                "app.spotty_bunny_agent_win32._wait_for_managed_overlay",
                side_effect=lambda *, pid_dir, timeout_s: (
                    timeout_s == ROLLBACK_WAIT_TIMEOUT_S
                ),
            ):
                code = install_agent(
                    platform="win32",
                    print_err=stderr.write,
                    program=program,
                    schtasks=fake,
                    timeout_s=0.01,
                )
        self.assertEqual(code, 1)
        self.assertEqual(fake.registered_xml, previous_xml)
        self.assertIn("restored the previous Scheduled Task", stderr.getvalue())


class UpgradeAgentTests(SimpleTestCase):
    def test_rejects_non_win32(self) -> None:
        from app.spotty_bunny_agent_win32 import upgrade_agent

        stderr = StringIO()
        code = upgrade_agent(platform="darwin", print_err=stderr.write)
        self.assertEqual(code, 1)
        self.assertIn("only available on Windows", stderr.getvalue())

    def test_rejects_when_not_installed(self) -> None:
        from app.spotty_bunny_agent_win32 import upgrade_agent

        stderr = StringIO()
        code = upgrade_agent(
            platform="win32", print_err=stderr.write, schtasks=_FakeSchtasks()
        )
        self.assertEqual(code, 1)
        self.assertIn("Scheduled Task is not installed", stderr.getvalue())

    def test_delegates_to_install_when_installed(self) -> None:
        from app.spotty_bunny_agent_win32 import upgrade_agent

        fake = _FakeSchtasks()
        fake.registered = True
        with (
            TemporaryDirectory() as tmp,
            patch(
                "app.spotty_bunny_agent_win32.install_agent", return_value=0
            ) as install,
        ):
            program = _write_executable(Path(tmp) / "spotty-bunny.exe")
            pid_dir = Path(tmp) / "run"
            code = upgrade_agent(
                pid_dir=pid_dir,
                platform="win32",
                program=program,
                schtasks=fake,
                timeout_s=5.0,
            )
        self.assertEqual(code, 0)
        install.assert_called_once_with(
            pid_dir=pid_dir,
            platform="win32",
            print_err=install.call_args.kwargs["print_err"],
            program=program,
            schtasks=fake,
            timeout_s=5.0,
        )


class UninstallAgentTests(SimpleTestCase):
    def test_rejects_non_win32(self) -> None:
        from app.spotty_bunny_agent_win32 import uninstall_agent

        stderr = StringIO()
        code = uninstall_agent(platform="darwin", print_err=stderr.write)
        self.assertEqual(code, 1)
        self.assertIn("only available on Windows", stderr.getvalue())

    def test_removes_task_stops_process_and_clears_pid(self) -> None:
        from app.spotty_bunny_agent_win32 import uninstall_agent

        fake = _FakeSchtasks()
        fake.registered = True
        with TemporaryDirectory() as tmp:
            pid_dir = Path(tmp) / "run"
            stderr = StringIO()
            with (
                patch("app.spotty_bunny_agent_win32.stop_spotty_bunny") as stop,
                patch("app.spotty_bunny_agent_win32.clear_spotty_bunny_pid") as clear,
            ):
                code = uninstall_agent(
                    pid_dir=pid_dir,
                    platform="win32",
                    print_err=stderr.write,
                    schtasks=fake,
                )
        self.assertEqual(code, 0)
        self.assertFalse(fake.registered)
        stop.assert_called_once_with(pid_dir=pid_dir)
        clear.assert_called_once_with(pid_dir=pid_dir)
        self.assertIn("uninstalled Scheduled Task", stderr.getvalue())

    def test_idempotent_when_already_uninstalled(self) -> None:
        from app.spotty_bunny_agent_win32 import uninstall_agent

        code = uninstall_agent(
            platform="win32", print_err=lambda _m: None, schtasks=_FakeSchtasks()
        )
        self.assertEqual(code, 0)


class StatusAgentTests(SimpleTestCase):
    def test_not_installed_shape(self) -> None:
        from app.spotty_bunny_agent_win32 import status_agent

        lines: list[str] = []
        code = status_agent(
            platform="win32", print_fn=lines.append, schtasks=_FakeSchtasks()
        )
        self.assertEqual(code, 1)
        self.assertIn("running: no", lines)
        self.assertIn("pid: none", lines)
        self.assertIn("task: not installed", lines)
        joined = "\n".join(lines)
        self.assertNotIn("interpreter:", joined)
        self.assertNotIn("accessibility:", joined)
        self.assertNotIn("input_monitoring:", joined)
        self.assertNotIn("launchd:", joined)

    def test_installed_and_running_is_healthy(self) -> None:
        from app.spotty_bunny_agent_win32 import status_agent
        from app.spotty_bunny_tap_health import TAP_STATE_OK, SpottyBunnyHealth

        fake = _FakeSchtasks()
        fake.registered = True
        fake.running = True
        fake.task_to_run = '"C:\\bin\\spotty-bunny.exe"'
        health = SpottyBunnyHealth(
            last_chord_at=None,
            last_event_at=None,
            reinstall_failures=0,
            tap=TAP_STATE_OK,
            updated_at=0.0,
        )
        lines: list[str] = []
        with (
            patch(
                "app.spotty_bunny_agent_win32.spotty_bunny_is_running",
                return_value=True,
            ),
            patch(
                "app.spotty_bunny_agent_win32.read_spotty_bunny_health",
                return_value=health,
            ),
            patch(
                "app.spotty_bunny_agent_win32._program_launch_target_ok",
                return_value=True,
            ),
        ):
            code = status_agent(platform="win32", print_fn=lines.append, schtasks=fake)
        self.assertEqual(code, 0)
        self.assertIn("running: yes", lines)
        self.assertIn("task: running", lines)
        self.assertIn("binary: C:\\bin\\spotty-bunny.exe", lines)
        self.assertIn(f"tap: {TAP_STATE_OK}", lines)

    def test_unhealthy_when_tap_not_ok_while_running(self) -> None:
        from app.spotty_bunny_agent_win32 import status_agent
        from app.spotty_bunny_tap_health import TAP_STATE_MISSING, SpottyBunnyHealth

        fake = _FakeSchtasks()
        fake.registered = True
        health = SpottyBunnyHealth(
            last_chord_at=None,
            last_event_at=None,
            reinstall_failures=0,
            tap=TAP_STATE_MISSING,
            updated_at=0.0,
        )
        with (
            patch(
                "app.spotty_bunny_agent_win32.spotty_bunny_is_running",
                return_value=True,
            ),
            patch(
                "app.spotty_bunny_agent_win32.read_spotty_bunny_health",
                return_value=health,
            ),
        ):
            code = status_agent(
                platform="win32", print_fn=lambda _line: None, schtasks=fake
            )
        self.assertEqual(code, 1)


class IsAgentInstalledTests(SimpleTestCase):
    def test_delegates_to_is_task_installed(self) -> None:
        from app.spotty_bunny_agent_win32 import is_agent_installed

        fake = _FakeSchtasks()
        self.assertFalse(is_agent_installed(schtasks=fake))
        fake.registered = True
        self.assertTrue(is_agent_installed(schtasks=fake))


class RunWin32AgentCommandTests(SimpleTestCase):
    def test_hotkey_delegates_without_requiring_kwargs(self) -> None:
        from app.spotty_bunny_agent_win32 import run_win32_agent_command

        with patch(
            "app.spotty_bunny_agent_win32.hotkey_command", return_value=0
        ) as hotkey:
            code = run_win32_agent_command("hotkey", ["control"])
        self.assertEqual(code, 0)
        hotkey.assert_called_once_with(["control"])

    def test_extra_arguments_are_rejected(self) -> None:
        from app.spotty_bunny_agent_win32 import run_win32_agent_command

        code = run_win32_agent_command("status", ["unexpected"])
        self.assertEqual(code, 2)

    def test_dispatches_to_each_subcommand(self) -> None:
        from app.spotty_bunny_agent_win32 import run_win32_agent_command

        for command in ("install", "status", "uninstall", "upgrade"):
            with patch(
                f"app.spotty_bunny_agent_win32.{command}_agent", return_value=0
            ) as handler:
                code = run_win32_agent_command(command, (), schtasks=_FakeSchtasks())
            self.assertEqual(code, 0)
            handler.assert_called_once_with(
                schtasks=handler.call_args.kwargs["schtasks"]
            )

    def test_unknown_command_is_rejected(self) -> None:
        from app.spotty_bunny_agent_win32 import run_win32_agent_command

        code = run_win32_agent_command("bogus")
        self.assertEqual(code, 2)


def _write_executable(path: Path, *, content: str = "#!/bin/sh\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path


class _FakeSchtasks:
    """Stateful ``schtasks.exe`` fake, mirroring ``_FakeLaunchctl``'s shape."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.registered = False
        self.registered_xml: str | None = None
        self.running = False
        self.task_to_run = ""
        self.create_should_fail = False

    def __call__(
        self, argv: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        action = argv[1] if len(argv) > 1 else None
        if action == "/Create":
            xml_path = Path(argv[argv.index("/XML") + 1])
            if self.create_should_fail:
                return subprocess.CompletedProcess(
                    argv, 1, "", "ERROR: Access is denied."
                )
            self.registered_xml = xml_path.read_text(encoding="utf-16")
            self.registered = True
            return subprocess.CompletedProcess(argv, 0, "", "")
        if action == "/Delete":
            if not self.registered:
                return subprocess.CompletedProcess(
                    argv, 1, "", "ERROR: The system cannot find the file specified.\n"
                )
            self.registered = False
            self.registered_xml = None
            self.running = False
            return subprocess.CompletedProcess(argv, 0, "", "")
        if action == "/Run":
            if not self.registered:
                return subprocess.CompletedProcess(argv, 1, "", "ERROR: not found")
            self.running = True
            return subprocess.CompletedProcess(argv, 0, "", "")
        if action == "/Query":
            if not self.registered:
                return subprocess.CompletedProcess(
                    argv, 1, "", "ERROR: The system cannot find the file specified.\n"
                )
            if "/XML" in argv:
                return subprocess.CompletedProcess(
                    argv, 0, self.registered_xml or "", ""
                )
            if "/V" in argv:
                status = "Running" if self.running else "Ready"
                stdout = (
                    f"Status:                               {status}\n"
                    f"Task To Run:                          {self.task_to_run}\n"
                )
                return subprocess.CompletedProcess(argv, 0, stdout, "")
            return subprocess.CompletedProcess(argv, 0, "", "")
        return subprocess.CompletedProcess(argv, 1, "", f"unhandled: {action}")

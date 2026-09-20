"""Tests for the Spotty Bunny Windows Scheduled Task agent."""

from __future__ import annotations

import os
import subprocess
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase

from app.spotty_bunny_task_win32 import create_or_update_task, format_task_xml


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
            with (
                patch(
                    "app.spotty_bunny_agent_win32.spotty_bunny_is_running",
                    return_value=True,
                ),
                patch(
                    "app.spotty_bunny_agent_win32.read_spotty_bunny_runtime",
                    # None before the task runs, a new pid after -- the
                    # unchanged-pid case is covered by the "never becomes
                    # healthy" tests below.
                    side_effect=[None, (4242, "test")],
                ),
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

    def test_rejects_bare_interpreter_fallback(self) -> None:
        import sys

        from app.spotty_bunny_agent_win32 import install_agent

        with TemporaryDirectory() as tmp:
            pid_dir = Path(tmp) / "run"
            stderr = StringIO()
            with patch(
                "app.spotty_bunny_agent_win32.spotty_bunny_program_arguments",
                return_value=[sys.executable, "-m", "app.spotty_bunny_cli"],
            ):
                code = install_agent(
                    pid_dir=pid_dir,
                    platform="win32",
                    print_err=stderr.write,
                    schtasks=_FakeSchtasks(),
                )
        self.assertEqual(code, 1)
        self.assertIn("no packaged spotty-bunny", stderr.getvalue())

    def test_rolls_back_when_create_fails(self) -> None:
        from app.spotty_bunny_agent_win32 import install_agent

        fake = _FakeSchtasks()
        fake.create_should_fail = True
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            program = _write_executable(home / "spotty-bunny.exe")
            pid_dir = home / "run"
            stderr = StringIO()
            code = install_agent(
                pid_dir=pid_dir,
                platform="win32",
                print_err=stderr.write,
                program=program,
                schtasks=fake,
            )
        self.assertEqual(code, 1)
        self.assertIn("schtasks /Create failed", stderr.getvalue())
        self.assertIn("schtasks said: ERROR: Access is denied.", stderr.getvalue())
        self.assertIn("no Scheduled Task was registered", stderr.getvalue())
        self.assertNotIn("non-functional", stderr.getvalue())

    def test_create_failure_over_an_existing_task_says_it_was_kept(self) -> None:
        # An upgrade whose /Create fails leaves the previous task registered,
        # so the outcome must not claim "no Scheduled Task was registered":
        # the "is a task still installed" check has to win over task_created.
        from app.spotty_bunny_agent_win32 import install_agent

        fake = _FakeSchtasks()
        fake.registered = True
        fake.registered_xml = format_task_xml(
            program_arguments=["C:\\bin\\spotty-bunny.exe"]
        )
        fake.create_should_fail = True
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            program = _write_executable(home / "spotty-bunny.exe")
            stderr = StringIO()
            code = install_agent(
                pid_dir=home / "run",
                platform="win32",
                print_err=stderr.write,
                program=program,
                schtasks=fake,
            )
        self.assertEqual(code, 1)
        self.assertTrue(fake.registered)
        self.assertIn(
            "kept the previous Scheduled Task configuration registered",
            stderr.getvalue(),
        )
        self.assertNotIn("no Scheduled Task was registered", stderr.getvalue())
        self.assertIn("schtasks said: ERROR: Access is denied.", stderr.getvalue())

    def test_removes_task_when_fresh_install_never_becomes_healthy(self) -> None:
        from app.spotty_bunny_agent_win32 import install_agent

        fake = _FakeSchtasks()
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            program = _write_executable(home / "spotty-bunny.exe")
            pid_dir = home / "run"
            stderr = StringIO()
            with patch(
                "app.spotty_bunny_agent_win32._wait_for_managed_overlay",
                return_value=False,
            ):
                code = install_agent(
                    pid_dir=pid_dir,
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

    def test_removes_task_when_no_new_instance_starts(self) -> None:
        """The pre-existing overlay (often this very process) staying up
        unchanged must not be mistaken for the task's own run -- only the
        real _wait_for_managed_overlay/_new_overlay_running guard against
        this, so nothing here mocks either of them away."""
        from app.spotty_bunny_agent_win32 import install_agent

        fake = _FakeSchtasks()
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            program = _write_executable(home / "spotty-bunny.exe")
            pid_dir = home / "run"
            stderr = StringIO()
            with (
                patch(
                    "app.spotty_bunny_agent_win32.spotty_bunny_is_running",
                    return_value=True,
                ),
                patch(
                    "app.spotty_bunny_agent_win32.read_spotty_bunny_runtime",
                    # Same pid before and after run_task_once -- nothing new
                    # ever came up.
                    return_value=(4242, "test"),
                ),
            ):
                code = install_agent(
                    pid_dir=pid_dir,
                    platform="win32",
                    print_err=stderr.write,
                    program=program,
                    schtasks=fake,
                    timeout_s=0.01,
                )
        self.assertEqual(code, 1)
        self.assertFalse(fake.registered)
        self.assertIn("overlay did not start", stderr.getvalue())

    def test_restores_previous_task_when_upgrade_never_becomes_healthy(self) -> None:
        from app.spotty_bunny_agent_win32 import ROLLBACK_WAIT_TIMEOUT_S, install_agent

        fake = _FakeSchtasks()
        fake.registered = True
        fake.registered_xml = format_task_xml(
            program_arguments=["C:\\bin\\old-spotty-bunny.exe"]
        )
        previous_xml = fake.registered_xml
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            program = _write_executable(home / "spotty-bunny.exe")
            pid_dir = home / "run"
            stderr = StringIO()
            with patch(
                "app.spotty_bunny_agent_win32._wait_for_managed_overlay",
                side_effect=lambda *, pid_dir, timeout_s, exclude_pid=None: (
                    timeout_s == ROLLBACK_WAIT_TIMEOUT_S
                ),
            ):
                code = install_agent(
                    pid_dir=pid_dir,
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

        # Uninstall stops the recorded overlay and clears its pid file, so it
        # must be pointed at a temporary directory and a fake stop: with the
        # defaults this test terminated the developer's real overlay (#527).
        with (
            TemporaryDirectory() as tmp,
            patch("app.spotty_bunny_agent_win32.stop_spotty_bunny") as stop,
            patch("app.spotty_bunny_agent_win32.clear_spotty_bunny_pid") as clear,
        ):
            pid_dir = Path(tmp) / "run"
            code = uninstall_agent(
                pid_dir=pid_dir,
                platform="win32",
                print_err=lambda _m: None,
                schtasks=_FakeSchtasks(),
            )
        self.assertEqual(code, 0)
        stop.assert_called_once_with(pid_dir=pid_dir)
        clear.assert_called_once_with(pid_dir=pid_dir)

    def test_reports_failure_and_leaves_overlay_running_when_delete_fails(
        self,
    ) -> None:
        from app.spotty_bunny_agent_win32 import uninstall_agent

        fake = _FakeSchtasks()
        fake.registered = True
        fake.delete_should_fail_with = "ERROR: Access is denied."
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
        self.assertEqual(code, 1)
        self.assertTrue(fake.registered)
        stop.assert_not_called()
        clear.assert_not_called()
        self.assertIn("schtasks /Delete failed", stderr.getvalue())
        self.assertNotIn("uninstalled Scheduled Task", stderr.getvalue())


class StatusAgentTests(SimpleTestCase):
    def test_not_installed_shape(self) -> None:
        from app.spotty_bunny_agent_win32 import status_agent

        lines: list[str] = []
        # Not the host's real overlay: with the defaults this reported
        # "running: yes" whenever Spotty Bunny was actually running (#527).
        with (
            TemporaryDirectory() as tmp,
            patch(
                "app.spotty_bunny_agent_win32.read_spotty_bunny_health",
                return_value=None,
            ),
        ):
            code = status_agent(
                pid_dir=Path(tmp) / "run",
                platform="win32",
                print_fn=lines.append,
                schtasks=_FakeSchtasks(),
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
        create_or_update_task(
            format_task_xml(program_arguments=["C:\\bin\\spotty-bunny.exe"]),
            schtasks=fake,
        )
        fake.running = True
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


class InstallOverRunningOverlayTests(SimpleTestCase):
    """Installing/upgrading while an overlay is already running (#510).

    The task uses MultipleInstancesPolicy=IgnoreNew, so ``schtasks /Run`` is a
    no-op until the previous instance has gone away.
    """

    PREVIOUS_PID = 4242
    NEW_PID = 5151

    def _install(
        self,
        *,
        previous: tuple[int, str] | None,
        fake: "_IgnoreNewSchtasks | None" = None,
        create_fails: bool = False,
        idle_timeout_s: float = 0.05,
    ) -> tuple[int, "_IgnoreNewSchtasks", list[str], str]:
        from app.spotty_bunny_agent_win32 import install_agent

        fake = fake or _IgnoreNewSchtasks()
        fake.create_should_fail = create_fails
        events: list[str] = []
        fake.events = events

        def _runtime(*, pid_dir: Path | None = None) -> tuple[int, str] | None:
            return (self.NEW_PID, "test") if fake.spawned else previous

        def _stop(*, pid_dir: Path | None = None) -> bool:
            events.append("stop")
            fake.overlay_exit()
            return True

        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            program = _write_executable(home / "spotty-bunny.exe")
            stderr = StringIO()
            with (
                patch(
                    "app.spotty_bunny_agent_win32.read_spotty_bunny_runtime",
                    side_effect=_runtime,
                ),
                patch(
                    "app.spotty_bunny_agent_win32.spotty_bunny_is_running",
                    return_value=True,
                ),
                patch(
                    "app.spotty_bunny_agent_win32.stop_spotty_bunny",
                    side_effect=_stop,
                ),
                patch("app.spotty_bunny_agent_win32.clear_spotty_bunny_pid"),
                patch("app.spotty_bunny_agent_win32.time.sleep"),
                patch(
                    "app.spotty_bunny_agent_win32.TASK_IDLE_WAIT_TIMEOUT_S",
                    idle_timeout_s,
                ),
            ):
                code = install_agent(
                    pid_dir=home / "run",
                    platform="win32",
                    print_err=stderr.write,
                    program=program,
                    schtasks=fake,
                    timeout_s=0.05,
                )
        return code, fake, events, stderr.getvalue()

    def test_stops_the_previous_overlay_so_the_task_can_start_a_new_one(self) -> None:
        fake = _IgnoreNewSchtasks()
        fake.running = True  # the previous overlay's task instance
        code, fake, events, stderr = self._install(
            previous=(self.PREVIOUS_PID, "old"), fake=fake
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(fake.spawned, 1)
        self.assertEqual(events, ["create", "stop", "run"])

    def test_the_run_is_ignored_when_the_previous_overlay_is_left_running(self) -> None:
        # The control: this is what happened before, and why the fix exists.
        fake = _IgnoreNewSchtasks()
        fake.running = True
        with patch(
            "app.spotty_bunny_agent_win32._stop_previous_overlay", lambda *a, **k: None
        ):
            code, fake, _events, stderr = self._install(
                previous=(self.PREVIOUS_PID, "old"), fake=fake
            )
        self.assertEqual(fake.spawned, 0)
        self.assertEqual(code, 1)
        self.assertIn("did not start", stderr)

    def test_does_not_stop_the_overlay_when_it_is_this_process(self) -> None:
        # Menu-triggered install/upgrade runs inside the overlay itself, and
        # stopping it would end the caller.
        fake = _IgnoreNewSchtasks()
        fake.running = True  # this process is the task's running instance
        _code, _fake, events, _stderr = self._install(
            previous=(os.getpid(), "me"), fake=fake
        )
        self.assertNotIn("stop", events)

    def test_the_menu_triggered_path_still_times_out_and_rolls_back(self) -> None:
        # Known limitation (#523): the overlay cannot stop itself, so under
        # IgnoreNew the task's /Run is ignored and the wait times out. This
        # pins today's behavior so a fix is a deliberate change, not a surprise.
        fake = _IgnoreNewSchtasks()
        fake.running = True
        code, fake, _events, stderr = self._install(
            previous=(os.getpid(), "me"), fake=fake
        )
        self.assertEqual(fake.spawned, 0)
        self.assertEqual(code, 1)
        self.assertIn("did not start", stderr)
        # With no earlier task definition the rollback removes the new one.
        self.assertIn("removed the non-functional Scheduled Task", stderr)

    def test_does_not_stop_anything_when_nothing_was_running(self) -> None:
        code, fake, events, stderr = self._install(previous=None)
        self.assertEqual(code, 0, stderr)
        self.assertEqual(events, ["create", "run"])

    def test_does_not_stop_it_before_the_task_is_registered(self) -> None:
        # Registration failing must not take the working overlay down first;
        # any stop on this path is the rollback's own, not the install's.
        with patch("app.spotty_bunny_agent_win32._stop_previous_overlay") as stop:
            code, _fake, _events, _stderr = self._install(
                previous=(self.PREVIOUS_PID, "old"), create_fails=True
            )
        self.assertEqual(code, 1)
        stop.assert_not_called()

    def test_waits_until_task_scheduler_reports_the_task_idle(self) -> None:
        fake = _IgnoreNewSchtasks()
        fake.running = True
        fake.lingers_after_exit = 2  # /Query still says Running twice more
        code, fake, events, stderr = self._install(
            previous=(self.PREVIOUS_PID, "old"), fake=fake, idle_timeout_s=30.0
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(fake.spawned, 1)

    def test_waits_for_the_task_to_go_idle_but_only_for_a_bounded_time(self) -> None:
        fake = _IgnoreNewSchtasks()
        fake.running = True
        fake.stays_running_after_exit = True  # Task Scheduler never catches up
        code, fake, events, _stderr = self._install(
            previous=(self.PREVIOUS_PID, "old"), fake=fake, idle_timeout_s=0.0
        )
        # Bounded: it proceeded to /Run rather than hanging.
        self.assertIn("run", events)
        self.assertEqual(code, 1)


class RollbackFailedInstallTests(SimpleTestCase):
    def test_does_not_terminate_the_calling_process(self) -> None:
        """Regression: install/upgrade is often menu-triggered from within
        the running overlay itself, so the pid file's recorded pid can be
        this very process -- stop_spotty_bunny()/clear_spotty_bunny_pid()
        must be skipped rather than tearing down the caller mid-rollback."""
        from app.spotty_bunny_agent_win32 import _rollback_failed_install

        with (
            patch(
                "app.spotty_bunny_agent_win32.read_spotty_bunny_runtime",
                return_value=(os.getpid(), "test"),
            ),
            patch("app.spotty_bunny_agent_win32.stop_spotty_bunny") as stop,
            patch("app.spotty_bunny_agent_win32.clear_spotty_bunny_pid") as clear,
        ):
            _rollback_failed_install(None, pid_dir=None, schtasks=_FakeSchtasks())
        stop.assert_not_called()
        clear.assert_not_called()

    def test_terminates_a_recorded_process_that_is_not_the_caller(self) -> None:
        from app.spotty_bunny_agent_win32 import _rollback_failed_install

        other_pid = os.getpid() + 1
        with (
            patch(
                "app.spotty_bunny_agent_win32.read_spotty_bunny_runtime",
                return_value=(other_pid, "test"),
            ),
            patch("app.spotty_bunny_agent_win32.stop_spotty_bunny") as stop,
            patch("app.spotty_bunny_agent_win32.clear_spotty_bunny_pid") as clear,
        ):
            _rollback_failed_install(None, pid_dir=None, schtasks=_FakeSchtasks())
        stop.assert_called_once_with(pid_dir=None)
        clear.assert_called_once_with(pid_dir=None)


class WaitForManagedOverlayTests(SimpleTestCase):
    """Direct coverage of the exclude_pid guard (install_agent's higher-level
    tests above cover it end to end, but patch this function away in most
    cases)."""

    def test_excludes_the_pre_existing_pid(self) -> None:
        from app.spotty_bunny_agent_win32 import _wait_for_managed_overlay

        with (
            patch(
                "app.spotty_bunny_agent_win32.read_spotty_bunny_runtime",
                return_value=(4242, "test"),
            ),
            patch(
                "app.spotty_bunny_agent_win32.spotty_bunny_is_running",
                return_value=True,
            ),
        ):
            self.assertFalse(
                _wait_for_managed_overlay(
                    pid_dir=None, timeout_s=0.01, exclude_pid=4242
                )
            )

    def test_accepts_a_different_pid(self) -> None:
        from app.spotty_bunny_agent_win32 import _wait_for_managed_overlay

        with (
            patch(
                "app.spotty_bunny_agent_win32.read_spotty_bunny_runtime",
                return_value=(9999, "test"),
            ),
            patch(
                "app.spotty_bunny_agent_win32.spotty_bunny_is_running",
                return_value=True,
            ),
        ):
            self.assertTrue(
                _wait_for_managed_overlay(
                    pid_dir=None, timeout_s=0.01, exclude_pid=4242
                )
            )

    def test_accepts_any_pid_when_nothing_was_previously_running(self) -> None:
        from app.spotty_bunny_agent_win32 import _wait_for_managed_overlay

        with (
            patch(
                "app.spotty_bunny_agent_win32.read_spotty_bunny_runtime",
                return_value=(9999, "test"),
            ),
            patch(
                "app.spotty_bunny_agent_win32.spotty_bunny_is_running",
                return_value=True,
            ),
        ):
            self.assertTrue(
                _wait_for_managed_overlay(
                    pid_dir=None, timeout_s=0.01, exclude_pid=None
                )
            )

    def test_false_when_nothing_is_running_at_all(self) -> None:
        from app.spotty_bunny_agent_win32 import _wait_for_managed_overlay

        with patch(
            "app.spotty_bunny_agent_win32.read_spotty_bunny_runtime",
            return_value=None,
        ):
            self.assertFalse(
                _wait_for_managed_overlay(
                    pid_dir=None, timeout_s=0.01, exclude_pid=None
                )
            )


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
        self.create_should_fail = False
        self.delete_should_fail_with: str | None = None

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
            if self.delete_should_fail_with is not None:
                return subprocess.CompletedProcess(
                    argv, 1, "", self.delete_should_fail_with
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
                stdout = f"Status:                               {status}\n"
                return subprocess.CompletedProcess(argv, 0, stdout, "")
            return subprocess.CompletedProcess(argv, 0, "", "")
        return subprocess.CompletedProcess(argv, 1, "", f"unhandled: {action}")


class _IgnoreNewSchtasks(_FakeSchtasks):
    """A fake whose task has ``MultipleInstancesPolicy=IgnoreNew``.

    ``/Run`` while the task is running does nothing, exactly like Task
    Scheduler; ``overlay_exit`` models the running instance going away.
    """

    def __init__(self) -> None:
        super().__init__()
        self.events: list[str] = []
        self.spawned = 0
        self.stays_running_after_exit = False
        self.lingers_after_exit = 0
        self._exited = False

    def __call__(
        self, argv: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        action = argv[1] if len(argv) > 1 else None
        if action == "/Create":
            result = super().__call__(argv, **kwargs)
            if result.returncode == 0:
                self.events.append("create")
            return result
        if action == "/Query" and "/V" in argv and self._exited:
            if self.lingers_after_exit > 0:
                self.lingers_after_exit -= 1
            else:
                self.running = False
                self._exited = False
        if action == "/Run":
            self.events.append("run")
            if self.running:
                self.calls.append(list(argv))
                return subprocess.CompletedProcess(argv, 0, "", "")
            result = super().__call__(argv, **kwargs)
            self.spawned += 1
            return result
        return super().__call__(argv, **kwargs)

    def overlay_exit(self) -> None:
        if self.stays_running_after_exit:
            return
        if self.lingers_after_exit:
            self._exited = True  # /Query reports Running until it has lingered
        else:
            self.running = False

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from app.spotty_bunny_agent import (
    AGENT_LABEL,
    CHORD_TEST_PROMPT,
    TCC_FIX_PROMPT,
    TCC_PERMISSIONS,
    TccStatus,
    doctor_agent,
    format_agent_plist,
)
from app.spotty_bunny_grant import (
    RUNTIME_GRANT_HEARTBEAT_S,
    RUNTIME_GRANT_MAX_AGE_S,
    InterpreterIdentity,
    RuntimeGrant,
    describe_interpreter,
    diagnose_grant,
    diagnose_running_agent,
    process_executable,
    read_recorded_grant,
    read_runtime_grant,
    record_grant,
    runtime_grant_due,
    runtime_grant_rejection,
    write_runtime_grant,
)
from app.spotty_bunny_tap_health import SpottyBunnyHealth
from bookmarks.macos_test_support import macos_only, pyobjc_available

NEW = InterpreterIdentity(
    path="/opt/py/3.14.2/bin/python", sha256="b" * 64, version="Python 3.14.2"
)
OLD = InterpreterIdentity(
    path="/opt/py/3.14.1/bin/python", sha256="a" * 64, version="Python 3.14.1"
)
_PASTE_STEP = "  2. Click +, press ⌘⇧G, paste this path, and click Open:"


def _report(**changes: object) -> RuntimeGrant:
    base = RuntimeGrant(
        accessibility=True,
        executable="/opt/py/Python",
        input_monitoring=True,
        launchd=True,
        pid=77,
        updated_at=0.0,
    )
    return replace(base, **changes)  # type: ignore[arg-type]


class SpottyBunnyGrantTests(SimpleTestCase):
    def test_describe_interpreter_hashes_and_reports_version(self) -> None:
        with TemporaryDirectory() as tmp:
            python = Path(tmp) / "python"
            python.write_bytes(b"binary")
            identity = describe_interpreter(
                python,
                run=lambda *_a, **_k: subprocess.CompletedProcess(
                    [], 0, stdout="Python 3.14.2\n", stderr=""
                ),
            )
            self.assertEqual(identity.path, str(python.resolve()))
            self.assertEqual(identity.version, "Python 3.14.2")
            self.assertEqual(len(identity.sha256 or ""), 64)

    def test_diagnose_binary_replaced_in_place(self) -> None:
        current = InterpreterIdentity(OLD.path, "c" * 64, "Python 3.14.2")
        result = diagnose_grant(
            accessibility=False,
            current=current,
            input_monitoring=False,
            recorded=OLD,
        )
        self.assertEqual(result.state, "interpreter_modified")
        self.assertFalse(result.healthy)

    def test_diagnose_healthy(self) -> None:
        result = diagnose_grant(
            accessibility=True, current=OLD, input_monitoring=True, recorded=OLD
        )
        self.assertEqual(result.state, "ok")
        self.assertTrue(result.healthy)

    def test_diagnose_interpreter_moved_names_both_and_new_path(self) -> None:
        result = diagnose_grant(
            accessibility=False,
            current=NEW,
            input_monitoring=False,
            recorded=OLD,
        )
        text = "\n".join(result.lines)
        self.assertEqual(result.state, "interpreter_moved")
        self.assertFalse(result.healthy)
        self.assertIn(OLD.path, text)
        self.assertIn(NEW.path, text)
        self.assertIn("Input Monitoring", text)
        self.assertIn("bunnify spotty-bunny upgrade", text)

    def test_diagnose_stale_record_with_both_granted_is_healthy(self) -> None:
        result = diagnose_grant(
            accessibility=True, current=NEW, input_monitoring=True, recorded=OLD
        )
        self.assertEqual(result.state, "ok")
        self.assertTrue(result.healthy)
        self.assertIn(OLD.label(), "\n".join(result.lines))

    def test_diagnose_revoked_same_interpreter(self) -> None:
        result = diagnose_grant(
            accessibility=True, current=OLD, input_monitoring=False, recorded=OLD
        )
        self.assertEqual(result.state, "revoked")
        self.assertIn("Input Monitoring", result.lines[0])
        self.assertNotIn("Accessibility", result.lines[0])

    def test_diagnose_follow_up_matches_install_state(self) -> None:
        installed = diagnose_grant(
            accessibility=False, current=NEW, input_monitoring=False, recorded=OLD
        )
        not_installed = diagnose_grant(
            accessibility=False,
            agent_installed=False,
            current=NEW,
            input_monitoring=False,
            recorded=OLD,
        )
        self.assertIn("spotty-bunny upgrade", installed.lines[-1])
        self.assertIn("spotty-bunny install", not_installed.lines[-1])

    def test_framework_python_asks_for_the_app_bundle(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "Versions" / "3.14"
            launcher = root / "bin" / "python3.14"
            bundle = root / "Resources" / "Python.app"
            app = bundle / "Contents" / "MacOS" / "Python"
            app.parent.mkdir(parents=True)
            launcher.parent.mkdir(parents=True)
            launcher.write_bytes(b"x")
            app.write_bytes(b"y")
            identity = describe_interpreter(
                launcher,
                run=lambda *_a, **_k: subprocess.CompletedProcess([], 1, "", ""),
            )
            self.assertEqual(identity.app_path, str(app.resolve()))
            result = diagnose_grant(
                accessibility=False,
                current=identity,
                input_monitoring=False,
                recorded=None,
            )
            paste = result.lines[result.lines.index(_PASTE_STEP) + 1].strip()
            self.assertEqual(paste, str(bundle.resolve()))
            self.assertIn("“Python”", "\n".join(result.lines))

    def test_non_framework_python_asks_for_the_interpreter_path(self) -> None:
        result = diagnose_grant(
            accessibility=False, current=NEW, input_monitoring=False, recorded=None
        )
        paste = result.lines[result.lines.index(_PASTE_STEP) + 1].strip()
        self.assertEqual(paste, NEW.path)

    def test_diagnose_app_binary_replaced_with_same_launcher(self) -> None:
        recorded = InterpreterIdentity(
            OLD.path, OLD.sha256, OLD.version, "/a/Python", "1" * 64
        )
        current = InterpreterIdentity(
            OLD.path, OLD.sha256, OLD.version, "/a/Python", "2" * 64
        )
        result = diagnose_grant(
            accessibility=False,
            current=current,
            input_monitoring=False,
            recorded=recorded,
        )
        self.assertEqual(result.state, "interpreter_modified")

    def test_diagnose_unrecorded(self) -> None:
        result = diagnose_grant(
            accessibility=False, current=NEW, input_monitoring=False, recorded=None
        )
        self.assertEqual(result.state, "unrecorded")
        self.assertIn("Accessibility and Input Monitoring are not", result.lines[0])

    def test_diagnose_unrecorded_single_permission_is_singular(self) -> None:
        result = diagnose_grant(
            accessibility=True, current=NEW, input_monitoring=False, recorded=None
        )
        self.assertIn("Input Monitoring is not", result.lines[0])

    def test_healthy_note_skips_terminal_caveat_when_agent_reported(self) -> None:
        result = diagnose_grant(
            accessibility=True,
            current=NEW,
            input_monitoring=True,
            recorded=OLD,
        )
        self.assertNotIn("terminal", "\n".join(result.lines))

    def test_running_agent_on_removed_interpreter_is_flagged(self) -> None:
        lines = diagnose_running_agent(
            current=NEW, executable="/gone/3.14.1/Python", pid=42
        )
        text = "\n".join(lines)
        self.assertIn("pid 42", text)
        self.assertIn("has been removed", text)
        self.assertIn(NEW.path, text)

    def test_running_agent_on_framework_app_binary_matches(self) -> None:
        current = InterpreterIdentity(
            NEW.path,
            NEW.sha256,
            NEW.version,
            "/opt/py/Python.app/Contents/MacOS/Python",
        )
        self.assertEqual(
            diagnose_running_agent(
                current=current, executable=current.app_path, pid=42
            ),
            (),
        )

    def test_running_agent_with_unusable_executable_is_ignored(self) -> None:
        for executable in (None, "python3"):
            self.assertEqual(
                diagnose_running_agent(current=NEW, executable=executable, pid=1),
                (),
            )

    def test_process_executable_reads_ps_and_tolerates_failure(self) -> None:
        ok = process_executable(
            7,
            run=lambda *_a, **_k: subprocess.CompletedProcess(
                [], 0, stdout="/opt/py/Python\n", stderr=""
            ),
        )
        failed = process_executable(
            7, run=lambda *_a, **_k: subprocess.CompletedProcess([], 1, "", "")
        )
        self.assertEqual(ok, "/opt/py/Python")
        self.assertIsNone(failed)

    @macos_only(sys.platform == "darwin", "ps reports the full image path on macOS")
    def test_process_executable_reports_this_process(self) -> None:
        import os

        executable = process_executable(os.getpid())
        self.assertIsNotNone(executable)
        assert executable is not None
        self.assertTrue(os.path.isabs(executable))

    def test_runtime_grant_round_trip_and_corrupt(self) -> None:
        grant = _report(pid=9, updated_at=1.5)
        with TemporaryDirectory() as tmp:
            grant_dir = Path(tmp) / "nested"
            self.assertIsNone(read_runtime_grant(grant_dir=grant_dir))
            self.assertTrue(write_runtime_grant(grant, grant_dir=grant_dir))
            self.assertEqual(read_runtime_grant(grant_dir=grant_dir), grant)
            (grant_dir / ".spotty-bunny-runtime-grant").write_text(
                "{}", encoding="utf-8"
            )
            self.assertIsNone(read_runtime_grant(grant_dir=grant_dir))

    def test_runtime_grant_without_provenance_reads_as_not_launchd(self) -> None:
        with TemporaryDirectory() as tmp:
            grant_dir = Path(tmp)
            (grant_dir / ".spotty-bunny-runtime-grant").write_text(
                '{"accessibility": true, "executable": "/x", '
                '"input_monitoring": true, "pid": 1, "updated_at": 2.0}',
                encoding="utf-8",
            )
            grant = read_runtime_grant(grant_dir=grant_dir)
        assert grant is not None
        self.assertFalse(grant.launchd)

    def test_runtime_grant_due_on_change_or_heartbeat_only(self) -> None:
        first = _report(updated_at=100.0)
        self.assertTrue(runtime_grant_due(None, first))
        self.assertFalse(runtime_grant_due(first, _report(updated_at=160.0)))
        self.assertTrue(
            runtime_grant_due(first, _report(input_monitoring=False, updated_at=160.0))
        )
        self.assertTrue(
            runtime_grant_due(
                first, _report(updated_at=100.0 + RUNTIME_GRANT_HEARTBEAT_S)
            )
        )

    def test_runtime_grant_rejection_reasons(self) -> None:
        now = 1000.0
        cases = {
            "no report": None,
            "pid 76": _report(pid=76, updated_at=now),
            "not started by launchd": _report(launchd=False, updated_at=now),
            "stale": _report(updated_at=now - RUNTIME_GRANT_MAX_AGE_S - 1),
        }
        for reason, report in cases.items():
            with self.subTest(reason=reason):
                rejection = runtime_grant_rejection(report, now=now, pid=77)
                self.assertIn(reason, rejection or "")
        self.assertIsNone(
            runtime_grant_rejection(_report(updated_at=now), now=now, pid=77)
        )

    def test_read_missing_or_corrupt_returns_none(self) -> None:
        with TemporaryDirectory() as tmp:
            grant_dir = Path(tmp)
            self.assertIsNone(read_recorded_grant(grant_dir=grant_dir))
            (grant_dir / ".spotty-bunny-tcc-grant").write_text(
                "{nope", encoding="utf-8"
            )
            self.assertIsNone(read_recorded_grant(grant_dir=grant_dir))

    def test_record_and_read_round_trip(self) -> None:
        with TemporaryDirectory() as tmp:
            grant_dir = Path(tmp) / "nested"
            self.assertTrue(record_grant(OLD, grant_dir=grant_dir))
            self.assertEqual(read_recorded_grant(grant_dir=grant_dir), OLD)


class SpottyBunnyDoctorTests(SimpleTestCase):
    def _run(
        self,
        *,
        answers: tuple[str, ...] = (),
        current: InterpreterIdentity,
        fresh_program: bool = False,
        health: SpottyBunnyHealth | None = None,
        install_plist: bool = False,
        interactive: bool = False,
        plist_program: str | None = None,
        recorded: InterpreterIdentity | None,
        report: RuntimeGrant | None = None,
        running_executable: str | None = None,
        running_pid: int | None = None,
        tcc: TccStatus,
        tcc_after: tuple[TccStatus, ...] = (),
    ) -> tuple[int, str]:
        """Run doctor_agent; *plist_program* installs a plist instead of ``program``.

        *install_plist* installs a plist for the live ``program``; *tcc_after*
        queues the probe results that follow *tcc* (the last one repeats).
        """
        lines: list[str] = []
        probes: list[Path] = []
        results = [tcc, *tcc_after]
        pending = list(answers)
        self.prompts: list[str] = []
        self.opened: list[str] = []

        def probe(path: Path) -> TccStatus:
            probes.append(path)
            return results.pop(0) if len(results) > 1 else results[0]

        def ask(message: str) -> str:
            self.prompts.append(message)
            if not pending:
                raise AssertionError(f"unexpected prompt: {message}")
            return pending.pop(0)

        def open_settings(url: str) -> bool:
            self.opened.append(url)
            return True

        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            program = home / "spotty-bunny"
            program.write_text(f"#!{sys.executable}\n", encoding="utf-8")
            if install_plist:
                plist_program = str(program)
            if plist_program is not None:
                plist = home / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
                plist.parent.mkdir(parents=True)
                plist.write_text(
                    format_agent_plist(home=home, program_arguments=[plist_program]),
                    encoding="utf-8",
                )
            with (
                patch(
                    "app.spotty_bunny_agent.describe_interpreter", return_value=current
                ),
                patch(
                    "app.spotty_bunny_agent.read_recorded_grant", return_value=recorded
                ),
                patch("app.spotty_bunny_agent.read_runtime_grant", return_value=report),
                patch("app.spotty_bunny_agent.record_grant") as record,
                patch(
                    "app.spotty_bunny_agent._running_agent_pid",
                    return_value=running_pid,
                ),
                patch(
                    "app.spotty_bunny_agent.process_executable",
                    return_value=running_executable,
                ),
                patch(
                    "app.spotty_bunny_agent.read_spotty_bunny_health",
                    return_value=health,
                ),
                patch(
                    "app.spotty_bunny_agent.spotty_bunny_program",
                    return_value=program if fresh_program else None,
                ),
                patch(
                    "app.spotty_bunny_agent._is_interactive", return_value=interactive
                ),
                patch(
                    "app.spotty_bunny_agent._reload_agent", return_value=True
                ) as reload,
            ):
                code = doctor_agent(
                    home=home,
                    open_settings=open_settings,
                    platform="darwin",
                    print_fn=lines.append,
                    probe_tcc=probe,
                    program=None if plist_program is not None else program,
                    prompt_fn=ask,
                    request_tcc=lambda _p: TccStatus(False, False),
                )
                self.recorded_calls = record.call_count
                self.reload_calls = reload.call_count
        self.probe_calls = len(probes)
        return code, "\n".join(lines)

    def test_doctor_prefers_the_running_agents_own_report(self) -> None:
        code, text = self._run(
            current=NEW,
            recorded=NEW,
            report=_report(executable=NEW.path, updated_at=time.time()),
            running_executable=NEW.path,
            running_pid=77,
            tcc=TccStatus(False, False),
        )
        self.assertEqual(code, 0)
        self.assertEqual(self.probe_calls, 0)
        self.assertIn(
            "permissions_source: running spotty-bunny (pid 77, reported", text
        )

    def test_doctor_ignores_report_from_another_pid(self) -> None:
        code, text = self._run(
            current=NEW,
            recorded=NEW,
            report=_report(executable=NEW.path, pid=76, updated_at=time.time()),
            running_executable=NEW.path,
            running_pid=77,
            tcc=TccStatus(False, False),
        )
        self.assertEqual(code, 1)
        self.assertEqual(self.probe_calls, 1)
        self.assertIn("permissions_source: launchd probe (report is from pid 76", text)

    def test_doctor_ignores_report_from_terminal_started_overlay(self) -> None:
        code, text = self._run(
            current=NEW,
            recorded=NEW,
            report=_report(executable=NEW.path, launchd=False, updated_at=time.time()),
            running_executable=NEW.path,
            running_pid=77,
            tcc=TccStatus(True, True),
        )
        self.assertEqual(code, 0)
        self.assertEqual(self.probe_calls, 1)
        self.assertIn("not started by launchd", text)

    def test_doctor_ignores_stale_report(self) -> None:
        code, text = self._run(
            current=NEW,
            recorded=NEW,
            report=_report(executable=NEW.path, updated_at=1.0),
            running_executable=NEW.path,
            running_pid=77,
            tcc=TccStatus(False, False),
        )
        self.assertEqual(code, 1)
        self.assertEqual(self.probe_calls, 1)
        self.assertIn("report is stale", text)

    def test_doctor_checks_replacement_and_flags_stale_plist(self) -> None:
        code, text = self._run(
            current=NEW,
            fresh_program=True,
            plist_program="/gone/bin/spotty-bunny",
            recorded=NEW,
            tcc=TccStatus(True, True),
        )
        self.assertEqual(code, 1)
        self.assertEqual(self.probe_calls, 1)
        gone = Path("/gone/bin/spotty-bunny")
        self.assertIn(f"spotty-bunny binary no longer exists: {gone}", text)
        self.assertIn("A replacement interpreter is available", text)
        self.assertIn("diagnosis: ok", text)
        self.assertIn("problem: the LaunchAgent plist is stale", text)
        self.assertEqual(self.recorded_calls, 0)

    def test_doctor_reports_unhealthy_event_tap(self) -> None:
        health = SpottyBunnyHealth(
            last_chord_at=None,
            last_event_at=None,
            reinstall_failures=2,
            tap="disabled",
            updated_at=time.time(),
        )
        code, text = self._run(
            current=NEW,
            health=health,
            recorded=NEW,
            report=_report(executable=NEW.path, updated_at=time.time()),
            running_executable=NEW.path,
            running_pid=77,
            tcc=TccStatus(False, False),
        )
        self.assertEqual(code, 1)
        self.assertIn("problem: event tap is disabled (reinstall_failures: 2)", text)

    def test_doctor_skips_tap_health_when_overlay_not_running(self) -> None:
        health = SpottyBunnyHealth(None, None, 0, "disabled", 1.0)
        code, text = self._run(
            current=NEW, health=health, recorded=NEW, tcc=TccStatus(True, True)
        )
        self.assertEqual(code, 0)
        self.assertNotIn("event tap", text)

    def test_doctor_does_not_offer_fix_when_not_interactive(self) -> None:
        code, _text = self._run(current=NEW, recorded=NEW, tcc=TccStatus(False, False))
        self.assertEqual(code, 1)
        self.assertEqual(self.prompts, [])
        self.assertEqual(self.opened, [])

    def test_doctor_fix_declined_changes_nothing(self) -> None:
        code, _text = self._run(
            answers=("n",),
            current=NEW,
            install_plist=True,
            interactive=True,
            recorded=NEW,
            tcc=TccStatus(False, False),
        )
        self.assertEqual(code, 1)
        self.assertEqual(self.prompts, [TCC_FIX_PROMPT])
        self.assertEqual(self.opened, [])
        self.assertEqual(self.reload_calls, 0)
        self.assertEqual(self.recorded_calls, 0)

    def test_doctor_fix_opens_each_pane_restarts_and_confirms(self) -> None:
        code, text = self._run(
            answers=("", "", "", "", "", "y"),
            current=NEW,
            install_plist=True,
            interactive=True,
            recorded=NEW,
            tcc=TccStatus(False, False),
            tcc_after=(
                TccStatus(False, False),
                TccStatus(False, False),
                TccStatus(True, False),
                TccStatus(True, True),
            ),
        )
        self.assertEqual(code, 0)
        self.assertEqual(self.opened, [TCC_PERMISSIONS[0][2], TCC_PERMISSIONS[1][2]])
        self.assertEqual(self.prompts[0], TCC_FIX_PROMPT)
        self.assertEqual(self.prompts[-1], CHORD_TEST_PROMPT)
        self.assertIn("step 1/2", text)
        self.assertIn("step 2/2", text)
        self.assertIn("restarted spotty-bunny", text)
        self.assertEqual(self.reload_calls, 1)
        self.assertEqual(self.recorded_calls, 1)

    def test_doctor_fix_without_agent_points_at_install(self) -> None:
        code, text = self._run(
            answers=("", "", ""),
            current=NEW,
            interactive=True,
            recorded=NEW,
            tcc=TccStatus(False, False),
            tcc_after=(TccStatus(False, False), TccStatus(True, True)),
        )
        self.assertEqual(code, 1)
        self.assertIn("Now run: spotty-bunny install", text)
        self.assertEqual(self.reload_calls, 0)
        self.assertEqual(self.recorded_calls, 1)

    def test_doctor_flags_agent_still_running_removed_interpreter(self) -> None:
        old_exe = "/gone/3.14.1/Python.app/Contents/MacOS/Python"
        report = _report(executable=old_exe, updated_at=time.time())
        code, text = self._run(
            current=NEW,
            recorded=None,
            report=report,
            running_executable=old_exe,
            running_pid=77,
            tcc=TccStatus(False, False),
        )
        self.assertEqual(code, 1)
        self.assertEqual(self.probe_calls, 1)
        self.assertIn(f"running_executable: {old_exe} (pid 77)", text)
        self.assertIn("has been removed", text)
        self.assertIn("keeps working only until it restarts", text)

    def test_doctor_names_changed_interpreter(self) -> None:
        code, text = self._run(current=NEW, recorded=OLD, tcc=TccStatus(False, False))
        self.assertEqual(code, 1)
        self.assertIn("diagnosis: interpreter_moved", text)
        self.assertIn(f"authorized_interpreter: {OLD.label()}", text)
        self.assertIn(NEW.path, text)

    def test_doctor_does_not_write_baseline_for_unrecorded_grant(self) -> None:
        code, text = self._run(current=OLD, recorded=None, tcc=TccStatus(True, True))
        self.assertEqual(code, 0)
        self.assertIn("authorized_interpreter: not recorded", text)
        self.assertIn("to record it", text)
        self.assertEqual(self.recorded_calls, 0)

    def test_doctor_rejects_non_macos(self) -> None:
        errors: list[str] = []
        code = doctor_agent(platform="linux", print_err=errors.append)
        self.assertEqual(code, 1)
        self.assertTrue(errors)

    def test_doctor_leaves_stale_record_when_granted(self) -> None:
        code, text = self._run(current=NEW, recorded=OLD, tcc=TccStatus(True, True))
        self.assertEqual(code, 0)
        self.assertEqual(self.recorded_calls, 0)
        self.assertIn("diagnosis: ok", text)
        self.assertNotIn("from your terminal", text)

    def test_doctor_reports_missing_interpreter(self) -> None:
        lines: list[str] = []
        with (
            TemporaryDirectory() as tmp,
            patch("app.spotty_bunny_agent.read_recorded_grant", return_value=OLD),
        ):
            program = Path(tmp) / "spotty-bunny"
            program.write_text("#!/nonexistent/python\n", encoding="utf-8")
            code = doctor_agent(
                home=Path(tmp),
                platform="darwin",
                print_fn=lines.append,
                probe_tcc=lambda _p: TccStatus(True, True),
                program=program,
            )
        text = "\n".join(lines)
        self.assertEqual(code, 1)
        self.assertIn("no longer exists", text)
        self.assertIn(f"authorized_interpreter: {OLD.label()}", text)

    def test_doctor_reports_missing_binary_not_interpreter(self) -> None:
        lines: list[str] = []
        with TemporaryDirectory() as tmp:
            code = doctor_agent(
                home=Path(tmp),
                platform="darwin",
                print_fn=lines.append,
                probe_tcc=lambda _p: TccStatus(True, True),
                program=Path(tmp) / "gone" / "spotty-bunny",
            )
        text = "\n".join(lines)
        self.assertEqual(code, 1)
        self.assertIn("spotty-bunny binary no longer exists", text)
        self.assertIn("spotty-bunny install", text)
        self.assertNotIn("LaunchAgent points", text)


class SpottyBunnyGrantRecordingTests(SimpleTestCase):
    def _reload(self, command: str, *, bootstrap_ok: bool) -> MagicMock:
        from app.spotty_bunny_agent import install_agent, upgrade_agent

        def launchctl(
            argv: list[str], **_k: object
        ) -> subprocess.CompletedProcess[str]:
            code = 1 if argv[1] == "bootstrap" and not bootstrap_ok else 0
            return subprocess.CompletedProcess(argv, code, "", "")

        probed: list[Path] = []

        def probe(path: Path) -> TccStatus:
            probed.append(path)
            return TccStatus(True, True)

        with (
            TemporaryDirectory() as tmp,
            patch("app.spotty_bunny_agent.record_grant") as record,
            patch(
                "app.spotty_bunny_agent.describe_interpreter", return_value=NEW
            ) as describe,
        ):
            home = Path(tmp)
            program = home / "bin" / "spotty-bunny"
            program.parent.mkdir()
            program.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            program.chmod(0o755)
            if command == "upgrade":
                plist = home / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
                plist.parent.mkdir(parents=True)
                plist.write_text(
                    format_agent_plist(home=home, program_arguments=["/old/sb"]),
                    encoding="utf-8",
                )
            run = upgrade_agent if command == "upgrade" else install_agent
            run(
                home=home,
                launchctl=launchctl,
                platform="darwin",
                print_err=lambda _m: None,
                probe_tcc=probe,
                program=program,
                skip_chord_confirm=True,
            )
        if record.called:
            record.assert_called_once_with(NEW)
            describe.assert_called_once_with(probed[-1])
        return record

    def test_install_and_upgrade_record_grant_after_successful_reload(self) -> None:
        for command in ("install", "upgrade"):
            with self.subTest(command=command):
                record = self._reload(command, bootstrap_ok=True)
                self.assertEqual(record.call_count, 1)

    def test_install_and_upgrade_skip_record_when_bootstrap_fails(self) -> None:
        for command in ("install", "upgrade"):
            with self.subTest(command=command):
                record = self._reload(command, bootstrap_ok=False)
                self.assertEqual(record.call_count, 0)


class BunnifyDoctorCommandTests(SimpleTestCase):
    def test_main_dispatches_doctor_with_env_file(self) -> None:
        from click.testing import CliRunner

        from app.cli import main

        env_file = Path("/tmp/custom-config.toml")
        with (
            patch("app.cli.sys.platform", "linux"),
            patch("app.cli.run_status", return_value=1) as status,
        ):
            result = CliRunner().invoke(main, ["--env-file", str(env_file), "doctor"])
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(status.call_args.kwargs["env_path"], env_file)
        self.assertIn("only available on macOS", result.output)

    def test_main_doctor_reports_config_errors_without_traceback(self) -> None:
        from click.testing import CliRunner

        from app.cli import main

        with patch("app.cli.run_status", side_effect=ValueError("bad config.toml")):
            result = CliRunner().invoke(main, ["doctor"])
        self.assertIn("error: bad config.toml", result.output)
        self.assertNotIsInstance(result.exception, ValueError)

    def test_non_macos_reports_server_and_skips_spotty(self) -> None:
        from app.cli import run_doctor

        lines: list[str] = []
        with (
            patch("app.cli.sys.platform", "linux"),
            patch("app.cli.run_status", return_value=0),
        ):
            code = run_doctor(print_fn=lines.append)
        self.assertEqual(code, 0)
        self.assertIn("only available on macOS", "\n".join(lines))

    def test_macos_runs_spotty_doctor_when_installed(self) -> None:
        from app.cli import run_doctor

        with (
            patch("app.cli.sys.platform", "darwin"),
            patch("app.cli.run_status", return_value=0),
            patch("app.spotty_bunny_agent.is_agent_installed", return_value=True),
            patch("app.spotty_bunny_agent.doctor_agent", return_value=1) as doctor,
        ):
            code = run_doctor(print_fn=lambda _l: None)
        doctor.assert_called_once()
        self.assertEqual(code, 1)

    def test_macos_skips_spotty_doctor_when_absent(self) -> None:
        from app.cli import run_doctor

        with (
            patch("app.cli.sys.platform", "darwin"),
            patch("app.cli.run_status", return_value=0),
            patch("app.spotty_bunny_agent.is_agent_installed", return_value=False),
            patch(
                "app.spotty_bunny_launch.spotty_bunny_is_running", return_value=False
            ),
            patch("app.spotty_bunny_agent.doctor_agent") as doctor,
        ):
            code = run_doctor(print_fn=lambda _l: None)
        doctor.assert_not_called()
        self.assertEqual(code, 0)

    def test_run_doctor_passes_env_path_to_status(self) -> None:
        from app.cli import run_doctor

        env_path = Path("/tmp/custom-config.toml")
        with (
            patch("app.cli.sys.platform", "linux"),
            patch("app.cli.run_status", return_value=0) as status,
        ):
            run_doctor(env_path=env_path, print_fn=lambda _l: None)
        self.assertEqual(status.call_args.kwargs["env_path"], env_path)


@macos_only(pyobjc_available(), "needs macOS with PyObjC")
class SpottyBunnyRuntimeGrantRecorderTests(SimpleTestCase):
    def _record(
        self, *, at: float, environ: dict[str, str], input_monitoring: bool = True
    ) -> MagicMock:
        from app import spotty_bunny_app

        with (
            patch.dict("os.environ", environ, clear=True),
            patch.object(spotty_bunny_app, "AXIsProcessTrusted", return_value=True),
            patch.object(
                spotty_bunny_app,
                "CGPreflightListenEventAccess",
                return_value=input_monitoring,
            ),
            patch.object(
                spotty_bunny_app, "_own_executable", return_value="/opt/py/Python"
            ),
            patch.object(
                spotty_bunny_app, "write_runtime_grant", return_value=True
            ) as write,
        ):
            spotty_bunny_app._record_runtime_grant(time_fn=lambda: at)
        return write

    def setUp(self) -> None:
        from app import spotty_bunny_app

        patcher = patch.object(spotty_bunny_app, "_last_runtime_grant", None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_records_payload_with_launchd_provenance(self) -> None:
        import os

        write = self._record(at=5.0, environ={"XPC_SERVICE_NAME": AGENT_LABEL})
        write.assert_called_once_with(_report(pid=os.getpid(), updated_at=5.0))

    def test_terminal_started_overlay_is_not_launchd(self) -> None:
        write = self._record(at=5.0, environ={"XPC_SERVICE_NAME": "0"})
        self.assertFalse(write.call_args.args[0].launchd)

    def test_writes_only_on_change_or_heartbeat(self) -> None:
        launchd = {"XPC_SERVICE_NAME": AGENT_LABEL}
        self.assertEqual(self._record(at=0.0, environ=launchd).call_count, 1)
        self.assertEqual(self._record(at=60.0, environ=launchd).call_count, 0)
        changed = self._record(at=120.0, environ=launchd, input_monitoring=False)
        self.assertEqual(changed.call_count, 1)
        heartbeat = self._record(
            at=120.0 + RUNTIME_GRANT_HEARTBEAT_S,
            environ=launchd,
            input_monitoring=False,
        )
        self.assertEqual(heartbeat.call_count, 1)

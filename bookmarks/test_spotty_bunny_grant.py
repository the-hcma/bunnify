from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import skipUnless
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from app.spotty_bunny_agent import TccStatus, doctor_agent
from app.spotty_bunny_grant import (
    InterpreterIdentity,
    RuntimeGrant,
    describe_interpreter,
    diagnose_grant,
    diagnose_running_agent,
    process_executable,
    read_recorded_grant,
    read_runtime_grant,
    record_grant,
    record_runtime_grant,
)

OLD = InterpreterIdentity(
    path="/opt/py/3.14.1/bin/python", sha256="a" * 64, version="Python 3.14.1"
)
NEW = InterpreterIdentity(
    path="/opt/py/3.14.2/bin/python", sha256="b" * 64, version="Python 3.14.2"
)
_PASTE_STEP = "  2. Click +, press ⌘⇧G, paste this path, and click Open:"


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
            probed_by_agent=True,
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

    @skipUnless(sys.platform == "darwin", "ps reports the full image path on macOS")
    def test_process_executable_reports_this_process(self) -> None:
        import os

        executable = process_executable(os.getpid())
        self.assertIsNotNone(executable)
        assert executable is not None
        self.assertTrue(os.path.isabs(executable))

    def test_runtime_grant_round_trip_and_corrupt(self) -> None:
        with TemporaryDirectory() as tmp:
            grant_dir = Path(tmp) / "nested"
            self.assertIsNone(read_runtime_grant(grant_dir=grant_dir))
            self.assertTrue(
                record_runtime_grant(
                    accessibility=True,
                    executable="/opt/py/Python",
                    grant_dir=grant_dir,
                    input_monitoring=False,
                    pid=9,
                    time_fn=lambda: 1.5,
                )
            )
            self.assertEqual(
                read_runtime_grant(grant_dir=grant_dir),
                RuntimeGrant(True, "/opt/py/Python", False, 9, 1.5),
            )
            (grant_dir / ".spotty-bunny-runtime-grant").write_text(
                "{}", encoding="utf-8"
            )
            self.assertIsNone(read_runtime_grant(grant_dir=grant_dir))

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
        current: InterpreterIdentity,
        recorded: InterpreterIdentity | None,
        report: RuntimeGrant | None = None,
        running_executable: str | None = None,
        running_pid: int | None = None,
        tcc: TccStatus,
    ) -> tuple[int, str]:
        lines: list[str] = []
        probes: list[Path] = []

        def probe(path: Path) -> TccStatus:
            probes.append(path)
            return tcc

        with (
            TemporaryDirectory() as tmp,
            patch("app.spotty_bunny_agent.describe_interpreter", return_value=current),
            patch("app.spotty_bunny_agent.read_recorded_grant", return_value=recorded),
            patch("app.spotty_bunny_agent.read_runtime_grant", return_value=report),
            patch("app.spotty_bunny_agent.record_grant") as record,
            patch(
                "app.spotty_bunny_agent._running_agent_pid", return_value=running_pid
            ),
            patch(
                "app.spotty_bunny_agent.process_executable",
                return_value=running_executable,
            ),
            patch("app.spotty_bunny_agent.read_spotty_bunny_health", return_value=None),
        ):
            program = Path(tmp) / "spotty-bunny"
            program.write_text(f"#!{sys.executable}\n", encoding="utf-8")
            code = doctor_agent(
                home=Path(tmp),
                platform="darwin",
                print_fn=lines.append,
                probe_tcc=probe,
                program=program,
            )
            self.recorded_calls = record.call_count
        self.probe_calls = len(probes)
        return code, "\n".join(lines)

    def test_doctor_prefers_the_running_agents_own_report(self) -> None:
        report = RuntimeGrant(True, NEW.path, True, 77, 1.0)
        code, text = self._run(
            current=NEW,
            recorded=NEW,
            report=report,
            running_executable=NEW.path,
            running_pid=77,
            tcc=TccStatus(False, False),
        )
        self.assertEqual(code, 0)
        self.assertEqual(self.probe_calls, 0)
        self.assertIn("permissions_source: running spotty-bunny (pid 77)", text)
        self.assertNotIn("probed from this terminal", text)

    def test_doctor_ignores_report_from_another_pid(self) -> None:
        report = RuntimeGrant(True, NEW.path, True, 76, 1.0)
        code, text = self._run(
            current=NEW,
            recorded=NEW,
            report=report,
            running_executable=NEW.path,
            running_pid=77,
            tcc=TccStatus(False, False),
        )
        self.assertEqual(code, 1)
        self.assertEqual(self.probe_calls, 1)
        self.assertIn("permissions_source: this terminal", text)

    def test_doctor_flags_agent_still_running_removed_interpreter(self) -> None:
        old_exe = "/gone/3.14.1/Python.app/Contents/MacOS/Python"
        report = RuntimeGrant(True, old_exe, True, 77, 1.0)
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
        self.assertIn("probed from this terminal", text)

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
    def _install(self, *, bootstrap_ok: bool) -> MagicMock:
        from app.spotty_bunny_agent import install_agent

        def launchctl(
            argv: list[str], **_k: object
        ) -> subprocess.CompletedProcess[str]:
            code = 1 if argv[1] == "bootstrap" and not bootstrap_ok else 0
            return subprocess.CompletedProcess(argv, code, "", "")

        with (
            TemporaryDirectory() as tmp,
            patch("app.spotty_bunny_agent.record_grant") as record,
        ):
            program = Path(tmp) / "bin" / "spotty-bunny"
            program.parent.mkdir()
            program.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            program.chmod(0o755)
            install_agent(
                home=Path(tmp),
                launchctl=launchctl,
                platform="darwin",
                print_err=lambda _m: None,
                probe_tcc=lambda _p: TccStatus(True, True),
                program=program,
                skip_chord_confirm=True,
            )
        return record

    def test_install_records_grant_after_successful_reload(self) -> None:
        self.assertEqual(self._install(bootstrap_ok=True).call_count, 1)

    def test_install_does_not_record_grant_when_bootstrap_fails(self) -> None:
        self.assertEqual(self._install(bootstrap_ok=False).call_count, 0)


class BunnifyDoctorCommandTests(SimpleTestCase):
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

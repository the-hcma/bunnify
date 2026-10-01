from __future__ import annotations

import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase

from app.spotty_bunny_agent import TccStatus, doctor_agent
from app.spotty_bunny_grant import (
    InterpreterIdentity,
    describe_interpreter,
    diagnose_grant,
    read_recorded_grant,
    record_grant,
)

OLD = InterpreterIdentity(
    path="/opt/py/3.14.1/bin/python", sha256="a" * 64, version="Python 3.14.1"
)
NEW = InterpreterIdentity(
    path="/opt/py/3.14.2/bin/python", sha256="b" * 64, version="Python 3.14.2"
)


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

    def test_diagnose_moved_wins_even_if_probe_reports_granted(self) -> None:
        result = diagnose_grant(
            accessibility=True, current=NEW, input_monitoring=True, recorded=OLD
        )
        self.assertEqual(result.state, "interpreter_moved")

    def test_diagnose_revoked_same_interpreter(self) -> None:
        result = diagnose_grant(
            accessibility=True, current=OLD, input_monitoring=False, recorded=OLD
        )
        self.assertEqual(result.state, "revoked")
        self.assertIn("Input Monitoring", result.lines[0])
        self.assertNotIn("Accessibility", result.lines[0])

    def test_diagnose_unrecorded(self) -> None:
        result = diagnose_grant(
            accessibility=False, current=NEW, input_monitoring=False, recorded=None
        )
        self.assertEqual(result.state, "unrecorded")

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
        tcc: TccStatus,
    ) -> tuple[int, str]:
        lines: list[str] = []
        with (
            TemporaryDirectory() as tmp,
            patch("app.spotty_bunny_agent.describe_interpreter", return_value=current),
            patch("app.spotty_bunny_agent.read_recorded_grant", return_value=recorded),
            patch("app.spotty_bunny_agent.record_grant") as record,
            patch("app.spotty_bunny_agent.spotty_bunny_is_running", return_value=False),
            patch("app.spotty_bunny_agent.read_spotty_bunny_health", return_value=None),
        ):
            program = Path(tmp) / "spotty-bunny"
            program.write_text("#!/usr/bin/python3\n", encoding="utf-8")
            code = doctor_agent(
                home=Path(tmp),
                platform="darwin",
                print_fn=lines.append,
                probe_tcc=lambda _p: tcc,
                program=program,
            )
            self.recorded_calls = record.call_count
        return code, "\n".join(lines)

    def test_doctor_names_changed_interpreter(self) -> None:
        code, text = self._run(current=NEW, recorded=OLD, tcc=TccStatus(False, False))
        self.assertEqual(code, 1)
        self.assertIn("diagnosis: interpreter_moved", text)
        self.assertIn(f"authorized_interpreter: {OLD.label()}", text)
        self.assertIn(NEW.path, text)

    def test_doctor_healthy_baselines_unrecorded_grant(self) -> None:
        code, text = self._run(current=OLD, recorded=None, tcc=TccStatus(True, True))
        self.assertEqual(code, 0)
        self.assertIn("authorized_interpreter: not recorded", text)
        self.assertEqual(self.recorded_calls, 1)

    def test_doctor_rejects_non_macos(self) -> None:
        errors: list[str] = []
        code = doctor_agent(platform="linux", print_err=errors.append)
        self.assertEqual(code, 1)
        self.assertTrue(errors)

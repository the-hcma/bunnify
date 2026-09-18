from __future__ import annotations

import subprocess
from pathlib import Path

from django.test import SimpleTestCase

from app.spotty_bunny_task_win32 import (
    TASK_NAME,
    _field_from_query_output,
    _split_windows_command_line,
    _status_from_query_output,
    create_or_update_task,
    format_task_xml,
    is_task_installed,
    is_task_running,
    remove_task,
    run_task_once,
    task_program_arguments,
    task_xml,
)


class FormatTaskXmlTests(SimpleTestCase):
    def test_includes_logon_trigger_and_restart_on_failure(self) -> None:
        xml = format_task_xml(program_arguments=["C:\\bin\\spotty-bunny.exe"])
        self.assertIn("<LogonTrigger>", xml)
        self.assertIn("<Enabled>true</Enabled>", xml)
        self.assertIn("<RestartOnFailure>", xml)
        self.assertIn("<Interval>PT1M</Interval>", xml)
        self.assertIn("<Count>999</Count>", xml)
        self.assertIn("<LogonType>InteractiveToken</LogonType>", xml)

    def test_command_is_the_first_argument_unquoted(self) -> None:
        xml = format_task_xml(
            program_arguments=["C:\\Program Files\\spotty-bunny.exe", "--foo"]
        )
        self.assertIn("<Command>C:\\Program Files\\spotty-bunny.exe</Command>", xml)

    def test_command_only_no_extra_arguments(self) -> None:
        xml = format_task_xml(program_arguments=["C:\\bin\\spotty-bunny.exe"])
        self.assertIn("<Arguments></Arguments>", xml)

    def test_arguments_with_spaces_are_quoted(self) -> None:
        xml = format_task_xml(
            program_arguments=[
                "C:\\bin\\spotty-bunny.exe",
                "--pid-dir",
                "C:\\Users\\a b\\run",
            ]
        )
        self.assertIn('<Arguments>--pid-dir "C:\\Users\\a b\\run"</Arguments>', xml)

    def test_xml_special_characters_are_escaped(self) -> None:
        xml = format_task_xml(
            program_arguments=["C:\\bin\\spotty-bunny.exe", "--flag=<a&b>"]
        )
        self.assertIn("&lt;a&amp;b&gt;", xml)
        self.assertNotIn("<a&b>", xml)


class SplitWindowsCommandLineTests(SimpleTestCase):
    def test_simple_unquoted_tokens(self) -> None:
        self.assertEqual(
            _split_windows_command_line("C:\\bin\\spotty-bunny.exe --flag value"),
            ["C:\\bin\\spotty-bunny.exe", "--flag", "value"],
        )

    def test_quoted_path_with_spaces(self) -> None:
        self.assertEqual(
            _split_windows_command_line('"C:\\Program Files\\spotty-bunny.exe" --flag'),
            ["C:\\Program Files\\spotty-bunny.exe", "--flag"],
        )

    def test_odd_backslashes_before_quote_yield_literal_quote(self) -> None:
        # 3 backslashes then a quote: floor(3/2)=1 literal backslash, plus
        # one literal quote (odd count means the quote does not toggle
        # quoting) -- matches CommandLineToArgvW.
        raw = "arg" + "\\" * 3 + '"' + "end"
        self.assertEqual(_split_windows_command_line(raw), ["arg" + "\\" + '"' + "end"])

    def test_even_backslashes_before_quote_toggle_quoting(self) -> None:
        # Two backslashes before a quote collapse to one literal backslash
        # and the quote toggles quoting rather than becoming literal.
        self.assertEqual(
            _split_windows_command_line('"a b\\\\" c'),
            ["a b\\", "c"],
        )

    def test_round_trips_list2cmdline_output(self) -> None:
        original = [
            "C:\\bin\\spotty-bunny.exe",
            "--pid-dir",
            "C:\\Users\\a b\\run",
            "--plain",
        ]
        command = subprocess.list2cmdline(original)
        self.assertEqual(_split_windows_command_line(command), original)

    def test_empty_string_yields_no_arguments(self) -> None:
        self.assertEqual(_split_windows_command_line(""), [])


class FieldFromQueryOutputTests(SimpleTestCase):
    def test_extracts_named_field(self) -> None:
        text = (
            "Status:                              Ready\n"
            "TaskName:                             \\Bunnify\n"
        )
        self.assertEqual(_field_from_query_output(text, "Status"), "Ready")

    def test_missing_field_returns_none(self) -> None:
        self.assertIsNone(_field_from_query_output("Status: Ready\n", "TaskName"))

    def test_status_from_query_output_helper(self) -> None:
        text = "Status:                              Running\n"
        self.assertEqual(_status_from_query_output(text), "Running")


class CreateOrUpdateTaskTests(SimpleTestCase):
    def test_writes_xml_to_temp_file_and_calls_create(self) -> None:
        fake = _FakeSchtasks()
        xml = format_task_xml(program_arguments=["C:\\bin\\spotty-bunny.exe"])
        self.assertTrue(create_or_update_task(xml, schtasks=fake))
        [call] = fake.calls
        self.assertEqual(call[1], "/Create")
        self.assertIn("/TN", call)
        self.assertEqual(call[call.index("/TN") + 1], TASK_NAME)
        self.assertIn("/F", call)
        self.assertEqual(fake.registered_xml, xml)

    def test_temp_file_is_cleaned_up(self) -> None:
        fake = _FakeSchtasks()
        xml = format_task_xml(program_arguments=["C:\\bin\\spotty-bunny.exe"])
        create_or_update_task(xml, schtasks=fake)
        self.assertFalse(fake.last_xml_path.exists())

    def test_temp_file_cleaned_up_even_on_failure(self) -> None:
        fake = _FakeSchtasks()
        fake.create_should_fail = True
        xml = format_task_xml(program_arguments=["C:\\bin\\spotty-bunny.exe"])
        self.assertFalse(create_or_update_task(xml, schtasks=fake))
        self.assertFalse(fake.last_xml_path.exists())


class RemoveTaskTests(SimpleTestCase):
    def test_removes_registered_task(self) -> None:
        fake = _FakeSchtasks()
        fake.registered = True
        self.assertTrue(remove_task(schtasks=fake))
        self.assertFalse(fake.registered)

    def test_missing_task_is_idempotent_success(self) -> None:
        fake = _FakeSchtasks()
        self.assertTrue(remove_task(schtasks=fake))

    def test_genuine_failure_is_reported(self) -> None:
        fake = _FakeSchtasks()
        fake.registered = True
        fake.delete_should_fail_with = "ERROR: Access is denied."
        self.assertFalse(remove_task(schtasks=fake))


class IsTaskInstalledTests(SimpleTestCase):
    def test_true_when_registered(self) -> None:
        fake = _FakeSchtasks()
        fake.registered = True
        self.assertTrue(is_task_installed(schtasks=fake))

    def test_false_when_not_registered(self) -> None:
        self.assertFalse(is_task_installed(schtasks=_FakeSchtasks()))


class IsTaskRunningTests(SimpleTestCase):
    def test_false_when_not_installed(self) -> None:
        self.assertFalse(is_task_running(schtasks=_FakeSchtasks()))

    def test_false_when_registered_but_not_running(self) -> None:
        fake = _FakeSchtasks()
        fake.registered = True
        self.assertFalse(is_task_running(schtasks=fake))

    def test_true_after_run_task_once(self) -> None:
        fake = _FakeSchtasks()
        fake.registered = True
        run_task_once(schtasks=fake)
        self.assertTrue(is_task_running(schtasks=fake))


class TaskXmlTests(SimpleTestCase):
    def test_none_when_not_installed(self) -> None:
        self.assertIsNone(task_xml(schtasks=_FakeSchtasks()))

    def test_returns_registered_xml(self) -> None:
        fake = _FakeSchtasks()
        xml = format_task_xml(program_arguments=["C:\\bin\\spotty-bunny.exe"])
        create_or_update_task(xml, schtasks=fake)
        self.assertEqual(task_xml(schtasks=fake), xml)


class TaskProgramArgumentsTests(SimpleTestCase):
    def test_none_when_not_installed(self) -> None:
        self.assertIsNone(task_program_arguments(schtasks=_FakeSchtasks()))

    def test_reads_command_and_arguments_from_registered_xml(self) -> None:
        fake = _FakeSchtasks()
        xml = format_task_xml(
            program_arguments=[
                "C:\\Program Files\\spotty-bunny.exe",
                "--pid-dir",
                "C:\\a b",
            ]
        )
        create_or_update_task(xml, schtasks=fake)
        self.assertEqual(
            task_program_arguments(schtasks=fake),
            ["C:\\Program Files\\spotty-bunny.exe", "--pid-dir", "C:\\a b"],
        )

    def test_command_only_no_extra_arguments(self) -> None:
        fake = _FakeSchtasks()
        xml = format_task_xml(program_arguments=["C:\\bin\\spotty-bunny.exe"])
        create_or_update_task(xml, schtasks=fake)
        self.assertEqual(
            task_program_arguments(schtasks=fake), ["C:\\bin\\spotty-bunny.exe"]
        )

    def test_spaced_command_path_round_trips(self) -> None:
        # Regression: <Command> is written unquoted even with a space in
        # the path -- this must not be parsed via the free-text "Task To
        # Run" display field, which would truncate at the first space.
        fake = _FakeSchtasks()
        xml = format_task_xml(
            program_arguments=["C:\\Users\\John Doe\\.local\\bin\\spotty-bunny.exe"]
        )
        create_or_update_task(xml, schtasks=fake)
        self.assertEqual(
            task_program_arguments(schtasks=fake),
            ["C:\\Users\\John Doe\\.local\\bin\\spotty-bunny.exe"],
        )


class SchtasksErrorHandlingTests(SimpleTestCase):
    def test_oserror_is_reported_as_a_failed_process(self) -> None:
        def raising_runner(argv: list[str], **_kwargs: object) -> object:
            raise OSError("schtasks.exe not found")

        self.assertFalse(is_task_installed(schtasks=raising_runner))

    def test_timeout_is_reported_as_a_failed_process(self) -> None:
        def raising_runner(argv: list[str], **_kwargs: object) -> object:
            raise subprocess.TimeoutExpired(cmd=argv, timeout=15)

        self.assertFalse(is_task_installed(schtasks=raising_runner))


class _FakeSchtasks:
    """Stateful ``schtasks.exe`` fake, mirroring ``_FakeLaunchctl``'s shape."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.registered = False
        self.registered_xml: str | None = None
        self.running = False
        self.create_should_fail = False
        self.delete_should_fail_with: str | None = None
        self.last_xml_path: Path = Path()

    def __call__(
        self, argv: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        action = argv[1] if len(argv) > 1 else None
        if action == "/Create":
            self.last_xml_path = Path(argv[argv.index("/XML") + 1])
            if self.create_should_fail:
                return subprocess.CompletedProcess(
                    argv, 1, "", "ERROR: Access is denied."
                )
            self.registered_xml = self.last_xml_path.read_text(encoding="utf-16")
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

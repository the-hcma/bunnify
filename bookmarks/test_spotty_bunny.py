from __future__ import annotations

import logging
import os
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from django.test import SimpleTestCase

from app.spotty_bunny_cli import (
    LOG_ENV_VAR,
    SpottyBunnyEventTapError,
    main,
    run_spotty_bunny,
)
from app.spotty_bunny_history import (
    HistoryNavigator,
    append_history_line,
    apply_history_selector,
    load_history_lines,
)
from app.spotty_bunny_hotkey import (
    CONTROL_LEFT_KEYCODE,
    CONTROL_RIGHT_KEYCODE,
    ChordTracker,
    apply_control_event,
    apply_hid_snapshot,
    describe_key,
    resolve_control_snapshot,
)
from app.spotty_bunny_quit import (
    WAKE_EVENT_SELECTOR,
    post_application_wake_event,
    quit_ns_app,
)


class SpottyBunnyCliTests(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        log_dir = TemporaryDirectory()
        self.addCleanup(log_dir.cleanup)
        self.log_root = Path(log_dir.name)
        self.log_file = self.log_root / "spotty-bunny.log"
        env_patch = patch.dict(os.environ, {LOG_ENV_VAR: ""}, clear=False)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        data_patch = patch("app.spotty_bunny_cli.data_dir", return_value=self.log_root)
        data_patch.start()
        self.addCleanup(data_patch.stop)

    def tearDown(self) -> None:
        for name in ("app.spotty_bunny_app", "app.spotty_bunny_cli"):
            logger = logging.getLogger(name)
            for handler in logger.handlers:
                handler.close()
            logger.handlers.clear()
        super().tearDown()

    def test_default_log_file_is_created(self) -> None:
        stderr = StringIO()
        with (
            patch("app.spotty_bunny_cli.sys.platform", "linux"),
            patch("app.spotty_bunny_cli.sys.stderr", stderr),
        ):
            self.assertEqual(main([]), 1)
        self.assertTrue(self.log_file.is_file())
        self.assertIn(str(self.log_file), stderr.getvalue())

    def test_default_log_level_is_info(self) -> None:
        stderr = StringIO()
        with (
            patch("app.spotty_bunny_cli.sys.platform", "linux"),
            patch("app.spotty_bunny_cli.sys.stderr", stderr),
        ):
            self.assertEqual(main([]), 1)
        self.assertEqual(
            logging.getLogger("app.spotty_bunny_app").level,
            logging.INFO,
        )
        self.assertEqual(
            logging.getLogger("app.spotty_bunny_cli").level,
            logging.INFO,
        )

    def test_env_log_file(self) -> None:
        custom = self.log_root / "from-env.log"
        stderr = StringIO()
        with (
            patch.dict(os.environ, {LOG_ENV_VAR: str(custom)}),
            patch("app.spotty_bunny_cli.sys.platform", "linux"),
            patch("app.spotty_bunny_cli.sys.stderr", stderr),
        ):
            self.assertEqual(main(["--verbose"]), 1)
        self.assertIn("spotty-bunny starting", custom.read_text(encoding="utf-8"))

    def test_explicit_log_file_receives_debug(self) -> None:
        custom = self.log_root / "custom.log"
        stderr = StringIO()
        with (
            patch("app.spotty_bunny_cli.sys.platform", "linux"),
            patch("app.spotty_bunny_cli.sys.stderr", stderr),
        ):
            self.assertEqual(main(["--verbose", "--log-file", str(custom)]), 1)
        self.assertIn("spotty-bunny starting", custom.read_text(encoding="utf-8"))
        self.assertIn("log_level=DEBUG", custom.read_text(encoding="utf-8"))

    def test_help_exits_zero(self) -> None:
        stdout = StringIO()
        with (
            patch("sys.stdout", stdout),
            self.assertRaises(SystemExit) as raised,
        ):
            main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        help_text = stdout.getvalue()
        self.assertIn("search box", help_text)
        self.assertIn("spotty-bunny", help_text)
        self.assertIn("--log-file", help_text)
        self.assertIn("--log-level", help_text)
        self.assertIn("--verbose", help_text)

    def test_log_level_sets_logger(self) -> None:
        stderr = StringIO()
        with (
            patch("app.spotty_bunny_cli.sys.platform", "linux"),
            patch("app.spotty_bunny_cli.sys.stderr", stderr),
        ):
            self.assertEqual(main(["--log-level", "INFO"]), 1)
        self.assertEqual(
            logging.getLogger("app.spotty_bunny_app").level,
            logging.INFO,
        )
        self.assertEqual(
            logging.getLogger("app.spotty_bunny_cli").level,
            logging.INFO,
        )

    def test_missing_pyobjc_prints_extra_hint(self) -> None:
        def boom() -> int:
            raise ImportError("No module named 'Cocoa'")

        stderr = StringIO()
        with (
            patch("app.spotty_bunny_cli.sys.platform", "darwin"),
            patch("app.spotty_bunny_cli._load_run_spotty_bunny_app", side_effect=boom),
            patch("app.spotty_bunny_cli.sys.stderr", stderr),
        ):
            self.assertEqual(run_spotty_bunny(), 1)
        self.assertIn("bunnify[macos]", stderr.getvalue())
        self.assertIn("uv sync --extra macos", stderr.getvalue())

    def test_not_macos_prints_hint(self) -> None:
        stderr = StringIO()
        with (
            patch("app.spotty_bunny_cli.sys.platform", "linux"),
            patch("app.spotty_bunny_cli.sys.stderr", stderr),
        ):
            self.assertEqual(main([]), 1)
        self.assertIn("only available on macOS", stderr.getvalue())

    def test_spotty_bunny_shortcut_dispatches_extra_args(self) -> None:
        from app.cli import main as cli_main

        with patch("app.spotty_bunny_cli.main", return_value=1) as spotty:
            result = CliRunner().invoke(cli_main, ["spotty-bunny", "foo"])

        self.assertEqual(result.exit_code, 1, result.output)
        spotty.assert_called_once_with(["foo"])

    def test_spotty_bunny_shortcut_dispatches_to_cli(self) -> None:
        from app.cli import main as cli_main

        with patch("app.spotty_bunny_cli.main", return_value=1) as spotty:
            result = CliRunner().invoke(cli_main, ["spotty-bunny"])

        self.assertEqual(result.exit_code, 1, result.output)
        spotty.assert_called_once_with([])

    def test_tap_failure_prints_permission_hint(self) -> None:
        def fail_tap() -> int:
            raise SpottyBunnyEventTapError("event tap was not created")

        stderr = StringIO()
        with (
            patch("app.spotty_bunny_cli.sys.platform", "darwin"),
            patch(
                "app.spotty_bunny_cli._load_run_spotty_bunny_app",
                return_value=fail_tap,
            ),
            patch("app.spotty_bunny_cli.sys.stderr", stderr),
        ):
            self.assertEqual(run_spotty_bunny(), 1)
        self.assertIn("Accessibility", stderr.getvalue())
        self.assertIn("Input Monitoring", stderr.getvalue())

    def test_unwritable_log_file_falls_back_to_stderr(self) -> None:
        blocker = self.log_root / "not-a-directory"
        blocker.write_text("x", encoding="utf-8")
        custom = blocker / "spotty-bunny.log"
        stderr = StringIO()
        with (
            patch("app.spotty_bunny_cli.sys.platform", "linux"),
            patch("app.spotty_bunny_cli.sys.stderr", stderr),
        ):
            self.assertEqual(main(["--log-file", str(custom)]), 1)
        text = stderr.getvalue()
        self.assertIn("cannot write log file", text)
        self.assertIn("logging to stderr only", text)
        self.assertIn("only available on macOS", text)

    def test_verbose_overrides_log_level(self) -> None:
        stderr = StringIO()
        with (
            patch("app.spotty_bunny_cli.sys.platform", "linux"),
            patch("app.spotty_bunny_cli.sys.stderr", stderr),
        ):
            self.assertEqual(main(["--verbose", "--log-level", "ERROR"]), 1)
        self.assertEqual(
            logging.getLogger("app.spotty_bunny_app").level,
            logging.DEBUG,
        )
        self.assertEqual(
            logging.getLogger("app.spotty_bunny_cli").level,
            logging.DEBUG,
        )

    def test_verbose_writes_debug_to_default_log_file(self) -> None:
        stderr = StringIO()
        with (
            patch("app.spotty_bunny_cli.sys.platform", "linux"),
            patch("app.spotty_bunny_cli.sys.stderr", stderr),
        ):
            self.assertEqual(main(["--verbose"]), 1)
        logged = self.log_file.read_text(encoding="utf-8")
        self.assertIn("spotty-bunny starting", logged)
        self.assertIn("log_level=DEBUG", logged)


class SpottyBunnyCompleteTests(SimpleTestCase):
    def test_apply_completion_appends_when_start_position_is_zero(self) -> None:
        from app.spotty_bunny_complete import CompletionRow, apply_completion

        row = CompletionRow(insert="the-hcma/bunnify", meta="", start_position=0)
        self.assertEqual(apply_completion("pr ", row), "pr the-hcma/bunnify")

    def test_apply_completion_replaces_prefix(self) -> None:
        from app.spotty_bunny_complete import CompletionRow, apply_completion

        row = CompletionRow(insert="gh", meta="GitHub", start_position=-1)
        self.assertEqual(apply_completion("g", row), "gh")

    def test_completion_still_current_requires_matching_seq_and_field(self) -> None:
        from app.spotty_bunny_complete import completion_still_current

        self.assertTrue(
            completion_still_current(expected_seq=2, field="gh", prefix="gh", seq=2)
        )
        self.assertFalse(
            completion_still_current(expected_seq=2, field="gho", prefix="gh", seq=2)
        )
        self.assertFalse(
            completion_still_current(expected_seq=2, field="gh", prefix="gh", seq=3)
        )

    def test_completion_row_after_selector_supports_page_keys(self) -> None:
        from app.spotty_bunny_complete import completion_row_after_selector

        self.assertEqual(
            completion_row_after_selector(7, row_count=20, selector="pageUp:"),
            2,
        )
        self.assertEqual(
            completion_row_after_selector(7, row_count=20, selector="pageDown:"),
            12,
        )
        self.assertEqual(
            completion_row_after_selector(0, row_count=3, selector="moveDown:"),
            1,
        )

    def test_first_token_fuzzy_matches_description(self) -> None:
        from app.client import KeyEntry
        from app.spotty_bunny_complete import completions_for, make_spotty_completer

        completer = make_spotty_completer(
            entries=[
                KeyEntry(key="gh", description="GitHub"),
                KeyEntry(key="g", description="Google"),
            ]
        )
        rows = completions_for("hub", completer)
        self.assertEqual([row.insert for row in rows], ["gh"])

    def test_meta_commands_are_excluded(self) -> None:
        from app.spotty_bunny_complete import completions_for, make_spotty_completer

        rows = completions_for("q", make_spotty_completer(entries=[]))
        self.assertEqual(rows, [])

    def test_open_search_uses_suggestions_fn(self) -> None:
        from app.client import KeyEntry
        from app.spotty_bunny_complete import completions_for, make_spotty_completer

        def suggestions(query: str) -> list[str]:
            if query.startswith("g "):
                return [f"{query} news"]
            return []

        completer = make_spotty_completer(
            entries=[KeyEntry(key="g", description="Google")],
            suggestions_fn=suggestions,
        )
        rows = completions_for("g hello", completer)
        self.assertEqual([row.insert for row in rows], ["g hello news"])

    def test_param_suggest_fn_is_used(self) -> None:
        from app.client import KeyEntry
        from app.spotty_bunny_complete import (
            apply_completion,
            completions_for,
            make_spotty_completer,
        )

        completer = make_spotty_completer(
            entries=[
                KeyEntry(key="pr", description="PR", params=("org/repo", "n")),
            ],
            param_suggest_fn=lambda **_kwargs: ["the-hcma/bunnify"],
        )
        rows = completions_for("pr ", completer)
        self.assertEqual([row.insert for row in rows], ["the-hcma/bunnify"])
        self.assertEqual(rows[0].start_position, 0)
        self.assertEqual(apply_completion("pr ", rows[0]), "pr the-hcma/bunnify")

    def test_wrapper_asks_first_token_fuzzy_completer(self) -> None:
        from prompt_toolkit.completion import Completion

        from app.spotty_bunny_complete import completions_for

        completer = MagicMock()
        completer.get_completions.return_value = [
            Completion("gh", start_position=-1, display_meta="GitHub"),
        ]
        rows = completions_for("g", completer)
        completer.get_completions.assert_called_once()
        document = completer.get_completions.call_args[0][0]
        self.assertEqual(document.text, "g")
        self.assertEqual([row.insert for row in rows], ["gh"])
        self.assertEqual(rows[0].meta, "GitHub")


class SpottyBunnyHistoryTests(SimpleTestCase):
    def test_append_round_trips_prompt_toolkit_file_history(self) -> None:
        from prompt_toolkit.history import FileHistory

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "repl_history"
            append_history_line("g hello", path=path)
            append_history_line("  gh  ", path=path)
            append_history_line("", path=path)
            self.assertEqual(load_history_lines(path=path), ["g hello", "gh"])
            self.assertEqual(
                list(FileHistory(str(path)).load_history_strings()),
                ["gh", "g hello"],
            )

    def test_append_unwritable_parent_is_ignored(self) -> None:
        with TemporaryDirectory() as tmp:
            parent = Path(tmp) / "blocked"
            parent.write_text("not-a-dir")
            append_history_line("gh", path=parent / "repl_history")

    def test_apply_history_selector_ignores_return(self) -> None:
        navigator = HistoryNavigator(["gh"])
        self.assertIsNone(apply_history_selector(navigator, "", "insertNewline:"))

    def test_down_at_live_line_keeps_current(self) -> None:
        navigator = HistoryNavigator(["gh"])
        self.assertEqual(navigator.down("typed"), "typed")

    def test_down_restores_draft_after_up(self) -> None:
        navigator = HistoryNavigator(["gh", "g hello"])
        self.assertEqual(navigator.up("draft"), "g hello")
        self.assertEqual(navigator.up("g hello"), "gh")
        self.assertEqual(navigator.down("gh"), "g hello")
        self.assertEqual(navigator.down("g hello"), "draft")

    def test_edit_recalled_line_becomes_draft(self) -> None:
        navigator = HistoryNavigator(["gh", "g hello"])
        self.assertEqual(navigator.up("abc"), "g hello")
        self.assertEqual(navigator.up("g hello!"), "gh")
        self.assertEqual(navigator.down("gh"), "g hello")
        self.assertEqual(navigator.down("g hello"), "g hello!")

    def test_load_invalid_utf8_returns_empty(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "repl_history"
            path.write_bytes(b"\xff\xfe")
            self.assertEqual(load_history_lines(path=path), [])

    def test_load_missing_file_returns_empty(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing" / "repl_history"
            self.assertEqual(load_history_lines(path=path), [])

    def test_up_at_oldest_stays_at_oldest(self) -> None:
        navigator = HistoryNavigator(["gh", "g hello"])
        self.assertEqual(navigator.up("draft"), "g hello")
        self.assertEqual(navigator.up("g hello"), "gh")
        self.assertEqual(navigator.up("gh"), "gh")

    def test_up_on_empty_history_keeps_current(self) -> None:
        navigator = HistoryNavigator()
        self.assertEqual(navigator.up("typed"), "typed")
        self.assertEqual(
            apply_history_selector(navigator, "typed", "moveUp:"),
            "typed",
        )
        self.assertEqual(
            apply_history_selector(navigator, "typed", "moveDown:"),
            "typed",
        )


class SpottyBunnyHotkeyTests(SimpleTestCase):
    def test_batched_hid_both_down_fires_on_completing_keycode(self) -> None:
        tracker = ChordTracker()
        self.assertTrue(
            apply_hid_snapshot(
                tracker,
                keycode=CONTROL_RIGHT_KEYCODE,
                left_down=True,
                right_down=True,
            )
        )
        tracker = ChordTracker()
        self.assertTrue(
            apply_hid_snapshot(
                tracker,
                keycode=CONTROL_LEFT_KEYCODE,
                left_down=True,
                right_down=True,
            )
        )

    def test_both_from_idle_does_not_fire(self) -> None:
        tracker = ChordTracker()
        self.assertFalse(tracker.sync(left_down=True, right_down=True))

    def test_describe_key_ctrl_a(self) -> None:
        self.assertEqual(describe_key(0, control=True), "CTRL-A")

    def test_describe_key_ctrl_shift_a(self) -> None:
        self.assertEqual(
            describe_key(0, control=True, shift=True),
            "CTRL-SHIFT-A",
        )

    def test_describe_key_letter_a(self) -> None:
        self.assertEqual(describe_key(0), "A")

    def test_describe_key_letter_d(self) -> None:
        self.assertEqual(describe_key(2), "D")

    def test_describe_key_left_control_not_prefixed(self) -> None:
        self.assertEqual(
            describe_key(CONTROL_LEFT_KEYCODE, control=True),
            "leftControl",
        )

    def test_describe_key_unknown_with_modifiers(self) -> None:
        self.assertEqual(
            describe_key(200, control=True, shift=True),
            "CTRL-SHIFT-keycode:200",
        )

    def test_device_flag_sees_right_control_without_hid(self) -> None:
        left, right = resolve_control_snapshot(
            keycode=CONTROL_RIGHT_KEYCODE,
            hid_left=True,
            hid_right=False,
            flag_left=True,
            flag_right=True,
            held_left=True,
            held_right=False,
        )
        self.assertEqual((left, right), (True, True))

    def test_hid_misses_right_control_keycode_edge_fires(self) -> None:
        tracker = ChordTracker()
        left, right = resolve_control_snapshot(
            keycode=CONTROL_LEFT_KEYCODE,
            hid_left=True,
            hid_right=False,
            flag_left=True,
            flag_right=False,
            held_left=False,
            held_right=False,
        )
        self.assertFalse(
            apply_hid_snapshot(
                tracker,
                keycode=CONTROL_LEFT_KEYCODE,
                left_down=left,
                right_down=right,
            )
        )
        left, right = resolve_control_snapshot(
            keycode=CONTROL_RIGHT_KEYCODE,
            hid_left=True,
            hid_right=False,
            flag_left=True,
            flag_right=False,
            held_left=tracker.held_left,
            held_right=tracker.held_right,
        )
        self.assertEqual((left, right), (True, True))
        self.assertTrue(
            apply_hid_snapshot(
                tracker,
                keycode=CONTROL_RIGHT_KEYCODE,
                left_down=left,
                right_down=right,
            )
        )

    def test_hid_miss_key_down_flags_key_up_fires_once(self) -> None:
        tracker = ChordTracker()
        self.assertFalse(
            apply_control_event(
                tracker,
                keycode=CONTROL_LEFT_KEYCODE,
                hid_left=True,
                hid_right=False,
                flag_left=True,
                flag_right=False,
                control_flag=True,
                flags_changed=True,
            )
        )
        right_kwargs = {
            "keycode": CONTROL_RIGHT_KEYCODE,
            "hid_left": True,
            "hid_right": False,
            "flag_left": True,
            "flag_right": False,
            "control_flag": True,
        }
        self.assertFalse(
            apply_control_event(tracker, flags_changed=False, **right_kwargs)
        )
        self.assertTrue(
            apply_control_event(tracker, flags_changed=True, **right_kwargs)
        )
        self.assertFalse(
            apply_control_event(tracker, flags_changed=True, **right_kwargs)
        )
        self.assertFalse(
            apply_control_event(tracker, flags_changed=False, **right_kwargs)
        )
        self.assertTrue(tracker.held_left)
        self.assertTrue(tracker.held_right)

    def test_hid_miss_right_release_then_repress_fires(self) -> None:
        clock = _FakeClock()
        tracker = ChordTracker(monotonic=clock)
        held_left = {
            "hid_left": True,
            "hid_right": False,
            "flag_left": True,
            "flag_right": False,
            "control_flag": True,
        }
        self.assertFalse(
            apply_control_event(
                tracker,
                keycode=CONTROL_LEFT_KEYCODE,
                flags_changed=True,
                **held_left,
            )
        )
        self.assertTrue(
            apply_control_event(
                tracker,
                keycode=CONTROL_RIGHT_KEYCODE,
                flags_changed=True,
                **held_left,
            )
        )
        clock.advance(0.001)
        self.assertFalse(
            apply_control_event(
                tracker,
                keycode=CONTROL_RIGHT_KEYCODE,
                flags_changed=True,
                **held_left,
            )
        )
        self.assertTrue(tracker.held_right)
        clock.advance(0.029)
        self.assertFalse(
            apply_control_event(
                tracker,
                keycode=CONTROL_RIGHT_KEYCODE,
                flags_changed=True,
                **held_left,
            )
        )
        self.assertTrue(tracker.held_left)
        self.assertFalse(tracker.held_right)
        clock.advance(0.07)
        self.assertTrue(
            apply_control_event(
                tracker,
                keycode=CONTROL_RIGHT_KEYCODE,
                flags_changed=True,
                **held_left,
            )
        )

    def test_hid_misses_both_controls_press_release_repress(self) -> None:
        tracker = ChordTracker()
        miss = {
            "hid_left": False,
            "hid_right": False,
            "flag_left": False,
            "flag_right": False,
        }
        self.assertFalse(
            apply_control_event(
                tracker,
                keycode=CONTROL_LEFT_KEYCODE,
                control_flag=True,
                flags_changed=True,
                **miss,
            )
        )
        self.assertTrue(tracker.held_left)
        self.assertFalse(tracker.held_right)
        self.assertTrue(
            apply_control_event(
                tracker,
                keycode=CONTROL_RIGHT_KEYCODE,
                control_flag=True,
                flags_changed=True,
                **miss,
            )
        )
        self.assertFalse(
            apply_control_event(
                tracker,
                keycode=CONTROL_LEFT_KEYCODE,
                control_flag=False,
                flags_changed=True,
                **miss,
            )
        )
        self.assertFalse(tracker.held_left)
        self.assertFalse(tracker.held_right)
        self.assertFalse(
            apply_control_event(
                tracker,
                keycode=CONTROL_LEFT_KEYCODE,
                control_flag=True,
                flags_changed=True,
                **miss,
            )
        )
        self.assertTrue(
            apply_control_event(
                tracker,
                keycode=CONTROL_RIGHT_KEYCODE,
                control_flag=True,
                flags_changed=True,
                **miss,
            )
        )

    def test_hid_misses_left_control_keycode_edge_fires(self) -> None:
        tracker = ChordTracker()
        left, right = resolve_control_snapshot(
            keycode=CONTROL_RIGHT_KEYCODE,
            hid_left=False,
            hid_right=True,
            flag_left=False,
            flag_right=True,
            held_left=False,
            held_right=False,
            control_flag=True,
        )
        self.assertFalse(
            apply_hid_snapshot(
                tracker,
                keycode=CONTROL_RIGHT_KEYCODE,
                left_down=left,
                right_down=right,
            )
        )
        left, right = resolve_control_snapshot(
            keycode=CONTROL_LEFT_KEYCODE,
            hid_left=False,
            hid_right=True,
            flag_left=False,
            flag_right=True,
            held_left=tracker.held_left,
            held_right=tracker.held_right,
            control_flag=True,
        )
        self.assertEqual((left, right), (True, True))
        self.assertTrue(
            apply_hid_snapshot(
                tracker,
                keycode=CONTROL_LEFT_KEYCODE,
                left_down=left,
                right_down=right,
            )
        )

    def test_hold_left_then_right_fires_once(self) -> None:
        tracker = ChordTracker()
        self.assertFalse(tracker.sync(left_down=True, right_down=False))
        self.assertTrue(tracker.sync(left_down=True, right_down=True))
        self.assertFalse(tracker.sync(left_down=True, right_down=True))

    def test_hold_right_then_left_fires_once(self) -> None:
        tracker = ChordTracker()
        self.assertFalse(tracker.sync(left_down=False, right_down=True))
        self.assertTrue(tracker.sync(left_down=True, right_down=True))

    def test_release_one_then_press_again_fires(self) -> None:
        tracker = ChordTracker()
        tracker.sync(left_down=True, right_down=False)
        tracker.sync(left_down=True, right_down=True)
        self.assertFalse(tracker.sync(left_down=True, right_down=False))
        self.assertTrue(tracker.sync(left_down=True, right_down=True))

    def test_sequential_singles_do_not_fire(self) -> None:
        tracker = ChordTracker()
        self.assertFalse(tracker.sync(left_down=True, right_down=False))
        self.assertFalse(tracker.sync(left_down=False, right_down=False))
        self.assertFalse(tracker.sync(left_down=False, right_down=True))

    def test_keycode_edge_skipped_when_not_flags_changed(self) -> None:
        left, right = resolve_control_snapshot(
            keycode=CONTROL_RIGHT_KEYCODE,
            hid_left=True,
            hid_right=False,
            flag_left=True,
            flag_right=False,
            held_left=True,
            held_right=False,
            control_flag=True,
            flags_changed=False,
        )
        self.assertEqual((left, right), (True, False))

    def test_shift_flags_changed_does_not_drop_held_right(self) -> None:
        left, right = resolve_control_snapshot(
            keycode=56,
            hid_left=True,
            hid_right=False,
            flag_left=True,
            flag_right=False,
            held_left=True,
            held_right=True,
            control_flag=True,
            flags_changed=True,
        )
        self.assertEqual((left, right), (True, True))


class SpottyBunnyQuitTests(SimpleTestCase):
    def test_post_application_wake_event_posts_at_start(self) -> None:
        ns_app = MagicMock()
        other_event = MagicMock(return_value="wake")
        post_application_wake_event(
            event_type=15,
            ns_app=ns_app,
            other_event=other_event,
        )
        other_event.assert_called_once_with(
            15,
            (0.0, 0.0),
            0,
            0.0,
            0,
            None,
            0,
            0,
            0,
        )
        ns_app.postEvent_atStart_.assert_called_once_with("wake", True)

    def test_quit_ns_app_stops_then_wakes(self) -> None:
        order: list[str] = []
        ns_app = MagicMock()
        ns_app.stop_.side_effect = lambda _sender: order.append("stop")

        def post_wake() -> None:
            order.append("wake")

        quit_ns_app(ns_app=ns_app, post_wake=post_wake)
        self.assertEqual(order, ["stop", "wake"])

    def test_wake_event_selector_is_wired_in_app_module(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "app" / "spotty_bunny_app.py"
        ).read_text(encoding="utf-8")
        self.assertIn("WAKE_EVENT_SELECTOR", source)
        self.assertEqual(
            WAKE_EVENT_SELECTOR,
            "otherEventWithType_location_modifierFlags_timestamp_windowNumber"
            "_context_subtype_data1_data2_",
        )


class SpottyBunnyLaunchTests(SimpleTestCase):
    def test_ensure_spotty_bunny_running_skips_when_already_running(self) -> None:
        from app.spotty_bunny_launch import (
            SPOTTY_BUNNY_PID_FILE,
            ensure_spotty_bunny_running,
        )

        with TemporaryDirectory() as tmp:
            pid_dir = Path(tmp)
            (pid_dir / SPOTTY_BUNNY_PID_FILE).write_text(f"{os.getpid()}\n")
            with (
                patch("app.spotty_bunny_launch.sys.platform", "darwin"),
                patch(
                    "app.spotty_bunny_launch._spotty_bunny_process_alive",
                    return_value=True,
                ),
            ):
                self.assertTrue(
                    ensure_spotty_bunny_running(
                        pid_dir=pid_dir,
                        spawn=lambda _cmd: self.fail("should not spawn"),
                    )
                )

    def test_ensure_spotty_bunny_running_spawns_on_darwin(self) -> None:
        from app.spotty_bunny_launch import (
            SPOTTY_BUNNY_PID_FILE,
            ensure_spotty_bunny_running,
        )

        with TemporaryDirectory() as tmp:
            pid_dir = Path(tmp)
            with (
                patch("app.spotty_bunny_launch.sys.platform", "darwin"),
                patch(
                    "app.spotty_bunny_launch._spotty_bunny_process_alive",
                    return_value=True,
                ),
            ):
                self.assertTrue(
                    ensure_spotty_bunny_running(
                        pid_dir=pid_dir,
                        spawn=lambda _cmd: 4242,
                    )
                )
            self.assertEqual(
                (pid_dir / SPOTTY_BUNNY_PID_FILE).read_text(encoding="utf-8"),
                "4242\n",
            )

    def test_ensure_spotty_bunny_running_fails_when_child_exits(self) -> None:
        from app.spotty_bunny_launch import (
            SPOTTY_BUNNY_PID_FILE,
            ensure_spotty_bunny_running,
        )

        with TemporaryDirectory() as tmp:
            pid_dir = Path(tmp)
            with (
                patch("app.spotty_bunny_launch.sys.platform", "darwin"),
                patch(
                    "app.spotty_bunny_launch._spotty_bunny_process_alive",
                    return_value=False,
                ),
            ):
                self.assertFalse(
                    ensure_spotty_bunny_running(
                        pid_dir=pid_dir,
                        spawn=lambda _cmd: 4242,
                    )
                )
            self.assertFalse((pid_dir / SPOTTY_BUNNY_PID_FILE).exists())

    def test_spotty_bunny_is_running_clears_stale_pid(self) -> None:
        from app.spotty_bunny_launch import (
            SPOTTY_BUNNY_PID_FILE,
            ensure_spotty_bunny_running,
            spotty_bunny_is_running,
        )

        with TemporaryDirectory() as tmp:
            pid_dir = Path(tmp)
            pid_path = pid_dir / SPOTTY_BUNNY_PID_FILE
            pid_path.write_text("999999999\n", encoding="utf-8")
            self.assertFalse(spotty_bunny_is_running(pid_dir=pid_dir))
            self.assertFalse(pid_path.exists())

            spawned: list[object] = []

            def spawn(_cmd: object) -> int:
                spawned.append(_cmd)
                return 4242

            with (
                patch("app.spotty_bunny_launch.sys.platform", "darwin"),
                patch(
                    "app.spotty_bunny_launch._spotty_bunny_process_alive",
                    return_value=True,
                ),
            ):
                self.assertTrue(
                    ensure_spotty_bunny_running(pid_dir=pid_dir, spawn=spawn)
                )
            self.assertEqual(len(spawned), 1)
            self.assertEqual(pid_path.read_text(encoding="utf-8"), "4242\n")

    def test_placeholder_documents_examples(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "app" / "spotty_bunny_app.py"
        ).read_text(encoding="utf-8")
        self.assertIn("gh, c, yt, docs", source)

    def test_primary_screen_uses_menu_bar_display(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "app" / "spotty_bunny_app.py"
        ).read_text(encoding="utf-8")
        self.assertIn("screens[0]", source)
        self.assertNotIn("mainScreen()", source)

    def test_about_panel_constants(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "app" / "spotty_bunny_about.py"
        ).read_text(encoding="utf-8")
        self.assertIn("Copyright © 2026 thehcma", source)
        self.assertIn("Quick shortcut overlay for Bunnify", source)
        self.assertIn("https://github.com/the-hcma/bunnify", source)

    def test_search_panel_has_no_title_bar_label(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "app" / "spotty_bunny_app.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn('setTitle_("spotty-bunny")', source)
        self.assertIn("showAbout:", source)

    def test_about_panel_build_info_prewarmed(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "app" / "spotty_bunny_app.py"
        ).read_text(encoding="utf-8")
        self.assertIn("self._io.submit(get_build_info", source)

    def test_about_panel_resign_does_not_dismiss_main_while_visible(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "app" / "spotty_bunny_app.py"
        ).read_text(encoding="utf-8")
        self.assertIn("resigning is self._about_panel", source)
        self.assertIn("NSApp.keyWindow() is self._about_panel", source)
        self.assertIn("self._about_panel.setDelegate_(self)", source)
        self.assertIn("self._about_open", source)


class SpottyBunnyResolveTests(SimpleTestCase):
    def test_failure_does_not_append_history(self) -> None:
        from app.client import ClientError
        from app.spotty_bunny_resolve import resolve_query

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "repl_history"

            def append(line: str) -> None:
                append_history_line(line, path=path)

            def boom(*_args: object, **_kwargs: object) -> object:
                raise ClientError("unknown shortcut")

            with self.assertRaises(ClientError):
                resolve_query(
                    "nope",
                    base_url="http://127.0.0.1:9",
                    append_fn=append,
                    open_fn=lambda _url: None,
                    resolve_fn=boom,
                )
            self.assertEqual(load_history_lines(path=path), [])

    def test_lookup_does_not_open_or_append(self) -> None:
        from app.client import ResolvedShortcut
        from app.spotty_bunny_resolve import lookup_resolved_url

        seen: dict[str, object] = {}

        def resolve_fn(query: str, **kwargs: object) -> ResolvedShortcut:
            seen.update(kwargs)
            return ResolvedShortcut(
                url="https://github.com",
                kind="shortcut",
                key=query,
            )

        url = lookup_resolved_url(
            "  gh  ",
            base_url="http://127.0.0.1:8000",
            resolve_fn=resolve_fn,
        )
        self.assertEqual(url, "https://github.com")
        self.assertIs(seen.get("strict"), True)

    def test_open_failure_does_not_append_history(self) -> None:
        from app.client import ClientError, ResolvedShortcut
        from app.spotty_bunny_resolve import resolve_query

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "repl_history"

            def append(line: str) -> None:
                append_history_line(line, path=path)

            def boom_open(_url: str) -> None:
                raise ClientError("no browser")

            with self.assertRaises(ClientError):
                resolve_query(
                    "gh",
                    base_url="http://127.0.0.1:8000",
                    append_fn=append,
                    open_fn=boom_open,
                    resolve_fn=lambda query, **_kwargs: ResolvedShortcut(
                        url="https://github.com",
                        kind="shortcut",
                        key=query,
                    ),
                )
            self.assertEqual(load_history_lines(path=path), [])

    def test_resolve_still_current_requires_matching_seq(self) -> None:
        from app.spotty_bunny_resolve import resolve_still_current

        self.assertTrue(resolve_still_current(expected_seq=4, seq=4))
        self.assertFalse(resolve_still_current(expected_seq=4, seq=5))

    def test_success_appends_shared_history_and_opens(self) -> None:
        from app.client import ResolvedShortcut
        from app.spotty_bunny_resolve import resolve_query

        opened: list[str] = []
        seen: dict[str, object] = {}
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "repl_history"

            def append(line: str) -> None:
                append_history_line(line, path=path)

            def resolve_fn(query: str, **kwargs: object) -> ResolvedShortcut:
                seen.update(kwargs)
                return ResolvedShortcut(
                    url="https://github.com",
                    kind="shortcut",
                    key=query,
                )

            url = resolve_query(
                "  gh  ",
                base_url="http://127.0.0.1:8000",
                append_fn=append,
                open_fn=opened.append,
                resolve_fn=resolve_fn,
            )
            self.assertEqual(url, "https://github.com")
            self.assertEqual(opened, ["https://github.com"])
            self.assertEqual(load_history_lines(path=path), ["gh"])
            self.assertIs(seen.get("strict"), True)


class _FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds

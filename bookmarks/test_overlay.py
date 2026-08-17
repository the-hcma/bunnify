from __future__ import annotations

import logging
import os
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from click.testing import CliRunner
from django.test import SimpleTestCase

from app.overlay_cli import (
    OVERLAY_LOG_ENV_VAR,
    OverlayEventTapError,
    main,
    run_overlay,
)
from app.overlay_hotkey import (
    CONTROL_LEFT_KEYCODE,
    CONTROL_RIGHT_KEYCODE,
    ChordTracker,
    apply_hid_snapshot,
    describe_key,
    resolve_control_snapshot,
)


class OverlayCliTests(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        log_dir = TemporaryDirectory()
        self.addCleanup(log_dir.cleanup)
        self.log_root = Path(log_dir.name)
        self.log_file = self.log_root / "bunnify-overlay.log"
        env_patch = patch.dict(os.environ, {OVERLAY_LOG_ENV_VAR: ""}, clear=False)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        data_patch = patch("app.overlay_cli.data_dir", return_value=self.log_root)
        data_patch.start()
        self.addCleanup(data_patch.stop)

    def tearDown(self) -> None:
        for name in ("app.overlay_app", "app.overlay_cli"):
            logger = logging.getLogger(name)
            for handler in logger.handlers:
                handler.close()
            logger.handlers.clear()
        super().tearDown()

    def test_default_log_file_is_created(self) -> None:
        stderr = StringIO()
        with (
            patch("app.overlay_cli.sys.platform", "linux"),
            patch("app.overlay_cli.sys.stderr", stderr),
        ):
            self.assertEqual(main([]), 1)
        self.assertTrue(self.log_file.is_file())
        self.assertIn(str(self.log_file), stderr.getvalue())

    def test_default_log_level_is_warning(self) -> None:
        stderr = StringIO()
        with (
            patch("app.overlay_cli.sys.platform", "linux"),
            patch("app.overlay_cli.sys.stderr", stderr),
        ):
            self.assertEqual(main([]), 1)
        self.assertEqual(logging.getLogger("app.overlay_app").level, logging.WARNING)
        self.assertEqual(logging.getLogger("app.overlay_cli").level, logging.WARNING)

    def test_env_overlay_log_file(self) -> None:
        custom = self.log_root / "from-env.log"
        stderr = StringIO()
        with (
            patch.dict(os.environ, {OVERLAY_LOG_ENV_VAR: str(custom)}),
            patch("app.overlay_cli.sys.platform", "linux"),
            patch("app.overlay_cli.sys.stderr", stderr),
        ):
            self.assertEqual(main(["--verbose"]), 1)
        self.assertIn("overlay starting", custom.read_text(encoding="utf-8"))

    def test_explicit_log_file_receives_debug(self) -> None:
        custom = self.log_root / "custom.log"
        stderr = StringIO()
        with (
            patch("app.overlay_cli.sys.platform", "linux"),
            patch("app.overlay_cli.sys.stderr", stderr),
        ):
            self.assertEqual(main(["--verbose", "--log-file", str(custom)]), 1)
        self.assertIn("overlay starting", custom.read_text(encoding="utf-8"))
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
        self.assertIn("--log-file", help_text)
        self.assertIn("--log-level", help_text)
        self.assertIn("--verbose", help_text)

    def test_log_level_sets_logger(self) -> None:
        stderr = StringIO()
        with (
            patch("app.overlay_cli.sys.platform", "linux"),
            patch("app.overlay_cli.sys.stderr", stderr),
        ):
            self.assertEqual(main(["--log-level", "INFO"]), 1)
        self.assertEqual(logging.getLogger("app.overlay_app").level, logging.INFO)
        self.assertEqual(logging.getLogger("app.overlay_cli").level, logging.INFO)

    def test_missing_pyobjc_prints_extra_hint(self) -> None:
        def boom() -> int:
            raise ImportError("No module named 'Cocoa'")

        stderr = StringIO()
        with (
            patch("app.overlay_cli.sys.platform", "darwin"),
            patch("app.overlay_cli._load_run_overlay_app", side_effect=boom),
            patch("app.overlay_cli.sys.stderr", stderr),
        ):
            self.assertEqual(run_overlay(), 1)
        self.assertIn("bunnify[macos]", stderr.getvalue())
        self.assertIn("uv sync --extra macos", stderr.getvalue())

    def test_not_macos_prints_hint(self) -> None:
        stderr = StringIO()
        with (
            patch("app.overlay_cli.sys.platform", "linux"),
            patch("app.overlay_cli.sys.stderr", stderr),
        ):
            self.assertEqual(main([]), 1)
        self.assertIn("only available on macOS", stderr.getvalue())

    def test_overlay_shortcut_dispatches_extra_args(self) -> None:
        from app.cli import main as cli_main

        with patch("app.overlay_cli.main", return_value=1) as overlay:
            result = CliRunner().invoke(cli_main, ["overlay", "foo"])

        self.assertEqual(result.exit_code, 1, result.output)
        overlay.assert_called_once_with(["foo"])

    def test_overlay_shortcut_dispatches_to_overlay_cli(self) -> None:
        from app.cli import main as cli_main

        with patch("app.overlay_cli.main", return_value=1) as overlay:
            result = CliRunner().invoke(cli_main, ["overlay"])

        self.assertEqual(result.exit_code, 1, result.output)
        overlay.assert_called_once_with([])

    def test_tap_failure_prints_permission_hint(self) -> None:
        def fail_tap() -> int:
            raise OverlayEventTapError("event tap was not created")

        stderr = StringIO()
        with (
            patch("app.overlay_cli.sys.platform", "darwin"),
            patch("app.overlay_cli._load_run_overlay_app", return_value=fail_tap),
            patch("app.overlay_cli.sys.stderr", stderr),
        ):
            self.assertEqual(run_overlay(), 1)
        self.assertIn("Accessibility", stderr.getvalue())
        self.assertIn("Input Monitoring", stderr.getvalue())

    def test_verbose_overrides_log_level(self) -> None:
        stderr = StringIO()
        with (
            patch("app.overlay_cli.sys.platform", "linux"),
            patch("app.overlay_cli.sys.stderr", stderr),
        ):
            self.assertEqual(main(["--verbose", "--log-level", "ERROR"]), 1)
        self.assertEqual(logging.getLogger("app.overlay_app").level, logging.DEBUG)
        self.assertEqual(logging.getLogger("app.overlay_cli").level, logging.DEBUG)

    def test_verbose_writes_debug_to_default_log_file(self) -> None:
        stderr = StringIO()
        with (
            patch("app.overlay_cli.sys.platform", "linux"),
            patch("app.overlay_cli.sys.stderr", stderr),
        ):
            self.assertEqual(main(["--verbose"]), 1)
        logged = self.log_file.read_text(encoding="utf-8")
        self.assertIn("overlay starting", logged)
        self.assertIn("log_level=DEBUG", logged)


class OverlayHotkeyTests(SimpleTestCase):
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

from __future__ import annotations

from io import StringIO
from unittest.mock import patch

from click.testing import CliRunner
from django.test import SimpleTestCase

from app.overlay_cli import OverlayEventTapError, main, run_overlay
from app.overlay_hotkey import (
    CONTROL_LEFT_KEYCODE,
    CONTROL_RIGHT_KEYCODE,
    ChordTracker,
    apply_hid_snapshot,
)


class OverlayCliTests(SimpleTestCase):
    def test_help_exits_zero(self) -> None:
        stdout = StringIO()
        with (
            patch("sys.stdout", stdout),
            self.assertRaises(SystemExit) as raised,
        ):
            main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("search box", stdout.getvalue())

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

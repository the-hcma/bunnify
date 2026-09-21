from __future__ import annotations

import ctypes
import sys
import time
from contextlib import contextmanager
from unittest import skipUnless
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from app.spotty_bunny_complete import CompletionRow
from app.spotty_bunny_icon_win32 import _rgb
from app.spotty_bunny_io import ImmediateIo
from app.spotty_bunny_menu import CHECK_FOR_UPDATES_STATUS, logo_menu_specs
from app.spotty_bunny_status import SHORTCUTS_LOAD_FAILED
from app.spotty_bunny_tap_health import (
    TAP_HEALTH_CHECK_INTERVAL_S,
    try_write_spotty_bunny_health,
)
from app.spotty_bunny_update import UpdateStatus
from app.spotty_bunny_win32_app import (
    FIELD_PLACEHOLDER,
    TIMER_ID_HEALTH,
    TIMER_ID_UPDATE,
    UPDATE_CHECK_INTERVAL_MS,
    VK_DOWN,
    VK_ESCAPE,
    VK_PRIOR,
    VK_RETURN,
    VK_TAB,
    VK_UP,
    WM_APP_COMPLETIONS_READY,
    WM_APP_RESOLVE_READY,
    WM_APP_TOGGLE,
    WM_APP_TRAY,
    SpottyBunnyWin32Controller,
    _center_overlay,
    _create_font,
    _create_overlay_window,
    _draw_placeholder,
    _handle_tray_message,
    _make_overlay_wndproc,
    _OverlayTheme,
    _paint_overlay,
    _register_overlay_class,
    _selector_for_vk,
    _set_window_timer,
    _show_context_menu,
    _show_overlay_window,
    _subclass_edit_control,
    overlay_layout,
    overlay_origin,
    run_spotty_bunny_win32_app,
)
from bookmarks.win32_test_support import real_win32_available


class SelectorForVkTests(SimpleTestCase):
    def test_known_keys_map_to_expected_selectors(self) -> None:
        self.assertEqual(_selector_for_vk(VK_TAB), "insertTab:")
        self.assertEqual(_selector_for_vk(VK_UP), "moveUp:")
        self.assertEqual(_selector_for_vk(VK_DOWN), "moveDown:")
        self.assertEqual(_selector_for_vk(VK_PRIOR), "pageUp:")

    def test_unmapped_key_returns_none(self) -> None:
        self.assertIsNone(_selector_for_vk(0x41))  # 'A'
        self.assertIsNone(_selector_for_vk(VK_RETURN))
        self.assertIsNone(_selector_for_vk(VK_ESCAPE))


def _make_controller() -> SpottyBunnyWin32Controller:
    controller = SpottyBunnyWin32Controller(io=ImmediateIo())
    # show() kicks off a real network call (fetch_key_entries) via
    # _load_completer_async(); none of these tests exercise completer
    # loading itself (that's covered by app.spotty_bunny_complete's own
    # tests), so stub it out to keep this suite offline and fast.
    controller._load_completer_async = lambda: None
    # __init__ seeds _update_status/_outdated from the real on-disk PyPI
    # cache (read_cached_update_status()), which isn't isolated in test
    # settings -- on a machine whose cache reports the installed version
    # as outdated, that would make _outdated start True and the
    # transition assertions below environment-dependent. Also, show()
    # triggers a background PyPI refresh whenever the cache is stale,
    # which it always is with no cache file (the common CI/dev case).
    # Pin both to deterministic, fresh values here; StartupUpdateStatusTests
    # below exercises the real seeding/stale-cache paths directly.
    controller._update_status = UpdateStatus(
        checked_at=time.time(), current="0.0.0", latest=None, outdated=False
    )
    controller._outdated = False
    return controller


class MenuDispatchTests(SimpleTestCase):
    def test_dispatch_table_covers_every_action_in_every_spec_combination(
        self,
    ) -> None:
        controller = _make_controller()
        table = controller.menu_dispatch_table()
        for installed in (False, True):
            for outdated in (False, True):
                for _title, action in logo_menu_specs(
                    installed=installed, outdated=outdated
                ):
                    self.assertIn(action, table)

    def test_unknown_action_logs_and_does_not_raise(self) -> None:
        controller = _make_controller()
        with self.assertLogs("app.spotty_bunny_win32_app", level="WARNING"):
            controller.dispatch_menu_action("bogusAction:")

    def test_quit_action_calls_request_quit(self) -> None:
        controller = _make_controller()
        controller.request_quit = MagicMock()
        controller.dispatch_menu_action("quitSpottyBunny:")
        controller.request_quit.assert_called_once()

    def test_install_success_marks_installed_and_quits(self) -> None:
        controller = _make_controller()
        controller.request_quit = MagicMock()
        with patch(
            "app.spotty_bunny_agent_win32.install_agent", return_value=0
        ) as install:
            controller.dispatch_menu_action("installSpottyBunny:")
        install.assert_called_once()
        controller.request_quit.assert_called_once()
        self.assertTrue(controller._agent_installed)

    def test_install_failure_stays_running_and_does_not_quit(self) -> None:
        controller = _make_controller()
        controller.request_quit = MagicMock()
        statuses: list[str] = []
        controller.set_status_text = statuses.append
        with patch("app.spotty_bunny_agent_win32.install_agent", return_value=1):
            controller.dispatch_menu_action("installSpottyBunny:")
        controller.request_quit.assert_not_called()
        self.assertFalse(controller._agent_installed)
        self.assertTrue(any("failed" in s.lower() for s in statuses))

    def test_upgrade_failure_stays_running_and_does_not_quit(self) -> None:
        controller = _make_controller()
        controller.request_quit = MagicMock()
        with patch("app.spotty_bunny_agent_win32.upgrade_agent", return_value=1):
            controller.dispatch_menu_action("upgradeSpottyBunny:")
        controller.request_quit.assert_not_called()

    def test_uninstall_success_marks_uninstalled_and_quits(self) -> None:
        controller = _make_controller()
        controller._agent_installed = True
        controller.request_quit = MagicMock()
        with patch("app.spotty_bunny_agent_win32.uninstall_agent", return_value=0):
            controller.dispatch_menu_action("uninstallSpottyBunny:")
        controller.request_quit.assert_called_once()
        self.assertFalse(controller._agent_installed)

    def test_uninstall_failure_stays_running_and_does_not_quit(self) -> None:
        controller = _make_controller()
        controller._agent_installed = True
        controller.request_quit = MagicMock()
        statuses: list[str] = []
        controller.set_status_text = statuses.append
        with patch("app.spotty_bunny_agent_win32.uninstall_agent", return_value=1):
            controller.dispatch_menu_action("uninstallSpottyBunny:")
        controller.request_quit.assert_not_called()
        self.assertTrue(controller._agent_installed)
        self.assertTrue(any("failed" in s.lower() for s in statuses))


class RefreshAgentInstalledTests(SimpleTestCase):
    def test_sets_true_when_task_is_registered(self) -> None:
        controller = _make_controller()
        with patch(
            "app.spotty_bunny_agent_win32.is_agent_installed", return_value=True
        ):
            controller.refresh_agent_installed()
        self.assertTrue(controller._agent_installed)

    def test_sets_false_when_task_is_not_registered(self) -> None:
        controller = _make_controller()
        controller._agent_installed = True
        with patch(
            "app.spotty_bunny_agent_win32.is_agent_installed", return_value=False
        ):
            controller.refresh_agent_installed()
        self.assertFalse(controller._agent_installed)


class CheckForUpdatesTests(SimpleTestCase):
    def test_outdated_transition_calls_set_icon_outdated(self) -> None:
        controller = _make_controller()
        controller._io = ImmediateIo()
        calls: list[bool] = []
        controller.set_icon_outdated = calls.append
        status = MagicMock()
        with (
            patch(
                "app.spotty_bunny_win32_app.refresh_update_status",
                return_value=status,
            ),
            patch("app.spotty_bunny_win32_app.badge_should_show", return_value=True),
            patch("app.spotty_bunny_win32_app.summarize_update_check", return_value=""),
        ):
            controller.check_for_updates()
        self.assertEqual(calls, [True])
        self.assertTrue(controller._outdated)

    def test_unchanged_outdated_state_does_not_re_render_icon(self) -> None:
        controller = _make_controller()
        controller._io = ImmediateIo()
        controller._outdated = False
        calls: list[bool] = []
        controller.set_icon_outdated = calls.append
        status = MagicMock()
        with (
            patch(
                "app.spotty_bunny_win32_app.refresh_update_status",
                return_value=status,
            ),
            patch("app.spotty_bunny_win32_app.badge_should_show", return_value=False),
            patch("app.spotty_bunny_win32_app.summarize_update_check", return_value=""),
        ):
            controller.check_for_updates()
        self.assertEqual(calls, [])

    def test_failure_sets_status_and_leaves_icon_and_outdated_untouched(self) -> None:
        controller = _make_controller()
        controller._io = ImmediateIo()
        controller._outdated = False
        calls: list[bool] = []
        controller.set_icon_outdated = calls.append
        statuses: list[str] = []
        controller.set_status_text = statuses.append

        def boom(**_kwargs: object) -> object:
            raise ConnectionError("unreachable")

        with patch(
            "app.spotty_bunny_win32_app.refresh_update_status", side_effect=boom
        ):
            controller.check_for_updates()
        # First call is CHECK_FOR_UPDATES_STATUS ("Checking..."); the second
        # (final) one must be the failure message.
        self.assertEqual(statuses[-1], "Could not check for updates.")
        self.assertFalse(controller._outdated)
        self.assertEqual(calls, [])


class StartupUpdateStatusTests(SimpleTestCase):
    def test_init_seeds_outdated_from_cached_status(self) -> None:
        status = MagicMock()
        with (
            patch(
                "app.spotty_bunny_win32_app.read_cached_update_status",
                return_value=status,
            ),
            patch("app.spotty_bunny_win32_app.badge_should_show", return_value=True),
        ):
            controller = SpottyBunnyWin32Controller(io=ImmediateIo())
        self.assertIs(controller._update_status, status)
        self.assertTrue(controller._outdated)

    def test_init_not_outdated_when_cache_says_current(self) -> None:
        status = MagicMock()
        with (
            patch(
                "app.spotty_bunny_win32_app.read_cached_update_status",
                return_value=status,
            ),
            patch("app.spotty_bunny_win32_app.badge_should_show", return_value=False),
        ):
            controller = SpottyBunnyWin32Controller(io=ImmediateIo())
        self.assertFalse(controller._outdated)

    def test_show_refreshes_in_background_when_cache_is_stale(self) -> None:
        controller = _make_controller()
        calls: list[tuple[bool, bool]] = []
        controller._refresh_update_status = lambda *, force, announce: calls.append(
            (force, announce)
        )
        with patch("app.spotty_bunny_win32_app.cache_is_stale", return_value=True):
            controller.show()
        self.assertEqual(calls, [(False, False)])

    def test_show_does_not_refresh_when_cache_is_fresh(self) -> None:
        controller = _make_controller()
        calls: list[tuple[bool, bool]] = []
        controller._refresh_update_status = lambda *, force, announce: calls.append(
            (force, announce)
        )
        with patch("app.spotty_bunny_win32_app.cache_is_stale", return_value=False):
            controller.show()
        self.assertEqual(calls, [])

    def test_refresh_update_status_quiet_updates_icon_without_status_text(
        self,
    ) -> None:
        controller = _make_controller()
        controller._io = ImmediateIo()
        icon_calls: list[bool] = []
        controller.set_icon_outdated = icon_calls.append
        status_calls: list[str] = []
        controller.set_status_text = status_calls.append
        status = MagicMock()
        with (
            patch(
                "app.spotty_bunny_win32_app.refresh_update_status",
                return_value=status,
            ),
            patch("app.spotty_bunny_win32_app.badge_should_show", return_value=True),
        ):
            controller._refresh_update_status(force=False, announce=False)
        self.assertEqual(icon_calls, [True])
        self.assertEqual(status_calls, [])

    def test_refresh_update_status_quiet_failure_does_not_set_status(self) -> None:
        controller = _make_controller()
        controller._io = ImmediateIo()
        status_calls: list[str] = []
        controller.set_status_text = status_calls.append

        def boom(**_kwargs: object) -> object:
            raise ConnectionError("unreachable")

        with patch(
            "app.spotty_bunny_win32_app.refresh_update_status", side_effect=boom
        ):
            controller._refresh_update_status(force=False, announce=False)
        self.assertEqual(status_calls, [])
        # A failed refresh must still clear the in-flight guard -- otherwise
        # one transient PyPI failure would permanently block every later
        # update check (both the manual menu item and the 24h timer tick).
        self.assertFalse(controller._update_check_pending)

    def test_manual_check_during_quiet_refresh_is_requeued_not_racy(self) -> None:
        # Regression: without a pending/requeue guard, a quiet show()-time
        # refresh and a manual "Check for Updates" click can run
        # concurrently; whichever's fetch resolves last silently overwrites
        # the other's result (see macOS's own _update_check_pending guard,
        # app/spotty_bunny_app.py:1086, for the same race).
        controller = _make_controller()
        controller._io = _CapturingIo()
        status_calls: list[str] = []
        controller.set_status_text = status_calls.append

        controller._refresh_update_status(force=False, announce=False)
        self.assertEqual(len(controller._io.jobs), 1)

        controller.check_for_updates()
        # The click's own status shows immediately, but no second
        # refresh_update_status() job is submitted while one is in flight.
        self.assertEqual(status_calls, [CHECK_FOR_UPDATES_STATUS])
        self.assertEqual(len(controller._io.jobs), 1)
        self.assertTrue(controller._update_check_requeue)

        # The in-flight (quiet) job's own possibly-stale result resolves...
        _work, on_done = controller._io.jobs[0]
        on_done(
            UpdateStatus(checked_at=1.0, current="1.0.0", latest=None, outdated=False)
        )

        # ...and the requeued manual check fires immediately afterwards
        # (now itself in flight as job 2), instead of the click being
        # silently dropped.
        self.assertEqual(len(controller._io.jobs), 2)
        # The full sequence, not just the last entry -- the requeue branch
        # must make its own set_status_text(CHECK_FOR_UPDATES_STATUS) call
        # (app/spotty_bunny_win32_app.py's _refresh_update_status), not just
        # rely on check_for_updates()'s earlier one still being the last
        # item by coincidence.
        self.assertEqual(
            status_calls, [CHECK_FOR_UPDATES_STATUS, CHECK_FOR_UPDATES_STATUS]
        )
        self.assertTrue(controller._update_check_pending)
        self.assertFalse(controller._update_check_requeue)


class ShowHideToggleTests(SimpleTestCase):
    def test_toggle_shows_then_hides(self) -> None:
        controller = _make_controller()
        self.assertFalse(controller.visible)
        controller.toggle()
        self.assertTrue(controller.visible)
        controller.toggle()
        self.assertFalse(controller.visible)

    def test_show_and_hide_call_set_window_visible(self) -> None:
        controller = _make_controller()
        visibility_calls: list[bool] = []
        controller.set_window_visible = visibility_calls.append
        controller.show()
        controller.hide()
        self.assertEqual(visibility_calls, [True, False])

    def test_show_clears_stale_field_text(self) -> None:
        # Regression: a leftover query from the previous open must not
        # resubmit on Return, or get concatenated onto newly typed text.
        controller = _make_controller()
        controller.set_field_text("gh")
        controller.show()
        self.assertEqual(controller.get_field_text(), "")

    def test_show_resets_a_previously_failed_shortcuts_load(self) -> None:
        # Regression: a stale failure from a previous open must not report
        # "could not load shortcuts" on the very next Tab press, before the
        # freshly (re-)kicked-off _load_completer_async() has even had a
        # chance to fail again for real.
        controller = _make_controller()
        controller._shortcuts_load_failed = True
        controller.show()
        self.assertFalse(controller._shortcuts_load_failed)

    def test_show_rebuilds_history_with_newly_appended_lines(self) -> None:
        # Regression: a session-long tray process must see queries appended
        # by earlier resolves, not just the snapshot taken at __init__.
        controller = _make_controller()
        with patch(
            "app.spotty_bunny_win32_app.load_history_lines",
            return_value=["yt"],
        ):
            controller.show()
        self.assertEqual(controller._history.up(""), "yt")

    def test_hide_clears_resolving_flag(self) -> None:
        # Regression: a resolve that completes after hide() must not be
        # locked out of ever resolving again (resolve_still_current would
        # keep tripping the stale-seq early return in handle_resolve_ready).
        controller = _make_controller()
        controller.show()
        controller._resolving = True
        controller.hide()
        self.assertFalse(controller._resolving)

    def test_hide_clears_completion_rows_and_about(self) -> None:
        controller = _make_controller()
        controller.show()
        controller._completion_rows = [CompletionRow("gh", "GitHub", 0)]
        controller._completion_visible = True
        controller.about_open = True
        controller.hide()
        self.assertEqual(controller._completion_rows, [])
        self.assertFalse(controller._completion_visible)
        self.assertFalse(controller.about_open)
        self.assertFalse(controller.visible)

    def test_dismiss_with_escape_closes_about_before_hiding(self) -> None:
        controller = _make_controller()
        controller.show()
        controller.about_open = True
        controller.dismiss_with_escape()
        self.assertFalse(controller.about_open)
        self.assertTrue(controller.visible)
        controller.dismiss_with_escape()
        self.assertFalse(controller.visible)

    def test_show_about_sets_about_open_and_creates_the_window(self) -> None:
        controller = _make_controller()
        controller.create_about_window = MagicMock(return_value=99)
        controller.show_about()
        self.assertTrue(controller.about_open)
        self.assertEqual(controller.about_hwnd, 99)
        controller.create_about_window.assert_called_once()

    def test_show_about_is_idempotent_while_already_open(self) -> None:
        controller = _make_controller()
        controller.create_about_window = MagicMock(return_value=99)
        controller.show_about()
        controller.show_about()
        controller.create_about_window.assert_called_once()

    def test_hide_about_destroys_the_window(self) -> None:
        controller = _make_controller()
        controller.create_about_window = MagicMock(return_value=99)
        controller.destroy_about_window = MagicMock()
        controller.show_about()
        controller.hide_about()
        controller.destroy_about_window.assert_called_once_with(99)
        self.assertIsNone(controller.about_hwnd)
        self.assertFalse(controller.about_open)

    def test_hide_about_without_a_window_is_a_no_op(self) -> None:
        controller = _make_controller()
        controller.destroy_about_window = MagicMock()
        controller.hide_about()
        controller.destroy_about_window.assert_not_called()
        self.assertFalse(controller.about_open)

    def test_show_about_raising_leaves_about_open_false(self) -> None:
        """Regression: about_open must not be set before create_about_
        window() actually returns -- a raise there must not permanently
        suppress the overlay's auto-hide gate or future show_about() calls."""
        controller = _make_controller()
        controller.create_about_window = MagicMock(side_effect=OSError("boom"))
        with self.assertRaises(OSError):
            controller.show_about()
        self.assertFalse(controller.about_open)
        self.assertIsNone(controller.about_hwnd)

    def test_hide_about_raising_still_clears_the_flags(self) -> None:
        """Regression: a raise from destroy_about_window() must not leave
        about_open stuck True with a dead/absent hwnd."""
        controller = _make_controller()
        controller.create_about_window = MagicMock(return_value=99)
        controller.destroy_about_window = MagicMock(side_effect=OSError("boom"))
        controller.show_about()
        with self.assertRaises(OSError):
            controller.hide_about()
        self.assertFalse(controller.about_open)
        self.assertIsNone(controller.about_hwnd)


class HandleEditKeydownTests(SimpleTestCase):
    def test_return_submits_query(self) -> None:
        controller = _make_controller()
        controller.set_field_text("gh")
        submitted: list[str] = []
        controller._io = ImmediateIo()

        def fake_lookup(query: str, **_kwargs: object) -> str:
            submitted.append(query)
            return "https://github.com"

        open_url_fn = MagicMock()
        append_history_fn = MagicMock()
        controller._open_url_fn = open_url_fn
        controller._append_history_fn = append_history_fn
        with (
            patch(
                "app.spotty_bunny_win32_app.lookup_resolved_url",
                side_effect=fake_lookup,
            ),
            patch("app.spotty_bunny_win32_app.resolve_base_url", return_value="u"),
        ):
            handled = controller.handle_edit_keydown(VK_RETURN)
        self.assertTrue(handled)
        self.assertEqual(submitted, ["gh"])
        open_url_fn.assert_called_once_with("https://github.com")
        append_history_fn.assert_called_once_with("gh")

    def test_return_with_empty_field_and_selected_row_submits_that_row(self) -> None:
        controller = _make_controller()
        controller._io = ImmediateIo()
        controller._completion_rows = [
            CompletionRow("gh", "GitHub", -2),
            CompletionRow("gcal", "Calendar", -2),
        ]
        controller._completion_prefix = "g"
        controller._completion_visible = True
        controller._completion_index = 1
        controller.set_field_text("")
        submitted: list[str] = []

        def fake_lookup(query: str, **_kwargs: object) -> str:
            submitted.append(query)
            return "https://calendar.google.com"

        with (
            patch(
                "app.spotty_bunny_win32_app.lookup_resolved_url",
                side_effect=fake_lookup,
            ),
            patch("app.spotty_bunny_win32_app.resolve_base_url", return_value="u"),
        ):
            controller._open_url_fn = MagicMock()
            controller._append_history_fn = MagicMock()
            controller.handle_edit_keydown(VK_RETURN)
        # apply_completion("g", row) with start_position=-2 replaces the
        # whole "g" prefix with the selected row's insert text.
        self.assertEqual(submitted, ["gcal"])

    def test_escape_hides_when_visible(self) -> None:
        controller = _make_controller()
        controller.show()
        self.assertTrue(controller.handle_edit_keydown(VK_ESCAPE))
        self.assertFalse(controller.visible)

    def test_tab_requests_completions(self) -> None:
        controller = _make_controller()
        controller._completer = object()
        with patch(
            "app.spotty_bunny_win32_app.completions_for",
            return_value=[CompletionRow("gh", "GitHub", 0)],
        ):
            handled = controller.handle_edit_keydown(VK_TAB)
        self.assertTrue(handled)
        self.assertEqual(
            controller._completion_rows, [CompletionRow("gh", "GitHub", 0)]
        )

    def test_tab_with_no_completer_loaded_is_a_safe_no_op(self) -> None:
        # Regression: this is the real state for the first seconds after
        # show() while _load_completer_async() is still in flight.
        # completions_for(prefix, None) would raise AttributeError if this
        # guard were removed, propagating out of the edit-control wndproc.
        controller = _make_controller()
        controller._completer = None
        rows_calls: list[list[CompletionRow]] = []
        controller.set_completion_rows = rows_calls.append
        status_calls: list[str] = []
        controller.set_status_text = status_calls.append
        handled = controller.handle_edit_keydown(VK_TAB)
        self.assertTrue(handled)
        self.assertEqual(controller._completion_rows, [])
        self.assertFalse(controller._completion_visible)
        self.assertEqual(rows_calls, [])
        # Load hasn't failed yet (still in flight) -- no status to report.
        self.assertEqual(status_calls, [])

    def test_tab_with_failed_completer_load_reports_status(self) -> None:
        controller = _make_controller()
        controller._completer = None
        controller._shortcuts_load_failed = True
        status_calls: list[str] = []
        controller.set_status_text = status_calls.append
        handled = controller.handle_edit_keydown(VK_TAB)
        self.assertTrue(handled)
        self.assertEqual(status_calls, [SHORTCUTS_LOAD_FAILED])

    def test_up_arrow_after_single_auto_inserted_match_is_consumed(self) -> None:
        # Regression (deferred from #426's review): after Tab auto-inserts a
        # single match, the completion table is hidden but the rows are
        # still tracked -- completion_navigation_disposition() returns
        # "consume" in that state, and arrow keys must not fall through to
        # history navigation.
        controller = _make_controller()
        controller._completion_rows = [CompletionRow("gh", "GitHub", 0)]
        controller._completion_visible = False
        controller._completion_index = 0
        controller.set_field_text("github")
        handled = controller.handle_edit_keydown(VK_UP)
        self.assertTrue(handled)
        self.assertEqual(controller._completion_index, 0)
        self.assertEqual(controller.get_field_text(), "github")

    def test_up_arrow_without_completion_rows_walks_history(self) -> None:
        controller = _make_controller()
        controller._history._lines = ["gh", "yt"]
        controller._history._cursor = 2
        handled = controller.handle_edit_keydown(VK_UP)
        self.assertTrue(handled)
        self.assertEqual(controller.get_field_text(), "yt")

    def test_up_arrow_with_visible_completion_rows_moves_selection_instead(
        self,
    ) -> None:
        controller = _make_controller()
        controller._completion_rows = [
            CompletionRow("a", "", 0),
            CompletionRow("b", "", 0),
        ]
        controller._completion_visible = True
        controller._completion_index = 1
        handled = controller.handle_edit_keydown(VK_UP)
        self.assertTrue(handled)
        self.assertEqual(controller._completion_index, 0)

    def test_unmapped_character_key_is_not_handled(self) -> None:
        controller = _make_controller()
        self.assertFalse(controller.handle_edit_keydown(0x41))

    def test_arrow_selection_writes_row_into_field(self) -> None:
        # Regression: the LISTBOX highlight moving must not be the only
        # effect -- Return reads the field text, so the selected row has to
        # land there too (mirrors macOS's _move_completion).
        controller = _make_controller()
        controller._completion_rows = [
            CompletionRow("gh", "", -1),
            CompletionRow("gcal", "", -1),
        ]
        controller._completion_prefix = "g"
        controller._completion_visible = True
        controller._completion_index = 0
        controller.set_field_text("gh")
        controller.handle_edit_keydown(VK_DOWN)
        self.assertEqual(controller._completion_index, 1)
        self.assertEqual(controller.get_field_text(), "gcal")

    def test_browse_all_selection_does_not_touch_field(self) -> None:
        # Empty prefix (Tab on an empty field): the field must stay empty
        # so _submit_query's own empty-field/_completion_index fallback
        # handles it, matching macOS's completion_browse_all guard.
        controller = _make_controller()
        controller._completion_rows = [
            CompletionRow("gh", "", 0),
            CompletionRow("gcal", "", 0),
        ]
        controller._completion_prefix = ""
        controller._completion_visible = True
        controller._completion_index = 0
        controller.set_field_text("")
        controller.handle_edit_keydown(VK_DOWN)
        self.assertEqual(controller.get_field_text(), "")


class _CapturingIo:
    """Records submitted (work, on_done) pairs instead of running them."""

    def __init__(self) -> None:
        self.jobs: list[tuple] = []

    def submit(self, fn, on_done) -> None:
        self.jobs.append((fn, on_done))


class SubmitQueryCancellationTests(SimpleTestCase):
    def test_empty_field_return_dismisses_without_resolving(self) -> None:
        # No existing test reaches this branch without either a non-empty
        # field or a selected completion row -- without it, deleting the
        # `if not query: self.hide(); return` guard would send an empty
        # query through lookup_resolved_url's non-strict fallback instead.
        controller = _make_controller()
        controller.show()
        controller.set_field_text("")
        open_url_fn = MagicMock()
        controller._open_url_fn = open_url_fn
        controller.handle_edit_keydown(VK_RETURN)
        self.assertFalse(controller.visible)
        open_url_fn.assert_not_called()

    def test_hide_before_resolve_completes_skips_opener_and_appender(self) -> None:
        # Regression: hide()'s _resolve_seq += 1 is the only thing stopping
        # a resolve that finishes after hide() from opening a browser and
        # appending to history for a query the user already dismissed.
        controller = _make_controller()
        controller.show()
        controller.set_field_text("gh")
        io = _CapturingIo()
        controller._io = io
        open_url_fn = MagicMock()
        append_history_fn = MagicMock()
        controller._open_url_fn = open_url_fn
        controller._append_history_fn = append_history_fn
        with (
            patch(
                "app.spotty_bunny_win32_app.lookup_resolved_url",
                return_value="https://github.com",
            ),
            patch("app.spotty_bunny_win32_app.resolve_base_url", return_value="u"),
        ):
            controller.handle_edit_keydown(VK_RETURN)
            self.assertEqual(len(io.jobs), 1)
            work, _on_done = io.jobs[0]
            controller.hide()
            work()
        open_url_fn.assert_not_called()
        append_history_fn.assert_not_called()

    def test_second_return_while_resolving_does_not_queue_another_job(self) -> None:
        # Regression: nothing previously asserted the _resolving re-entrancy
        # guard, so a double-tap of Return could queue two resolves.
        controller = _make_controller()
        controller.set_field_text("gh")
        io = _CapturingIo()
        controller._io = io
        with (
            patch(
                "app.spotty_bunny_win32_app.lookup_resolved_url",
                return_value="https://github.com",
            ),
            patch("app.spotty_bunny_win32_app.resolve_base_url", return_value="u"),
        ):
            controller.handle_edit_keydown(VK_RETURN)
            self.assertEqual(len(io.jobs), 1)
            resolve_seq_after_first = controller._resolve_seq
            controller.handle_edit_keydown(VK_RETURN)
        self.assertEqual(len(io.jobs), 1)
        self.assertEqual(controller._resolve_seq, resolve_seq_after_first)


class LoadCompleterAsyncTests(SimpleTestCase):
    """Exercises the real _load_completer_async, not the _make_controller stub."""

    def test_success_sets_completer_base_url_and_entries(self) -> None:
        controller = SpottyBunnyWin32Controller(io=ImmediateIo())
        entries = [object()]
        with (
            patch(
                "app.spotty_bunny_win32_app.resolve_base_url",
                return_value="http://127.0.0.1:8000",
            ),
            patch("app.spotty_bunny_win32_app.fetch_key_entries", return_value=entries),
            patch(
                "app.spotty_bunny_win32_app.make_spotty_completer",
                return_value="a-completer",
            ),
        ):
            controller._load_completer_async()
        self.assertEqual(controller._completer, "a-completer")
        self.assertEqual(controller._base_url, "http://127.0.0.1:8000")
        self.assertEqual(controller._entries, entries)

    def test_failure_leaves_completer_unset(self) -> None:
        controller = SpottyBunnyWin32Controller(io=ImmediateIo())

        def boom(**_kwargs: object) -> object:
            raise ConnectionError("unreachable")

        with patch("app.spotty_bunny_win32_app.resolve_base_url", side_effect=boom):
            with self.assertLogs("app.spotty_bunny_win32_app", level="WARNING"):
                controller._load_completer_async()
        self.assertIsNone(controller._completer)
        self.assertTrue(controller._shortcuts_load_failed)

    def test_success_clears_a_previously_failed_load(self) -> None:
        controller = SpottyBunnyWin32Controller(io=ImmediateIo())
        controller._shortcuts_load_failed = True
        with (
            patch(
                "app.spotty_bunny_win32_app.resolve_base_url",
                return_value="http://127.0.0.1:8000",
            ),
            patch("app.spotty_bunny_win32_app.fetch_key_entries", return_value=[]),
            patch(
                "app.spotty_bunny_win32_app.make_spotty_completer",
                return_value="a-completer",
            ),
        ):
            controller._load_completer_async()
        self.assertFalse(controller._shortcuts_load_failed)


class CompletionsReadyTests(SimpleTestCase):
    def test_stale_seq_is_ignored(self) -> None:
        controller = _make_controller()
        controller._completion_seq = 5
        controller._pending_completions[3] = [CompletionRow("gh", "", 0)]
        controller.handle_completions_ready(3)
        self.assertEqual(controller._completion_rows, [])

    def test_current_seq_applies_rows_and_auto_inserts_single_match(self) -> None:
        controller = _make_controller()
        controller.set_field_text("g")
        controller._completion_prefix = "g"
        controller._completion_seq = 1
        controller._pending_completions[1] = [CompletionRow("gh", "GitHub", -1)]
        controller.handle_completions_ready(1)
        self.assertEqual(controller.get_field_text(), "gh")
        # A single non-browse-all match is auto-inserted, and completion_
        # table_should_show() deliberately doesn't pop a one-row dropdown
        # for it (matches app.spotty_bunny_complete's contract).
        self.assertFalse(controller._completion_visible)

    def test_current_seq_shows_table_for_multiple_matches(self) -> None:
        controller = _make_controller()
        controller.set_field_text("g")
        controller._completion_prefix = "g"
        controller._completion_seq = 1
        controller._pending_completions[1] = [
            CompletionRow("gh", "GitHub", -1),
            CompletionRow("gcal", "Calendar", -1),
        ]
        controller.handle_completions_ready(1)
        self.assertTrue(controller._completion_visible)

    def test_exception_result_is_ignored(self) -> None:
        controller = _make_controller()
        controller._completion_seq = 1
        controller._pending_completions[1] = ValueError("boom")
        controller.handle_completions_ready(1)
        self.assertEqual(controller._completion_rows, [])


class ResolveReadyTests(SimpleTestCase):
    def test_success_hides_overlay(self) -> None:
        controller = _make_controller()
        controller.show()
        controller._resolve_seq = 1
        controller._resolving = True
        controller._pending_resolves[1] = "https://github.com"
        controller.handle_resolve_ready(1)
        self.assertFalse(controller.visible)
        self.assertFalse(controller._resolving)

    def test_failure_sets_status_and_stays_open(self) -> None:
        controller = _make_controller()
        controller.show()
        controller._resolve_seq = 1
        controller._resolving = True
        statuses: list[str] = []
        controller.set_status_text = statuses.append
        controller._pending_resolves[1] = ValueError("nope")
        controller.handle_resolve_ready(1)
        self.assertTrue(controller.visible)
        self.assertFalse(controller._resolving)
        self.assertTrue(statuses)

    def test_stale_seq_is_ignored(self) -> None:
        controller = _make_controller()
        controller.show()
        controller._resolve_seq = 2
        controller._pending_resolves[1] = "https://github.com"
        controller.handle_resolve_ready(1)
        self.assertTrue(controller.visible)


class HandleAppMessageTests(SimpleTestCase):
    def test_toggle_message_toggles_visibility(self) -> None:
        controller = _make_controller()
        controller.handle_app_message(WM_APP_TOGGLE, 0, 0)
        self.assertTrue(controller.visible)

    def test_resolve_ready_message_routes_to_handler(self) -> None:
        controller = _make_controller()
        controller.show()
        controller._resolve_seq = 7
        controller._pending_resolves[7] = "https://example.com"
        controller.handle_app_message(WM_APP_RESOLVE_READY, 7, 0)
        self.assertFalse(controller.visible)

    def test_completions_ready_message_routes_to_handler(self) -> None:
        controller = _make_controller()
        controller._completion_seq = 3
        controller._completion_prefix = "g"
        controller.set_field_text("g")
        controller._pending_completions[3] = [CompletionRow("gh", "", -1)]
        controller.handle_app_message(WM_APP_COMPLETIONS_READY, 3, 0)
        self.assertEqual(controller.get_field_text(), "gh")


class MoveCompletionTests(SimpleTestCase):
    def test_moving_selection_calls_set_completion_index(self) -> None:
        controller = _make_controller()
        indices: list[int] = []
        controller.set_completion_index = indices.append
        controller._completion_rows = [
            CompletionRow("a", "", 0),
            CompletionRow("b", "", 0),
        ]
        controller._completion_visible = True
        controller._completion_index = 0
        controller.handle_edit_keydown(VK_DOWN)
        self.assertEqual(indices, [1])


class HandleCompletionSelectedTests(SimpleTestCase):
    def test_click_writes_row_into_field_and_refocuses(self) -> None:
        # Regression: clicking a LISTBOX row gives it keyboard focus as a
        # side effect of the click -- without explicitly refocusing the
        # field, Escape/Return would go to the listbox instead from then on.
        controller = _make_controller()
        controller._completion_rows = [
            CompletionRow("gh", "", -1),
            CompletionRow("gcal", "", -1),
        ]
        controller._completion_prefix = "g"
        focus_calls = 0

        def _focus() -> None:
            nonlocal focus_calls
            focus_calls += 1

        controller.focus_field = _focus
        controller.handle_completion_selected(1)
        self.assertEqual(controller.get_field_text(), "gcal")
        self.assertEqual(controller._completion_index, 1)
        self.assertEqual(focus_calls, 1)

    def test_browse_all_click_does_not_touch_field(self) -> None:
        controller = _make_controller()
        controller._completion_rows = [CompletionRow("gh", "", 0)]
        controller._completion_prefix = ""
        controller.set_field_text("")
        controller.handle_completion_selected(0)
        self.assertEqual(controller.get_field_text(), "")
        self.assertEqual(controller._completion_index, 0)

    def test_out_of_range_index_still_refocuses(self) -> None:
        controller = _make_controller()
        controller._completion_rows = [CompletionRow("gh", "", 0)]
        focus_calls = 0

        def _focus() -> None:
            nonlocal focus_calls
            focus_calls += 1

        controller.focus_field = _focus
        controller.handle_completion_selected(-1)
        self.assertEqual(focus_calls, 1)


class HandleFieldChangedTests(SimpleTestCase):
    def test_diverging_text_hides_stale_rows(self) -> None:
        controller = _make_controller()
        controller._completion_rows = [
            CompletionRow("gh", "", -1),
            CompletionRow("gcal", "", -1),
        ]
        controller._completion_prefix = "g"
        controller._completion_visible = True
        controller.set_field_text("git")
        rows_calls: list[list[CompletionRow]] = []
        controller.set_completion_rows = rows_calls.append
        controller.handle_field_changed()
        self.assertEqual(controller._completion_rows, [])
        self.assertFalse(controller._completion_visible)
        self.assertEqual(rows_calls, [[]])

    def test_text_still_matching_a_row_keeps_rows(self) -> None:
        controller = _make_controller()
        controller._completion_rows = [
            CompletionRow("gh", "", -1),
            CompletionRow("gcal", "", -1),
        ]
        controller._completion_prefix = "g"
        controller._completion_visible = True
        controller.set_field_text("gcal")
        controller.handle_field_changed()
        self.assertEqual(len(controller._completion_rows), 2)
        self.assertTrue(controller._completion_visible)

    def test_applying_completion_flag_suppresses_invalidation(self) -> None:
        controller = _make_controller()
        controller._completion_rows = [CompletionRow("gh", "", -1)]
        controller._completion_prefix = "g"
        controller._completion_visible = True
        controller.set_field_text("unrelated-text")
        controller._applying_completion = True
        controller.handle_field_changed()
        self.assertEqual(len(controller._completion_rows), 1)


class ResolveAndSetChordVksTests(SimpleTestCase):
    def test_valid_choice_is_applied(self) -> None:
        controller = _make_controller()
        with patch(
            "app.spotty_bunny_win32_app.load_spotty_bunny_hotkey",
            return_value="control",
        ):
            controller.resolve_and_set_chord_vks()
        self.assertIsNotNone(controller._left_vk)
        self.assertIsNotNone(controller._right_vk)

    def test_invalid_config_value_falls_back_to_control_chord(self) -> None:
        # A hand-edited config.toml with an out-of-range value must not
        # crash the whole process before a tray icon ever appears (mirrors
        # macOS's _resolve_configured_chord fallback).
        from app.spotty_bunny_hotkey_win32 import VK_LCONTROL, VK_RCONTROL

        controller = _make_controller()

        def boom() -> str:
            raise ValueError("invalid choice")

        with (
            patch(
                "app.spotty_bunny_win32_app.load_spotty_bunny_hotkey",
                side_effect=boom,
            ),
            self.assertLogs("app.spotty_bunny_win32_app", level="WARNING"),
        ):
            controller.resolve_and_set_chord_vks()
        self.assertEqual(
            (controller._left_vk, controller._right_vk), (VK_LCONTROL, VK_RCONTROL)
        )


class CheckEventTapHealthTests(SimpleTestCase):
    def test_re_resolves_chord_and_reinstalls_hook(self) -> None:
        # Regression: WH_KEYBOARD_LL exposes no "still active" query, so
        # this unconditional reinstall is the only recovery from a hook
        # Windows silently dropped -- deleting either call here would leave
        # the chord dead for the rest of the session with no test noticing.
        controller = _make_controller()
        with (
            patch.object(controller, "resolve_and_set_chord_vks") as resolve_vks,
            patch.object(controller, "_reinstall_hook") as reinstall,
        ):
            controller.check_event_tap_health()
        resolve_vks.assert_called_once()
        reinstall.assert_called_once()


class ReinstallHookTests(SimpleTestCase):
    """Exercises the real _reinstall_hook body (CheckEventTapHealthTests
    above mocks it out to test check_event_tap_health's delegation only)."""

    def test_installs_with_resolved_vks_and_wires_on_chord_to_toggle(self) -> None:
        controller = _make_controller()
        controller._left_vk = 0xAA
        controller._right_vk = 0xBB
        posted: list[tuple] = []
        controller.post_app_message = lambda *args: posted.append(args)
        fake_hook = object()
        with patch(
            "app.spotty_bunny_win32_app.install_chord_hook",
            return_value=fake_hook,
        ) as install_hook:
            controller._reinstall_hook()
        self.assertIs(controller._hook, fake_hook)
        install_hook.assert_called_once()
        kwargs = install_hook.call_args.kwargs
        self.assertEqual(kwargs["left_vk"], 0xAA)
        self.assertEqual(kwargs["right_vk"], 0xBB)
        # The acceptance criterion itself: firing the passed on_chord must
        # post WM_APP_TOGGLE through post_app_message.
        kwargs["on_chord"]()
        self.assertEqual(posted, [(WM_APP_TOGGLE, 0, 0)])

    def test_falls_back_to_default_vks_when_unresolved(self) -> None:
        from app.spotty_bunny_hotkey_win32 import VK_LCONTROL, VK_RCONTROL

        controller = _make_controller()
        self.assertIsNone(controller._left_vk)
        self.assertIsNone(controller._right_vk)
        with patch(
            "app.spotty_bunny_win32_app.install_chord_hook",
            return_value=object(),
        ) as install_hook:
            controller._reinstall_hook()
        kwargs = install_hook.call_args.kwargs
        self.assertEqual(kwargs["left_vk"], VK_LCONTROL)
        self.assertEqual(kwargs["right_vk"], VK_RCONTROL)

    def test_failed_install_leaves_hook_none(self) -> None:
        controller = _make_controller()
        with patch(
            "app.spotty_bunny_win32_app.install_chord_hook",
            side_effect=OSError("no hook"),
        ):
            controller._reinstall_hook()
        self.assertIsNone(controller._hook)

    def test_uninstalls_the_previous_hook_first(self) -> None:
        controller = _make_controller()
        old_hook = MagicMock()
        controller._hook = old_hook
        with patch(
            "app.spotty_bunny_win32_app.install_chord_hook",
            return_value=object(),
        ):
            controller._reinstall_hook()
        old_hook.uninstall.assert_called_once()


class _FakeWin32Con:
    """Real winuser.h values, hardcoded (win32con isn't importable off Windows)."""

    WM_TIMER = 0x0113
    WM_ACTIVATE = 0x0006
    WA_INACTIVE = 0
    WM_COMMAND = 0x0111
    EN_CHANGE = 0x0300
    LB_GETCURSEL = 0x0188
    WM_DESTROY = 0x0002
    WM_LBUTTONUP = 0x0202
    WM_RBUTTONUP = 0x0205
    WM_CONTEXTMENU = 0x007B
    MF_STRING = 0x0000
    TPM_LEFTALIGN = 0x0000
    TPM_RETURNCMD = 0x0100
    COLOR_WINDOW = 5
    DT_LEFT = 0x0000
    DT_NOPREFIX = 0x0800
    DT_SINGLELINE = 0x0020
    DT_VCENTER = 0x0004
    GWL_WNDPROC = -4
    NULL_PEN = 8
    PS_SOLID = 0
    TRANSPARENT = 1
    WM_CTLCOLOREDIT = 0x0133
    WM_CTLCOLORLISTBOX = 0x0134
    WM_CTLCOLORSTATIC = 0x0138
    WM_KEYDOWN = 0x0100
    WM_PAINT = 0x000F


def _make_fake_win32gui() -> MagicMock:
    win32gui = MagicMock()
    win32gui.DefWindowProc = MagicMock(return_value=0)
    return win32gui


class RegisterOverlayClassTests(SimpleTestCase):
    def test_sets_a_background_brush(self) -> None:
        # Regression: an unset hbrBackground leaves the margins around the
        # EDIT/STATIC/LISTBOX children unpainted, showing whatever was on
        # screen behind the popup.
        controller = _make_controller()
        win32gui = _make_fake_win32gui()
        _register_overlay_class(controller, win32gui=win32gui, win32con=_FakeWin32Con)
        wnd_class = win32gui.WNDCLASS.return_value
        self.assertEqual(wnd_class.hbrBackground, _FakeWin32Con.COLOR_WINDOW + 1)
        win32gui.RegisterClass.assert_called_once_with(wnd_class)


class OverlayWndProcTests(SimpleTestCase):
    def test_wm_timer_update_calls_check_for_updates(self) -> None:
        controller = _make_controller()
        controller.check_for_updates = MagicMock()
        win32gui = _make_fake_win32gui()
        wndproc = _make_overlay_wndproc(
            controller, win32gui=win32gui, win32con=_FakeWin32Con
        )
        wndproc(1, _FakeWin32Con.WM_TIMER, TIMER_ID_UPDATE, 0)
        controller.check_for_updates.assert_called_once()

    def test_wm_timer_health_calls_check_event_tap_health(self) -> None:
        controller = _make_controller()
        controller.check_event_tap_health = MagicMock()
        win32gui = _make_fake_win32gui()
        wndproc = _make_overlay_wndproc(
            controller, win32gui=win32gui, win32con=_FakeWin32Con
        )
        wndproc(1, _FakeWin32Con.WM_TIMER, TIMER_ID_HEALTH, 0)
        controller.check_event_tap_health.assert_called_once()

    def test_wm_activate_inactive_hides_when_about_not_open(self) -> None:
        controller = _make_controller()
        controller.about_open = False
        controller.hide = MagicMock()
        win32gui = _make_fake_win32gui()
        wndproc = _make_overlay_wndproc(
            controller, win32gui=win32gui, win32con=_FakeWin32Con
        )
        wndproc(1, _FakeWin32Con.WM_ACTIVATE, _FakeWin32Con.WA_INACTIVE, 0)
        controller.hide.assert_called_once()

    def test_wm_activate_inactive_leaves_overlay_up_when_about_open(self) -> None:
        # Pins the exact invariant show_about()'s stub docstring says it
        # deliberately avoids breaking.
        controller = _make_controller()
        controller.about_open = True
        controller.hide = MagicMock()
        win32gui = _make_fake_win32gui()
        wndproc = _make_overlay_wndproc(
            controller, win32gui=win32gui, win32con=_FakeWin32Con
        )
        wndproc(1, _FakeWin32Con.WM_ACTIVATE, _FakeWin32Con.WA_INACTIVE, 0)
        controller.hide.assert_not_called()

    def test_wm_command_en_change_calls_handle_field_changed(self) -> None:
        controller = _make_controller()
        controller.handle_field_changed = MagicMock()
        win32gui = _make_fake_win32gui()
        wndproc = _make_overlay_wndproc(
            controller, win32gui=win32gui, win32con=_FakeWin32Con
        )
        wparam = (_FakeWin32Con.EN_CHANGE << 16) | 0
        wndproc(1, _FakeWin32Con.WM_COMMAND, wparam, 0)
        controller.handle_field_changed.assert_called_once()

    def test_wm_command_lbn_selchange_reads_listbox_selection(self) -> None:
        controller = _make_controller()
        controller.handle_completion_selected = MagicMock()
        win32gui = _make_fake_win32gui()
        win32gui.SendMessage = MagicMock(return_value=1)
        wndproc = _make_overlay_wndproc(
            controller, win32gui=win32gui, win32con=_FakeWin32Con
        )
        list_hwnd = 555
        wparam = (1 << 16) | 0  # LBN_SELCHANGE == 1
        wndproc(1, _FakeWin32Con.WM_COMMAND, wparam, list_hwnd)
        win32gui.SendMessage.assert_called_once_with(
            list_hwnd, _FakeWin32Con.LB_GETCURSEL, 0, 0
        )
        controller.handle_completion_selected.assert_called_once_with(1)

    def test_wm_destroy_posts_quit_message(self) -> None:
        controller = _make_controller()
        win32gui = _make_fake_win32gui()
        wndproc = _make_overlay_wndproc(
            controller, win32gui=win32gui, win32con=_FakeWin32Con
        )
        wndproc(1, _FakeWin32Con.WM_DESTROY, 0, 0)
        win32gui.PostQuitMessage.assert_called_once_with(0)

    def test_app_toggle_message_routes_through_handle_app_message(self) -> None:
        controller = _make_controller()
        win32gui = _make_fake_win32gui()
        wndproc = _make_overlay_wndproc(
            controller, win32gui=win32gui, win32con=_FakeWin32Con
        )
        self.assertFalse(controller.visible)
        wndproc(1, WM_APP_TOGGLE, 0, 0)
        self.assertTrue(controller.visible)

    def test_wm_app_tray_routes_lparam_to_handle_tray_message(self) -> None:
        # Regression: Shell_NotifyIcon's callback message delivers the
        # mouse-event code in lparam, not wparam -- passing the wrong one
        # (or deleting this branch) would leave the suite green while the
        # tray icon's left/right-click silently stopped working.
        controller = _make_controller()
        controller.show_about = MagicMock()
        win32gui = _make_fake_win32gui()
        wndproc = _make_overlay_wndproc(
            controller, win32gui=win32gui, win32con=_FakeWin32Con
        )
        wndproc(1, WM_APP_TRAY, 0, _FakeWin32Con.WM_LBUTTONUP)
        controller.show_about.assert_called_once()

    def test_wm_app_tray_right_click_shows_context_menu(self) -> None:
        controller = _make_controller()
        win32gui = _make_fake_win32gui()
        wndproc = _make_overlay_wndproc(
            controller, win32gui=win32gui, win32con=_FakeWin32Con
        )
        with patch("app.spotty_bunny_win32_app._show_context_menu") as show_menu:
            wndproc(1, WM_APP_TRAY, 0, _FakeWin32Con.WM_RBUTTONUP)
        show_menu.assert_called_once()

    def test_unhandled_message_falls_through_to_def_window_proc(self) -> None:
        controller = _make_controller()
        win32gui = _make_fake_win32gui()
        wndproc = _make_overlay_wndproc(
            controller, win32gui=win32gui, win32con=_FakeWin32Con
        )
        wndproc(1, 0x9999, 2, 3)
        win32gui.DefWindowProc.assert_called_once_with(1, 0x9999, 2, 3)


class OverlayLayoutTests(SimpleTestCase):
    def test_compact_panel_matches_the_macos_size(self) -> None:
        layout = overlay_layout()
        self.assertEqual((layout.panel_width, layout.panel_height), (640, 76))

    def test_field_and_logo_share_the_first_row_without_overlapping(self) -> None:
        layout = overlay_layout()
        field_x, field_y, field_w, field_h = layout.field
        logo_x, logo_y, logo_w, logo_h = layout.logo
        self.assertEqual((field_x, field_y, field_h), (10, 10, 56))
        self.assertEqual(field_x + field_w + 8, logo_x)  # LOGO_GAP
        self.assertEqual(logo_x + logo_w + 10, layout.panel_width)  # PANEL_INSET
        self.assertEqual(logo_y + logo_h // 2, field_y + field_h // 2)

    def test_the_text_box_sits_inside_the_field_with_a_text_inset(self) -> None:
        layout = overlay_layout()
        field_x, field_y, field_w, field_h = layout.field
        edit_x, edit_y, edit_w, edit_h = layout.edit
        self.assertEqual(edit_x - field_x, 12)
        self.assertEqual(field_x + field_w - (edit_x + edit_w), 12)
        self.assertEqual(edit_y + edit_h // 2, field_y + field_h // 2)

    def test_status_line_adds_its_height_only_while_visible(self) -> None:
        compact = overlay_layout()
        with_status = overlay_layout(status_visible=True)
        self.assertEqual(with_status.panel_height - compact.panel_height, 8 + 24)

    def test_completion_list_adds_its_height_only_while_visible(self) -> None:
        compact = overlay_layout()
        with_rows = overlay_layout(rows_visible=True)
        self.assertEqual(with_rows.panel_height - compact.panel_height, 8 + 140)

    def test_rows_stack_top_to_bottom_field_status_list(self) -> None:
        layout = overlay_layout(rows_visible=True, status_visible=True)
        field_bottom = layout.field[1] + layout.field[3]
        self.assertEqual(layout.status[1], field_bottom + 8)
        self.assertEqual(layout.rows[1], layout.status[1] + layout.status[3] + 8)
        self.assertEqual(layout.panel_height, layout.rows[1] + layout.rows[3] + 10)

    def test_list_moves_up_when_there_is_no_status_line(self) -> None:
        with_status = overlay_layout(rows_visible=True, status_visible=True)
        without = overlay_layout(rows_visible=True)
        self.assertLess(without.rows[1], with_status.rows[1])

    def test_the_field_row_never_moves(self) -> None:
        self.assertEqual(
            overlay_layout().field,
            overlay_layout(rows_visible=True, status_visible=True).field,
        )


def _make_theme_win32gui() -> MagicMock:
    win32gui = _make_fake_win32gui()
    win32gui.CreateSolidBrush = MagicMock(side_effect=lambda color: ("brush", color))
    win32gui.BeginPaint = MagicMock(return_value=("hdc", "paint"))
    win32gui.GetClientRect = MagicMock(return_value=(0, 0, 640, 76))
    win32gui.CreatePen = MagicMock(return_value="pen")
    win32gui.GetStockObject = MagicMock(return_value="null-pen")
    win32gui.SelectObject = MagicMock(return_value="old")
    return win32gui


class OverlayThemeTests(SimpleTestCase):
    def test_brushes_use_the_macos_panel_fill_and_black(self) -> None:
        win32gui = _make_theme_win32gui()
        theme = _OverlayTheme(win32gui=win32gui)
        self.assertEqual(theme.fill_brush, ("brush", _rgb(0x5C, 0x8C, 0xD6)))
        self.assertEqual(theme.black_brush, ("brush", 0))

    def test_starts_with_the_compact_layout(self) -> None:
        self.assertEqual(
            _OverlayTheme(win32gui=_make_theme_win32gui()).layout, overlay_layout()
        )


class ThemedRegisterOverlayClassTests(SimpleTestCase):
    def test_the_class_background_is_the_panel_fill_brush(self) -> None:
        win32gui = _make_theme_win32gui()
        theme = _OverlayTheme(win32gui=win32gui)
        _register_overlay_class(
            _make_controller(), theme=theme, win32gui=win32gui, win32con=_FakeWin32Con
        )
        self.assertEqual(win32gui.WNDCLASS.return_value.hbrBackground, theme.fill_brush)


class ThemedOverlayWndProcTests(SimpleTestCase):
    def _wndproc(self):
        win32gui = _make_theme_win32gui()
        theme = _OverlayTheme(win32gui=win32gui)
        wndproc = _make_overlay_wndproc(
            _make_controller(), theme=theme, win32gui=win32gui, win32con=_FakeWin32Con
        )
        return wndproc, win32gui, theme

    def test_wm_paint_paints_the_chrome_and_reports_handled(self) -> None:
        wndproc, win32gui, _theme = self._wndproc()
        self.assertEqual(wndproc(1, _FakeWin32Con.WM_PAINT, 0, 0), 0)
        win32gui.BeginPaint.assert_called_once_with(1)
        win32gui.EndPaint.assert_called_once_with(1, "paint")
        win32gui.DefWindowProc.assert_not_called()

    def test_edit_and_list_are_white_on_black(self) -> None:
        for message in (
            _FakeWin32Con.WM_CTLCOLOREDIT,
            _FakeWin32Con.WM_CTLCOLORLISTBOX,
        ):
            wndproc, win32gui, theme = self._wndproc()
            self.assertEqual(wndproc(1, message, 555, 0), theme.black_brush)
            win32gui.SetTextColor.assert_called_once_with(555, 0xFFFFFF)
            win32gui.SetBkColor.assert_called_once_with(555, 0)

    def test_static_text_is_transparent_status_colored_on_the_panel(self) -> None:
        wndproc, win32gui, theme = self._wndproc()
        self.assertEqual(
            wndproc(1, _FakeWin32Con.WM_CTLCOLORSTATIC, 555, 0), theme.fill_brush
        )
        win32gui.SetBkMode.assert_called_once_with(555, _FakeWin32Con.TRANSPARENT)
        win32gui.SetTextColor.assert_called_once_with(555, _rgb(0xFF, 0xC2, 0x85))

    def test_without_a_theme_paint_falls_through_to_the_default_proc(self) -> None:
        win32gui = _make_fake_win32gui()
        wndproc = _make_overlay_wndproc(
            _make_controller(), win32gui=win32gui, win32con=_FakeWin32Con
        )
        wndproc(1, _FakeWin32Con.WM_PAINT, 0, 0)
        win32gui.DefWindowProc.assert_called_once_with(1, _FakeWin32Con.WM_PAINT, 0, 0)


class LogoContextMenuTests(SimpleTestCase):
    """Right-clicking the bunny logo shows the action menu (#513)."""

    def _wndproc(self, *, logo_hwnd: int = 555):
        win32gui = _make_theme_win32gui()
        theme = _OverlayTheme(win32gui=win32gui)
        theme.logo_hwnd = logo_hwnd
        controller = _make_controller()
        wndproc = _make_overlay_wndproc(
            controller, theme=theme, win32gui=win32gui, win32con=_FakeWin32Con
        )
        return wndproc, win32gui, controller

    def test_right_clicking_the_logo_shows_the_menu(self) -> None:
        wndproc, win32gui, controller = self._wndproc()
        with patch("app.spotty_bunny_win32_app._show_context_menu") as show:
            result = wndproc(1, _FakeWin32Con.WM_CONTEXTMENU, 555, 0)
        self.assertEqual(result, 0)
        show.assert_called_once()
        self.assertIs(show.call_args.args[0], controller)
        win32gui.DefWindowProc.assert_not_called()

    def test_a_context_menu_request_from_another_control_is_left_alone(self) -> None:
        wndproc, win32gui, _controller = self._wndproc()
        with patch("app.spotty_bunny_win32_app._show_context_menu") as show:
            wndproc(1, _FakeWin32Con.WM_CONTEXTMENU, 999, 0)
        show.assert_not_called()
        win32gui.DefWindowProc.assert_called_once()

    def test_before_the_logo_exists_no_control_matches(self) -> None:
        # logo_hwnd starts at 0; a WM_CONTEXTMENU with wparam 0 (for example
        # keyboard-invoked) must not pop the menu.
        wndproc, win32gui, _controller = self._wndproc(logo_hwnd=0)
        with patch("app.spotty_bunny_win32_app._show_context_menu") as show:
            wndproc(1, _FakeWin32Con.WM_CONTEXTMENU, 0, 0)
        show.assert_not_called()
        win32gui.DefWindowProc.assert_called_once()

    def test_without_a_theme_there_is_no_logo_to_match(self) -> None:
        win32gui = _make_theme_win32gui()
        wndproc = _make_overlay_wndproc(
            _make_controller(), win32gui=win32gui, win32con=_FakeWin32Con
        )
        with patch("app.spotty_bunny_win32_app._show_context_menu") as show:
            wndproc(1, _FakeWin32Con.WM_CONTEXTMENU, 0, 0)
        show.assert_not_called()

    def test_the_menu_offers_the_same_actions_as_the_tray(self) -> None:
        win32gui = MagicMock()
        win32gui.CreatePopupMenu.return_value = 77
        win32gui.GetCursorPos.return_value = (10, 20)
        win32gui.TrackPopupMenu.return_value = 0
        controller = _make_controller()
        specs = controller.current_menu_specs()
        _show_context_menu(controller, win32gui=win32gui, win32con=_FakeWin32Con)
        titles = [call.args[3] for call in win32gui.AppendMenu.call_args_list]
        self.assertEqual(titles, [title for title, _action in specs])
        self.assertTrue(titles)


class LogoClickTests(SimpleTestCase):
    """Clicking the bunny logo opens About, like the macOS panel's logo."""

    _WM_COMMAND = _FakeWin32Con.WM_COMMAND

    def _wndproc(self, *, logo_hwnd: int = 555):
        win32gui = _make_theme_win32gui()
        theme = _OverlayTheme(win32gui=win32gui)
        theme.logo_hwnd = logo_hwnd
        controller = _make_controller()
        controller.show_about = MagicMock()
        controller.handle_completion_selected = MagicMock()
        wndproc = _make_overlay_wndproc(
            controller, theme=theme, win32gui=win32gui, win32con=_FakeWin32Con
        )
        return wndproc, win32gui, controller

    def test_clicking_the_logo_opens_about(self) -> None:
        wndproc, win32gui, controller = self._wndproc()
        stn_clicked = 0
        self.assertEqual(wndproc(1, self._WM_COMMAND, (stn_clicked << 16) | 9, 555), 0)
        controller.show_about.assert_called_once_with()
        win32gui.DefWindowProc.assert_not_called()

    def test_a_click_from_some_other_control_does_not_open_about(self) -> None:
        wndproc, win32gui, controller = self._wndproc()
        wndproc(1, self._WM_COMMAND, 0 | 9, 999)
        controller.show_about.assert_not_called()

    def test_double_clicking_the_logo_is_not_a_completion_selection(self) -> None:
        # STN_DBLCLK is 1, the same value as LBN_SELCHANGE. Without an explicit
        # swallow it would be handled as "row 0 of the list was selected".
        wndproc, win32gui, controller = self._wndproc()
        stn_dblclk = 1
        result = wndproc(1, self._WM_COMMAND, (stn_dblclk << 16) | 9, 555)
        self.assertEqual(result, 0)
        controller.handle_completion_selected.assert_not_called()
        controller.show_about.assert_not_called()
        win32gui.SendMessage.assert_not_called()

    def test_a_real_list_selection_still_works(self) -> None:
        wndproc, win32gui, controller = self._wndproc()
        win32gui.SendMessage = MagicMock(return_value=2)
        lbn_selchange = 1
        wndproc(1, self._WM_COMMAND, (lbn_selchange << 16) | 9, 777)
        controller.handle_completion_selected.assert_called_once_with(2)
        controller.show_about.assert_not_called()

    def test_before_the_logo_exists_no_control_matches(self) -> None:
        # logo_hwnd starts at 0; a stray lparam of 0 must not open About.
        wndproc, _gui, controller = self._wndproc(logo_hwnd=0)
        wndproc(1, self._WM_COMMAND, 0, 0)
        controller.show_about.assert_not_called()

    def test_without_a_theme_the_logo_is_not_wired(self) -> None:
        controller = _make_controller()
        controller.show_about = MagicMock()
        win32gui = _make_fake_win32gui()
        wndproc = _make_overlay_wndproc(
            controller, win32gui=win32gui, win32con=_FakeWin32Con
        )
        wndproc(1, self._WM_COMMAND, 0, 555)
        controller.show_about.assert_not_called()


class ShowAboutGateTests(SimpleTestCase):
    """The overlay auto-hides when it loses activation, and creating About
    activates About. Opening it from the overlay's own logo must not hide the
    overlay it was clicked on."""

    def _wndproc(self, controller):
        return _make_overlay_wndproc(
            controller, win32gui=_make_fake_win32gui(), win32con=_FakeWin32Con
        )

    def test_the_flag_is_set_only_while_the_popup_is_being_created(self) -> None:
        controller = _make_controller()
        seen: list[tuple[bool, bool]] = []

        def create() -> int:
            seen.append((controller.about_opening, controller.about_open))
            return 42

        controller.create_about_window = create
        controller.show_about()
        self.assertEqual(seen, [(True, False)])
        self.assertFalse(controller.about_opening)
        self.assertTrue(controller.about_open)
        self.assertEqual(controller.about_hwnd, 42)

    def test_a_failed_creation_leaves_both_flags_clear(self) -> None:
        controller = _make_controller()
        controller.create_about_window = MagicMock(side_effect=RuntimeError("boom"))
        with self.assertRaises(RuntimeError):
            controller.show_about()
        self.assertFalse(controller.about_opening)
        self.assertFalse(controller.about_open)
        self.assertIsNone(controller.about_hwnd)

    def test_the_overlay_stays_up_while_about_is_created(self) -> None:
        controller = _make_controller()
        controller.hide = MagicMock()
        wndproc = self._wndproc(controller)

        def create() -> int:
            # What Windows does: activating About deactivates the overlay.
            wndproc(1, _FakeWin32Con.WM_ACTIVATE, _FakeWin32Con.WA_INACTIVE, 0)
            return 42

        controller.create_about_window = create
        controller.show_about()
        controller.hide.assert_not_called()

    def test_the_overlay_still_hides_on_deactivation_otherwise(self) -> None:
        controller = _make_controller()
        controller.hide = MagicMock()
        wndproc = self._wndproc(controller)
        wndproc(1, _FakeWin32Con.WM_ACTIVATE, _FakeWin32Con.WA_INACTIVE, 0)
        controller.hide.assert_called_once()

    def test_the_overlay_stays_up_while_about_is_open(self) -> None:
        controller = _make_controller()
        controller.hide = MagicMock()
        controller.about_open = True
        wndproc = self._wndproc(controller)
        wndproc(1, _FakeWin32Con.WM_ACTIVATE, _FakeWin32Con.WA_INACTIVE, 0)
        controller.hide.assert_not_called()

    def test_a_failed_creation_does_not_suppress_later_auto_hide(self) -> None:
        controller = _make_controller()
        controller.hide = MagicMock()
        controller.create_about_window = MagicMock(side_effect=RuntimeError("boom"))
        wndproc = self._wndproc(controller)
        with self.assertRaises(RuntimeError):
            controller.show_about()
        wndproc(1, _FakeWin32Con.WM_ACTIVATE, _FakeWin32Con.WA_INACTIVE, 0)
        controller.hide.assert_called_once()


class PaintOverlayTests(SimpleTestCase):
    def test_draws_the_panel_then_the_black_field(self) -> None:
        win32gui = _make_theme_win32gui()
        theme = _OverlayTheme(win32gui=win32gui)
        _paint_overlay(1, theme, win32con=_FakeWin32Con, win32gui=win32gui)
        panel, field = win32gui.RoundRect.call_args_list
        self.assertEqual(panel.args, ("hdc", 1, 1, 639, 75, 20, 20))
        field_x, field_y, field_w, field_h = theme.layout.field
        self.assertEqual(
            field.args,
            (
                "hdc",
                field_x,
                field_y,
                field_x + field_w + 1,
                field_y + field_h + 1,
                16,
                16,
            ),
        )

    def test_selects_the_fill_then_the_black_brush(self) -> None:
        win32gui = _make_theme_win32gui()
        theme = _OverlayTheme(win32gui=win32gui)
        _paint_overlay(1, theme, win32con=_FakeWin32Con, win32gui=win32gui)
        selected = [call.args[1] for call in win32gui.SelectObject.call_args_list]
        self.assertLess(
            selected.index(theme.fill_brush), selected.index(theme.black_brush)
        )

    def _recording_win32gui(self) -> tuple[MagicMock, list[tuple[str, object]]]:
        win32gui = _make_theme_win32gui()
        order: list[tuple[str, object]] = []

        def select(_dc, obj):
            order.append(("select", obj))
            return "old"

        win32gui.SelectObject = MagicMock(side_effect=select)
        win32gui.DeleteObject = MagicMock(
            side_effect=lambda obj: order.append(("delete", obj))
        )
        return win32gui, order

    def test_frame_pen_is_released_and_paint_ended_even_on_error(self) -> None:
        # A painting error must not leak the 2px frame pen or leave the DC
        # holding our objects: the cleanup lives in the finally block.
        win32gui, order = self._recording_win32gui()
        win32gui.RoundRect = MagicMock(side_effect=RuntimeError("boom"))
        theme = _OverlayTheme(win32gui=win32gui)
        with self.assertRaises(RuntimeError):
            _paint_overlay(1, theme, win32con=_FakeWin32Con, win32gui=win32gui)
        win32gui.DeleteObject.assert_called_once_with("pen")
        win32gui.EndPaint.assert_called_once_with(1, "paint")
        # Deselect before deleting: GDI will not delete a selected object.
        last_restore = max(
            i for i, step in enumerate(order) if step == ("select", "old")
        )
        self.assertLess(last_restore, order.index(("delete", "pen")))

    def test_the_original_pen_and_brush_are_restored_after_painting(self) -> None:
        win32gui, order = self._recording_win32gui()
        theme = _OverlayTheme(win32gui=win32gui)
        _paint_overlay(1, theme, win32con=_FakeWin32Con, win32gui=win32gui)
        # Both original objects are selected back before the pen is deleted.
        restores = [i for i, step in enumerate(order) if step == ("select", "old")]
        self.assertEqual(len(restores), 2)
        self.assertLess(max(restores), order.index(("delete", "pen")))

    def test_a_failure_before_the_pen_exists_deletes_nothing(self) -> None:
        win32gui, _order = self._recording_win32gui()
        win32gui.GetClientRect = MagicMock(side_effect=RuntimeError("stale hdc"))
        theme = _OverlayTheme(win32gui=win32gui)
        with self.assertRaises(RuntimeError):
            _paint_overlay(1, theme, win32con=_FakeWin32Con, win32gui=win32gui)
        win32gui.DeleteObject.assert_not_called()
        win32gui.EndPaint.assert_called_once_with(1, "paint")

    def test_a_failed_pen_creation_deletes_nothing(self) -> None:
        win32gui, _order = self._recording_win32gui()
        win32gui.CreatePen = MagicMock(side_effect=RuntimeError("no pen"))
        theme = _OverlayTheme(win32gui=win32gui)
        with self.assertRaises(RuntimeError):
            _paint_overlay(1, theme, win32con=_FakeWin32Con, win32gui=win32gui)
        win32gui.DeleteObject.assert_not_called()
        win32gui.EndPaint.assert_called_once_with(1, "paint")

    def test_paint_is_ended_even_if_the_cleanup_itself_fails(self) -> None:
        win32gui, _order = self._recording_win32gui()
        win32gui.DeleteObject = MagicMock(side_effect=RuntimeError("cleanup boom"))
        theme = _OverlayTheme(win32gui=win32gui)
        with self.assertRaises(RuntimeError):
            _paint_overlay(1, theme, win32con=_FakeWin32Con, win32gui=win32gui)
        win32gui.EndPaint.assert_called_once_with(1, "paint")

    def test_frame_pen_is_deleted(self) -> None:
        win32gui = _make_theme_win32gui()
        theme = _OverlayTheme(win32gui=win32gui)
        _paint_overlay(1, theme, win32con=_FakeWin32Con, win32gui=win32gui)
        win32gui.DeleteObject.assert_called_once_with("pen")


class DrawPlaceholderTests(SimpleTestCase):
    def _win32gui(self, *, text_length: int) -> MagicMock:
        win32gui = _make_fake_win32gui()
        win32gui.GetWindowTextLength = MagicMock(return_value=text_length)
        win32gui.GetDC = MagicMock(return_value="hdc")
        win32gui.GetClientRect = MagicMock(return_value=(0, 0, 500, 30))
        win32gui.SelectObject = MagicMock(return_value="old-font")
        return win32gui

    def test_draws_the_hint_into_an_empty_field(self) -> None:
        win32gui = self._win32gui(text_length=0)
        _draw_placeholder(5, 9, win32con=_FakeWin32Con, win32gui=win32gui)
        win32gui.SetTextColor.assert_called_once_with("hdc", _rgb(0x8C, 0x8C, 0x8C))
        args = win32gui.DrawText.call_args.args
        self.assertEqual(args[:4], ("hdc", FIELD_PLACEHOLDER, -1, (0, 0, 500, 30)))
        win32gui.SelectObject.assert_any_call("hdc", 9)
        win32gui.SelectObject.assert_any_call("hdc", "old-font")
        win32gui.ReleaseDC.assert_called_once_with(5, "hdc")

    def test_draws_nothing_once_the_user_has_typed(self) -> None:
        win32gui = self._win32gui(text_length=2)
        _draw_placeholder(5, 9, win32con=_FakeWin32Con, win32gui=win32gui)
        win32gui.GetDC.assert_not_called()
        win32gui.DrawText.assert_not_called()

    def test_the_dc_is_released_even_if_drawing_fails(self) -> None:
        win32gui = self._win32gui(text_length=0)
        win32gui.DrawText = MagicMock(side_effect=RuntimeError("boom"))
        with self.assertRaises(RuntimeError):
            _draw_placeholder(5, 9, win32con=_FakeWin32Con, win32gui=win32gui)
        win32gui.ReleaseDC.assert_called_once_with(5, "hdc")


class SubclassEditControlTests(SimpleTestCase):
    def _subclass(self, *, font):
        win32gui = _make_fake_win32gui()
        win32gui.SetWindowLong = MagicMock(return_value="original-proc")
        win32gui.CallWindowProc = MagicMock(return_value=77)
        controller = _make_controller()
        controller.handle_edit_keydown = MagicMock(return_value=False)
        _subclass_edit_control(
            5, controller, font=font, win32gui=win32gui, win32con=_FakeWin32Con
        )
        wndproc = win32gui.SetWindowLong.call_args.args[2]
        return wndproc, win32gui, controller

    def test_paint_runs_the_original_proc_then_draws_the_placeholder(self) -> None:
        wndproc, win32gui, _controller = self._subclass(font=9)
        with patch("app.spotty_bunny_win32_app._draw_placeholder") as draw:
            result = wndproc(5, _FakeWin32Con.WM_PAINT, 0, 0)
        self.assertEqual(result, 77)
        win32gui.CallWindowProc.assert_called_once_with(
            "original-proc", 5, _FakeWin32Con.WM_PAINT, 0, 0
        )
        draw.assert_called_once_with(5, 9, win32con=_FakeWin32Con, win32gui=win32gui)

    def test_no_font_means_no_placeholder(self) -> None:
        wndproc, _win32gui, _controller = self._subclass(font=None)
        with patch("app.spotty_bunny_win32_app._draw_placeholder") as draw:
            wndproc(5, _FakeWin32Con.WM_PAINT, 0, 0)
        draw.assert_not_called()

    def test_other_messages_do_not_draw_the_placeholder(self) -> None:
        wndproc, _win32gui, _controller = self._subclass(font=9)
        with patch("app.spotty_bunny_win32_app._draw_placeholder") as draw:
            wndproc(5, 0x9999, 0, 0)
        draw.assert_not_called()

    def test_handled_keys_are_swallowed_before_the_original_proc(self) -> None:
        wndproc, win32gui, controller = self._subclass(font=9)
        controller.handle_edit_keydown = MagicMock(return_value=True)
        self.assertEqual(wndproc(5, _FakeWin32Con.WM_KEYDOWN, 0x09, 0), 0)
        win32gui.CallWindowProc.assert_not_called()


class CreateFontTests(SimpleTestCase):
    def test_builds_a_cleartype_segoe_ui_font_of_the_requested_pixel_height(
        self,
    ) -> None:
        win32gui = _make_fake_win32gui()
        spec = win32gui.LOGFONT.return_value
        win32gui.CreateFontIndirect = MagicMock(return_value=123)
        self.assertEqual(_create_font(win32gui, height=22), 123)
        self.assertEqual(spec.lfFaceName, "Segoe UI")
        self.assertEqual(spec.lfHeight, -22)
        self.assertEqual(spec.lfQuality, 5)


class CreateOverlayWindowTests(SimpleTestCase):
    """Drive the real ``_create_overlay_window`` against a recording fake."""

    def _create(self, *, fonts: list[int] | None = None, outdated: bool = False):
        controller = _make_controller()
        # _make_controller pins this to False; a test can seed the cache-derived
        # state the way __init__ does on a machine whose update cache says so.
        controller._outdated = outdated
        win32gui = _make_theme_win32gui()
        win32gui.error = _FakeGuiError
        handles = iter(range(100, 200))
        win32gui.CreateWindowEx = MagicMock(side_effect=lambda *_a: next(handles))
        win32gui.GetWindowRect = MagicMock(return_value=(640, 400, 1280, 476))
        win32gui.CreateFontIndirect = (
            MagicMock(side_effect=list(fonts))
            if fonts is not None
            else MagicMock(return_value=321)
        )
        win32gui.SendMessage = MagicMock(return_value=0)
        win32gui.SetWindowLong = MagicMock(return_value="original-proc")
        win32con = MagicMock()
        # Real winuser.h values where a test inspects style bits (a MagicMock
        # `|` would hide a missing flag).
        win32con.WS_CHILD = 0x40000000
        win32con.WS_VISIBLE = 0x10000000
        win32con.SS_ICON = 0x00000003
        win32con.SS_NOTIFY = 0x00000100
        with patch(
            "app.spotty_bunny_win32_app.make_spotty_bunny_icon_win32",
            return_value=555,
        ) as make_icon:
            hwnd = _create_overlay_window(
                controller, win32gui=win32gui, win32con=win32con
            )
        return controller, win32gui, win32con, hwnd, make_icon

    def test_the_panel_is_created_compact_and_children_use_the_layout(self) -> None:
        _controller, win32gui, _con, hwnd, _icon = self._create()
        layout = overlay_layout()
        creates = win32gui.CreateWindowEx.call_args_list
        self.assertEqual(hwnd, 100)
        self.assertEqual(creates[0].args[6:8], (640, 76))
        classes = [call.args[1] for call in creates[1:]]
        self.assertEqual(classes, ["EDIT", "STATIC", "STATIC", "LISTBOX"])
        self.assertEqual(creates[1].args[4:8], layout.edit)
        self.assertEqual(creates[2].args[4:8], layout.logo)
        self.assertEqual(creates[3].args[4:8], layout.status)
        self.assertEqual(creates[4].args[4:8], layout.rows)

    def test_the_status_line_is_shown_only_while_it_has_text(self) -> None:
        controller, win32gui, con, _hwnd, _icon = self._create()
        # 100 overlay, 101 edit, 102 logo, 103 status, 104 list.
        controller.set_status_text("Unknown shortcut")
        win32gui.ShowWindow.assert_any_call(103, con.SW_SHOW)
        win32gui.ShowWindow.reset_mock()
        controller.set_status_text("")
        win32gui.ShowWindow.assert_any_call(103, con.SW_HIDE)
        self.assertNotIn(
            ((103, con.SW_SHOW),), [c.args for c in win32gui.ShowWindow.call_args_list]
        )

    def test_the_completion_list_is_shown_only_while_it_has_rows(self) -> None:
        controller, win32gui, con, _hwnd, _icon = self._create()
        controller.set_completion_rows([CompletionRow("gh", "GitHub", 0)])
        win32gui.ShowWindow.assert_any_call(104, con.SW_SHOW)
        win32gui.ShowWindow.reset_mock()
        controller.set_completion_rows([])
        win32gui.ShowWindow.assert_any_call(104, con.SW_HIDE)

    def test_status_and_list_start_hidden(self) -> None:
        _controller, win32gui, con, _hwnd, _icon = self._create()
        win32gui.ShowWindow.assert_any_call(103, con.SW_HIDE)
        win32gui.ShowWindow.assert_any_call(104, con.SW_HIDE)

    def test_the_status_line_and_list_toggle_independently(self) -> None:
        controller, win32gui, con, _hwnd, _icon = self._create()
        controller.set_status_text("x")
        win32gui.ShowWindow.reset_mock()
        controller.set_completion_rows([CompletionRow("gh", "GitHub", 0)])
        # Showing the list must not hide the status line that is still up.
        win32gui.ShowWindow.assert_any_call(103, con.SW_SHOW)
        win32gui.ShowWindow.assert_any_call(104, con.SW_SHOW)

    def test_the_text_box_and_the_placeholder_share_one_font(self) -> None:
        # The placeholder is painted into the same box the user types in, so
        # it must use the Edit's own font, not the smaller status/list one.
        controller, win32gui, con, _hwnd, _icon = self._create(fonts=[901, 902])
        edit, status, rows = 101, 103, 104
        win32gui.SendMessage.assert_any_call(edit, con.WM_SETFONT, 901, True)
        win32gui.SendMessage.assert_any_call(status, con.WM_SETFONT, 902, True)
        win32gui.SendMessage.assert_any_call(rows, con.WM_SETFONT, 902, True)
        con.WM_PAINT = 0x000F
        con.WM_KEYDOWN = 0x0100
        subclass_proc = win32gui.SetWindowLong.call_args.args[2]
        win32gui.CallWindowProc = MagicMock(return_value=0)
        with patch("app.spotty_bunny_win32_app._draw_placeholder") as draw:
            subclass_proc(edit, con.WM_PAINT, 0, 0)
        draw.assert_called_once_with(edit, 901, win32con=con, win32gui=win32gui)

    def test_the_panel_is_rounded_to_its_size(self) -> None:
        _controller, win32gui, _con, hwnd, _icon = self._create()
        win32gui.CreateRoundRectRgn.assert_called_with(0, 0, 641, 77, 20, 20)
        self.assertEqual(win32gui.SetWindowRgn.call_args.args[0], hwnd)

    def test_the_logo_reports_clicks_to_the_overlay(self) -> None:
        _controller, win32gui, con, _hwnd, _icon = self._create()
        logo_style = win32gui.CreateWindowEx.call_args_list[2].args[3]
        self.assertTrue(logo_style & con.SS_NOTIFY, "SS_NOTIFY missing: no clicks")
        self.assertEqual(logo_style & con.SS_ICON, con.SS_ICON)

    def test_clicking_the_created_logo_opens_about(self) -> None:
        controller, win32gui, con, _hwnd, _icon = self._create()
        controller.show_about = MagicMock()
        con.WM_COMMAND = 0x0111
        # The window class was registered with the wndproc built for this
        # overlay; the logo is the third window created (100 overlay, 101 edit,
        # 102 logo).
        wndproc = win32gui.WNDCLASS.return_value.lpfnWndProc
        wndproc(100, con.WM_COMMAND, 0, 102)
        controller.show_about.assert_called_once_with()

    def test_clicking_another_child_does_not_open_about(self) -> None:
        controller, win32gui, con, _hwnd, _icon = self._create()
        controller.show_about = MagicMock()
        con.WM_COMMAND = 0x0111
        wndproc = win32gui.WNDCLASS.return_value.lpfnWndProc
        wndproc(100, con.WM_COMMAND, 0, 103)  # the status line
        controller.show_about.assert_not_called()

    def test_the_logo_is_the_bunny_on_the_panel_color(self) -> None:
        _controller, _gui, _con, _hwnd, make_icon = self._create()
        make_icon.assert_called_once_with(
            40,
            background_rgb=(0x5C, 0x8C, 0xD6),
            glyph_rgb=(0xFF, 0xFF, 0xFF),
            outdated=False,
        )

    def test_the_logo_starts_with_the_cache_derived_badge_state(self) -> None:
        # Same regression the tray icon pins in
        # test_tray_icon_created_with_initial_outdated_state: nothing else
        # corrects the first paint, so it must already reflect _outdated. A
        # literal outdated=False at the call site would still pass the
        # assertion above, because _make_controller pins the flag to False.
        _controller, _gui, _con, _hwnd, make_icon = self._create(outdated=True)
        make_icon.assert_called_once_with(
            40,
            background_rgb=(0x5C, 0x8C, 0xD6),
            glyph_rgb=(0xFF, 0xFF, 0xFF),
            outdated=True,
        )

    def test_a_status_line_grows_the_panel_and_keeps_its_top_left(self) -> None:
        controller, win32gui, con, hwnd, _icon = self._create()
        controller.set_status_text("Unknown shortcut")
        args = win32gui.SetWindowPos.call_args.args
        self.assertEqual(args[:2], (hwnd, 0))
        self.assertEqual(args[2:4], (640, 400))  # top-left from GetWindowRect
        self.assertEqual(
            args[4:6], (640, overlay_layout(status_visible=True).panel_height)
        )
        self.assertEqual(args[6], con.SWP_NOZORDER | con.SWP_NOACTIVATE)

    def test_clearing_the_status_shrinks_the_panel_again(self) -> None:
        controller, win32gui, _con, _hwnd, _icon = self._create()
        controller.set_status_text("Unknown shortcut")
        controller.set_status_text("")
        self.assertEqual(win32gui.SetWindowPos.call_args.args[5], 76)

    def test_completions_grow_the_panel_and_an_empty_list_shrinks_it(self) -> None:
        controller, win32gui, _con, _hwnd, _icon = self._create()
        controller.set_completion_rows([CompletionRow("gh", "GitHub", 0)])
        self.assertEqual(
            win32gui.SetWindowPos.call_args.args[5],
            overlay_layout(rows_visible=True).panel_height,
        )
        controller.set_completion_rows([])
        self.assertEqual(win32gui.SetWindowPos.call_args.args[5], 76)

    def test_relayout_repositions_every_child_and_repaints(self) -> None:
        controller, win32gui, _con, hwnd, _icon = self._create()
        win32gui.MoveWindow.reset_mock()
        win32gui.InvalidateRect.reset_mock()
        controller.set_status_text("x")
        layout = overlay_layout(status_visible=True)
        moved = [call.args[1:5] for call in win32gui.MoveWindow.call_args_list]
        self.assertEqual(moved, [layout.edit, layout.logo, layout.status, layout.rows])
        win32gui.InvalidateRect.assert_called_once_with(hwnd, None, True)

    def test_completion_labels_and_selection_reach_the_listbox(self) -> None:
        controller, win32gui, con, _hwnd, _icon = self._create()
        win32gui.SendMessage.reset_mock()
        controller.set_completion_rows(
            [CompletionRow("gh", "GitHub", 0), CompletionRow("c", "", 0)]
        )
        sent = [call.args[1:] for call in win32gui.SendMessage.call_args_list]
        self.assertIn((con.LB_RESETCONTENT, 0, 0), sent)
        self.assertIn((con.LB_ADDSTRING, 0, "gh  GitHub"), sent)
        self.assertIn((con.LB_ADDSTRING, 0, "c"), sent)
        self.assertIn((con.LB_SETCURSEL, 0, 0), sent)

    def test_the_logo_icon_can_be_swapped_and_the_old_one_is_destroyed(self) -> None:
        controller, win32gui, con, _hwnd, _created_icon = self._create()
        win32gui.SendMessage = MagicMock(return_value=555)  # previous icon
        with patch(
            "app.spotty_bunny_win32_app.make_spotty_bunny_icon_win32",
            return_value=999,
        ) as make_icon:
            controller.set_logo_outdated(True)
        self.assertEqual(make_icon.call_args.kwargs["outdated"], True)
        win32gui.SendMessage.assert_called_once_with(
            101 + 1, con.STM_SETIMAGE, con.IMAGE_ICON, 999
        )
        win32gui.DestroyIcon.assert_called_once_with(555)

    def test_the_controller_hooks_are_wired_to_the_real_controls(self) -> None:
        controller, win32gui, _con, _hwnd, _icon = self._create()
        controller.get_field_text()
        win32gui.GetWindowText.assert_called_once_with(101)
        controller.set_field_text("gh")
        win32gui.SetWindowText.assert_called_with(101, "gh")


@skipUnless(real_win32_available(), "needs Windows with pywin32 (the windows extra)")
class RealCreateOverlayWindowTests(SimpleTestCase):
    def test_the_real_overlay_builds_resizes_and_paints(self) -> None:
        # One test on purpose: it registers the overlay's window class, which
        # can only be registered once per process.
        import win32con  # pyright: ignore[reportMissingModuleSource]
        import win32gui  # pyright: ignore[reportMissingModuleSource]

        from app import spotty_bunny_win32_app as overlay_module

        controller = _make_controller()
        hwnd = _create_overlay_window(controller, win32gui=win32gui, win32con=win32con)

        def size() -> tuple[int, int]:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            return right - left, bottom - top

        try:
            self.assertEqual(size(), (640, 76))
            controller.set_status_text("Unknown shortcut")
            self.assertEqual(
                size(), (640, overlay_layout(status_visible=True).panel_height)
            )
            controller.set_completion_rows([CompletionRow("gh", "GitHub", 0)])
            self.assertEqual(
                size(),
                (
                    640,
                    overlay_layout(rows_visible=True, status_visible=True).panel_height,
                ),
            )
            controller.set_completion_rows([])
            controller.set_status_text("")
            self.assertEqual(size(), (640, 76))
            self.assertTrue(win32gui.FindWindowEx(hwnd, 0, "EDIT", None))

            # A real click on the real logo control reaches the overlay's
            # wndproc as STN_CLICKED and opens About. The logo is the first
            # STATIC child (created before the status line).
            logo = win32gui.FindWindowEx(hwnd, 0, "STATIC", None)
            self.assertTrue(logo)
            controller.show_about = MagicMock()
            controller.handle_completion_selected = MagicMock()
            win32gui.SendMessage(logo, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, 0)
            win32gui.SendMessage(logo, win32con.WM_LBUTTONUP, 0, 0)
            controller.show_about.assert_called_once_with()
            # A real right-click on the real logo reaches the wndproc as
            # WM_CONTEXTMENU. The real menu is modal, so record the request.
            menu_requests: list[object] = []
            original_menu = overlay_module._show_context_menu
            overlay_module._show_context_menu = lambda *a, **k: menu_requests.append(a)
            try:
                win32gui.SendMessage(
                    logo, win32con.WM_RBUTTONDOWN, win32con.MK_RBUTTON, 0
                )
                win32gui.SendMessage(logo, win32con.WM_RBUTTONUP, 0, 0)
            finally:
                overlay_module._show_context_menu = original_menu
            self.assertEqual(len(menu_requests), 1)
            # ... and the real menu it asks for actually appears (a popup menu
            # window, class #32768), then goes away when cancelled.
            import threading
            import time

            controller.hwnd = hwnd
            seen_menu: list[bool] = []
            finished = threading.Event()

            def watch_and_cancel() -> None:
                # The menu is modal, so this thread is the only way out. Wait
                # (bounded) for the popup to exist, then keep posting the
                # cancel until the modal call has returned: a late-starting
                # menu can never leave the test blocked.
                deadline = time.monotonic() + 10
                while not finished.is_set() and time.monotonic() < deadline:
                    if win32gui.FindWindow("#32768", None):
                        seen_menu.append(True)
                        break
                    time.sleep(0.02)
                while not finished.is_set():
                    win32gui.PostMessage(hwnd, win32con.WM_CANCELMODE, 0, 0)
                    time.sleep(0.2)

            watcher = threading.Thread(target=watch_and_cancel, daemon=True)
            watcher.start()
            try:
                overlay_module._show_context_menu(
                    controller, win32gui=win32gui, win32con=win32con
                )
            finally:
                finished.set()
                watcher.join(timeout=5)
            self.assertEqual(seen_menu, [True])
            # A double-click reports STN_DBLCLK (== LBN_SELCHANGE): it must
            # not be mistaken for a completion-list selection.
            controller.show_about.reset_mock()
            win32gui.SendMessage(
                logo, win32con.WM_LBUTTONDBLCLK, win32con.MK_LBUTTON, 0
            )
            controller.handle_completion_selected.assert_not_called()

            # pywin32 swallows exceptions raised inside a wndproc (it only
            # prints them), so record what the paint handler did instead.
            paint_calls: list[int] = []
            paint_errors: list[Exception] = []
            original = overlay_module._paint_overlay

            def recording_paint(*args, **kwargs) -> None:
                paint_calls.append(1)
                try:
                    original(*args, **kwargs)
                except Exception as exc:
                    paint_errors.append(exc)
                    raise

            with patch.object(overlay_module, "_paint_overlay", recording_paint):
                win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)
                win32gui.InvalidateRect(hwnd, None, True)
                win32gui.UpdateWindow(hwnd)
            self.assertTrue(paint_calls, "the overlay was never painted")
            self.assertEqual(paint_errors, [])

            controller.set_field_text("gh")
            self.assertEqual(controller.get_field_text(), "gh")
        finally:
            win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
            win32gui.DestroyWindow(hwnd)
            # Destroying the overlay runs its wndproc's WM_DESTROY handler,
            # which calls PostQuitMessage. Consume that WM_QUIT here, or it
            # stays in this thread's queue and a later test that peeks for its
            # own message (the real WM_TIMER test) receives it instead.
            win32gui.PumpWaitingMessages()


class TrayMessageTests(SimpleTestCase):
    def test_left_click_calls_show_about(self) -> None:
        controller = _make_controller()
        controller.show_about = MagicMock()
        win32gui = _make_fake_win32gui()
        _handle_tray_message(
            controller,
            _FakeWin32Con.WM_LBUTTONUP,
            win32gui=win32gui,
            win32con=_FakeWin32Con,
        )
        controller.show_about.assert_called_once()

    def test_right_click_shows_context_menu(self) -> None:
        controller = _make_controller()
        with patch("app.spotty_bunny_win32_app._show_context_menu") as show_menu:
            _handle_tray_message(
                controller,
                _FakeWin32Con.WM_RBUTTONUP,
                win32gui=_make_fake_win32gui(),
                win32con=_FakeWin32Con,
            )
        show_menu.assert_called_once()


class ShowContextMenuTests(SimpleTestCase):
    def test_selected_action_is_dispatched(self) -> None:
        controller = _make_controller()
        controller.hwnd = 42
        controller.dispatch_menu_action = MagicMock()
        win32gui = _make_fake_win32gui()
        win32gui.CreatePopupMenu = MagicMock(return_value=7)
        win32gui.GetCursorPos = MagicMock(return_value=(10, 20))
        # First appended item (index 0) is returned as "selected".
        win32gui.TrackPopupMenu = MagicMock(return_value=1000)
        with patch(
            "app.spotty_bunny_win32_app.logo_menu_specs",
            return_value=(("Quit", "quitSpottyBunny:"),),
        ):
            _show_context_menu(controller, win32gui=win32gui, win32con=_FakeWin32Con)
        controller.dispatch_menu_action.assert_called_once_with("quitSpottyBunny:")
        win32gui.DestroyMenu.assert_called_once_with(7)

    def test_dismissed_menu_dispatches_nothing(self) -> None:
        controller = _make_controller()
        controller.hwnd = 42
        controller.dispatch_menu_action = MagicMock()
        win32gui = _make_fake_win32gui()
        win32gui.CreatePopupMenu = MagicMock(return_value=7)
        win32gui.GetCursorPos = MagicMock(return_value=(10, 20))
        win32gui.TrackPopupMenu = MagicMock(return_value=0)
        with patch(
            "app.spotty_bunny_win32_app.logo_menu_specs",
            return_value=(("Quit", "quitSpottyBunny:"),),
        ):
            _show_context_menu(controller, win32gui=win32gui, win32con=_FakeWin32Con)
        controller.dispatch_menu_action.assert_not_called()

    def test_a_refused_foreground_call_does_not_stop_the_menu(self) -> None:
        # Same foreground-lock refusal as showing the overlay: it must not
        # abort the right-click menu.
        controller = _make_controller()
        controller.hwnd = 42
        controller.dispatch_menu_action = MagicMock()
        win32gui = _make_fake_win32gui()
        win32gui.error = _FakeGuiError
        win32gui.SetForegroundWindow = MagicMock(
            side_effect=_FakeGuiError(0, "SetForegroundWindow", "")
        )
        win32gui.CreatePopupMenu = MagicMock(return_value=7)
        win32gui.GetCursorPos = MagicMock(return_value=(10, 20))
        win32gui.TrackPopupMenu = MagicMock(return_value=1000)
        with patch(
            "app.spotty_bunny_win32_app.logo_menu_specs",
            return_value=(("Quit", "quitSpottyBunny:"),),
        ):
            _show_context_menu(controller, win32gui=win32gui, win32con=_FakeWin32Con)
        controller.dispatch_menu_action.assert_called_once_with("quitSpottyBunny:")


class _FakeGuiError(Exception):
    """Stand-in for ``win32gui.error`` (``pywintypes.error``)."""


def _make_focus_modules(
    *, foreground: int = 100, foreground_tid: int = 555, this_tid: int = 1
) -> tuple[MagicMock, MagicMock, MagicMock]:
    win32gui = _make_fake_win32gui()
    win32gui.error = _FakeGuiError
    win32gui.GetForegroundWindow = MagicMock(return_value=foreground)
    win32gui.GetWindowRect = MagicMock(return_value=(0, 0, 420, 204))
    win32api = MagicMock()
    win32api.GetCurrentThreadId = MagicMock(return_value=this_tid)
    win32api.MonitorFromPoint = MagicMock(return_value=77)
    win32api.GetMonitorInfo = MagicMock(return_value={"Work": (0, 0, 1920, 1040)})
    win32process = MagicMock()
    win32process.GetWindowThreadProcessId = MagicMock(
        return_value=(foreground_tid, 4242)
    )
    return win32gui, win32api, win32process


class OverlayOriginTests(SimpleTestCase):
    def test_centered_horizontally_and_45_percent_down_the_free_height(self) -> None:
        # Same math as macOS _center_panel: origin.y = visible.y + free * 0.55
        # measured from the bottom, i.e. the top edge is 45% of the free
        # height below the top of the work area.
        x, y = overlay_origin((0, 0, 1920, 1080), 640, 76)
        self.assertEqual(x, (1920 - 640) // 2)
        self.assertEqual(y, int((1080 - 76) * 0.45))

    def test_respects_a_work_area_that_does_not_start_at_the_origin(self) -> None:
        # A left-docked taskbar shifts the work area's left edge.
        x, y = overlay_origin((60, 30, 1980, 1110), 640, 76)
        self.assertEqual(x, 60 + (1920 - 640) // 2)
        self.assertEqual(y, 30 + int((1080 - 76) * 0.45))

    def test_an_overlay_larger_than_the_work_area_is_pinned_to_the_corner(self) -> None:
        self.assertEqual(overlay_origin((10, 20, 110, 220), 500, 500), (10, 20))

    def test_taller_overlays_sit_higher(self) -> None:
        compact = overlay_origin((0, 0, 1920, 1080), 640, 76)
        expanded = overlay_origin((0, 0, 1920, 1080), 640, 300)
        self.assertLess(expanded[1], compact[1])


class CenterOverlayTests(SimpleTestCase):
    def test_moves_the_window_to_the_computed_origin_keeping_its_size(self) -> None:
        win32gui, win32api, _ = _make_focus_modules()
        win32con = MagicMock()
        _center_overlay(10, win32api=win32api, win32con=win32con, win32gui=win32gui)
        x, y = overlay_origin((0, 0, 1920, 1040), 420, 204)
        win32gui.SetWindowPos.assert_called_once_with(
            10,
            win32con.HWND_TOPMOST,
            x,
            y,
            0,
            0,
            win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
        )

    def test_uses_the_primary_monitor(self) -> None:
        win32gui, win32api, _ = _make_focus_modules()
        win32con = MagicMock()
        _center_overlay(10, win32api=win32api, win32con=win32con, win32gui=win32gui)
        win32api.MonitorFromPoint.assert_called_once_with(
            (0, 0), win32con.MONITOR_DEFAULTTOPRIMARY
        )

    def test_a_monitor_query_failure_leaves_the_window_alone(self) -> None:
        win32gui, win32api, _ = _make_focus_modules()
        win32api.GetMonitorInfo = MagicMock(
            side_effect=_FakeGuiError(0, "GetMonitorInfo", "")
        )
        _center_overlay(10, win32api=win32api, win32con=MagicMock(), win32gui=win32gui)
        win32gui.SetWindowPos.assert_not_called()

    def test_a_window_geometry_failure_leaves_the_window_alone(self) -> None:
        # The other half of the fail-soft contract: GetWindowRect raises for a
        # stale/invalid hwnd. It must stay inside the guard, not escape into
        # the wndproc and keep the overlay from ever appearing.
        win32gui, win32api, _ = _make_focus_modules()
        win32gui.GetWindowRect = MagicMock(
            side_effect=_FakeGuiError(6, "GetWindowRect", "")
        )
        _center_overlay(10, win32api=win32api, win32con=MagicMock(), win32gui=win32gui)
        win32gui.SetWindowPos.assert_not_called()

    def test_a_failed_move_is_not_fatal(self) -> None:
        win32gui, win32api, _ = _make_focus_modules()
        win32gui.SetWindowPos = MagicMock(
            side_effect=_FakeGuiError(5, "SetWindowPos", "")
        )
        _center_overlay(10, win32api=win32api, win32con=MagicMock(), win32gui=win32gui)
        win32gui.SetWindowPos.assert_called_once()


class ShowOverlayWindowTests(SimpleTestCase):
    def test_centers_before_showing(self) -> None:
        win32gui, win32api, win32process = _make_focus_modules()
        order: list[str] = []
        win32gui.SetWindowPos = MagicMock(
            side_effect=lambda *_a: order.append("position")
        )
        win32gui.ShowWindow = MagicMock(side_effect=lambda *_a: order.append("show"))
        _show_overlay_window(
            10,
            20,
            win32api=win32api,
            win32con=MagicMock(),
            win32gui=win32gui,
            win32process=win32process,
        )
        self.assertEqual(order, ["position", "show"])

    def test_moves_the_overlay_not_its_text_box_to_the_centered_origin(self) -> None:
        # _show_overlay_window is handed the overlay and its Edit control; the
        # move must target the overlay (10), not the Edit (20), and use the
        # origin overlay_origin computes: (1920-420)//2 = 750 across, and
        # int((1040-204)*0.45) = 376 down the 1920x1040 work area.
        win32gui, win32api, win32process = _make_focus_modules()
        win32con = MagicMock()
        _show_overlay_window(
            10,
            20,
            win32api=win32api,
            win32con=win32con,
            win32gui=win32gui,
            win32process=win32process,
        )
        win32gui.SetWindowPos.assert_called_once_with(
            10,
            win32con.HWND_TOPMOST,
            750,
            376,
            0,
            0,
            win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
        )

    def _show(self, win32gui, win32api, win32process) -> None:
        _show_overlay_window(
            10,
            20,
            win32api=win32api,
            win32con=MagicMock(),
            win32gui=win32gui,
            win32process=win32process,
        )

    def test_refused_foreground_does_not_abort_showing(self) -> None:
        # Regression: SetForegroundWindow raises pywintypes.error (0, ...) when
        # Windows' foreground lock refuses a background process. That used to
        # propagate out of the wndproc, so the box never got keyboard focus.
        win32gui, win32api, win32process = _make_focus_modules()
        win32gui.SetForegroundWindow = MagicMock(
            side_effect=_FakeGuiError(0, "SetForegroundWindow", "")
        )
        self._show(win32gui, win32api, win32process)
        win32gui.ShowWindow.assert_called_once()
        win32gui.SetFocus.assert_called_once_with(20)

    def test_focus_failure_is_not_fatal(self) -> None:
        win32gui, win32api, win32process = _make_focus_modules()
        win32gui.SetFocus = MagicMock(side_effect=_FakeGuiError(5, "SetFocus", ""))
        self._show(win32gui, win32api, win32process)
        win32gui.SetForegroundWindow.assert_called_once_with(10)

    def test_attaches_to_the_foreground_thread_around_the_call(self) -> None:
        win32gui, win32api, win32process = _make_focus_modules()
        order: list[str] = []
        win32process.AttachThreadInput = MagicMock(
            side_effect=lambda _a, _b, attach: order.append(f"attach={attach}")
        )
        win32gui.SetForegroundWindow = MagicMock(
            side_effect=lambda _h: order.append("foreground")
        )
        self._show(win32gui, win32api, win32process)
        self.assertEqual(order, ["attach=True", "foreground", "attach=False"])
        win32process.AttachThreadInput.assert_any_call(1, 555, True)
        win32process.AttachThreadInput.assert_any_call(1, 555, False)

    def test_detaches_even_when_the_foreground_call_is_refused(self) -> None:
        win32gui, win32api, win32process = _make_focus_modules()
        win32gui.SetForegroundWindow = MagicMock(
            side_effect=_FakeGuiError(0, "SetForegroundWindow", "")
        )
        self._show(win32gui, win32api, win32process)
        win32process.AttachThreadInput.assert_called_with(1, 555, False)

    def test_no_attach_when_nothing_has_the_foreground(self) -> None:
        win32gui, win32api, win32process = _make_focus_modules(foreground=0)
        self._show(win32gui, win32api, win32process)
        win32process.AttachThreadInput.assert_not_called()
        win32gui.SetForegroundWindow.assert_called_once_with(10)

    def test_no_attach_when_the_foreground_is_this_thread(self) -> None:
        win32gui, win32api, win32process = _make_focus_modules(
            foreground_tid=1, this_tid=1
        )
        self._show(win32gui, win32api, win32process)
        win32process.AttachThreadInput.assert_not_called()

    def test_failed_attach_still_tries_the_foreground_call(self) -> None:
        win32gui, win32api, win32process = _make_focus_modules()
        win32process.AttachThreadInput = MagicMock(
            side_effect=_FakeGuiError(5, "AttachThreadInput", "")
        )
        win32gui.error = _FakeGuiError
        self._show(win32gui, win32api, win32process)
        win32gui.SetForegroundWindow.assert_called_once_with(10)
        win32gui.SetFocus.assert_called_once_with(20)

    def test_a_failed_detach_does_not_abort_showing(self) -> None:
        # The attach succeeds and only the detach (attach=False) raises: it
        # runs in a finally block, so an unguarded failure there would escape
        # _take_foreground and abort showing the overlay -- the #477 failure.
        win32gui, win32api, win32process = _make_focus_modules()

        def attach_thread_input(_this_thread, _foreground_thread, attach):
            if not attach:
                raise _FakeGuiError(5, "AttachThreadInput", "")

        win32process.AttachThreadInput = MagicMock(side_effect=attach_thread_input)
        self._show(win32gui, win32api, win32process)
        win32process.AttachThreadInput.assert_any_call(1, 555, True)
        win32process.AttachThreadInput.assert_any_call(1, 555, False)
        win32gui.SetForegroundWindow.assert_called_once_with(10)
        win32gui.SetFocus.assert_called_once_with(20)

    def test_a_foreground_window_that_vanishes_does_not_abort_showing(self) -> None:
        # The foreground window can close between GetForegroundWindow and the
        # thread lookup; pywin32 raises the same (0, ...) shape as a refusal.
        win32gui, win32api, win32process = _make_focus_modules()
        win32process.GetWindowThreadProcessId = MagicMock(
            side_effect=_FakeGuiError(0, "GetWindowThreadProcessId", "")
        )
        self._show(win32gui, win32api, win32process)
        win32process.AttachThreadInput.assert_not_called()
        win32gui.SetForegroundWindow.assert_called_once_with(10)
        win32gui.SetFocus.assert_called_once_with(20)

    def test_a_failing_foreground_window_query_does_not_abort_showing(self) -> None:
        win32gui, win32api, win32process = _make_focus_modules()
        win32gui.GetForegroundWindow = MagicMock(
            side_effect=_FakeGuiError(0, "GetForegroundWindow", "")
        )
        self._show(win32gui, win32api, win32process)
        win32process.AttachThreadInput.assert_not_called()
        win32gui.SetFocus.assert_called_once_with(20)


class OverlayWindowVisibilityTests(SimpleTestCase):
    """Drive the ``set_window_visible`` closure ``_create_overlay_window`` builds.

    ``_show_overlay_window`` is tested directly above; this pins the call site
    that actually fixes the report -- the right window/edit pair, and the
    guarded helper rather than the raw calls.
    """

    @contextmanager
    def _create(self):
        controller = _make_controller()
        win32gui, win32api, win32process = _make_focus_modules()
        handles = iter(range(100, 200))
        win32gui.CreateWindowEx = MagicMock(side_effect=lambda *_a: next(handles))
        win32gui.GetWindowRect = MagicMock(return_value=(0, 0, 640, 76))
        win32api.MonitorFromPoint = MagicMock(return_value=77)
        win32api.GetMonitorInfo = MagicMock(return_value={"Work": (0, 0, 1920, 1040)})
        win32con = MagicMock()
        with (
            patch(
                "app.spotty_bunny_win32_app.make_spotty_bunny_icon_win32",
                return_value=1,
            ),
            patch.dict(
                sys.modules,
                {"win32api": win32api, "win32process": win32process},
            ),
        ):
            _create_overlay_window(controller, win32gui=win32gui, win32con=win32con)
            yield controller, win32gui, win32con

    def test_showing_targets_the_overlay_and_its_text_box(self) -> None:
        with self._create() as (controller, win32gui, win32con):
            controller.set_window_visible(True)
            # 100 is the overlay window, 101 the Edit control created after it.
            win32gui.ShowWindow.assert_any_call(100, win32con.SW_SHOW)
            win32gui.SetForegroundWindow.assert_called_once_with(100)
            win32gui.SetFocus.assert_called_once_with(101)

    def test_showing_moves_the_overlay_window_to_the_centered_origin(self) -> None:
        with self._create() as (controller, win32gui, win32con):
            # Creation may position the window too; only the show is under test.
            win32gui.SetWindowPos.reset_mock()
            controller.set_window_visible(True)
            # 100 is the overlay (not its Edit, 101). Its (0,0,640,76) rect in
            # the 1920x1040 work area centers at x=640, y=int(964*0.45)=433.
            win32gui.SetWindowPos.assert_called_once_with(
                100,
                win32con.HWND_TOPMOST,
                640,
                433,
                0,
                0,
                win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
            )

    def test_a_refused_foreground_call_does_not_propagate_out_of_the_closure(
        self,
    ) -> None:
        with self._create() as (controller, win32gui, _con):
            win32gui.SetForegroundWindow = MagicMock(
                side_effect=_FakeGuiError(0, "SetForegroundWindow", "")
            )
            controller.set_window_visible(True)
            win32gui.SetFocus.assert_called_once_with(101)

    def test_hiding_hides_the_overlay(self) -> None:
        with self._create() as (controller, win32gui, win32con):
            controller.set_window_visible(False)
            win32gui.ShowWindow.assert_any_call(100, win32con.SW_HIDE)
            win32gui.SetForegroundWindow.assert_not_called()


@skipUnless(real_win32_available(), "needs Windows with pywin32 (the windows extra)")
class RealCenterOverlayTests(SimpleTestCase):
    def test_a_real_window_lands_centered_in_the_primary_work_area(self) -> None:
        import win32api  # pyright: ignore[reportMissingModuleSource]
        import win32con  # pyright: ignore[reportMissingModuleSource]
        import win32gui  # pyright: ignore[reportMissingModuleSource]

        hwnd = win32gui.CreateWindowEx(
            win32con.WS_EX_TOOLWINDOW,
            "STATIC",
            "t",
            win32con.WS_POPUP,
            0,
            0,
            300,
            80,
            0,
            0,
            0,
            None,
        )
        try:
            _center_overlay(
                hwnd, win32api=win32api, win32con=win32con, win32gui=win32gui
            )
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            monitor = win32api.MonitorFromPoint(
                (0, 0), win32con.MONITOR_DEFAULTTOPRIMARY
            )
            work = win32api.GetMonitorInfo(monitor)["Work"]
            self.assertEqual((left, top), overlay_origin(work, 300, 80))
            self.assertEqual((right - left, bottom - top), (300, 80))
            self.assertGreaterEqual(left, work[0])
            self.assertLessEqual(right, work[2])
            self.assertLessEqual(bottom, work[3])
        finally:
            win32gui.DestroyWindow(hwnd)


@skipUnless(real_win32_available(), "needs Windows with pywin32 (the windows extra)")
class RealShowOverlayWindowTests(SimpleTestCase):
    def test_showing_a_real_window_never_raises(self) -> None:
        # The foreground lock decides whether focus is granted, which depends
        # on the desktop; the contract is only that it never raises.
        import win32api  # pyright: ignore[reportMissingModuleSource]
        import win32con  # pyright: ignore[reportMissingModuleSource]
        import win32gui  # pyright: ignore[reportMissingModuleSource]
        import win32process  # pyright: ignore[reportMissingModuleSource]

        hwnd = win32gui.CreateWindowEx(
            0, "STATIC", "t", win32con.WS_POPUP, 0, 0, 10, 10, 0, 0, 0, None
        )
        edit = win32gui.CreateWindowEx(
            0,
            "EDIT",
            "",
            win32con.WS_CHILD | win32con.WS_VISIBLE,
            0,
            0,
            5,
            5,
            hwnd,
            0,
            0,
            None,
        )
        try:
            _show_overlay_window(
                hwnd,
                edit,
                win32api=win32api,
                win32con=win32con,
                win32gui=win32gui,
                win32process=win32process,
            )
        finally:
            win32gui.DestroyWindow(hwnd)


_REAL_HEALTH_WRITE = try_write_spotty_bunny_health


class RunSpottyBunnyWin32AppTests(SimpleTestCase):
    def test_tray_icon_created_with_initial_outdated_state(self) -> None:
        # Regression: the tray icon is created (icon_state = {"handle":
        # make_spotty_bunny_icon_win32(16, ...)}) before set_icon_outdated
        # is wired up to the controller, so unlike every later re-render,
        # nothing else will ever correct this first icon's badge state --
        # it must already reflect __init__'s cache-derived _outdated, or a
        # real launch shows "current" for up to a day even when the
        # on-disk cache already says otherwise.
        win32gui = _make_fake_win32gui()
        win32con = MagicMock()
        win32api = MagicMock()
        make_icon = MagicMock(return_value=99)
        with (
            patch.dict(
                sys.modules,
                {"win32gui": win32gui, "win32con": win32con, "win32api": win32api},
            ),
            patch(
                "app.spotty_bunny_win32_app.read_cached_update_status",
                return_value=MagicMock(),
            ),
            patch("app.spotty_bunny_win32_app.badge_should_show", return_value=True),
            patch(
                "app.spotty_bunny_win32_app._create_overlay_window", return_value=123
            ),
            patch(
                "app.spotty_bunny_win32_app.install_chord_hook",
                return_value=MagicMock(),
            ),
            patch(
                "app.spotty_bunny_win32_app.install_console_quit_handler",
                return_value=lambda: None,
            ),
            patch("app.spotty_bunny_win32_app.pump_hook_messages"),
            patch("app.spotty_bunny_win32_app.make_spotty_bunny_icon_win32", make_icon),
            patch("app.spotty_bunny_win32_app._set_window_timer"),
        ):
            run_spotty_bunny_win32_app()
        make_icon.assert_any_call(16, outdated=True)

    def test_refreshing_the_tray_icon_refreshes_the_overlay_logo_too(self) -> None:
        captured: list[SpottyBunnyWin32Controller] = []

        def fake_create(controller, **_kwargs):
            captured.append(controller)
            controller.set_logo_outdated = MagicMock()
            return 123

        with (
            patch.dict(
                sys.modules,
                {
                    "win32gui": _make_fake_win32gui(),
                    "win32con": MagicMock(),
                    "win32api": MagicMock(),
                },
            ),
            patch(
                "app.spotty_bunny_win32_app.read_cached_update_status",
                return_value=MagicMock(),
            ),
            patch("app.spotty_bunny_win32_app.badge_should_show", return_value=False),
            patch("app.spotty_bunny_win32_app._create_overlay_window", fake_create),
            patch(
                "app.spotty_bunny_win32_app.install_chord_hook",
                return_value=MagicMock(),
            ),
            patch(
                "app.spotty_bunny_win32_app.install_console_quit_handler",
                return_value=lambda: None,
            ),
            patch("app.spotty_bunny_win32_app.pump_hook_messages"),
            patch(
                "app.spotty_bunny_win32_app.make_spotty_bunny_icon_win32",
                MagicMock(return_value=99),
            ),
            patch("app.spotty_bunny_win32_app._set_window_timer"),
        ):
            run_spotty_bunny_win32_app()
            [controller] = captured
            controller.set_icon_outdated(True)
        controller.set_logo_outdated.assert_called_once_with(True)

    def _run_app(
        self,
        *,
        hook: object,
        health_write: MagicMock | None = None,
    ) -> None:
        """Run the app's startup with fakes, recording its health writes."""
        with (
            patch.dict(
                sys.modules,
                {
                    "win32gui": _make_fake_win32gui(),
                    "win32con": MagicMock(),
                    "win32api": MagicMock(),
                },
            ),
            patch(
                "app.spotty_bunny_win32_app.read_cached_update_status",
                return_value=MagicMock(),
            ),
            patch("app.spotty_bunny_win32_app.badge_should_show", return_value=False),
            patch(
                "app.spotty_bunny_win32_app._create_overlay_window", return_value=123
            ),
            patch("app.spotty_bunny_win32_app.install_chord_hook", **hook),  # type: ignore[arg-type]
            patch(
                "app.spotty_bunny_win32_app.install_console_quit_handler",
                return_value=lambda: None,
            ),
            patch("app.spotty_bunny_win32_app.pump_hook_messages"),
            patch(
                "app.spotty_bunny_win32_app.make_spotty_bunny_icon_win32",
                MagicMock(return_value=99),
            ),
            patch("app.spotty_bunny_win32_app._set_window_timer"),
            patch(
                "app.spotty_bunny_win32_app.try_write_spotty_bunny_health",
                health_write if health_write is not None else _REAL_HEALTH_WRITE,
            ),
        ):
            run_spotty_bunny_win32_app()

    def test_startup_records_this_processs_own_tap_health(self) -> None:
        # The health file otherwise keeps the previous run's "ok" until a
        # chord fires (#534).
        write = MagicMock()
        self._run_app(hook={"return_value": MagicMock()}, health_write=write)
        write.assert_called_once()
        self.assertEqual(write.call_args.kwargs["tap"], "ok")
        self.assertEqual(write.call_args.kwargs["reinstall_failures"], 0)

    def test_startup_builds_on_an_empty_snapshot_not_the_previous_runs(self) -> None:
        # A write keeps the prior last_chord/last_event unless told otherwise.
        write = MagicMock()
        self._run_app(hook={"return_value": MagicMock()}, health_write=write)
        previous = write.call_args.kwargs["previous"]
        self.assertIsNone(previous.last_chord_at)
        self.assertIsNone(previous.last_event_at)
        self.assertEqual(previous.reinstall_failures, 0)

    def test_the_real_startup_write_drops_a_dead_runs_chord_times(self) -> None:
        # End to end through the real writer and the (isolated) data dir: a
        # snapshot left by a previous process must not survive into this one.
        from app.spotty_bunny_tap_health import (
            TAP_STATE_OK,
            read_spotty_bunny_health,
            write_spotty_bunny_health,
        )

        write_spotty_bunny_health(
            tap=TAP_STATE_OK,
            last_chord_at=1_700_000_000.0,
            last_event_at=1_700_000_001.0,
            reinstall_failures=3,
            previous=None,
        )
        self._run_app(hook={"return_value": MagicMock()})
        health = read_spotty_bunny_health()
        assert health is not None
        self.assertEqual(health.tap, TAP_STATE_OK)
        self.assertIsNone(health.last_chord_at)
        self.assertIsNone(health.last_event_at)
        self.assertEqual(health.reinstall_failures, 0)

    def test_a_refused_hook_records_no_health(self) -> None:
        # The process exits right after this, and its atexit cleanup removes
        # the health file, so a "missing" snapshot could never be read; the
        # error and console hint are the report.
        from app.spotty_bunny_cli import SpottyBunnyHookError

        write = MagicMock()
        with self.assertRaises(SpottyBunnyHookError):
            self._run_app(
                hook={"side_effect": OSError("hook refused")}, health_write=write
            )
        write.assert_not_called()

    def test_timers_start_through_user32_not_win32gui(self) -> None:
        # Regression: pywin32 312 has no win32gui.SetTimer, so startup died
        # with AttributeError. A MagicMock win32gui accepts any attribute and
        # hid that, hence the explicit assert_not_called.
        win32gui = _make_fake_win32gui()
        set_timer = MagicMock()
        with (
            patch.dict(
                sys.modules,
                {
                    "win32gui": win32gui,
                    "win32con": MagicMock(),
                    "win32api": MagicMock(),
                },
            ),
            patch(
                "app.spotty_bunny_win32_app.read_cached_update_status",
                return_value=MagicMock(),
            ),
            patch("app.spotty_bunny_win32_app.badge_should_show", return_value=False),
            patch(
                "app.spotty_bunny_win32_app._create_overlay_window", return_value=123
            ),
            patch(
                "app.spotty_bunny_win32_app.install_chord_hook",
                return_value=MagicMock(),
            ),
            patch(
                "app.spotty_bunny_win32_app.install_console_quit_handler",
                return_value=lambda: None,
            ),
            patch("app.spotty_bunny_win32_app.pump_hook_messages"),
            patch(
                "app.spotty_bunny_win32_app.make_spotty_bunny_icon_win32",
                MagicMock(return_value=99),
            ),
            patch("app.spotty_bunny_win32_app._set_window_timer", set_timer),
        ):
            run_spotty_bunny_win32_app()
        win32gui.SetTimer.assert_not_called()
        set_timer.assert_any_call(
            123, TIMER_ID_HEALTH, int(TAP_HEALTH_CHECK_INTERVAL_S * 1000)
        )
        set_timer.assert_any_call(123, TIMER_ID_UPDATE, UPDATE_CHECK_INTERVAL_MS)


@skipUnless(real_win32_available(), "needs Windows with pywin32 (the windows extra)")
class SetWindowTimerTests(SimpleTestCase):
    def test_a_real_wm_timer_arrives(self) -> None:
        import win32con  # pyright: ignore[reportMissingModuleSource]
        import win32gui  # pyright: ignore[reportMissingModuleSource]

        hwnd = win32gui.CreateWindowEx(
            0, "STATIC", "t", win32con.WS_POPUP, 0, 0, 1, 1, 0, 0, 0, None
        )
        try:
            _set_window_timer(hwnd, 7, 30)
            deadline = time.monotonic() + 3.0
            delivered = None
            while time.monotonic() < deadline and delivered is None:
                # pywin32 returns [found, (hwnd, message, wparam, lparam, ...)];
                # with an empty queue that is [0, (0, 0, 0, 0, 0, (0, 0))].
                found, message = win32gui.PeekMessage(
                    hwnd, win32con.WM_TIMER, win32con.WM_TIMER, win32con.PM_REMOVE
                )
                if found:
                    delivered = message
                else:
                    time.sleep(0.01)
            assert delivered is not None, "no WM_TIMER within 3s"
            # The dispatch in the wndproc keys on wparam, so pin the timer id
            # too, not just that some message arrived.
            self.assertEqual(delivered[1], win32con.WM_TIMER)
            self.assertEqual(delivered[2], 7)
        finally:
            # Destroying the window also kills its timers (win32gui has no
            # KillTimer in pywin32 312 either).
            win32gui.DestroyWindow(hwnd)

    def test_an_invalid_window_raises_os_error(self) -> None:
        with self.assertRaises(OSError) as caught:
            _set_window_timer(0xDEAD, 7, 30)
        # Pin the code, not just the type: without use_last_error the saved
        # error is 0 and WinError(0) would still raise, but as "[WinError 0]
        # The operation completed successfully".
        self.assertEqual(caught.exception.winerror, 1400)  # ERROR_INVALID_WINDOW_HANDLE


class SetWindowTimerWiringTests(SimpleTestCase):
    """The ctypes wiring, on any platform, against a fake ``user32``."""

    @staticmethod
    def _user32(*, result: int) -> MagicMock:
        user32 = MagicMock()
        user32.SetTimer = MagicMock(return_value=result)
        return user32

    def test_calls_user32_settimer_with_a_null_callback(self) -> None:
        user32 = self._user32(result=7)
        with patch("ctypes.WinDLL", return_value=user32, create=True) as win_dll:
            _set_window_timer(123, 7, 30)
        user32.SetTimer.assert_called_once_with(123, 7, 30, None)
        win_dll.assert_called_once_with("user32", use_last_error=True)

    def test_declares_pointer_sized_argument_and_result_types(self) -> None:
        # A 64-bit HWND/UINT_PTR must not be truncated to a C int.
        user32 = self._user32(result=7)
        with patch("ctypes.WinDLL", return_value=user32, create=True):
            _set_window_timer(123, 7, 30)
        self.assertEqual(user32.SetTimer.restype, ctypes.c_size_t)
        self.assertEqual(len(user32.SetTimer.argtypes), 4)
        self.assertEqual(user32.SetTimer.argtypes[1], ctypes.c_size_t)

    def test_a_refusal_raises_winerror_with_the_saved_last_error(self) -> None:
        user32 = self._user32(result=0)
        with (
            patch("ctypes.WinDLL", return_value=user32, create=True),
            patch("ctypes.get_last_error", return_value=1400, create=True),
            patch(
                "ctypes.WinError",
                return_value=OSError(1400, "Invalid window handle."),
                create=True,
            ) as win_error,
            self.assertRaises(OSError),
        ):
            _set_window_timer(123, 7, 30)
        win_error.assert_called_once_with(1400)

    def test_success_never_builds_an_error(self) -> None:
        user32 = self._user32(result=7)
        with (
            patch("ctypes.WinDLL", return_value=user32, create=True),
            patch("ctypes.WinError", create=True) as win_error,
        ):
            _set_window_timer(123, 7, 30)
        win_error.assert_not_called()

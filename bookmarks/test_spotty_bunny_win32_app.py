from __future__ import annotations

import ctypes
import sys
import time
from unittest import skipUnless
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from app.spotty_bunny_complete import CompletionRow
from app.spotty_bunny_io import ImmediateIo
from app.spotty_bunny_menu import CHECK_FOR_UPDATES_STATUS, logo_menu_specs
from app.spotty_bunny_status import SHORTCUTS_LOAD_FAILED
from app.spotty_bunny_tap_health import TAP_HEALTH_CHECK_INTERVAL_S
from app.spotty_bunny_update import UpdateStatus
from app.spotty_bunny_win32_app import (
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
    _handle_tray_message,
    _make_overlay_wndproc,
    _register_overlay_class,
    _selector_for_vk,
    _set_window_timer,
    _show_context_menu,
    _show_overlay_window,
    run_spotty_bunny_win32_app,
)


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
    MF_STRING = 0x0000
    TPM_LEFTALIGN = 0x0000
    TPM_RETURNCMD = 0x0100
    COLOR_WINDOW = 5


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
    win32api = MagicMock()
    win32api.GetCurrentThreadId = MagicMock(return_value=this_tid)
    win32process = MagicMock()
    win32process.GetWindowThreadProcessId = MagicMock(
        return_value=(foreground_tid, 4242)
    )
    return win32gui, win32api, win32process


class ShowOverlayWindowTests(SimpleTestCase):
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


@skipUnless(sys.platform == "win32", "needs the real user32")
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


@skipUnless(sys.platform == "win32", "needs the real user32")
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

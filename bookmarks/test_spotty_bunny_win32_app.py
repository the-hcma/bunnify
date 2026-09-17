from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from app.spotty_bunny_complete import CompletionRow
from app.spotty_bunny_io import ImmediateIo
from app.spotty_bunny_menu import logo_menu_specs
from app.spotty_bunny_win32_app import (
    VK_DOWN,
    VK_ESCAPE,
    VK_PRIOR,
    VK_RETURN,
    VK_TAB,
    VK_UP,
    WM_APP_COMPLETIONS_READY,
    WM_APP_RESOLVE_READY,
    WM_APP_TOGGLE,
    SpottyBunnyWin32Controller,
    _selector_for_vk,
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

    def test_uninstall_always_quits_regardless_of_exit_code(self) -> None:
        controller = _make_controller()
        controller.request_quit = MagicMock()
        with patch("app.spotty_bunny_agent_win32.uninstall_agent", return_value=1):
            controller.dispatch_menu_action("uninstallSpottyBunny:")
        controller.request_quit.assert_called_once()


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


class HandleEditKeydownTests(SimpleTestCase):
    def test_return_submits_query(self) -> None:
        controller = _make_controller()
        controller.set_field_text("gh")
        submitted: list[str] = []
        controller._io = ImmediateIo()

        def fake_lookup(query: str, **_kwargs: object) -> str:
            submitted.append(query)
            return "https://github.com"

        with (
            patch(
                "app.spotty_bunny_win32_app.lookup_resolved_url",
                side_effect=fake_lookup,
            ),
            patch("app.spotty_bunny_win32_app.resolve_base_url", return_value="u"),
        ):
            controller._open_url_fn = MagicMock()
            controller._append_history_fn = MagicMock()
            handled = controller.handle_edit_keydown(VK_RETURN)
        self.assertTrue(handled)
        self.assertEqual(submitted, ["gh"])

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

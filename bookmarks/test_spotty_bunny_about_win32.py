from __future__ import annotations

import ctypes
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from app.spotty_bunny_about_info import (
    AboutRuntimeInfo,
    about_details_text_and_links,
    about_version_text_and_links,
)
from app.spotty_bunny_about_win32 import (
    _NM_CLICK,
    _NM_RETURN,
    _NMLINK,
    _anchor_near_cursor,
    _handle_link_click,
    _make_about_wndproc,
    _url_from_notify,
    to_syslink_markup,
)


def _about_runtime(**overrides: object) -> AboutRuntimeInfo:
    defaults: dict[str, object] = {
        "bookmarks_display": "~/.config/bunnify/bookmarks.json",
        "bookmarks_uri": "file:///Users/me/.config/bunnify/bookmarks.json",
        "github_display": "github.com/acme/repo",
        "github_url": "https://github.com/acme/repo",
        "local_build_label": "0.10.0 (abc123456789)",
        "self_stale": False,
        "server_agent_installed": False,
        "server_build_label": "0.10.0 (abc123456789)",
        "server_display": "Local server · http://127.0.0.1:8000",
        "server_mode": "local",
        "server_skewed": False,
        "server_url": "http://127.0.0.1:8000",
    }
    defaults.update(overrides)
    return AboutRuntimeInfo(**defaults)  # type: ignore[arg-type]


class ToSyslinkMarkupTests(SimpleTestCase):
    def test_wraps_version_and_commit_link_spans(self) -> None:
        text, links = about_version_text_and_links("1.2.3", "abcdef1")
        markup = to_syslink_markup(text, links)
        self.assertIn(
            '<A HREF="https://pypi.org/project/bunnify/1.2.3/">1.2.3</A>', markup
        )
        self.assertIn(
            '<A HREF="https://github.com/the-hcma/bunnify/commit/abcdef1">abcdef1</A>',
            markup,
        )

    def test_wraps_every_link_span_in_the_details_block(self) -> None:
        text, links = about_details_text_and_links(_about_runtime())
        markup = to_syslink_markup(text, links)
        for link_text, url in links:
            self.assertIn(f'<A HREF="{url}">{link_text}</A>', markup)

    def test_escapes_ampersand_in_plain_text(self) -> None:
        markup = to_syslink_markup("a & b", ())
        self.assertIn("a &amp; b", markup)
        self.assertNotIn("a & b", markup)

    def test_escapes_special_characters_inside_link_text(self) -> None:
        markup = to_syslink_markup("<link>", (("<link>", "https://example.com"),))
        self.assertIn("&lt;link&gt;", markup)
        self.assertNotIn("<link>", markup)

    def test_no_links_returns_fully_escaped_text(self) -> None:
        self.assertEqual(to_syslink_markup("plain text", ()), "plain text")


class UrlFromNotifyTests(SimpleTestCase):
    def test_extracts_url_on_nm_click(self) -> None:
        link = _NMLINK()
        link.hdr.code = _NM_CLICK
        link.item.szUrl = "https://example.com"
        self.assertEqual(
            _url_from_notify(ctypes.addressof(link)), "https://example.com"
        )

    def test_extracts_url_on_nm_return(self) -> None:
        link = _NMLINK()
        link.hdr.code = _NM_RETURN
        link.item.szUrl = "https://example.com"
        self.assertEqual(
            _url_from_notify(ctypes.addressof(link)), "https://example.com"
        )

    def test_none_for_an_unrelated_notification_code(self) -> None:
        link = _NMLINK()
        link.hdr.code = 12345
        link.item.szUrl = "https://example.com"
        self.assertIsNone(_url_from_notify(ctypes.addressof(link)))


class HandleLinkClickTests(SimpleTestCase):
    def test_local_file_is_opened_via_handle_about_link_click(self) -> None:
        opener = MagicMock()
        with patch(
            "app.spotty_bunny_about_win32.handle_about_link_click", return_value=True
        ) as handler:
            _handle_link_click("file:///C:/a.txt", opener=opener)
        handler.assert_called_once_with("file:///C:/a.txt", start_file=opener)
        opener.assert_not_called()

    def test_non_file_link_is_opened_directly(self) -> None:
        opener = MagicMock()
        with patch(
            "app.spotty_bunny_about_win32.handle_about_link_click", return_value=False
        ):
            _handle_link_click("https://example.com", opener=opener)
        opener.assert_called_once_with("https://example.com")

    def test_oserror_from_opener_is_caught_and_logged(self) -> None:
        opener = MagicMock(side_effect=OSError("no handler"))
        with patch(
            "app.spotty_bunny_about_win32.handle_about_link_click", return_value=False
        ):
            with self.assertLogs("app.spotty_bunny_about_win32", level="WARNING"):
                _handle_link_click("https://example.com", opener=opener)


class AnchorNearCursorTests(SimpleTestCase):
    def test_clamps_near_the_bottom_right_corner(self) -> None:
        win32api = MagicMock()
        win32api.GetCursorPos.return_value = (1900, 1050)
        win32api.GetSystemMetrics.side_effect = lambda index: {0: 1920, 1: 1080}[index]
        left, top = _anchor_near_cursor(440, 300, win32api=win32api)
        self.assertEqual((left, top), (1920 - 440, 1080 - 300))

    def test_never_goes_negative_near_the_top_left_corner(self) -> None:
        win32api = MagicMock()
        win32api.GetCursorPos.return_value = (-5, -5)
        win32api.GetSystemMetrics.side_effect = lambda index: {0: 1920, 1: 1080}[index]
        left, top = _anchor_near_cursor(440, 300, win32api=win32api)
        self.assertEqual((left, top), (0, 0))

    def test_uses_the_cursor_position_when_it_fits_on_screen(self) -> None:
        win32api = MagicMock()
        win32api.GetCursorPos.return_value = (500, 400)
        win32api.GetSystemMetrics.side_effect = lambda index: {0: 1920, 1: 1080}[index]
        left, top = _anchor_near_cursor(440, 300, win32api=win32api)
        self.assertEqual((left, top), (500, 400))


class AboutWndProcTests(SimpleTestCase):
    def _fake_win32con(self) -> MagicMock:
        con = MagicMock()
        con.WM_NOTIFY = 0x004E
        con.WM_KEYDOWN = 0x0100
        con.VK_ESCAPE = 0x1B
        con.WM_ACTIVATE = 0x0006
        con.WA_INACTIVE = 0
        return con

    def test_wm_notify_link_click_dispatches_to_handle_link_click(self) -> None:
        win32con = self._fake_win32con()
        win32gui = MagicMock()
        wndproc = _make_about_wndproc(win32gui=win32gui, win32con=win32con)
        link = _NMLINK()
        link.hdr.code = _NM_CLICK
        link.item.szUrl = "https://example.com"
        with patch("app.spotty_bunny_about_win32._handle_link_click") as handle:
            result = wndproc(123, win32con.WM_NOTIFY, 0, ctypes.addressof(link))
        handle.assert_called_once_with("https://example.com")
        self.assertEqual(result, 0)

    def test_wm_notify_for_unrelated_code_does_not_dispatch(self) -> None:
        win32con = self._fake_win32con()
        win32gui = MagicMock()
        wndproc = _make_about_wndproc(win32gui=win32gui, win32con=win32con)
        link = _NMLINK()
        link.hdr.code = 999
        with patch("app.spotty_bunny_about_win32._handle_link_click") as handle:
            wndproc(123, win32con.WM_NOTIFY, 0, ctypes.addressof(link))
        handle.assert_not_called()

    def test_escape_hides_the_current_controllers_about_window(self) -> None:
        controller = MagicMock()
        win32con = self._fake_win32con()
        win32gui = MagicMock()
        wndproc = _make_about_wndproc(win32gui=win32gui, win32con=win32con)
        with patch(
            "app.spotty_bunny_about_win32._about_wndproc_controller", controller
        ):
            result = wndproc(123, win32con.WM_KEYDOWN, win32con.VK_ESCAPE, 0)
        controller.hide_about.assert_called_once()
        self.assertEqual(result, 0)

    def test_escape_is_a_no_op_when_no_controller_is_registered(self) -> None:
        win32con = self._fake_win32con()
        win32gui = MagicMock()
        wndproc = _make_about_wndproc(win32gui=win32gui, win32con=win32con)
        with patch("app.spotty_bunny_about_win32._about_wndproc_controller", None):
            result = wndproc(123, win32con.WM_KEYDOWN, win32con.VK_ESCAPE, 0)
        self.assertEqual(result, 0)

    def test_other_keydown_is_not_handled(self) -> None:
        controller = MagicMock()
        win32con = self._fake_win32con()
        win32gui = MagicMock()
        win32gui.DefWindowProc.return_value = 7
        wndproc = _make_about_wndproc(win32gui=win32gui, win32con=win32con)
        with patch(
            "app.spotty_bunny_about_win32._about_wndproc_controller", controller
        ):
            result = wndproc(123, win32con.WM_KEYDOWN, 0x41, 0)  # 'A'
        controller.hide_about.assert_not_called()
        self.assertEqual(result, 7)

    def test_deactivate_hides_the_current_controllers_about_window(self) -> None:
        controller = MagicMock()
        win32con = self._fake_win32con()
        win32gui = MagicMock()
        wndproc = _make_about_wndproc(win32gui=win32gui, win32con=win32con)
        with patch(
            "app.spotty_bunny_about_win32._about_wndproc_controller", controller
        ):
            result = wndproc(123, win32con.WM_ACTIVATE, win32con.WA_INACTIVE, 0)
        controller.hide_about.assert_called_once()
        self.assertEqual(result, 0)

    def test_unhandled_message_delegates_to_def_window_proc(self) -> None:
        win32con = self._fake_win32con()
        win32gui = MagicMock()
        win32gui.DefWindowProc.return_value = 42
        wndproc = _make_about_wndproc(win32gui=win32gui, win32con=win32con)
        result = wndproc(123, 0x9999, 0, 0)
        self.assertEqual(result, 42)


class RegisterAboutClassTests(SimpleTestCase):
    """The wndproc dispatch target follows the *latest* registering
    controller, rather than being pinned to whichever controller first
    triggered class registration (the process-global memo bug)."""

    def setUp(self) -> None:
        import app.spotty_bunny_about_win32 as about_win32

        self._about_win32 = about_win32
        self._previous_registered = about_win32._about_class_registered
        self._previous_controller = about_win32._about_wndproc_controller
        about_win32._about_class_registered = False
        about_win32._about_wndproc_controller = None

    def tearDown(self) -> None:
        self._about_win32._about_class_registered = self._previous_registered
        self._about_win32._about_wndproc_controller = self._previous_controller

    def test_registers_only_once_across_two_controllers(self) -> None:
        from app.spotty_bunny_about_win32 import _register_about_class

        win32con = MagicMock()
        win32gui = MagicMock()
        first = MagicMock()
        second = MagicMock()

        _register_about_class(first, win32gui=win32gui, win32con=win32con)
        _register_about_class(second, win32gui=win32gui, win32con=win32con)

        win32gui.RegisterClass.assert_called_once()

    def test_wndproc_dispatches_to_the_most_recently_registered_controller(
        self,
    ) -> None:
        from app.spotty_bunny_about_win32 import _register_about_class

        win32con = MagicMock()
        win32con.WM_KEYDOWN = 0x0100
        win32con.VK_ESCAPE = 0x1B
        win32gui = MagicMock()
        first = MagicMock()
        second = MagicMock()

        _register_about_class(first, win32gui=win32gui, win32con=win32con)
        wndproc = win32gui.WNDCLASS.return_value.lpfnWndProc
        _register_about_class(second, win32gui=win32gui, win32con=win32con)

        wndproc(123, win32con.WM_KEYDOWN, win32con.VK_ESCAPE, 0)
        first.hide_about.assert_not_called()
        second.hide_about.assert_called_once()


class BuildAboutWindowTests(SimpleTestCase):
    """Exercises the shipped window-creation function directly, with
    every win32* module injected as a mock -- no real Windows needed."""

    def setUp(self) -> None:
        import app.spotty_bunny_about_win32 as about_win32

        self._about_win32 = about_win32
        self._previous_registered = about_win32._about_class_registered
        self._previous_controller = about_win32._about_wndproc_controller
        about_win32._about_class_registered = False
        about_win32._about_wndproc_controller = None

    def tearDown(self) -> None:
        self._about_win32._about_class_registered = self._previous_registered
        self._about_win32._about_wndproc_controller = self._previous_controller

    def _fake_win32(
        self,
    ) -> tuple[MagicMock, MagicMock, MagicMock, list[dict[str, object]]]:
        win32con = MagicMock()
        win32con.WM_SETFONT = 0x30
        win32con.FW_BOLD = 700

        created: list[dict[str, object]] = []

        def create_window_ex(
            _ex_style,
            class_name,
            text,
            _style,
            x,
            y,
            width,
            height,
            *_rest,
        ):
            created.append(
                {
                    "class_name": class_name,
                    "text": text,
                    "x": x,
                    "y": y,
                    "width": width,
                    "height": height,
                }
            )
            return len(created)

        win32gui = MagicMock()
        win32gui.CreateWindowEx.side_effect = create_window_ex
        win32gui.GetModuleHandle.return_value = 1

        win32api = MagicMock()
        win32api.GetCursorPos.return_value = (100, 200)
        win32api.GetSystemMetrics.side_effect = lambda index: {0: 1920, 1: 1080}[index]

        return win32gui, win32con, win32api, created

    def _build(
        self, win32gui: MagicMock, win32con: MagicMock, win32api: MagicMock
    ) -> int:
        from app.spotty_bunny_about_win32 import build_about_window
        from app.spotty_bunny_update import UpdateStatus

        with (
            patch("app.spotty_bunny_about_win32._init_syslink_class"),
            patch(
                "app.spotty_bunny_about_win32.load_about_runtime_info",
                return_value=_about_runtime(),
            ),
            patch(
                "app.spotty_bunny_about_win32.read_cached_update_status",
                return_value=UpdateStatus(
                    checked_at=0.0, current="1.0.0", latest=None, outdated=False
                ),
            ),
            patch(
                "app.spotty_bunny_about_win32.get_build_info",
                return_value=("1.2.3", "abc1234"),
            ),
        ):
            return build_about_window(
                MagicMock(), win32gui=win32gui, win32con=win32con, win32api=win32api
            )

    def test_creates_the_top_level_window_and_every_child_row(self) -> None:
        win32gui, win32con, win32api, created = self._fake_win32()
        self._build(win32gui, win32con, win32api)

        # Top-level popup first, then title/summary/version/copyright/details.
        self.assertEqual(len(created), 6)
        self.assertEqual(created[1]["class_name"], "STATIC")
        self.assertEqual(created[1]["text"], "Spotty Bunny")
        self.assertEqual(created[2]["class_name"], "STATIC")
        self.assertEqual(created[3]["class_name"], "SysLink")
        self.assertEqual(created[4]["class_name"], "SysLink")
        self.assertEqual(created[5]["class_name"], "SysLink")

    def test_details_syslink_uses_to_syslink_markup_of_the_real_content(
        self,
    ) -> None:
        from app.spotty_bunny_about_info import about_details_text_and_links
        from app.spotty_bunny_about_win32 import to_syslink_markup

        win32gui, win32con, win32api, created = self._fake_win32()
        self._build(win32gui, win32con, win32api)

        details_text, details_links = about_details_text_and_links(_about_runtime())
        self.assertEqual(
            created[5]["text"], to_syslink_markup(details_text, details_links)
        )

    def test_version_syslink_uses_to_syslink_markup_of_the_real_content(self) -> None:
        from app.spotty_bunny_about_win32 import to_syslink_markup

        win32gui, win32con, win32api, created = self._fake_win32()
        self._build(win32gui, win32con, win32api)

        text, links = about_version_text_and_links("1.2.3", "abc1234")
        self.assertEqual(created[3]["text"], to_syslink_markup(text, links))

    def test_row_heights_match_between_the_window_and_its_children(self) -> None:
        win32gui, win32con, win32api, created = self._fake_win32()
        self._build(win32gui, win32con, win32api)

        window_height = created[0]["height"]
        child_span = sum(row["height"] for row in created[1:]) + 6 * (len(created) - 2)
        self.assertEqual(window_height, 12 * 2 + child_span)

    def test_window_is_positioned_at_the_anchor_near_cursor_result(self) -> None:
        win32gui, win32con, win32api, created = self._fake_win32()
        self._build(win32gui, win32con, win32api)

        self.assertEqual((created[0]["x"], created[0]["y"]), (100, 200))

    def test_adds_an_update_row_when_outdated(self) -> None:
        from app.spotty_bunny_about_win32 import build_about_window
        from app.spotty_bunny_update import UpdateStatus

        win32gui, win32con, win32api, created = self._fake_win32()
        with (
            patch("app.spotty_bunny_about_win32._init_syslink_class"),
            patch(
                "app.spotty_bunny_about_win32.load_about_runtime_info",
                return_value=_about_runtime(),
            ),
            patch(
                "app.spotty_bunny_about_win32.read_cached_update_status",
                return_value=UpdateStatus(
                    checked_at=0.0, current="1.0.0", latest="2.0.0", outdated=True
                ),
            ),
            patch(
                "app.spotty_bunny_about_win32.get_build_info",
                return_value=("1.2.3", "abc1234"),
            ),
        ):
            build_about_window(
                MagicMock(), win32gui=win32gui, win32con=win32con, win32api=win32api
            )

        self.assertEqual(len(created), 7)
        self.assertEqual(created[6]["text"], "Update available: 2.0.0")

    def test_class_registration_is_memoized_across_two_calls(self) -> None:
        win32gui, win32con, win32api, _created = self._fake_win32()
        self._build(win32gui, win32con, win32api)
        win32gui2, win32con2, win32api2, _created2 = self._fake_win32()
        self._build(win32gui2, win32con2, win32api2)

        win32gui.RegisterClass.assert_called_once()
        win32gui2.RegisterClass.assert_not_called()

    def test_calls_init_syslink_class(self) -> None:
        from app.spotty_bunny_about_win32 import build_about_window
        from app.spotty_bunny_update import UpdateStatus

        win32gui, win32con, win32api, _created = self._fake_win32()
        with (
            patch("app.spotty_bunny_about_win32._init_syslink_class") as init,
            patch(
                "app.spotty_bunny_about_win32.load_about_runtime_info",
                return_value=_about_runtime(),
            ),
            patch(
                "app.spotty_bunny_about_win32.read_cached_update_status",
                return_value=UpdateStatus(
                    checked_at=0.0, current="1.0.0", latest=None, outdated=False
                ),
            ),
            patch(
                "app.spotty_bunny_about_win32.get_build_info",
                return_value=("1.2.3", "abc1234"),
            ),
        ):
            build_about_window(
                MagicMock(), win32gui=win32gui, win32con=win32con, win32api=win32api
            )
        init.assert_called_once()


class InitSyslinkClassTests(SimpleTestCase):
    def test_requests_the_link_common_control_class(self) -> None:
        from app.spotty_bunny_about_win32 import _ICC_LINK_CLASS, _init_syslink_class

        windll = MagicMock()
        with patch("ctypes.windll", windll, create=True):
            _init_syslink_class()

        windll.comctl32.InitCommonControlsEx.assert_called_once()
        (icc_ptr,) = windll.comctl32.InitCommonControlsEx.call_args.args
        icc = icc_ptr._obj
        self.assertEqual(icc.dwICC, _ICC_LINK_CLASS)

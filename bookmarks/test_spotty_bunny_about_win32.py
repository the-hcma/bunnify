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
        controller = MagicMock()
        win32con = self._fake_win32con()
        win32gui = MagicMock()
        wndproc = _make_about_wndproc(controller, win32gui=win32gui, win32con=win32con)
        link = _NMLINK()
        link.hdr.code = _NM_CLICK
        link.item.szUrl = "https://example.com"
        with patch("app.spotty_bunny_about_win32._handle_link_click") as handle:
            result = wndproc(123, win32con.WM_NOTIFY, 0, ctypes.addressof(link))
        handle.assert_called_once_with("https://example.com")
        self.assertEqual(result, 0)

    def test_wm_notify_for_unrelated_code_does_not_dispatch(self) -> None:
        controller = MagicMock()
        win32con = self._fake_win32con()
        win32gui = MagicMock()
        wndproc = _make_about_wndproc(controller, win32gui=win32gui, win32con=win32con)
        link = _NMLINK()
        link.hdr.code = 999
        with patch("app.spotty_bunny_about_win32._handle_link_click") as handle:
            wndproc(123, win32con.WM_NOTIFY, 0, ctypes.addressof(link))
        handle.assert_not_called()

    def test_escape_hides_the_about_window(self) -> None:
        controller = MagicMock()
        win32con = self._fake_win32con()
        win32gui = MagicMock()
        wndproc = _make_about_wndproc(controller, win32gui=win32gui, win32con=win32con)
        result = wndproc(123, win32con.WM_KEYDOWN, win32con.VK_ESCAPE, 0)
        controller.hide_about.assert_called_once()
        self.assertEqual(result, 0)

    def test_other_keydown_is_not_handled(self) -> None:
        controller = MagicMock()
        win32con = self._fake_win32con()
        win32gui = MagicMock()
        win32gui.DefWindowProc.return_value = 7
        wndproc = _make_about_wndproc(controller, win32gui=win32gui, win32con=win32con)
        result = wndproc(123, win32con.WM_KEYDOWN, 0x41, 0)  # 'A'
        controller.hide_about.assert_not_called()
        self.assertEqual(result, 7)

    def test_deactivate_hides_the_about_window(self) -> None:
        controller = MagicMock()
        win32con = self._fake_win32con()
        win32gui = MagicMock()
        wndproc = _make_about_wndproc(controller, win32gui=win32gui, win32con=win32con)
        result = wndproc(123, win32con.WM_ACTIVATE, win32con.WA_INACTIVE, 0)
        controller.hide_about.assert_called_once()
        self.assertEqual(result, 0)

    def test_unhandled_message_delegates_to_def_window_proc(self) -> None:
        controller = MagicMock()
        win32con = self._fake_win32con()
        win32gui = MagicMock()
        win32gui.DefWindowProc.return_value = 42
        wndproc = _make_about_wndproc(controller, win32gui=win32gui, win32con=win32con)
        result = wndproc(123, 0x9999, 0, 0)
        self.assertEqual(result, 42)

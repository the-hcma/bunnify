from __future__ import annotations

import builtins
import sys
from unittest.mock import patch

from django.test import SimpleTestCase

from bookmarks.win32_test_support import real_win32_available


class RealWin32AvailableTests(SimpleTestCase):
    def test_false_off_windows(self) -> None:
        with patch.object(sys, "platform", "linux"):
            self.assertFalse(real_win32_available())

    def test_false_on_windows_without_pywin32(self) -> None:
        real_import = builtins.__import__

        def refuse_win32gui(name, *args, **kwargs):
            if name == "win32gui":
                raise ImportError("No module named 'win32gui'")
            return real_import(name, *args, **kwargs)

        with (
            patch.object(sys, "platform", "win32"),
            patch("builtins.__import__", refuse_win32gui),
        ):
            self.assertFalse(real_win32_available())

    def test_true_on_windows_with_pywin32(self) -> None:
        with (
            patch.object(sys, "platform", "win32"),
            patch.dict(sys.modules, {"win32gui": object()}),
        ):
            self.assertTrue(real_win32_available())

from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from django.test import SimpleTestCase

from bookmarks.macos_test_support import (
    REQUIRE_MACOS_TESTS_ENV,
    macos_only,
    pyobjc_available,
)


def _outcome(test_case: type[unittest.TestCase]) -> unittest.TestResult:
    result = unittest.TestResult()
    unittest.defaultTestLoader.loadTestsFromTestCase(test_case).run(result)
    return result


class MacosOnlyTests(SimpleTestCase):
    def _cases(self, *, available: bool) -> list[type[unittest.TestCase]]:
        class MethodCase(unittest.TestCase):
            @macos_only(available, "needs macOS")
            def test_it(self) -> None:
                pass

        @macos_only(available, "needs macOS")
        class ClassCase(unittest.TestCase):
            def test_it(self) -> None:
                pass

        return [MethodCase, ClassCase]

    def test_available_runs(self) -> None:
        for case in self._cases(available=True):
            result = _outcome(case)
            self.assertEqual((result.testsRun, result.skipped), (1, []))
            self.assertTrue(result.wasSuccessful())

    def test_unavailable_skips_by_default(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            cases = self._cases(available=False)
        for case in cases:
            result = _outcome(case)
            self.assertEqual(len(result.skipped), 1)
            self.assertTrue(result.wasSuccessful())

    def test_unavailable_fails_when_required(self) -> None:
        with patch.dict("os.environ", {REQUIRE_MACOS_TESTS_ENV: "1"}):
            cases = self._cases(available=False)
        for case in cases:
            result = _outcome(case)
            self.assertFalse(result.wasSuccessful())
            self.assertEqual(result.skipped, [])
            problems = result.failures + result.errors
            self.assertIn(REQUIRE_MACOS_TESTS_ENV, problems[0][1])


class PyobjcAvailableTests(SimpleTestCase):
    def test_false_off_macos(self) -> None:
        with patch.object(sys, "platform", "linux"):
            self.assertFalse(pyobjc_available())

    def test_false_on_macos_without_quartz(self) -> None:
        with (
            patch.object(sys, "platform", "darwin"),
            patch("importlib.util.find_spec", return_value=None),
        ):
            self.assertFalse(pyobjc_available())

    def test_true_on_macos_with_quartz(self) -> None:
        with (
            patch.object(sys, "platform", "darwin"),
            patch("importlib.util.find_spec", return_value=object()),
        ):
            self.assertTrue(pyobjc_available())

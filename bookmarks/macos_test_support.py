"""Shared guards for tests that need macOS (and usually PyObjC).

Off macOS those tests skip. The macOS CI job sets ``REQUIRE_MACOS_TESTS_ENV``
so a skip there fails instead: otherwise a renamed module or a PyObjC
packaging change would turn the job's coverage into ``OK (skipped=N)``.
"""

from __future__ import annotations

import functools
import importlib.util
import os
import sys
import unittest
from collections.abc import Callable
from typing import Any

REQUIRE_MACOS_TESTS_ENV = "BUNNIFY_REQUIRE_MACOS_TESTS"


def macos_only(available: bool, reason: str) -> Callable[[Any], Any]:
    """Skip a test (function or class) unless *available*; fail when required."""
    if available:
        return lambda obj: obj
    if os.environ.get(REQUIRE_MACOS_TESTS_ENV) != "1":
        return unittest.skip(reason)
    message = f"{REQUIRE_MACOS_TESTS_ENV}=1 but this macOS test cannot run: {reason}"

    def fail(obj: Any) -> Any:
        if isinstance(obj, type):

            def set_up_class(_cls: type) -> None:
                raise AssertionError(message)

            obj.setUpClass = classmethod(set_up_class)
            return obj

        @functools.wraps(obj)
        def wrapper(*_args: object, **_kwargs: object) -> None:
            raise AssertionError(message)

        return wrapper

    return fail


def pyobjc_available() -> bool:
    """True on macOS when PyObjC's Quartz bindings are importable."""
    return sys.platform == "darwin" and importlib.util.find_spec("Quartz") is not None

"""Django test runner that keeps the suite off the developer's real state (#527)."""

from __future__ import annotations

import os
import tempfile
from typing import Any

from django.test.runner import DiscoverRunner

from app.config import DATA_DIR_ENV_VAR

XDG_DATA_HOME_ENV_VAR = "XDG_DATA_HOME"
_ISOLATED_VARS = (DATA_DIR_ENV_VAR, XDG_DATA_HOME_ENV_VAR)


class IsolatedStateRunner(DiscoverRunner):
    """Run the tests with the data directory pointing at a throwaway location.

    The pid file, port file and health file all live under the data
    directory. Tests that call the real stop/terminate/clear helpers with
    their default locations (the macOS agent tests do, with the platform
    faked) would otherwise find, and kill, a Spotty Bunny overlay or
    managed server that is actually running on the machine.

    ``XDG_DATA_HOME`` is redirected and ``BUNNIFY_DATA_DIR`` cleared, so a
    test that isolates itself with either variable still overrides this.
    """

    def setup_test_environment(self, **kwargs: Any) -> None:
        super().setup_test_environment(**kwargs)
        self._state_dir = tempfile.TemporaryDirectory(prefix="bunnify-test-data-")
        self._previous = {name: os.environ.get(name) for name in _ISOLATED_VARS}
        os.environ.pop(DATA_DIR_ENV_VAR, None)
        os.environ[XDG_DATA_HOME_ENV_VAR] = self._state_dir.name

    def teardown_test_environment(self, **kwargs: Any) -> None:
        for name, value in self._previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self._state_dir.cleanup()
        super().teardown_test_environment(**kwargs)

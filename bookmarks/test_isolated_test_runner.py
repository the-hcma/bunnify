"""Tests for the isolated test runner's HOME and launchctl guards (#602)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from app.isolated_test_runner import (
    IsolatedStateRunner,
    RealLaunchctlBlockedError,
    _LaunchctlGuardedPopen,
    reject_real_launchctl,
)
from app.server_agent import agent_plist_path, is_agent_installed


class RunnerEnvironmentTests(SimpleTestCase):
    """These run under the project's TEST_RUNNER, so they assert it is active."""

    def test_home_is_a_throwaway_directory(self) -> None:
        for name in ("HOME", "USERPROFILE"):
            self.assertIn("bunnify-test-home-", os.environ[name], msg=name)
        self.assertIn("bunnify-test-home-", str(Path.home()))

    def test_no_real_launch_agent_is_visible(self) -> None:
        self.assertFalse(agent_plist_path().exists())
        self.assertFalse(is_agent_installed())

    def test_real_launchctl_is_blocked_through_subprocess(self) -> None:
        for argv in (
            ["launchctl", "bootout", "gui/501/com.thehcma.bunnify"],
            ["/bin/launchctl", "print", "gui/501/com.thehcma.bunnify"],
        ):
            with self.assertRaises(RealLaunchctlBlockedError, msg=repr(argv)):
                subprocess.run(argv, check=False, timeout=5)
        with self.assertRaises(RealLaunchctlBlockedError):
            subprocess.check_output("launchctl list", shell=True)

    def test_other_programs_still_run(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-c", "print('ok')"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(completed.stdout.strip(), "ok")

    def test_tests_that_patch_subprocess_are_unaffected(self) -> None:
        with patch("subprocess.run") as run:
            subprocess.run(["launchctl", "list"], check=False)
        run.assert_called_once()


class RejectRealLaunchctlTests(SimpleTestCase):
    def test_rejects_launchctl_in_any_spelling(self) -> None:
        for args in (
            ["launchctl", "list"],
            ("/bin/launchctl", "list"),
            [Path("/bin/launchctl")],
            "launchctl list",
            b"launchctl list",
            "/bin/launchctl bootout x",
        ):
            with self.assertRaises(RealLaunchctlBlockedError, msg=repr(args)):
                reject_real_launchctl(args)

    def test_allows_everything_else(self) -> None:
        for args in (
            ["git", "status"],
            ["echo", "launchctl"],
            "ls -l",
            [],
            "",
            None,
            [1, 2],
        ):
            reject_real_launchctl(args)  # must not raise


class RunnerTeardownTests(SimpleTestCase):
    def test_setup_installs_and_teardown_restores_guard_and_environment(self) -> None:
        # The live runner already guards Popen, so start from the real class.
        real_popen = _LaunchctlGuardedPopen.__mro__[1]
        before_env = {k: os.environ.get(k) for k in ("HOME", "USERPROFILE")}
        runner = IsolatedStateRunner()
        with (
            patch("subprocess.Popen", real_popen),
            patch("django.test.runner.DiscoverRunner.setup_test_environment"),
            patch("django.test.runner.DiscoverRunner.teardown_test_environment"),
        ):
            runner.setup_test_environment()
            inner_home = os.environ["HOME"]
            self.assertIn("bunnify-test-home-", inner_home)
            self.assertIs(subprocess.Popen, _LaunchctlGuardedPopen)
            runner.teardown_test_environment()
            self.assertIs(subprocess.Popen, real_popen)
        self.assertEqual({k: os.environ.get(k) for k in before_env}, before_env)
        self.assertFalse(Path(inner_home).exists())

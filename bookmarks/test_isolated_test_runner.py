"""Tests for the isolated test runner's HOME and launchctl guards (#602)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase
from django.test.runner import ParallelTestSuite

from app.isolated_test_runner import (
    IsolatedStateRunner,
    RealLaunchctlBlockedError,
    _invoked_programs,
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

    def test_windows_separators_are_normalized(self) -> None:
        # Simulates Windows path separators from any host: POSIX-mode shlex
        # would otherwise swallow the backslashes ("\\bin\\launchctl").
        for args in (
            [r"\bin\launchctl"],
            r"C:\tools\launchctl list",
            [r"C:\tools\launchctl", "list"],
        ):
            self.assertIn(
                "launchctl", _invoked_programs(args, sep="\\"), msg=repr(args)
            )
        self.assertIn(
            "launchctl",
            _invoked_programs(["true"], r"C:\tools\launchctl", sep="\\"),
        )
        # POSIX hosts keep backslash-as-escape behavior.
        self.assertNotIn("launchctl", _invoked_programs([r"a\launchctl"], sep="/"))

    def test_rejects_shell_and_executable_bypasses(self) -> None:
        for args in (
            '"/bin/launchctl" bootout x',
            "'launchctl' list",
            "cd /tmp && launchctl list",
            "true; /bin/launchctl list",
            "true;launchctl list",
            "cd /tmp&&launchctl list",
            "$(launchctl list)",
            "`launchctl list`",
            "echo `launchctl`",
            "(launchctl list)",
            'launchctl "unbalanced',
        ):
            with self.assertRaises(RealLaunchctlBlockedError, msg=repr(args)):
                reject_real_launchctl(args)
        with self.assertRaises(RealLaunchctlBlockedError):
            reject_real_launchctl(["true", "x"], executable="/bin/launchctl")
        with self.assertRaises(RealLaunchctlBlockedError):
            subprocess.run(["true"], executable="/bin/launchctl", check=False)
        with self.assertRaises(RealLaunchctlBlockedError):
            subprocess.run('"/bin/launchctl" list', shell=True, check=False)
        with self.assertRaises(RealLaunchctlBlockedError):
            # executable passed positionally: Popen(args, bufsize, executable)
            subprocess.Popen(["true"], -1, "/bin/launchctl")

    def test_rejects_wrapper_and_list_shell_forms(self) -> None:
        for args in (
            ["launchctl list"],
            ["/bin/sh", "-c", "/bin/launchctl list"],
            ["bash", "-c", "cd /tmp && launchctl list"],
            ["env", "launchctl", "list"],
            ["sudo", "-n", "/bin/launchctl", "list"],
            ["timeout", "5", "launchctl", "print", "gui/501/x"],
        ):
            with self.assertRaises(RealLaunchctlBlockedError, msg=repr(args)):
                reject_real_launchctl(args)
        with self.assertRaises(RealLaunchctlBlockedError):
            subprocess.run(["launchctl list"], shell=True, check=False)
        with self.assertRaises(RealLaunchctlBlockedError):
            subprocess.run(["/bin/sh", "-c", "/bin/launchctl list"], check=False)

    def test_rejects_nested_quoted_shell_commands(self) -> None:
        for args in (
            "sh -c 'launchctl list'",
            "bash -c \"cd /tmp && '/bin/launchctl' list\"",
            ["/bin/sh", "-c", "sh -c 'launchctl list'"],
            "sh -c \"sh -c 'env launchctl list'\"",
        ):
            with self.assertRaises(RealLaunchctlBlockedError, msg=repr(args)):
                reject_real_launchctl(args)
        with self.assertRaises(RealLaunchctlBlockedError):
            subprocess.run("sh -c 'launchctl list'", shell=True, check=False)

    def test_is_conservative_about_the_bare_word(self) -> None:
        # A backstop, not a sandbox: the bare word anywhere is blocked.
        with self.assertRaises(RealLaunchctlBlockedError):
            reject_real_launchctl(["echo", "launchctl"])

    def test_allows_everything_else(self) -> None:
        for args in (
            ["git", "status"],
            ["echo", "launchd"],
            ["git", "commit", "-m", "tidy launchctl-free code"],
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


class ParallelWorkerTests(SimpleTestCase):
    def test_runner_wires_the_guard_into_parallel_workers(self) -> None:
        suite = IsolatedStateRunner.parallel_test_suite
        self.assertTrue(issubclass(suite, ParallelTestSuite))
        # Django calls ``process_setup.__func__(*process_setup_args)`` in each
        # spawned worker, so it must be a plain module-level function.
        self.assertEqual(suite.process_setup.__module__, "app.isolated_test_runner")
        self.assertEqual(suite.process_setup_args, ())

    def test_fresh_interpreter_is_guarded_after_worker_setup(self) -> None:
        # Simulates a spawned worker: new interpreter, no runner setup, only the
        # worker hook. The program name comes from the environment so this test's
        # own arguments never contain the blocked word.
        code = (
            "import os, subprocess\n"
            "from app.isolated_test_runner import (\n"
            "    RealLaunchctlBlockedError, _parallel_worker_setup)\n"
            "_parallel_worker_setup()\n"
            "try:\n"
            "    subprocess.run([os.environ['GUARDED_PROGRAM'], 'help'], check=False)\n"
            "except RealLaunchctlBlockedError:\n"
            "    print('BLOCKED')\n"
        )
        project_root = str(Path(__file__).resolve().parent.parent)
        completed = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
            cwd=project_root,
            env={
                **os.environ,
                "GUARDED_PROGRAM": "launch" + "ctl",
                "PYTHONPATH": project_root,
            },
        )
        self.assertEqual(completed.stdout.strip(), "BLOCKED", msg=completed.stderr)

"""Django test runner that keeps the suite off the developer machine state (#602)."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import tempfile
from collections.abc import Mapping
from typing import Any

from django.test.runner import DiscoverRunner, ParallelTestSuite

from app.config import DATA_DIR_ENV_VAR

XDG_DATA_HOME_ENV_VAR = "XDG_DATA_HOME"
_DATA_VARS = (DATA_DIR_ENV_VAR, XDG_DATA_HOME_ENV_VAR)
_HOME_VARS = ("HOME", "USERPROFILE")
_BLOCKED_PROGRAMS = frozenset({"launchctl"})
_MAX_SHELL_NESTING = 4
_SHELL_SYNTAX = re.compile(r"[\s;&|<>()`$\"']")


class RealLaunchctlBlockedError(RuntimeError):
    """A test tried to run the real ``launchctl`` against the developer's launchd."""


def _invoked_programs(
    args: object, executable: object = None, sep: str = os.sep
) -> list[str]:
    """Return basenames of every word in ``args`` (plus ``executable``).

    This is a backstop against *accidental* calls, not a sandbox, so it is
    deliberately conservative: every word of every argument counts, which
    catches ``["launchctl", ...]``, ``"cd x && '/bin/launchctl' list"``,
    ``["/bin/sh", "-c", "launchctl list"]``, ``env``/``sudo``/``timeout``
    wrappers and an ``executable=`` override (which replaces argv[0]).
    """
    names: list[str] = []

    def add(value: object) -> None:
        """Record the program name of one path-like value (separators normalized)."""
        if isinstance(value, (str, bytes, os.PathLike)):
            text = os.fsdecode(value)
            if sep == "\\":
                text = text.replace("\\", "/")
            names.append(os.path.basename(text))

    def add_words(value: object, depth: int = 0) -> None:
        """Record each shell word of ``value``, recursing into nested commands."""
        if not isinstance(value, (str, bytes, os.PathLike)):
            return
        text = os.fsdecode(value)
        if sep == "\\":
            # Windows paths: POSIX-mode shlex would eat the backslashes.
            text = text.replace("\\", "/")
        lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        try:
            words = list(lexer)
        except ValueError:  # unbalanced quotes: fall back to a naive split
            words = text.split()
        for word in words:
            add(word)
            # shlex leaves backticks and `$(` attached to the word: split those too.
            for part in _SHELL_SYNTAX.split(word):
                if part:
                    add(part)
            # `sh -c 'launchctl list'` leaves one nested-quoted word: look inside.
            if (
                depth < _MAX_SHELL_NESTING
                and word != text
                and _SHELL_SYNTAX.search(word)
            ):
                add_words(word, depth + 1)

    add(executable)
    if isinstance(args, (list, tuple)):
        for part in args:
            add_words(part)
    else:
        add_words(args)
    return names


def reject_real_launchctl(args: object, executable: object = None) -> None:
    """Raise :class:`RealLaunchctlBlockedError` when this would run ``launchctl``."""
    if _BLOCKED_PROGRAMS.intersection(_invoked_programs(args, executable)):
        raise RealLaunchctlBlockedError(
            f"a test tried to run the real launchctl: {args!r}. That unloads the "
            "developer's production LaunchAgent (#602). Patch "
            "app.server_agent.bootout_loaded_agent, or inject a fake `launchctl` "
            "callable, instead."
        )


class _LaunchctlGuardedPopen(subprocess.Popen):  # pyright: ignore[reportMissingTypeArgument]
    """``subprocess.Popen`` that refuses to start ``launchctl``.

    ``subprocess.run`` / ``check_output`` / ``call`` all go through ``Popen``,
    so replacing it covers them. Tests that patch ``subprocess.run`` or
    ``Popen`` themselves bypass this guard, which is what we want.
    """

    def __init__(self, args: Any, *popenargs: Any, **kwargs: Any) -> None:
        """Refuse to start ``launchctl``; otherwise behave like ``subprocess.Popen``."""
        # Popen(args, bufsize, executable, ...): executable may be positional.
        executable = kwargs.get("executable")
        if executable is None and len(popenargs) > 1:
            executable = popenargs[1]
        reject_real_launchctl(args, executable)
        super().__init__(args, *popenargs, **kwargs)


def install_launchctl_guard() -> type[subprocess.Popen]:
    """Install the guard on ``subprocess.Popen``; return the class it replaced."""
    previous = subprocess.Popen
    subprocess.Popen = _LaunchctlGuardedPopen  # type: ignore[misc]
    return previous


def _parallel_worker_setup(*_args: Any) -> None:
    """Install the guard in a ``--parallel`` worker.

    Spawned workers (the macOS default) start a fresh interpreter, so the
    runner's own ``setup_test_environment`` never ran there. ``HOME`` is
    inherited through the environment; the ``Popen`` guard is not.
    """
    install_launchctl_guard()


class _GuardedParallelTestSuite(ParallelTestSuite):
    """Parallel suite whose worker processes install the launchctl guard."""

    process_setup = _parallel_worker_setup
    process_setup_args = ()


class IsolatedStateRunner(DiscoverRunner):
    """Run the tests without touching the developer's real machine state.

    The pid file, port file and health file all live under the data
    directory. Tests that call the real stop/terminate/clear helpers with
    their default locations (the macOS agent tests do, with the platform
    faked) would otherwise find, and kill, a Spotty Bunny overlay or
    managed server that is actually running on the machine.

    ``XDG_DATA_HOME`` is redirected and ``BUNNIFY_DATA_DIR`` cleared, so a
    test that isolates itself with either variable still overrides this.

    ``HOME`` / ``USERPROFILE`` point at a throwaway directory too, so code
    that looks for the real ``~/Library/LaunchAgents/*.plist`` finds nothing
    and behaves as it does on CI. As a backstop, starting a real
    ``launchctl`` raises :class:`RealLaunchctlBlockedError`: a forgotten
    patch fails the test instead of unloading the production agent (#602).
    """

    parallel_test_suite = _GuardedParallelTestSuite

    def setup_test_environment(self, **kwargs: Any) -> None:
        """Isolate data dir and HOME, and install the launchctl guard (#527, #602)."""
        super().setup_test_environment(**kwargs)
        self._state_dir = tempfile.TemporaryDirectory(prefix="bunnify-test-data-")
        self._home_dir = tempfile.TemporaryDirectory(prefix="bunnify-test-home-")
        self._previous: Mapping[str, str | None] = {
            name: os.environ.get(name) for name in (*_DATA_VARS, *_HOME_VARS)
        }
        os.environ.pop(DATA_DIR_ENV_VAR, None)
        os.environ[XDG_DATA_HOME_ENV_VAR] = self._state_dir.name
        for name in _HOME_VARS:
            os.environ[name] = self._home_dir.name
        self._previous_popen = install_launchctl_guard()

    def teardown_test_environment(self, **kwargs: Any) -> None:
        """Restore the environment and ``subprocess.Popen``; remove the temp dirs."""
        subprocess.Popen = self._previous_popen  # type: ignore[misc]
        for name, value in self._previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self._state_dir.cleanup()
        self._home_dir.cleanup()
        super().teardown_test_environment(**kwargs)

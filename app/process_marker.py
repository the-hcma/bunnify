"""Self-identifying argv marker for Bunnify's own background processes.

Bunnify repeatedly has to decide whether some process it found — a port
listener, a recorded pid — is one of its own. Inferring that from the
executable name is fragile: launchd runs the console script behind an
interpreter, uv and pipx install it under different paths, and unrelated
commands can mention ``bunnify-server`` in their arguments.

Every process Bunnify spawns therefore carries an explicit
``--bunnify-build <component>:<version>+<commit>`` token, which ``ps`` reports
verbatim. Recording the build alongside the component means the marker also
answers *which* build a process is running, without an HTTP probe.

Marker detection is an additional signal, never a replacement for the
name-based heuristics: during an upgrade the process holding the port was
started by an older build that predates the marker, so unmarked processes must
still be recognized.
"""

from __future__ import annotations

import shlex
from collections.abc import Sequence
from dataclasses import dataclass

from app.version import get_build_info

BUILD_MARKER_FLAG = "--bunnify-build"
SERVER_COMPONENT = "bunnify-server"
SPOTTY_BUNNY_COMPONENT = "spotty-bunny"


@dataclass(frozen=True)
class BuildMarker:
    """A parsed ``--bunnify-build`` token."""

    commit: str
    component: str
    version: str


def build_marker_arguments(
    component: str,
    *,
    commit: str | None = None,
    version: str | None = None,
) -> list[str]:
    """Return the argv pair stamping *component* with the running build."""
    return [
        BUILD_MARKER_FLAG,
        build_marker_value(component, commit=commit, version=version),
    ]


def build_marker_value(
    component: str,
    *,
    commit: str | None = None,
    version: str | None = None,
) -> str:
    """Return the ``component:version+commit`` marker value."""
    default_version, default_commit = get_build_info()
    resolved_version = version if version is not None else default_version
    resolved_commit = commit if commit is not None else default_commit
    return f"{component}:{resolved_version}+{resolved_commit}"


def marker_from_arguments(arguments: Sequence[str]) -> BuildMarker | None:
    """Return the build marker carried by *arguments*, if any."""
    for index, argument in enumerate(arguments):
        if argument == BUILD_MARKER_FLAG:
            if index + 1 < len(arguments):
                return parse_marker_value(arguments[index + 1])
            return None
        if argument.startswith(f"{BUILD_MARKER_FLAG}="):
            return parse_marker_value(argument.split("=", 1)[1])
    return None


def marker_from_command(command: str) -> BuildMarker | None:
    """Return the build marker in a ``ps`` command line, if any."""
    try:
        arguments = shlex.split(command)
    except ValueError:
        return None
    return marker_from_arguments(arguments)


def parse_marker_value(value: str) -> BuildMarker | None:
    """Parse ``component:version+commit``; ``None`` when malformed."""
    component, separator, build = value.partition(":")
    if not separator or not component or not build:
        return None
    version, separator, commit = build.rpartition("+")
    if not separator or not version or not commit:
        return None
    return BuildMarker(commit=commit, component=component, version=version)

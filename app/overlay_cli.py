"""Installed command-line entry point for the macOS shortcut overlay."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence

from app.version import build_version

EVENT_TAP_FAILED_MESSAGE = """\
bunnify-overlay: could not listen for the Control chord.

Grant Accessibility and Input Monitoring to this Python interpreter
(or Terminal) in System Settings → Privacy & Security, then re-run.
"""

MACOS_EXTRA_HINT = """\
bunnify-overlay: PyObjC is required (optional extra 'macos').

  pipx install 'bunnify[macos]'
  # development checkout:
  uv sync --extra macos
"""

NOT_MACOS_MESSAGE = "bunnify-overlay: this command is only available on macOS."


class OverlayEventTapError(RuntimeError):
    """Raised when a listen-only Control chord tap cannot be created."""


def build_parser() -> argparse.ArgumentParser:
    """Build the ``bunnify-overlay`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="bunnify-overlay",
        description=(
            "macOS Spotlight-style overlay: hold one Control, press the other "
            "to show a search box. Shortcut completion is not wired yet."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {build_version()}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the installed overlay command."""
    args = list(argv) if argv is not None else None
    build_parser().parse_args(args)
    return run_overlay()


def run_overlay() -> int:
    """Start the Cocoa overlay, or exit with an install / permission hint."""
    if sys.platform != "darwin":
        print(NOT_MACOS_MESSAGE, file=sys.stderr)
        return 1
    try:
        run_overlay_app = _load_run_overlay_app()
    except ImportError:
        print(MACOS_EXTRA_HINT, file=sys.stderr)
        return 1
    try:
        return run_overlay_app()
    except OverlayEventTapError:
        print(EVENT_TAP_FAILED_MESSAGE, file=sys.stderr)
        return 1


def _load_run_overlay_app() -> Callable[[], int]:
    from app.overlay_app import run_overlay_app

    return run_overlay_app


if __name__ == "__main__":
    raise SystemExit(main())

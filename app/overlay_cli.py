"""Installed command-line entry point for the macOS shortcut overlay."""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from app.config import data_dir
from app.version import build_version

EVENT_TAP_FAILED_MESSAGE = """\
bunnify-overlay: could not listen for the Control chord.

Grant Accessibility and Input Monitoring to this Python interpreter
(or Terminal) in System Settings → Privacy & Security, then re-run.
"""

LOG_BACKUP_COUNT = 5
LOG_FORMAT = (
    "[{asctime}] [{levelname}] [PID:{process}] [{name}:{funcName}:{lineno}] {message}"
)
LOG_LEVELS = ("CRITICAL", "DEBUG", "ERROR", "INFO", "WARNING")
LOG_MAX_BYTES = 10 * 1024 * 1024

MACOS_EXTRA_HINT = """\
bunnify-overlay: PyObjC is required (optional extra 'macos').

  pipx install 'bunnify[macos]'
  # development checkout:
  uv sync --extra macos
"""

NOT_MACOS_MESSAGE = "bunnify-overlay: this command is only available on macOS."

OVERLAY_LOG_ENV_VAR = "BUNNIFY_OVERLAY_LOG_FILE"
OVERLAY_LOG_FILE_NAME = "bunnify-overlay.log"


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
        "--log-file",
        type=Path,
        default=None,
        help="Log file (default: BUNNIFY_DATA_DIR/bunnify-overlay.log).",
    )
    parser.add_argument(
        "--log-level",
        type=str.upper,
        choices=LOG_LEVELS,
        default="WARNING",
        help="Application log level (default: WARNING). Same values as bunnify-server.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help=(
            "DEBUG logs on stderr and in the log file (key events, chord, "
            "show/hide). Overrides --log-level."
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
    parsed = build_parser().parse_args(args)
    log_level = "DEBUG" if parsed.verbose else parsed.log_level
    log_file = _overlay_log_file(parsed.log_file)
    _configure_overlay_logging(log_level, log_file)
    logging.getLogger(__name__).debug(
        "overlay starting (log_level=%s log_file=%s)",
        log_level,
        log_file,
    )
    print(f"bunnify-overlay: logging to {log_file}", file=sys.stderr)
    return run_overlay()


def run_overlay() -> int:
    """Start the Cocoa overlay, or exit with an install / permission hint."""
    if sys.platform != "darwin":
        print(NOT_MACOS_MESSAGE, file=sys.stderr)
        return 1
    try:
        run_overlay_app = _load_run_overlay_app()
    except ImportError:
        logging.getLogger(__name__).exception("PyObjC import failed")
        print(MACOS_EXTRA_HINT, file=sys.stderr)
        return 1
    try:
        return run_overlay_app()
    except OverlayEventTapError:
        logging.getLogger(__name__).exception("event tap was not created")
        print(EVENT_TAP_FAILED_MESSAGE, file=sys.stderr)
        return 1


def _configure_overlay_logging(log_level: str, log_file: Path) -> None:
    """Send overlay logs to a rotating file and stderr (same format as the server)."""
    level = getattr(logging, log_level)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S", style="{")
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(level)
    for name in ("app.overlay_app", "app.overlay_cli"):
        logger = logging.getLogger(name)
        for handler in logger.handlers:
            handler.close()
        logger.handlers.clear()
        logger.addHandler(file_handler)
        logger.addHandler(stream_handler)
        logger.setLevel(level)
        logger.propagate = False


def _load_run_overlay_app() -> Callable[[], int]:
    from app.overlay_app import run_overlay_app

    return run_overlay_app


def _overlay_log_file(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.expanduser()
    env = (os.environ.get(OVERLAY_LOG_ENV_VAR) or "").strip()
    if env:
        return Path(env).expanduser()
    return data_dir() / OVERLAY_LOG_FILE_NAME


if __name__ == "__main__":
    raise SystemExit(main())

"""Installed command-line entry point for Spotty Bunny."""

from __future__ import annotations

import argparse
import atexit
import logging
import logging.handlers
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from app.config import data_dir
from app.spotty_bunny_launch import clear_spotty_bunny_pid, write_spotty_bunny_pid
from app.version import build_version

COMMAND_NAME = "spotty-bunny"

EVENT_TAP_FAILED_MESSAGE = f"""\
{COMMAND_NAME}: could not listen for the Control chord.

Grant Accessibility and Input Monitoring to this Python interpreter
(or Terminal) in System Settings → Privacy & Security, then re-run.
"""

LOG_BACKUP_COUNT = 5
LOG_ENV_VAR = "BUNNIFY_SPOTTY_BUNNY_LOG_FILE"
LOG_FILE_NAME = "spotty-bunny.log"
LOG_FORMAT = (
    "[{asctime}] [{levelname}] [PID:{process}] [{name}:{funcName}:{lineno}] {message}"
)
LOG_LEVELS = ("CRITICAL", "DEBUG", "ERROR", "INFO", "WARNING")
LOG_MAX_BYTES = 10 * 1024 * 1024

MACOS_EXTRA_HINT = f"""\
{COMMAND_NAME}: PyObjC is required (optional extra 'macos').

  pipx install 'bunnify[macos]'
  # development checkout:
  uv sync --extra macos
"""

NOT_MACOS_MESSAGE = f"{COMMAND_NAME}: this command is only available on macOS."


class SpottyBunnyEventTapError(RuntimeError):
    """Raised when a listen-only Control chord tap cannot be created."""


def build_parser() -> argparse.ArgumentParser:
    """Build the ``spotty-bunny`` argument parser."""
    parser = argparse.ArgumentParser(
        prog=COMMAND_NAME,
        description=(
            "Spotty Bunny: macOS Spotlight-style search box. Hold one Control, "
            "press the other to show it. Subcommands: install, uninstall, "
            "status, upgrade (login LaunchAgent). Bare invocation is foreground."
        ),
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help=f"Log file (default: BUNNIFY_DATA_DIR/{LOG_FILE_NAME}).",
    )
    parser.add_argument(
        "--log-level",
        type=str.upper,
        choices=LOG_LEVELS,
        default="INFO",
        help="Application log level (default: INFO). Same values as bunnify-server.",
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
    """Run the installed Spotty Bunny command."""
    args = list(argv) if argv is not None else sys.argv[1:]
    if args:
        from app.spotty_bunny_agent import (
            AGENT_COMMANDS,
            UNKNOWN_COMMAND_MESSAGE,
            run_agent_command,
        )

        token = args[0]
        if token in AGENT_COMMANDS:
            return run_agent_command(token, args[1:])
        if not token.startswith("-"):
            print(UNKNOWN_COMMAND_MESSAGE.format(command=token), file=sys.stderr)
            return 2
    parsed = build_parser().parse_args(args)
    log_level = "DEBUG" if parsed.verbose else parsed.log_level
    log_file = _spotty_bunny_log_file(parsed.log_file)
    active_log = _configure_spotty_bunny_logging(log_level, log_file)
    logging.getLogger(__name__).debug(
        "spotty-bunny starting (log_level=%s log_file=%s)",
        log_level,
        active_log or log_file,
    )
    if active_log is not None:
        print(f"{COMMAND_NAME}: logging to {active_log}", file=sys.stderr)
    else:
        print(f"{COMMAND_NAME}: logging to stderr only", file=sys.stderr)
    if sys.platform == "darwin":
        write_spotty_bunny_pid(os.getpid())
        pid = os.getpid()
        atexit.register(lambda: clear_spotty_bunny_pid(only_pid=pid))
    return run_spotty_bunny()


def run_spotty_bunny() -> int:
    """Start Spotty Bunny, or exit with an install / permission hint."""
    if sys.platform != "darwin":
        print(NOT_MACOS_MESSAGE, file=sys.stderr)
        return 1
    try:
        run_app = _load_run_spotty_bunny_app()
    except ImportError:
        logging.getLogger(__name__).exception("PyObjC import failed")
        print(MACOS_EXTRA_HINT, file=sys.stderr)
        return 1
    try:
        return run_app()
    except SpottyBunnyEventTapError:
        logging.getLogger(__name__).exception("event tap was not created")
        print(EVENT_TAP_FAILED_MESSAGE, file=sys.stderr)
        return 1


def _configure_spotty_bunny_logging(log_level: str, log_file: Path) -> Path | None:
    """Send logs to a rotating file and stderr (same format as the server).

    Returns *log_file* when the rotating handler was attached. An unwritable
    path falls back to stderr so later errors (not-macOS, missing PyObjC)
    still print their hints.
    """
    level = getattr(logging, log_level)
    formatter = logging.Formatter(LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S", style="{")
    handlers: list[logging.Handler] = []
    active_log: Path | None = None
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        handlers.append(file_handler)
        active_log = log_file
    except OSError as exc:
        print(
            f"{COMMAND_NAME}: cannot write log file {log_file}: {exc}",
            file=sys.stderr,
        )
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(level)
    handlers.append(stream_handler)
    for name in ("app.spotty_bunny_app", "app.spotty_bunny_cli"):
        logger = logging.getLogger(name)
        for handler in logger.handlers:
            handler.close()
        logger.handlers.clear()
        for handler in handlers:
            logger.addHandler(handler)
        logger.setLevel(level)
        logger.propagate = False
    return active_log


def _load_run_spotty_bunny_app() -> Callable[[], int]:
    from app.spotty_bunny_app import run_spotty_bunny_app

    return run_spotty_bunny_app


def _spotty_bunny_log_file(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.expanduser()
    env = (os.environ.get(LOG_ENV_VAR) or "").strip()
    if env:
        return Path(env).expanduser()
    return data_dir() / LOG_FILE_NAME


if __name__ == "__main__":
    raise SystemExit(main())

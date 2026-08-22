"""pipx install detection and macOS optional-extra management."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

MACOS_EXTRA_PACKAGE = "bunnify[macos]"
MACOS_EXTRA_PROBE = (
    "import importlib.util, sys; "
    "sys.exit(0 if importlib.util.find_spec('AppKit') else 1)"
)
PIPX_INSTALL_TIMEOUT_S = 180


def install_macos_extra(
    pipx_bin: str,
    *,
    run_fn: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> bool:
    """Reinstall the pipx app with the ``macos`` extra. Return success."""
    runner = run_fn or subprocess.run
    try:
        completed = runner(
            [pipx_bin, "install", "--force", MACOS_EXTRA_PACKAGE],
            check=False,
            text=True,
            timeout=PIPX_INSTALL_TIMEOUT_S,
        )
    except OSError, subprocess.TimeoutExpired:
        return False
    return completed.returncode == 0


def macos_extra_installed(*, interpreter: Path | None = None) -> bool:
    """Return whether PyObjC (``AppKit``) is importable in the pipx venv."""
    python = interpreter
    if python is None:
        python = pipx_bunnify_venv_python()
    if python is None:
        python = Path(sys.executable)
    try:
        completed = subprocess.run(
            [str(python), "-c", MACOS_EXTRA_PROBE],
            capture_output=True,
            check=False,
            timeout=15,
        )
    except OSError, subprocess.TimeoutExpired:
        return False
    return completed.returncode == 0


def pipx_bunnify_path() -> Path | None:
    """Return the pipx ``bunnify`` app path when it exists."""
    override = os.environ.get("PIPX_BIN_DIR", "").strip()
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override) / "bunnify")
    candidates.append(Path.home() / ".local" / "bin" / "bunnify")
    for candidate in candidates:
        if candidate.is_file():
            try:
                return candidate.resolve()
            except OSError:
                return candidate
    return None


def pipx_bunnify_venv_python(*, pipx_home: Path | None = None) -> Path | None:
    """Return the pipx venv python for ``bunnify``, if present."""
    root = pipx_home
    if root is None:
        env_home = os.environ.get("PIPX_HOME", "").strip()
        root = Path(env_home) if env_home else Path.home() / ".local" / "share" / "pipx"
    python = root / "venvs" / "bunnify" / "bin" / "python"
    if python.is_file():
        return python
    return None

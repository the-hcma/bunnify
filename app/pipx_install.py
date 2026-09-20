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


def pipx_bunnify_display() -> str:
    """The pipx ``bunnify`` app as a user-facing path, for messages."""
    return f"~/.local/bin/{_app_name()}"


def pipx_bunnify_path() -> Path | None:
    """Return the pipx ``bunnify`` app path when it exists."""
    override = os.environ.get("PIPX_BIN_DIR", "").strip()
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override) / _app_name())
    candidates.append(Path.home() / ".local" / "bin" / _app_name())
    for candidate in candidates:
        if candidate.is_file():
            try:
                return candidate.resolve()
            except OSError:
                return candidate
    return None


def pipx_bunnify_venv_python(*, pipx_home: Path | None = None) -> Path | None:
    """Return the pipx venv python for ``bunnify``, if present."""
    roots = [pipx_home] if pipx_home is not None else _pipx_home_candidates()
    for root in roots:
        python = root / "venvs" / "bunnify" / _venv_python()
        if python.is_file():
            return python
    return None


def _app_name() -> str:
    """File name of the pipx-exposed ``bunnify`` app on this platform."""
    return "bunnify.exe" if sys.platform == "win32" else "bunnify"


def _pipx_home_candidates() -> list[Path]:
    """Return likely pipx home directories (``PIPX_HOME`` and common defaults)."""
    candidates: list[Path] = []
    env_home = os.environ.get("PIPX_HOME", "").strip()
    if env_home:
        candidates.append(Path(env_home))
    home = Path.home()
    relatives = [Path(".local") / "share" / "pipx", Path(".local") / "pipx"]
    if sys.platform == "win32":
        # pipx's Windows defaults: %LOCALAPPDATA%\pipx\pipx (current) and
        # ~\pipx (older releases).
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if local_app_data:
            candidates.append(Path(local_app_data) / "pipx" / "pipx")
        relatives.append(Path("pipx"))
    for relative in relatives:
        candidate = home / relative
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _venv_python() -> Path:
    """Interpreter path inside a pipx venv on this platform."""
    if sys.platform == "win32":
        return Path("Scripts") / "python.exe"
    return Path("bin") / "python"

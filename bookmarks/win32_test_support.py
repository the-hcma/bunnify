"""Shared guard for tests that call the real Win32 API.

Those tests need Windows *and* pywin32, which only the ``windows`` extra
installs (CI's Windows job uses ``uv sync --extra windows``). A plain
``uv sync`` on a Windows machine has neither ``win32gui`` nor ``win32api``,
so checking ``sys.platform`` alone would turn "not installed" into errors
instead of skips.
"""

from __future__ import annotations

import sys


def real_win32_available() -> bool:
    """True on Windows when pywin32's GUI modules can be imported."""
    if sys.platform != "win32":
        return False
    try:
        import win32gui  # noqa: F401  # pyright: ignore[reportMissingModuleSource]
    except ImportError:
        return False
    return True

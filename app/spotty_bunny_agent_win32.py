"""Spotty Bunny autostart (Windows) -- placeholder.

The real Scheduled Task-backed install/upgrade/status/uninstall lands in
https://github.com/the-hcma/bunnify/issues/427. This stub exists so #426's
tray menu (which always offers Install, or Uninstall/Upgrade once
installed) has something to call in the meantime, without blocking the
tray/overlay UI on the autostart work landing first.
"""

from __future__ import annotations

NOT_YET_IMPLEMENTED_MESSAGE = (
    "spotty-bunny: Windows autostart is not implemented yet. "
    "Track progress: https://github.com/the-hcma/bunnify/issues/427"
)


def is_agent_installed() -> bool:
    return False


def install_agent(**_kwargs: object) -> int:
    print(NOT_YET_IMPLEMENTED_MESSAGE)
    return 1


def uninstall_agent(**_kwargs: object) -> int:
    print(NOT_YET_IMPLEMENTED_MESSAGE)
    return 1


def upgrade_agent(**_kwargs: object) -> int:
    print(NOT_YET_IMPLEMENTED_MESSAGE)
    return 1

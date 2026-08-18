"""Right-click menu titles for the Spotty Bunny logo."""

from __future__ import annotations

QUIT_MENU_TITLE = "Quit Spotty Bunny"
UNINSTALL_INFORMATIVE = (
    "Removes the login LaunchAgent and stops Spotty Bunny. "
    "Bookmarks and config.env are kept."
)
UNINSTALL_MENU_TITLE = "Uninstall Spotty Bunny"
UPGRADE_MENU_TITLE = "Upgrade Spotty Bunny"
UPGRADE_STATUS = "Upgrading Bunnify from PyPI…"


def logo_menu_specs(*, outdated: bool) -> tuple[tuple[str, str], ...]:
    """Return logo menu (title, action) pairs in lexicographic title order.

    Upgrade is included only when a newer PyPI version is known.
    """
    items = (
        (QUIT_MENU_TITLE, "quitSpottyBunny:"),
        (UNINSTALL_MENU_TITLE, "uninstallSpottyBunny:"),
        (UPGRADE_MENU_TITLE, "upgradeSpottyBunny:"),
    )
    if outdated:
        return items
    return tuple(item for item in items if item[0] != UPGRADE_MENU_TITLE)

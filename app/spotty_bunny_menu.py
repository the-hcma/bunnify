"""Right-click menu titles for the Spotty Bunny logo."""

from __future__ import annotations

INSTALL_MENU_TITLE = "Install Spotty Bunny"
INSTALL_STATUS = "Installing LaunchAgent…"
QUIT_MENU_TITLE = "Quit Spotty Bunny"
UNINSTALL_INFORMATIVE = (
    "Removes the login LaunchAgent and stops Spotty Bunny. "
    "Bookmarks and config.env are kept."
)
UNINSTALL_MENU_TITLE = "Uninstall Spotty Bunny"
UPGRADE_MENU_TITLE = "Upgrade Spotty Bunny"
UPGRADE_STATUS = "Upgrading Bunnify from PyPI…"


def logo_menu_specs(
    *,
    installed: bool,
    outdated: bool,
) -> tuple[tuple[str, str], ...]:
    """Return logo menu (title, action) pairs in lexicographic title order.

    Install is shown when the LaunchAgent is missing. Upgrade is shown only
    when the agent is installed and a newer PyPI version is known.
    """
    items: list[tuple[str, str]] = [(QUIT_MENU_TITLE, "quitSpottyBunny:")]
    if installed:
        items.append((UNINSTALL_MENU_TITLE, "uninstallSpottyBunny:"))
        if outdated:
            items.append((UPGRADE_MENU_TITLE, "upgradeSpottyBunny:"))
    else:
        items.append((INSTALL_MENU_TITLE, "installSpottyBunny:"))
    return tuple(sorted(items, key=lambda item: item[0]))

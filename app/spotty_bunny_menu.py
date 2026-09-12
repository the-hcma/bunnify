"""Right-click menu titles for the Spotty Bunny logo."""

from __future__ import annotations

CHECK_FOR_UPDATES_MENU_TITLE = "Check for Updates"
CHECK_FOR_UPDATES_STATUS = "Checking for updates…"
INSTALL_MENU_TITLE = "Install"
INSTALL_STATUS = "Installing LaunchAgent…"
QUIT_MENU_TITLE = "Quit"
UNINSTALL_INFORMATIVE = (
    "Removes the login LaunchAgent and stops Spotty Bunny. "
    "Bookmarks and config.env are kept."
)
UNINSTALL_MENU_TITLE = "Uninstall"
UPGRADE_MENU_TITLE = "Upgrade"
UPGRADE_STATUS = "Upgrading Bunnify from PyPI…"


def logo_menu_specs(
    *,
    installed: bool,
    outdated: bool,
) -> tuple[tuple[str, str], ...]:
    """Return logo menu (title, action) pairs in lexicographic title order.

    Check for Updates always shows. Install is shown when the LaunchAgent is
    missing. Upgrade is shown only when the agent is installed and either a
    newer PyPI version is known or the running overlay is itself stale.
    """
    items: list[tuple[str, str]] = [
        (CHECK_FOR_UPDATES_MENU_TITLE, "checkForUpdates:"),
        (QUIT_MENU_TITLE, "quitSpottyBunny:"),
    ]
    if installed:
        items.append((UNINSTALL_MENU_TITLE, "uninstallSpottyBunny:"))
        if outdated:
            items.append((UPGRADE_MENU_TITLE, "upgradeSpottyBunny:"))
    else:
        items.append((INSTALL_MENU_TITLE, "installSpottyBunny:"))
    return tuple(sorted(items, key=lambda item: item[0]))

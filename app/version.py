"""Installed Bunnify distribution version."""

from importlib.metadata import PackageNotFoundError, version


def package_version() -> str:
    """Return the version from installed distribution metadata."""
    try:
        return version("bunnify")
    except PackageNotFoundError:
        return "unknown"

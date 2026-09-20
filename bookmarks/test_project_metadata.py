from __future__ import annotations

import tomllib
from pathlib import Path

from django.test import SimpleTestCase
from packaging.requirements import Requirement

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"

MACOS_PACKAGES = frozenset(
    {
        "pyobjc-core",
        "pyobjc-framework-applicationservices",
        "pyobjc-framework-cocoa",
        "pyobjc-framework-quartz",
    }
)
WINDOWS_PACKAGES = frozenset({"pywin32"})


def _project() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]


def _requirement(name: str) -> Requirement:
    matches = [
        requirement
        for requirement in map(Requirement, _project()["dependencies"])
        if requirement.name.lower() == name
    ]
    assert len(matches) == 1, f"{name} must be declared exactly once in dependencies"
    return matches[0]


def _applies(name: str, platform: str) -> bool:
    marker = _requirement(name).marker
    return marker is not None and marker.evaluate(
        {"sys_platform": platform, "extra": ""}
    )


class PlatformDependencyTests(SimpleTestCase):
    """A plain ``pip``/``pipx install bunnify`` must give a working
    spotty-bunny, so the platform packages are ordinary dependencies gated
    only by an environment marker, not by an extra the user has to know to ask
    for."""

    def test_pywin32_is_installed_on_windows_only(self) -> None:
        for name in WINDOWS_PACKAGES:
            with self.subTest(package=name):
                self.assertTrue(_applies(name, "win32"))
                self.assertFalse(_applies(name, "darwin"))
                self.assertFalse(_applies(name, "linux"))

    def test_pyobjc_is_installed_on_macos_only(self) -> None:
        for name in MACOS_PACKAGES:
            with self.subTest(package=name):
                self.assertTrue(_applies(name, "darwin"))
                self.assertFalse(_applies(name, "win32"))
                self.assertFalse(_applies(name, "linux"))

    def test_platform_markers_do_not_require_an_extra(self) -> None:
        # `extra == 'windows'` in a marker is what made them opt-in.
        for name in WINDOWS_PACKAGES | MACOS_PACKAGES:
            with self.subTest(package=name):
                marker = _requirement(name).marker
                assert marker is not None
                self.assertNotIn("extra", str(marker))

    def test_no_other_dependency_is_platform_specific(self) -> None:
        platform_specific = {
            requirement.name.lower()
            for requirement in map(Requirement, _project()["dependencies"])
            if requirement.marker is not None
        }
        self.assertEqual(platform_specific, WINDOWS_PACKAGES | MACOS_PACKAGES)

    def test_the_old_extras_remain_as_empty_aliases(self) -> None:
        # `pipx install 'bunnify[macos]'` / `'bunnify[windows]'` from earlier
        # releases and docs must keep working, without pulling anything extra.
        extras = _project()["optional-dependencies"]
        self.assertEqual(extras["macos"], [])
        self.assertEqual(extras["windows"], [])
        self.assertEqual(set(extras), {"macos", "windows"})

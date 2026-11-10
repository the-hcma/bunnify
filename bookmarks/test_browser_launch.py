"""Tests for per-shortcut browser/profile selection."""

from __future__ import annotations

import json
import plistlib
import sys
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import Client, SimpleTestCase, TestCase

from app import browser_launch
from app.browser_launch import (
    BrowserLaunchError,
    LaunchPlan,
    browser_from_identifier,
    detect_default_browser_id,
    find_installed_app,
    launch,
    list_profiles,
    plan_launch,
    resolve_profile_dir,
    user_data_dir,
)
from app.browser_spec import BrowserSpec, parse_browser_spec
from app.cli import _handle_resolved, open_url
from app.client import ClientError, ResolvedShortcut, resolve_shortcut
from app.spotty_bunny_resolve import lookup_resolved, open_resolved
from app.theme import Theme

from .models import Bookmark

LOCAL_STATE = {
    "profile": {
        "info_cache": {
            "Default": {"name": "Personal"},
            "Profile 1": {"name": "Work-BRK"},
            "Profile 2": {"name": "Dup"},
            "Profile 3": {"name": "Dup"},
        }
    }
}


def _write_local_state(user_data: Path) -> None:
    user_data.mkdir(parents=True, exist_ok=True)
    (user_data / "Local State").write_text(json.dumps(LOCAL_STATE), encoding="utf-8")


class BrowserSpecTests(SimpleTestCase):
    def test_parse_valid(self) -> None:
        self.assertEqual(
            parse_browser_spec({"app": "edge", "profile": "Work"}),
            BrowserSpec(app="edge", profile="Work"),
        )
        self.assertEqual(parse_browser_spec({"app": "chrome"}), BrowserSpec("chrome"))
        self.assertEqual(
            parse_browser_spec({"profile": "Work"}), BrowserSpec(profile="Work")
        )

    def test_parse_rejects_malformed(self) -> None:
        for raw in (None, {}, [], {"app": "firefox"}, {"profile": ""}, {"app": 3}):
            self.assertIsNone(parse_browser_spec(raw), msg=repr(raw))


class DetectionTests(SimpleTestCase):
    def test_identifier_mapping(self) -> None:
        self.assertEqual(browser_from_identifier("com.microsoft.edgemac"), "edge")
        self.assertEqual(browser_from_identifier("com.google.Chrome"), "chrome")
        self.assertEqual(browser_from_identifier("MSEdgeHTM"), "edge")
        self.assertEqual(browser_from_identifier("ChromeHTML.ABC123"), "chrome")
        self.assertIsNone(browser_from_identifier("com.apple.safari"))
        self.assertIsNone(browser_from_identifier(None))

    def test_macos_default_browser_from_launch_services(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            plist = browser_launch._mac_launch_services_plist(home)
            plist.parent.mkdir(parents=True)
            plist.write_bytes(
                plistlib.dumps(
                    {
                        "LSHandlers": [
                            {
                                "LSHandlerURLScheme": "mailto",
                                "LSHandlerRoleAll": "com.apple.mail",
                            },
                            {
                                "LSHandlerURLScheme": "https",
                                "LSHandlerRoleAll": "com.microsoft.edgemac",
                            },
                        ]
                    }
                )
            )
            self.assertEqual(
                detect_default_browser_id(platform="darwin", home=home),
                "com.microsoft.edgemac",
            )

    def test_macos_default_browser_unknown_without_plist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(
                detect_default_browser_id(platform="darwin", home=Path(tmp))
            )

    def test_windows_default_browser_from_registry(self) -> None:
        fake = MagicMock()
        fake.QueryValueEx.return_value = ("MSEdgeHTM", 1)
        with patch.dict(sys.modules, {"winreg": fake}):
            self.assertEqual(detect_default_browser_id(platform="win32"), "MSEdgeHTM")
        fake.OpenKey.side_effect = OSError
        with patch.dict(sys.modules, {"winreg": fake}):
            self.assertIsNone(detect_default_browser_id(platform="win32"))

    def test_windows_find_installed_app_via_app_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "msedge.exe"
            exe.write_text("")
            fake = MagicMock()
            fake.QueryValueEx.return_value = (str(exe), 1)
            with patch.dict(sys.modules, {"winreg": fake}):
                self.assertEqual(find_installed_app("edge", platform="win32"), str(exe))
            fake.QueryValueEx.return_value = (str(exe) + ".missing", 1)
            with patch.dict(sys.modules, {"winreg": fake}):
                self.assertIsNone(find_installed_app("edge", platform="win32"))

    def test_macos_find_installed_app_checks_user_applications(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "Applications" / "Microsoft Edge.app").mkdir(parents=True)
            self.assertEqual(
                find_installed_app(
                    "edge",
                    platform="darwin",
                    home=home,
                    system_apps=home / "NoSystemApps",
                ),
                str(home / "Applications" / "Microsoft Edge.app"),
            )


class ProfileLookupTests(SimpleTestCase):
    def test_user_data_dirs(self) -> None:
        home = Path("/h")
        self.assertEqual(
            user_data_dir("edge", platform="darwin", home=home),
            home / "Library/Application Support/Microsoft Edge",
        )
        self.assertEqual(
            user_data_dir("chrome", platform="win32", env={"LOCALAPPDATA": "/L"}),
            Path("/L") / "Google" / "Chrome" / "User Data",
        )
        self.assertIsNone(user_data_dir("chrome", platform="win32", env={}))
        self.assertIsNone(user_data_dir("chrome", platform="linux"))

    def test_list_profiles_and_exact_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write_local_state(Path(tmp))
            profiles = list_profiles(Path(tmp))
        self.assertEqual(profiles["Profile 1"], "Work-BRK")
        self.assertEqual(resolve_profile_dir("edge", "Work-BRK", profiles), "Profile 1")
        with self.assertRaises(BrowserLaunchError) as missing:
            resolve_profile_dir("edge", "work-brk", profiles)  # exact, case-sensitive
        self.assertIn('no profile named "work-brk"', str(missing.exception))
        self.assertIn('"Work-BRK"', str(missing.exception))
        with self.assertRaises(BrowserLaunchError) as ambiguous:
            resolve_profile_dir("edge", "Dup", profiles)
        self.assertIn("2 profiles named", str(ambiguous.exception))

    def test_unreadable_local_state_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(BrowserLaunchError):
                list_profiles(Path(tmp))


class PlanLaunchTests(SimpleTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)
        _write_local_state(self.home / "Library/Application Support/Microsoft Edge")

    def _plan(self, spec: BrowserSpec, **kwargs: object) -> LaunchPlan:
        params: dict[str, object] = {
            "platform": "darwin",
            "home": self.home,
            "find_app": lambda name: f"/Apps/{name}.app",
        }
        params.update(kwargs)
        return plan_launch("https://x.test/a b", spec, **params)  # type: ignore[arg-type]

    def test_macos_app_and_profile(self) -> None:
        plan = self._plan(BrowserSpec("edge", "Work-BRK"))
        self.assertEqual(
            plan.argv,
            (
                "open",
                "-na",
                "/Apps/edge.app",
                "--args",
                "--profile-directory=Profile 1",
                "https://x.test/a b",
            ),
        )
        self.assertEqual(plan.describe(), 'Edge, profile "Work-BRK"')

    def test_macos_app_only_uses_default_profile(self) -> None:
        plan = self._plan(BrowserSpec("edge"))
        self.assertEqual(
            plan.argv, ("open", "-a", "/Apps/edge.app", "https://x.test/a b")
        )
        self.assertIsNone(plan.profile_dir)

    def test_profile_only_uses_default_browser(self) -> None:
        plan = self._plan(
            BrowserSpec(profile="Work-BRK"),
            default_browser=lambda: "com.microsoft.edgemac",
        )
        self.assertEqual(plan.app, "edge")
        self.assertEqual(plan.profile_dir, "Profile 1")

    def test_profile_only_with_non_chromium_default_errors(self) -> None:
        with self.assertRaises(BrowserLaunchError) as ctx:
            self._plan(
                BrowserSpec(profile="Work-BRK"),
                default_browser=lambda: "com.apple.safari",
            )
        self.assertIn("com.apple.safari", str(ctx.exception))

    def test_missing_profile_errors_without_fallback(self) -> None:
        with self.assertRaises(BrowserLaunchError):
            self._plan(BrowserSpec("edge", "Nope"))

    def test_browser_not_installed_errors(self) -> None:
        with self.assertRaises(BrowserLaunchError) as ctx:
            self._plan(BrowserSpec("chrome"), find_app=lambda _name: None)
        self.assertIn("Chrome is not installed", str(ctx.exception))

    def test_unsupported_platform_errors(self) -> None:
        with self.assertRaises(BrowserLaunchError):
            self._plan(BrowserSpec("edge"), platform="linux")

    def test_windows_command(self) -> None:
        local = self.home / "local"
        _write_local_state(local / "Microsoft" / "Edge" / "User Data")
        plan = plan_launch(
            "https://x.test",
            BrowserSpec("edge", "Work-BRK"),
            platform="win32",
            env={"LOCALAPPDATA": str(local)},
            find_app=lambda _name: r"C:\Edge\msedge.exe",
        )
        self.assertEqual(
            plan.argv,
            (r"C:\Edge\msedge.exe", "--profile-directory=Profile 1", "https://x.test"),
        )


class LaunchTests(SimpleTestCase):
    PLAN = LaunchPlan("edge", "W", "Profile 1", ("open", "x"))

    def test_runs_argv(self) -> None:
        run = MagicMock(return_value=0)
        launch(self.PLAN, run=run)
        run.assert_called_once_with(("open", "x"))

    def test_nonzero_exit_is_an_error(self) -> None:
        with self.assertRaises(BrowserLaunchError):
            launch(self.PLAN, run=lambda _argv: 1)

    def test_oserror_is_an_error(self) -> None:
        def boom(_argv: tuple[str, ...]) -> int:
            raise OSError("nope")

        with self.assertRaises(BrowserLaunchError):
            launch(self.PLAN, run=boom)

    def test_launch_error_is_a_client_error(self) -> None:
        self.assertTrue(issubclass(BrowserLaunchError, ClientError))


class OpenUrlTests(SimpleTestCase):
    def test_no_browser_uses_default_opener_only(self) -> None:
        opener = MagicMock(return_value=True)
        with patch("app.cli.plan_launch") as plan:
            open_url("https://x.test", opener=opener)
        opener.assert_called_once_with("https://x.test")
        plan.assert_not_called()

    def test_browser_pin_launches_and_skips_default_opener(self) -> None:
        opener = MagicMock(return_value=True)
        spec = BrowserSpec("edge", "Work-BRK")
        with (
            patch("app.cli.plan_launch", return_value="PLAN") as plan,
            patch("app.cli.launch") as run,
        ):
            open_url("https://x.test", opener=opener, browser=spec)
        plan.assert_called_once_with("https://x.test", spec)
        run.assert_called_once_with("PLAN")
        opener.assert_not_called()

    def test_unavailable_pin_opens_nothing(self) -> None:
        opener = MagicMock(return_value=True)
        with patch("app.cli.plan_launch", side_effect=BrowserLaunchError("no")):
            with self.assertRaises(BrowserLaunchError):
                open_url("https://x.test", opener=opener, browser=BrowserSpec("edge"))
        opener.assert_not_called()


class HandleResolvedTests(SimpleTestCase):
    def _call(self, resolved: ResolvedShortcut, *, open_browser: bool) -> MagicMock:
        opener = MagicMock(return_value=True)
        with patch("app.cli.resolve_shortcut", return_value=resolved):
            _handle_resolved(
                "brk",
                base_url="http://b",
                theme=Theme(enabled=False),
                print_url=True,
                open_browser=open_browser,
                opener=opener,
            )
        return opener

    def test_dry_run_reports_browser_and_validates(self) -> None:
        resolved = ResolvedShortcut(
            "https://x.test", "bookmark", "brk", BrowserSpec("edge", "W")
        )
        plan = LaunchPlan("edge", "W", "Profile 1", ("open",))
        with (
            patch("app.cli.plan_launch", return_value=plan),
            patch("app.cli.launch") as run,
            patch("click.echo") as echo,
        ):
            self._call(resolved, open_browser=False)
        run.assert_not_called()
        printed = " ".join(str(c.args[0]) for c in echo.call_args_list)
        self.assertIn('Edge, profile "W"', printed)

    def test_dry_run_surfaces_lookup_errors(self) -> None:
        resolved = ResolvedShortcut(
            "https://x.test", "bookmark", "brk", BrowserSpec("edge", "Bad")
        )
        with patch("app.cli.plan_launch", side_effect=BrowserLaunchError("bad")):
            with self.assertRaises(BrowserLaunchError):
                self._call(resolved, open_browser=False)

    def test_unpinned_shortcut_never_touches_browser_launch(self) -> None:
        resolved = ResolvedShortcut("https://x.test", "bookmark", "gh")
        with patch("app.cli.plan_launch") as plan:
            opener = self._call(resolved, open_browser=True)
        plan.assert_not_called()
        opener.assert_called_once_with("https://x.test")


class SpottyResolveTests(SimpleTestCase):
    def test_lookup_carries_browser_pin(self) -> None:
        spec = BrowserSpec("edge", "W")
        fake = MagicMock(return_value=ResolvedShortcut("u", "bookmark", "k", spec))
        resolved = lookup_resolved("k", base_url="b", resolve_fn=fake)
        self.assertEqual(resolved.browser, spec)

    def test_open_resolved_passes_pin_only_when_present(self) -> None:
        opener = MagicMock()
        open_resolved(ResolvedShortcut("u", None, None), open_fn=opener)
        opener.assert_called_once_with("u")
        opener.reset_mock()
        spec = BrowserSpec("chrome")
        open_resolved(ResolvedShortcut("u", None, None, spec), open_fn=opener)
        opener.assert_called_once_with("u", browser=spec)


class ClientParseTests(SimpleTestCase):
    def test_resolve_shortcut_parses_browser(self) -> None:
        payload = {
            "ok": True,
            "url": "https://x.test",
            "kind": "bookmark",
            "key": "brk",
            "browser": {"app": "edge", "profile": "W"},
        }
        with patch("app.client._request_json", return_value=payload):
            resolved = resolve_shortcut("brk", base_url="http://b")
        self.assertEqual(resolved.browser, BrowserSpec("edge", "W"))
        del payload["browser"]
        with patch("app.client._request_json", return_value=payload):
            self.assertIsNone(resolve_shortcut("brk", base_url="http://b").browser)


class ServerBrowserTests(TestCase):
    def setUp(self) -> None:
        Bookmark.objects.create(
            key="brk",
            description="BRK",
            url="https://brk.test/#{id}",
            browser={"app": "edge", "profile": "Work-BRK"},
        )
        Bookmark.objects.create(key="gh", description="GH", url="https://github.com")

    def test_resolve_includes_browser_only_when_pinned(self) -> None:
        client = Client()
        pinned = client.get("/api/resolve/", {"q": "brk 7", "strict": "1"}).json()
        self.assertEqual(pinned["browser"], {"app": "edge", "profile": "Work-BRK"})
        plain = client.get("/api/resolve/", {"q": "gh", "strict": "1"}).json()
        self.assertNotIn("browser", plain)

    def test_keys_catalog_includes_browser(self) -> None:
        entries = {e["key"]: e for e in Client().get("/api/keys/").json()["entries"]}
        self.assertEqual(entries["brk"]["browser"]["app"], "edge")
        self.assertNotIn("browser", entries["gh"])

    def _load(self, data: dict[str, object]) -> str:
        out = StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bookmarks.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            call_command("load_bookmarks", file=str(path), stdout=out)
        return out.getvalue()

    def test_loader_stores_browser_block(self) -> None:
        self._load(
            {
                "b": {
                    "description": "B",
                    "url": "https://b.test",
                    "browser": {"app": "chrome", "profile": "P"},
                }
            }
        )
        self.assertEqual(
            Bookmark.objects.get(key="b").browser, {"app": "chrome", "profile": "P"}
        )

    def test_loader_rejects_invalid_browser_blocks(self) -> None:
        for bad in ({"app": "firefox"}, {}, {"profile": ""}, {"x": 1}):
            Bookmark.objects.all().delete()
            Bookmark.objects.create(key="keep", description="k", url="https://k.test")
            output = self._load(
                {"b": {"description": "B", "url": "https://b.test", "browser": bad}}
            )
            self.assertIn("validation failed", output, msg=repr(bad))
            self.assertTrue(Bookmark.objects.filter(key="keep").exists())

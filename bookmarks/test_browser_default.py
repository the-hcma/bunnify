"""Tests for the default browser profile, ``bunnify browsers`` and the installer."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import skipIf
from unittest.mock import patch

from django.test import SimpleTestCase

from app import browser_launch
from app.browser_default import (
    apply_default_browser,
    default_browser_prompt_enabled,
    load_default_browser,
    save_default_browser,
    save_default_browser_prompt,
)
from app.browser_launch import (
    BrowserLaunchError,
    BrowserProfilesAccessError,
    ProfileInfo,
    installed_browser_profiles,
    list_profile_details,
    macos_profile_access_hint,
    plan_launch,
)
from app.browser_spec import BrowserSpec
from app.browsers import offer_default_profile, run_browsers
from app.cli import open_url
from app.config import read_toml_document, write_toml_document
from app.theme import Theme

COLORS = Theme(enabled=False)
EDGE = {
    "edge": [
        ProfileInfo("Default", "hcma @ BRK Tech", "me@brk.tech"),
        ProfileInfo("Profile 1", "hcma @ BRK Commons", "me@commons.example"),
    ]
}


def _write_state(user_data: Path, profiles: dict[str, dict[str, str]]) -> None:
    user_data.mkdir(parents=True, exist_ok=True)
    for directory in profiles:
        (user_data / directory).mkdir(exist_ok=True)
    (user_data / "Local State").write_text(
        json.dumps({"profile": {"info_cache": profiles}}), encoding="utf-8"
    )


class ProfileDiscoveryTests(SimpleTestCase):
    def test_details_include_account_and_skip_stale_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            _write_state(
                data,
                {
                    "Default": {"name": "Work", "user_name": "me@brk.tech"},
                    "Profile 1": {"name": "Plain"},
                },
            )
            (data / "Profile 1").rmdir()
            details = list_profile_details(data)
        self.assertEqual(details, [ProfileInfo("Default", "Work", "me@brk.tech")])

    def test_permission_denied_raises_access_error_with_the_fix_on_macos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            _write_state(data, {"Default": {"name": "Work"}})
            with (
                patch.object(
                    Path, "read_text", side_effect=PermissionError(1, "denied")
                ),
                patch("app.browser_launch.sys.platform", "darwin"),
                self.assertRaises(BrowserProfilesAccessError) as ctx,
            ):
                list_profile_details(data)
        text = str(ctx.exception)
        self.assertIn("Cannot read browser profiles from", text)
        self.assertIn("Full Disk Access", text)
        self.assertIn("your terminal app", text)
        self.assertIn("Spotty Bunny (launchd)", text)
        self.assertIn(os.path.realpath(sys.executable), text)

    def test_permission_denied_has_no_macos_hint_elsewhere(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            _write_state(data, {"Default": {"name": "Work"}})
            with (
                patch.object(
                    Path, "read_text", side_effect=PermissionError(1, "denied")
                ),
                patch("app.browser_launch.sys.platform", "win32"),
                self.assertRaises(BrowserProfilesAccessError) as ctx,
            ):
                list_profile_details(data)
        self.assertNotIn("Full Disk Access", str(ctx.exception))

    def test_other_read_errors_stay_plain_launch_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(BrowserLaunchError) as ctx:
                list_profile_details(Path(tmp))
        self.assertNotIsInstance(ctx.exception, BrowserProfilesAccessError)

    def test_access_hint_names_the_real_executable(self) -> None:
        hint = macos_profile_access_hint("/opt/homebrew/bin/../bin/python3")
        self.assertIn(os.path.realpath("/opt/homebrew/bin/../bin/python3"), hint)

    def test_installed_profiles_skip_missing_browsers_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            _write_state(
                home / "Library/Application Support/Microsoft Edge",
                {"Default": {"name": "Work", "user_name": "me@brk.tech"}},
            )
            (home / "Library/Application Support/Google/Chrome").mkdir(parents=True)
            found = installed_browser_profiles(
                platform="darwin", home=home, find_app=lambda _app: "/Applications/X"
            )
            only_chrome_missing = installed_browser_profiles(
                platform="darwin",
                home=home,
                find_app=lambda app: None if app == "edge" else "/Applications/X",
            )
        self.assertEqual(
            found, {"edge": [ProfileInfo("Default", "Work", "me@brk.tech")]}
        )
        self.assertEqual(only_chrome_missing, {})

    def test_installed_profiles_propagate_access_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            _write_state(
                home / "Library/Application Support/Microsoft Edge",
                {"Default": {"name": "Work"}},
            )
            with (
                patch.object(
                    Path, "read_text", side_effect=PermissionError(1, "denied")
                ),
                self.assertRaises(BrowserProfilesAccessError),
            ):
                installed_browser_profiles(
                    platform="darwin",
                    home=home,
                    find_app=lambda _app: "/Applications/X",
                )


class DefaultBrowserConfigTests(SimpleTestCase):
    def _config(self, tmp: str) -> Path:
        return Path(tmp) / "config.toml"

    def test_unset_means_no_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(load_default_browser(env_path=self._config(tmp)))

    def test_save_and_load_round_trip_preserves_other_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._config(tmp)
            path.write_text('mode = "local"\n', encoding="utf-8")
            save_default_browser(
                BrowserSpec(app="edge", profile="hcma @ BRK Tech"), env_path=path
            )
            self.assertEqual(
                load_default_browser(env_path=path),
                BrowserSpec(app="edge", profile="hcma @ BRK Tech"),
            )
            self.assertIn('mode = "local"', path.read_text(encoding="utf-8"))
            save_default_browser(None, env_path=path)
            self.assertIsNone(load_default_browser(env_path=path))
            self.assertIn('mode = "local"', path.read_text(encoding="utf-8"))

    def test_invalid_browser_is_an_error_not_a_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._config(tmp)
            path.write_text('default_browser = "firefox"\n', encoding="utf-8")
            with self.assertRaisesRegex(BrowserLaunchError, "edge, chrome"):
                load_default_browser(env_path=path)

    def test_profile_only_default_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._config(tmp)
            path.write_text('default_browser_profile = "Work"\n', encoding="utf-8")
            self.assertEqual(
                load_default_browser(env_path=path), BrowserSpec(profile="Work")
            )

    def test_profile_names_with_edge_spaces_round_trip_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._config(tmp)
            save_default_browser(BrowserSpec("edge", "  Spaced name "), env_path=path)
            self.assertEqual(
                load_default_browser(env_path=path),
                BrowserSpec("edge", "  Spaced name "),
            )

    def test_prompt_opt_out_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._config(tmp)
            self.assertTrue(default_browser_prompt_enabled(env_path=path))
            save_default_browser_prompt(False, env_path=path)
            self.assertFalse(default_browser_prompt_enabled(env_path=path))
            save_default_browser_prompt(True, env_path=path)
            self.assertTrue(default_browser_prompt_enabled(env_path=path))


class ApplyDefaultBrowserTests(SimpleTestCase):
    DEFAULT = BrowserSpec(app="edge", profile="Work")

    def _apply(self, pinned: BrowserSpec | None) -> BrowserSpec | None:
        with patch("app.browser_default.sys.platform", "darwin"):
            return apply_default_browser(pinned, default=self.DEFAULT)

    def test_unpinned_uses_the_default(self) -> None:
        self.assertEqual(self._apply(None), self.DEFAULT)

    def test_explicit_profile_pin_wins(self) -> None:
        pin = BrowserSpec(app="edge", profile="Other")
        self.assertEqual(self._apply(pin), pin)
        profile_only = BrowserSpec(profile="Other")
        self.assertEqual(self._apply(profile_only), profile_only)

    def test_app_only_pin_gets_the_profile_when_same_browser(self) -> None:
        self.assertEqual(self._apply(BrowserSpec(app="edge")), self.DEFAULT)

    def test_app_only_pin_for_another_browser_is_left_alone(self) -> None:
        pin = BrowserSpec(app="chrome")
        self.assertEqual(self._apply(pin), pin)

    def test_no_default_changes_nothing(self) -> None:
        with (
            patch("app.browser_default.sys.platform", "darwin"),
            tempfile.TemporaryDirectory() as tmp,
        ):
            path = Path(tmp) / "config.toml"
            self.assertIsNone(apply_default_browser(None, env_path=path))
            pin = BrowserSpec(app="edge")
            self.assertEqual(apply_default_browser(pin, env_path=path), pin)

    def test_complete_pin_never_reads_the_default(self) -> None:
        with (
            patch("app.browser_default.sys.platform", "darwin"),
            tempfile.TemporaryDirectory() as tmp,
        ):
            path = Path(tmp) / "config.toml"
            path.write_text('default_browser = "firefox"\n', encoding="utf-8")
            pin = BrowserSpec(app="edge", profile="Other")
            self.assertEqual(apply_default_browser(pin, env_path=path), pin)
            profile_only = BrowserSpec(profile="Other")
            self.assertEqual(
                apply_default_browser(profile_only, env_path=path), profile_only
            )
            # A browser-only pin already says which browser to open, so a broken
            # default must not stop it ...
            browser_only = BrowserSpec(app="edge")
            self.assertEqual(
                apply_default_browser(browser_only, env_path=path), browser_only
            )
            # ... but an unpinned shortcut still reports the typo.
            with self.assertRaises(BrowserLaunchError):
                apply_default_browser(None, env_path=path)

    def test_save_writes_browser_and_profile_in_one_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            with patch("app.config.write_toml_document") as write:
                save_default_browser(BrowserSpec("edge", "Work"), env_path=path)
        write.assert_called_once()

    def test_browser_and_profile_are_read_from_one_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                'default_browser = "edge"\ndefault_browser_profile = "A"\n',
                encoding="utf-8",
            )
            with patch(
                "app.config.read_toml_document", wraps=read_toml_document
            ) as read:
                load_default_browser(env_path=path)
        self.assertEqual(read.call_count, 1)

    def test_open_url_honors_an_explicit_config_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "custom.toml"
            save_default_browser(self.DEFAULT, env_path=path)
            with (
                patch.dict(
                    os.environ, {"XDG_CONFIG_HOME": str(Path(tmp) / "elsewhere")}
                ),
                patch("app.browser_default.sys.platform", "darwin"),
                patch("app.cli.plan_launch", return_value="PLAN") as plan,
                patch("app.cli.launch"),
            ):
                open_url("https://example.com", env_path=path)
        plan.assert_called_once_with("https://example.com", self.DEFAULT)

    def test_browser_only_pin_ignores_a_profile_only_default(self) -> None:
        with (
            patch("app.browser_default.sys.platform", "darwin"),
            tempfile.TemporaryDirectory() as tmp,
        ):
            path = Path(tmp) / "config.toml"
            path.write_text('default_browser_profile = "Work"\n', encoding="utf-8")
            pin = BrowserSpec(app="edge")
            self.assertEqual(apply_default_browser(pin, env_path=path), pin)

    def test_default_is_ignored_off_macos_and_windows(self) -> None:
        with patch("app.browser_default.sys.platform", "linux"):
            self.assertIsNone(apply_default_browser(None, default=self.DEFAULT))

    def test_open_url_opens_unpinned_shortcuts_in_the_default_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bunnify" / "config.toml"
            path.parent.mkdir()
            save_default_browser(self.DEFAULT, env_path=path)
            with (
                patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp}),
                patch("app.browser_default.sys.platform", "darwin"),
                patch("app.cli.plan_launch", return_value="PLAN") as plan,
                patch("app.cli.launch") as launch,
            ):
                open_url("https://example.com")
        plan.assert_called_once_with("https://example.com", self.DEFAULT)
        launch.assert_called_once_with("PLAN")

    def test_open_url_without_a_default_uses_the_system_opener(self) -> None:
        opened: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp}):
                open_url(
                    "https://example.com", opener=lambda u: opened.append(u) or True
                )
        self.assertEqual(opened, ["https://example.com"])


class AtomicConfigWriteTests(SimpleTestCase):
    @skipIf(sys.platform == "win32", "POSIX modes and umask")
    def test_a_first_time_write_honors_the_umask_not_owner_only(self) -> None:
        old = os.umask(0o022)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "config.toml"
                document = read_toml_document(path)
                document["mode"] = "local"
                write_toml_document(path, document)
                self.assertEqual(path.stat().st_mode & 0o777, 0o644)
        finally:
            os.umask(old)

    def test_write_replaces_the_file_and_keeps_its_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text('mode = "local"\n', encoding="utf-8")
            path.chmod(0o640)
            document = read_toml_document(path)
            document["default_browser"] = "edge"
            write_toml_document(path, document)
            self.assertIn('default_browser = "edge"', path.read_text(encoding="utf-8"))
            if sys.platform != "win32":
                self.assertEqual(path.stat().st_mode & 0o777, 0o640)
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["config.toml"])

    def test_a_failed_fdopen_closes_the_descriptor_and_removes_the_temp_file(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            document = read_toml_document(path)
            with (
                patch("app.config.os.fdopen", side_effect=OSError("no memory")),
                patch("app.config.os.close", wraps=os.close) as close,
                self.assertRaises(OSError),
            ):
                write_toml_document(path, document)
            close.assert_called_once()
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_the_file_is_synced_before_it_replaces_the_original(self) -> None:
        order: list[str] = []
        real_replace = os.replace
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            document = read_toml_document(path)
            with (
                patch(
                    "app.config.os.fsync", side_effect=lambda _fd: order.append("sync")
                ),
                patch(
                    "app.config.os.replace",
                    side_effect=lambda a, b: (
                        order.append("replace"),
                        real_replace(a, b),
                    ),
                ),
            ):
                write_toml_document(path, document)
        self.assertEqual(order, ["sync", "replace"])

    def test_a_failed_write_leaves_the_original_intact_and_no_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text('mode = "local"\n', encoding="utf-8")
            document = read_toml_document(path)
            with (
                patch("app.config.os.replace", side_effect=OSError("disk full")),
                self.assertRaises(OSError),
            ):
                write_toml_document(path, document)
            self.assertEqual(path.read_text(encoding="utf-8"), 'mode = "local"\n')
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["config.toml"])


class ConfigRobustnessTests(SimpleTestCase):
    @skipIf(sys.platform == "win32", "symlinks need privileges on Windows")
    def test_write_goes_through_a_symlinked_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "dotfiles" / "config.toml"
            real.parent.mkdir()
            real.write_text('mode = "local"\n', encoding="utf-8")
            link = Path(tmp) / "config.toml"
            link.symlink_to(real)
            save_default_browser(BrowserSpec("edge", "Work"), env_path=link)
            self.assertTrue(link.is_symlink())
            self.assertIn('default_browser = "edge"', real.read_text(encoding="utf-8"))
            self.assertIn('mode = "local"', real.read_text(encoding="utf-8"))

    def test_malformed_config_is_a_launch_error_with_a_pinned_browser_still_opening(
        self,
    ) -> None:
        with (
            patch("app.browser_default.sys.platform", "darwin"),
            tempfile.TemporaryDirectory() as tmp,
        ):
            path = Path(tmp) / "config.toml"
            path.write_text("this is = = not toml\n", encoding="utf-8")
            with self.assertRaisesRegex(BrowserLaunchError, "Cannot read the default"):
                load_default_browser(env_path=path)
            with self.assertRaises(BrowserLaunchError):
                apply_default_browser(None, env_path=path)
            pin = BrowserSpec(app="edge")
            self.assertEqual(apply_default_browser(pin, env_path=path), pin)

    def test_profile_only_default_applies_to_unpinned_shortcuts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text('default_browser_profile = "Work"\n', encoding="utf-8")
            with (
                patch("app.browser_default.sys.platform", "darwin"),
                patch("app.cli.plan_launch", return_value="PLAN") as plan,
                patch("app.cli.launch"),
            ):
                open_url("https://example.com", env_path=path)
        plan.assert_called_once_with("https://example.com", BrowserSpec(profile="Work"))

    def test_one_broken_browser_does_not_hide_a_working_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            _write_state(
                home / "Library/Application Support/Microsoft Edge",
                {"Default": {"name": "Work"}},
            )
            chrome = home / "Library/Application Support/Google/Chrome"
            chrome.mkdir(parents=True)
            (chrome / "Local State").write_text("{not json", encoding="utf-8")
            found = installed_browser_profiles(
                platform="darwin", home=home, find_app=lambda _a: "/Applications/X"
            )
        self.assertEqual(list(found), ["edge"])

    def test_a_skipped_browsers_error_is_reported_through_on_error(self) -> None:
        reported: list[BrowserLaunchError] = []
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            _write_state(
                home / "Library/Application Support/Microsoft Edge",
                {"Default": {"name": "Work"}},
            )
            chrome = home / "Library/Application Support/Google/Chrome"
            chrome.mkdir(parents=True)
            (chrome / "Local State").write_text("{not json", encoding="utf-8")
            found = installed_browser_profiles(
                platform="darwin",
                home=home,
                find_app=lambda _a: "/Applications/X",
                on_error=reported.append,
            )
        self.assertEqual(list(found), ["edge"])
        self.assertEqual(len(reported), 1)
        self.assertIn("Chrome", str(reported[0]))

    def test_profile_only_default_works_with_the_real_plan_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            _write_state(
                home / "Library/Application Support/Microsoft Edge",
                {"Default": {"name": "Work"}},
            )
            spec = BrowserSpec(profile="Work")
            plan = plan_launch(
                "https://example.com",
                spec,
                platform="darwin",
                home=home,
                find_app=lambda _a: "/Applications/Microsoft Edge.app",
                default_browser=lambda: "com.microsoft.edgemac",
            )
            self.assertEqual(plan.app, "edge")
            self.assertEqual(plan.profile_dir, "Default")
            self.assertIn("--profile-directory=Default", plan.argv)
            # The profile name exists only in the other browser: a clear error.
            _write_state(
                home / "Library/Application Support/Google/Chrome",
                {"Default": {"name": "OnlyInChrome"}},
            )
            with self.assertRaisesRegex(BrowserLaunchError, "no profile named"):
                plan_launch(
                    "https://example.com",
                    BrowserSpec(profile="OnlyInChrome"),
                    platform="darwin",
                    home=home,
                    find_app=lambda _a: "/Applications/X.app",
                    default_browser=lambda: "com.microsoft.edgemac",
                )

    def test_profile_only_default_needs_edge_or_chrome_as_system_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            path = home / "config.toml"
            path.write_text('default_browser_profile = "Work"\n', encoding="utf-8")
            _write_state(
                home / "Library/Application Support/Microsoft Edge",
                {"Default": {"name": "Work"}},
            )
            with (
                patch("app.browser_default.sys.platform", "darwin"),
                patch(
                    "app.browser_launch.detect_default_browser_id",
                    return_value="com.apple.Safari",
                ),
                patch("app.browser_launch.Path.home", return_value=home),
                patch("app.browser_launch.sys.platform", "darwin"),
                patch(
                    "app.browser_launch.find_installed_app",
                    return_value="/Applications/X.app",
                ),
                patch("app.cli.launch") as launch,
                self.assertRaisesRegex(
                    BrowserLaunchError, "needs the default browser to be Edge"
                ),
            ):
                open_url("https://example.com", env_path=path)
        launch.assert_not_called()

    def test_profile_only_default_via_open_url_fails_when_only_the_other_browser_has_it(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            path = home / "config.toml"
            path.write_text(
                'default_browser_profile = "OnlyChrome"\n', encoding="utf-8"
            )
            _write_state(
                home / "Library/Application Support/Microsoft Edge",
                {"Default": {"name": "Work"}},
            )
            _write_state(
                home / "Library/Application Support/Google/Chrome",
                {"Default": {"name": "OnlyChrome"}},
            )
            with (
                patch("app.browser_default.sys.platform", "darwin"),
                patch(
                    "app.browser_launch.detect_default_browser_id",
                    return_value="com.microsoft.edgemac",
                ),
                patch("app.browser_launch.Path.home", return_value=home),
                patch("app.browser_launch.sys.platform", "darwin"),
                patch(
                    "app.browser_launch.find_installed_app",
                    return_value="/Applications/X.app",
                ),
                patch("app.cli.launch") as launch,
                self.assertRaisesRegex(BrowserLaunchError, "no profile named"),
            ):
                open_url("https://example.com", env_path=path)
        launch.assert_not_called()

    def test_when_every_browser_fails_the_first_error_is_raised(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            edge = home / "Library/Application Support/Microsoft Edge"
            edge.mkdir(parents=True)
            (edge / "Local State").write_text("{not json", encoding="utf-8")
            with self.assertRaises(BrowserLaunchError):
                installed_browser_profiles(
                    platform="darwin",
                    home=home,
                    find_app=lambda _a: "/Applications/X",
                )


class BrowsersCommandTests(SimpleTestCase):
    def _run(
        self, args: list[str], *, answers: tuple[str, ...] = (), default: str = ""
    ) -> tuple[int, str, str]:
        lines: list[str] = []
        pending = list(answers)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            if default:
                path.write_text(default, encoding="utf-8")
            with (
                patch("app.browsers.sys.platform", "darwin"),
                patch("app.browsers.detect_default_browser_id", return_value=None),
            ):
                code = run_browsers(
                    args,
                    env_path=path,
                    print_fn=lines.append,
                    prompt_fn=lambda _m: pending.pop(0),
                    found=EDGE,
                )
            saved = path.read_text(encoding="utf-8") if path.exists() else ""
        return code, "\n".join(lines), saved

    def test_lists_profiles_with_accounts_directories_and_current_default(self) -> None:
        code, text, _ = self._run(
            [],
            default=(
                'default_browser = "edge"\n'
                'default_browser_profile = "hcma @ BRK Tech"\n'
            ),
        )
        self.assertEqual(code, 0)
        self.assertIn("hcma @ BRK Tech", text)
        self.assertIn("me@brk.tech", text)
        self.assertIn("[Default]", text)
        self.assertIn("[Profile 1]", text)
        self.assertIn("default for unpinned shortcuts", text)
        self.assertIn(
            'Default for unpinned shortcuts: Edge, profile "hcma @ BRK Tech"', text
        )

    def test_list_keeps_the_saved_default_visible_when_discovery_fails(self) -> None:
        lines: list[str] = []
        with (
            patch("app.browsers.sys.platform", "darwin"),
            patch(
                "app.browsers.installed_browser_profiles",
                side_effect=BrowserProfilesAccessError("blocked"),
            ),
            tempfile.TemporaryDirectory() as tmp,
        ):
            path = Path(tmp) / "config.toml"
            path.write_text(
                'default_browser = "edge"\ndefault_browser_profile = "Work"\n',
                encoding="utf-8",
            )
            code = run_browsers([], env_path=path, print_fn=lines.append)
        self.assertEqual(code, 1)
        self.assertIn(
            'Default for unpinned shortcuts: Edge, profile "Work"', "\n".join(lines)
        )

    def test_list_says_not_set_when_there_is_no_default(self) -> None:
        _, text, _ = self._run([])
        self.assertIn("Default for unpinned shortcuts: not set", text)

    def test_default_command_saves_the_chosen_profile(self) -> None:
        code, text, saved = self._run(["default"], answers=("1",))
        self.assertEqual(code, 0)
        self.assertIn('default_browser = "edge"', saved)
        self.assertIn('default_browser_profile = "hcma @ BRK Tech"', saved)
        self.assertIn("✓ Default for unpinned shortcuts", text)

    def test_default_command_clear_and_keep(self) -> None:
        existing = 'default_browser = "edge"\ndefault_browser_profile = "X"\n'
        _, _, cleared = self._run(["default"], answers=("c",), default=existing)
        self.assertNotIn("default_browser", cleared)
        _, text, kept = self._run(["default"], answers=("",), default=existing)
        self.assertEqual(kept, existing)
        self.assertIn("unchanged", text)

    def test_default_command_reprompts_on_bad_input(self) -> None:
        _, text, saved = self._run(["default"], answers=("9", "x", "2"))
        self.assertIn("Enter a number from 1 to 2", text)
        self.assertIn('default_browser_profile = "hcma @ BRK Commons"', saved)

    def test_default_can_be_cleared_when_no_profiles_are_found(self) -> None:
        lines: list[str] = []
        with (
            patch("app.browsers.sys.platform", "darwin"),
            tempfile.TemporaryDirectory() as tmp,
        ):
            path = Path(tmp) / "config.toml"
            path.write_text(
                'default_browser = "edge"\ndefault_browser_profile = "Gone"\n',
                encoding="utf-8",
            )
            code = run_browsers(
                ["default"],
                env_path=path,
                print_fn=lines.append,
                prompt_fn=lambda _m: "c",
                found={},
            )
            saved = path.read_text(encoding="utf-8")
        self.assertEqual(code, 0)
        self.assertNotIn("default_browser", saved)
        self.assertIn("No profiles found for the saved default", "\n".join(lines))

    def test_default_can_be_cleared_when_discovery_is_denied(self) -> None:
        lines: list[str] = []
        with (
            patch("app.browsers.sys.platform", "darwin"),
            patch(
                "app.browsers.installed_browser_profiles",
                side_effect=BrowserProfilesAccessError("blocked: Full Disk Access"),
            ),
            tempfile.TemporaryDirectory() as tmp,
        ):
            path = Path(tmp) / "config.toml"
            path.write_text(
                'default_browser = "edge"\ndefault_browser_profile = "Gone"\n',
                encoding="utf-8",
            )
            code = run_browsers(
                ["default"],
                env_path=path,
                print_fn=lines.append,
                prompt_fn=lambda _m: "c",
            )
            saved = path.read_text(encoding="utf-8")
        self.assertEqual(code, 0)
        self.assertIn("Full Disk Access", lines[0])
        self.assertIn(
            "Could not list profiles to check the saved default", "\n".join(lines)
        )
        self.assertNotIn("may have been removed", "\n".join(lines))
        self.assertNotIn("default_browser", saved)

    def test_denied_discovery_without_a_saved_default_is_an_error(self) -> None:
        lines: list[str] = []
        with (
            patch("app.browsers.sys.platform", "darwin"),
            patch(
                "app.browsers.installed_browser_profiles",
                side_effect=BrowserProfilesAccessError("blocked"),
            ),
            tempfile.TemporaryDirectory() as tmp,
        ):
            code = run_browsers(
                ["default"],
                env_path=Path(tmp) / "c.toml",
                print_fn=lines.append,
                prompt_fn=lambda _m: self.fail("must not prompt"),
            )
        self.assertEqual(code, 1)

    def test_save_failure_is_an_error_message_not_a_traceback(self) -> None:
        lines: list[str] = []
        with (
            patch("app.browsers.sys.platform", "darwin"),
            patch(
                "app.browsers.save_default_browser", side_effect=OSError("read-only")
            ),
            tempfile.TemporaryDirectory() as tmp,
        ):
            code = run_browsers(
                ["default"],
                env_path=Path(tmp) / "c.toml",
                print_fn=lines.append,
                prompt_fn=lambda _m: "1",
                found=EDGE,
            )
        self.assertEqual(code, 1)
        self.assertIn("could not save", "\n".join(lines))

    def test_prompt_only_offers_clear_when_there_is_a_default_to_clear(self) -> None:
        lines: list[str] = []
        prompts: list[str] = []
        answers = ["", ""]
        with (
            patch("app.browsers.sys.platform", "darwin"),
            tempfile.TemporaryDirectory() as tmp,
        ):
            path = Path(tmp) / "config.toml"
            run_browsers(
                ["default"],
                env_path=path,
                print_fn=lines.append,
                prompt_fn=lambda m: prompts.append(m) or answers.pop(0),
                found=EDGE,
            )
            path.write_text(
                'default_browser = "edge"\ndefault_browser_profile = "X"\n',
                encoding="utf-8",
            )
            run_browsers(
                ["default"],
                env_path=path,
                print_fn=lines.append,
                prompt_fn=lambda m: prompts.append(m) or answers.pop(0),
                found=EDGE,
            )
        self.assertNotIn("clear", prompts[0])
        self.assertIn("c to clear", prompts[1])
        self.assertIn("OK, no default chosen", "\n".join(lines))

    def test_clear_without_a_saved_default_says_nothing_was_cleared(self) -> None:
        # "c" is not offered without a default, so it is rejected, not honored.
        _, text, saved = self._run(["default"], answers=("c", ""))
        self.assertIn("Enter a number from 1 to 2", text)
        self.assertNotIn("Cleared", text)
        self.assertEqual(saved, "")

    def test_no_profiles_and_no_default_is_an_error(self) -> None:
        lines: list[str] = []
        with (
            patch("app.browsers.sys.platform", "darwin"),
            tempfile.TemporaryDirectory() as tmp,
        ):
            code = run_browsers(
                ["default"],
                env_path=Path(tmp) / "c.toml",
                print_fn=lines.append,
                found={},
            )
        self.assertEqual(code, 1)
        self.assertIn("No Edge or Chrome profiles found", lines[0])

    def test_malformed_config_is_an_error_not_a_traceback(self) -> None:
        lines: list[str] = []
        with (
            patch("app.browsers.sys.platform", "darwin"),
            tempfile.TemporaryDirectory() as tmp,
        ):
            path = Path(tmp) / "config.toml"
            path.write_text("this is = = not toml\n", encoding="utf-8")
            code = run_browsers([], env_path=path, print_fn=lines.append, found=EDGE)
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].startswith("error:"))

    def test_default_needs_a_terminal_even_when_a_prompt_function_is_supplied(
        self,
    ) -> None:
        lines: list[str] = []
        with (
            patch("app.browsers.sys.platform", "darwin"),
            tempfile.TemporaryDirectory() as tmp,
        ):
            code = run_browsers(
                ["default"],
                env_path=Path(tmp) / "c.toml",
                print_fn=lines.append,
                prompt_fn=lambda _m: self.fail("must not prompt"),
                found=EDGE,
                interactive=False,
            )
        self.assertEqual(code, 1)
        self.assertIn("needs a terminal", lines[0])

    def test_ctrl_c_at_the_prompt_aborts_without_a_decision(self) -> None:
        for error in (KeyboardInterrupt(), EOFError()):
            with self.subTest(error=type(error).__name__):
                lines: list[str] = []

                def interrupted(_m: str, exc: BaseException = error) -> str:
                    raise exc

                with (
                    patch("app.browsers.sys.platform", "darwin"),
                    tempfile.TemporaryDirectory() as tmp,
                ):
                    path = Path(tmp) / "config.toml"
                    code = run_browsers(
                        ["default"],
                        env_path=path,
                        print_fn=lines.append,
                        prompt_fn=interrupted,
                        found=EDGE,
                    )
                    self.assertFalse(path.exists())
                self.assertEqual(code, 1)
                self.assertIn("Cancelled; nothing was changed", "\n".join(lines))
                self.assertNotIn("OK, no default chosen", "\n".join(lines))

    def test_unknown_arguments_print_usage(self) -> None:
        code, text, _ = self._run(["bogus"])
        self.assertEqual(code, 2)
        self.assertIn("usage: bunnify browsers", text)

    def test_unsupported_platform(self) -> None:
        lines: list[str] = []
        with patch("app.browsers.sys.platform", "linux"):
            code = run_browsers([], print_fn=lines.append, theme=COLORS)
        self.assertEqual(code, 1)
        self.assertIn("only supported on macOS and Windows", lines[0])

    def test_access_error_is_reported_with_exit_1(self) -> None:
        lines: list[str] = []
        with (
            patch("app.browsers.sys.platform", "darwin"),
            patch(
                "app.browsers.installed_browser_profiles",
                side_effect=BrowserProfilesAccessError("blocked: Full Disk Access"),
            ),
            tempfile.TemporaryDirectory() as tmp,
        ):
            code = run_browsers(
                [], env_path=Path(tmp) / "c.toml", print_fn=lines.append
            )
        self.assertEqual(code, 1)
        self.assertIn("Full Disk Access", lines[0])

    def test_duplicate_names_cannot_be_chosen(self) -> None:
        dup = {
            "edge": [
                ProfileInfo("Default", "Same"),
                ProfileInfo("Profile 1", "Same"),
                ProfileInfo("Profile 2", "Unique"),
            ]
        }
        lines: list[str] = []
        pending = ["1", "3"]
        with (
            patch("app.browsers.sys.platform", "darwin"),
            tempfile.TemporaryDirectory() as tmp,
        ):
            path = Path(tmp) / "config.toml"
            run_browsers(
                ["default"],
                env_path=path,
                print_fn=lines.append,
                prompt_fn=lambda _m: pending.pop(0),
                found=dup,
            )
            saved = path.read_text(encoding="utf-8")
        text = "\n".join(lines)
        self.assertIn("names 2 Edge profiles", text)
        self.assertIn('default_browser_profile = "Unique"', saved)


class InstallerStepTests(SimpleTestCase):
    def _offer(
        self,
        *,
        answer: str = "",
        config: str = "",
        found: dict[str, list[ProfileInfo]] | None = None,
    ) -> tuple[list[str], list[str], str]:
        lines: list[str] = []
        prompts: list[str] = []

        def ask(message: str) -> str:
            prompts.append(message)
            return answer

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            if config:
                path.write_text(config, encoding="utf-8")
            with patch("app.browsers.sys.platform", "darwin"):
                offer_default_profile(
                    ask=ask,
                    log=lines.append,
                    colors=COLORS,
                    env_path=path,
                    found=EDGE if found is None else found,
                )
            saved = path.read_text(encoding="utf-8") if path.exists() else ""
        return lines, prompts, saved

    def test_lists_profiles_and_saves_the_chosen_one(self) -> None:
        lines, prompts, saved = self._offer(answer="2")
        text = "\n".join(lines)
        self.assertIn("Default browser profile", text)
        self.assertIn("hcma @ BRK Commons", text)
        self.assertEqual(len(prompts), 1)
        self.assertIn("n to never ask", prompts[0])
        self.assertIn('default_browser_profile = "hcma @ BRK Commons"', saved)

    def test_installer_prompt_does_not_accept_the_clear_answer(self) -> None:
        lines: list[str] = []
        answers = ["c", ""]
        with (
            patch("app.browsers.sys.platform", "darwin"),
            tempfile.TemporaryDirectory() as tmp,
        ):
            offer_default_profile(
                ask=lambda _m: answers.pop(0),
                log=lines.append,
                colors=COLORS,
                env_path=Path(tmp) / "c.toml",
                found=EDGE,
            )
        self.assertIn("Enter a number from 1 to 2", "\n".join(lines))
        self.assertNotIn("Cleared", "\n".join(lines))

    def test_save_failure_never_fails_the_installer(self) -> None:
        lines: list[str] = []
        with (
            patch("app.browsers.sys.platform", "darwin"),
            patch(
                "app.browsers.save_default_browser", side_effect=OSError("read-only")
            ),
            tempfile.TemporaryDirectory() as tmp,
        ):
            offer_default_profile(
                ask=lambda _m: "1",
                log=lines.append,
                colors=COLORS,
                env_path=Path(tmp) / "c.toml",
                found=EDGE,
            )
        self.assertIn("Could not save the default browser profile", "\n".join(lines))

    def test_superscript_digits_are_not_a_crash(self) -> None:
        lines: list[str] = []
        answers = ["²", ""]
        with (
            patch("app.browsers.sys.platform", "darwin"),
            tempfile.TemporaryDirectory() as tmp,
        ):
            offer_default_profile(
                ask=lambda _m: answers.pop(0),
                log=lines.append,
                colors=COLORS,
                env_path=Path(tmp) / "c.toml",
                found=EDGE,
            )
        self.assertIn("Enter a number from 1 to 2", "\n".join(lines))

    def test_ctrl_c_in_the_installer_is_a_cancel_not_decide_later(self) -> None:
        lines: list[str] = []

        def interrupted(_m: str) -> str:
            raise KeyboardInterrupt

        with (
            patch("app.browsers.sys.platform", "darwin"),
            tempfile.TemporaryDirectory() as tmp,
        ):
            path = Path(tmp) / "config.toml"
            offer_default_profile(
                ask=interrupted,
                log=lines.append,
                colors=COLORS,
                env_path=path,
                found=EDGE,
            )
            self.assertFalse(path.exists())
        self.assertIn("Cancelled; nothing was changed", "\n".join(lines))
        self.assertNotIn("OK, no default chosen", "\n".join(lines))

    def test_enter_decides_later_and_saves_nothing(self) -> None:
        lines, _, saved = self._offer(answer="")
        self.assertEqual(saved, "")
        self.assertIn("OK, no default chosen", "\n".join(lines))
        self.assertNotIn("not set (unchanged)", "\n".join(lines))

    def test_n_opts_out_and_is_remembered(self) -> None:
        lines, _, saved = self._offer(answer="n")
        self.assertIn("default_browser_prompt = false", saved)
        self.assertIn("will not ask again", "\n".join(lines))
        lines_again, prompts, _ = self._offer(config=saved, answer="1")
        self.assertEqual(prompts, [])
        self.assertEqual(lines_again, [])

    def test_already_configured_just_reports_it(self) -> None:
        lines, prompts, _ = self._offer(
            config='default_browser = "edge"\ndefault_browser_profile = "Work"\n'
        )
        self.assertEqual(prompts, [])
        self.assertIn('Edge, profile "Work"', "\n".join(lines))

    def test_no_profiles_found_stays_silent(self) -> None:
        lines, prompts, _ = self._offer(found={})
        self.assertEqual((lines, prompts), ([], []))

    def test_access_error_is_skipped_with_the_reason(self) -> None:
        lines: list[str] = []
        with (
            patch("app.browsers.sys.platform", "darwin"),
            patch(
                "app.browsers.installed_browser_profiles",
                side_effect=BrowserProfilesAccessError("blocked: Full Disk Access"),
            ),
            tempfile.TemporaryDirectory() as tmp,
        ):
            offer_default_profile(
                ask=lambda _m: self.fail("must not prompt"),
                log=lines.append,
                colors=COLORS,
                env_path=Path(tmp) / "c.toml",
            )
        self.assertIn("Skipping the default browser profile step", lines[0])
        self.assertIn("Full Disk Access", lines[0])

    def test_malformed_config_is_skipped_with_the_reason(self) -> None:
        lines, prompts, _ = self._offer(config="not = = toml\n")
        self.assertEqual(prompts, [])
        self.assertIn("Skipping the default browser profile step", lines[0])

    def test_unsupported_platform_does_nothing(self) -> None:
        with patch("app.browsers.sys.platform", "linux"):
            offer_default_profile(
                ask=lambda _m: self.fail("must not prompt"),
                log=lambda _l: self.fail("must not log"),
                colors=COLORS,
            )


class ModuleSurfaceTests(SimpleTestCase):
    def test_launch_module_exports_what_the_features_use(self) -> None:
        for name in (
            "ProfileInfo",
            "BrowserProfilesAccessError",
            "installed_browser_profiles",
            "list_profile_details",
        ):
            self.assertTrue(hasattr(browser_launch, name), name)

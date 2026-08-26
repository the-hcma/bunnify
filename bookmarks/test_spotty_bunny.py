from __future__ import annotations

import logging
import os
import subprocess
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from django.test import SimpleTestCase

from app.spotty_bunny_agent import TccStatus
from app.spotty_bunny_cli import (
    LOG_ENV_VAR,
    SpottyBunnyEventTapError,
    main,
    run_spotty_bunny,
)
from app.spotty_bunny_history import (
    HistoryNavigator,
    append_history_line,
    apply_history_selector,
    load_history_lines,
)
from app.spotty_bunny_hotkey import (
    CONTROL_LEFT_KEYCODE,
    CONTROL_RIGHT_KEYCODE,
    ESCAPE_KEYCODE,
    PAGE_DOWN_KEYCODE,
    PAGE_UP_KEYCODE,
    TAB_KEYCODE,
    ChordTracker,
    apply_control_event,
    apply_hid_snapshot,
    describe_key,
    page_selector_for_keycode,
    resolve_control_snapshot,
)
from app.spotty_bunny_quit import (
    WAKE_EVENT_SELECTOR,
    post_application_wake_event,
    quit_ns_app,
)


class SpottyBunnyCliTests(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        log_dir = TemporaryDirectory()
        self.addCleanup(log_dir.cleanup)
        self.log_root = Path(log_dir.name)
        self.log_file = self.log_root / "spotty-bunny.log"
        env_patch = patch.dict(os.environ, {LOG_ENV_VAR: ""}, clear=False)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        data_patch = patch("app.spotty_bunny_cli.data_dir", return_value=self.log_root)
        data_patch.start()
        self.addCleanup(data_patch.stop)

    def tearDown(self) -> None:
        for name in ("app.spotty_bunny_app", "app.spotty_bunny_cli"):
            logger = logging.getLogger(name)
            for handler in logger.handlers:
                handler.close()
            logger.handlers.clear()
        super().tearDown()

    def test_default_log_file_is_created(self) -> None:
        stderr = StringIO()
        with (
            patch("app.spotty_bunny_cli.sys.platform", "linux"),
            patch("app.spotty_bunny_cli.sys.stderr", stderr),
        ):
            self.assertEqual(main([]), 1)
        self.assertTrue(self.log_file.is_file())
        self.assertIn(str(self.log_file), stderr.getvalue())

    def test_default_log_level_is_info(self) -> None:
        stderr = StringIO()
        with (
            patch("app.spotty_bunny_cli.sys.platform", "linux"),
            patch("app.spotty_bunny_cli.sys.stderr", stderr),
        ):
            self.assertEqual(main([]), 1)
        self.assertEqual(
            logging.getLogger("app.spotty_bunny_app").level,
            logging.INFO,
        )
        self.assertEqual(
            logging.getLogger("app.spotty_bunny_cli").level,
            logging.INFO,
        )

    def test_env_log_file(self) -> None:
        custom = self.log_root / "from-env.log"
        stderr = StringIO()
        with (
            patch.dict(os.environ, {LOG_ENV_VAR: str(custom)}),
            patch("app.spotty_bunny_cli.sys.platform", "linux"),
            patch("app.spotty_bunny_cli.sys.stderr", stderr),
        ):
            self.assertEqual(main(["--verbose"]), 1)
        self.assertIn("spotty-bunny starting", custom.read_text(encoding="utf-8"))

    def test_explicit_log_file_receives_debug(self) -> None:
        custom = self.log_root / "custom.log"
        stderr = StringIO()
        with (
            patch("app.spotty_bunny_cli.sys.platform", "linux"),
            patch("app.spotty_bunny_cli.sys.stderr", stderr),
        ):
            self.assertEqual(main(["--verbose", "--log-file", str(custom)]), 1)
        self.assertIn("spotty-bunny starting", custom.read_text(encoding="utf-8"))
        self.assertIn("log_level=DEBUG", custom.read_text(encoding="utf-8"))

    def test_help_exits_zero(self) -> None:
        stdout = StringIO()
        with (
            patch("sys.stdout", stdout),
            self.assertRaises(SystemExit) as raised,
        ):
            main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        help_text = stdout.getvalue()
        self.assertIn("search box", help_text)
        self.assertIn("spotty-bunny", help_text)
        self.assertIn("--log-file", help_text)
        self.assertIn("--log-level", help_text)
        self.assertIn("--verbose", help_text)
        self.assertIn("install", help_text)
        self.assertIn("uninstall", help_text)
        self.assertIn("LaunchAgent", help_text)

    def test_log_level_sets_logger(self) -> None:
        stderr = StringIO()
        with (
            patch("app.spotty_bunny_cli.sys.platform", "linux"),
            patch("app.spotty_bunny_cli.sys.stderr", stderr),
        ):
            self.assertEqual(main(["--log-level", "INFO"]), 1)
        self.assertEqual(
            logging.getLogger("app.spotty_bunny_app").level,
            logging.INFO,
        )
        self.assertEqual(
            logging.getLogger("app.spotty_bunny_cli").level,
            logging.INFO,
        )

    def test_missing_pyobjc_prints_extra_hint(self) -> None:
        def boom() -> int:
            raise ImportError("No module named 'Cocoa'")

        stderr = StringIO()
        with (
            patch("app.spotty_bunny_cli.sys.platform", "darwin"),
            patch("app.spotty_bunny_cli._load_run_spotty_bunny_app", side_effect=boom),
            patch("app.spotty_bunny_cli.sys.stderr", stderr),
        ):
            self.assertEqual(run_spotty_bunny(), 1)
        self.assertIn("bunnify[macos]", stderr.getvalue())
        self.assertIn("--force", stderr.getvalue())
        self.assertIn("bunnify onboard", stderr.getvalue())

    def test_not_macos_prints_hint(self) -> None:
        stderr = StringIO()
        with (
            patch("app.spotty_bunny_cli.sys.platform", "linux"),
            patch("app.spotty_bunny_cli.sys.stderr", stderr),
        ):
            self.assertEqual(main([]), 1)
        self.assertIn("only available on macOS", stderr.getvalue())

    def test_spotty_bunny_shortcut_dispatches_extra_args(self) -> None:
        from app.cli import main as cli_main

        with patch("app.spotty_bunny_cli.main", return_value=1) as spotty:
            result = CliRunner().invoke(cli_main, ["spotty-bunny", "foo"])

        self.assertEqual(result.exit_code, 1, result.output)
        spotty.assert_called_once_with(["foo"])

    def test_spotty_bunny_shortcut_dispatches_to_cli(self) -> None:
        from app.cli import main as cli_main

        with patch("app.spotty_bunny_cli.main", return_value=1) as spotty:
            result = CliRunner().invoke(cli_main, ["spotty-bunny"])

        self.assertEqual(result.exit_code, 1, result.output)
        spotty.assert_called_once_with([])

    def test_install_subcommand_does_not_start_overlay(self) -> None:
        with patch("app.spotty_bunny_agent.install_agent", return_value=0) as inst:
            self.assertEqual(main(["install"]), 0)
        inst.assert_called_once_with()

    def test_bunnify_spotty_bunny_install_forwards(self) -> None:
        from app.cli import main as cli_main

        with patch("app.spotty_bunny_cli.main", return_value=0) as spotty:
            result = CliRunner().invoke(cli_main, ["spotty-bunny", "install"])

        self.assertEqual(result.exit_code, 0, result.output)
        spotty.assert_called_once_with(["install"])

    def test_unknown_subcommand_prints_usage(self) -> None:
        stderr = StringIO()
        with patch("app.spotty_bunny_cli.sys.stderr", stderr):
            self.assertEqual(main(["not-a-command"]), 2)
        self.assertIn("unknown command", stderr.getvalue())
        self.assertIn("install", stderr.getvalue())

    def test_tap_failure_prints_permission_hint(self) -> None:
        def fail_tap() -> int:
            raise SpottyBunnyEventTapError("event tap was not created")

        stderr = StringIO()
        with (
            patch("app.spotty_bunny_cli.sys.platform", "darwin"),
            patch(
                "app.spotty_bunny_cli._load_run_spotty_bunny_app",
                return_value=fail_tap,
            ),
            patch("app.spotty_bunny_cli.sys.stderr", stderr),
        ):
            self.assertEqual(run_spotty_bunny(), 1)
        self.assertIn("Accessibility", stderr.getvalue())
        self.assertIn("Input Monitoring", stderr.getvalue())

    def test_unwritable_log_file_falls_back_to_stderr(self) -> None:
        blocker = self.log_root / "not-a-directory"
        blocker.write_text("x", encoding="utf-8")
        custom = blocker / "spotty-bunny.log"
        stderr = StringIO()
        with (
            patch("app.spotty_bunny_cli.sys.platform", "linux"),
            patch("app.spotty_bunny_cli.sys.stderr", stderr),
        ):
            self.assertEqual(main(["--log-file", str(custom)]), 1)
        text = stderr.getvalue()
        self.assertIn("cannot write log file", text)
        self.assertIn("logging to stderr only", text)
        self.assertIn("only available on macOS", text)

    def test_verbose_overrides_log_level(self) -> None:
        stderr = StringIO()
        with (
            patch("app.spotty_bunny_cli.sys.platform", "linux"),
            patch("app.spotty_bunny_cli.sys.stderr", stderr),
        ):
            self.assertEqual(main(["--verbose", "--log-level", "ERROR"]), 1)
        self.assertEqual(
            logging.getLogger("app.spotty_bunny_app").level,
            logging.DEBUG,
        )
        self.assertEqual(
            logging.getLogger("app.spotty_bunny_cli").level,
            logging.DEBUG,
        )

    def test_verbose_writes_debug_to_default_log_file(self) -> None:
        stderr = StringIO()
        with (
            patch("app.spotty_bunny_cli.sys.platform", "linux"),
            patch("app.spotty_bunny_cli.sys.stderr", stderr),
        ):
            self.assertEqual(main(["--verbose"]), 1)
        logged = self.log_file.read_text(encoding="utf-8")
        self.assertIn("spotty-bunny starting", logged)
        self.assertIn("log_level=DEBUG", logged)


class SpottyBunnyAboutInfoTests(SimpleTestCase):
    def test_about_link_spans_search_left_to_right(self) -> None:
        from app.spotty_bunny_about_info import about_link_spans

        text = "Repository: github.com/the-hcma/bunnify\nLicense: MIT License"
        spans = about_link_spans(
            text,
            (
                ("github.com/the-hcma/bunnify", "https://github.com/the-hcma/bunnify"),
                ("MIT License", "https://example.com/license"),
            ),
        )
        self.assertEqual(
            spans,
            (
                (
                    text.index("github.com/the-hcma/bunnify"),
                    len("github.com/the-hcma/bunnify"),
                    "https://github.com/the-hcma/bunnify",
                ),
                (
                    text.index("MIT License"),
                    len("MIT License"),
                    "https://example.com/license",
                ),
            ),
        )
        nested = about_link_spans(
            "github.com/the-hcma/bunnify",
            (
                ("github.com/the-hcma/bunnify", "https://repo"),
                ("bunnify", "https://skipped-if-before-cursor"),
            ),
        )
        self.assertEqual(
            nested,
            ((0, len("github.com/the-hcma/bunnify"), "https://repo"),),
        )

    def test_display_user_path_uses_tilde_for_home(self) -> None:
        from app.spotty_bunny_about_info import display_user_path

        home = Path.home()
        nested = home / ".config" / "bunnify" / "bookmarks.json"
        self.assertEqual(
            display_user_path(nested),
            "~/.config/bunnify/bookmarks.json",
        )

    def test_github_https_url_normalizes_remotes(self) -> None:
        from app.spotty_bunny_about_info import github_https_url

        expected = "https://github.com/acme/dots"
        self.assertEqual(github_https_url("git@github.com:acme/dots.git"), expected)
        self.assertEqual(
            github_https_url("https://github.com/acme/dots.git"),
            expected,
        )
        self.assertEqual(
            github_https_url("ssh://git@github.com/acme/dots.git"),
            expected,
        )
        self.assertEqual(
            github_https_url("git://github.com/acme/dots"),
            expected,
        )
        self.assertIsNone(github_https_url("https://gitlab.com/acme/dots.git"))

    def test_github_repo_url_for_path_reads_origin(self) -> None:
        from app.spotty_bunny_about_info import github_repo_url_for_path

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            bookmarks = root / "bookmarks.json"
            bookmarks.write_text("{}", encoding="utf-8")
            (root / ".git").mkdir()
            self.assertEqual(
                github_repo_url_for_path(
                    bookmarks,
                    origin_url_for=lambda _workdir: "git@github.com:acme/dots.git",
                ),
                "https://github.com/acme/dots",
            )

    def test_github_repo_url_for_path_skips_non_git_dirs(self) -> None:
        from app.spotty_bunny_about_info import github_repo_url_for_path

        with TemporaryDirectory() as tmp:
            bookmarks = Path(tmp) / "bookmarks.json"
            bookmarks.write_text("{}", encoding="utf-8")
            self.assertIsNone(github_repo_url_for_path(bookmarks))

    def test_handle_about_link_click_leaves_https_to_appkit(self) -> None:
        from app.spotty_bunny_about_info import handle_about_link_click

        def run(
            _argv: list[str], **_kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            self.fail("https links must not call open -t")
            return subprocess.CompletedProcess([], 1, "", "")

        self.assertFalse(
            handle_about_link_click("https://github.com/the-hcma/bunnify", run=run)
        )

    def test_handle_about_link_click_opens_file_uri(self) -> None:
        from app.spotty_bunny_about_info import handle_about_link_click

        calls: list[list[str]] = []

        def run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, "", "")

        self.assertTrue(handle_about_link_click("file:///tmp/bookmarks.json", run=run))
        self.assertEqual(calls, [["open", "-t", "/tmp/bookmarks.json"]])

    def test_load_about_runtime_info_local_server_and_file_link(self) -> None:
        from app.spotty_bunny_about_info import load_about_runtime_info

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            bookmarks = root / "bookmarks.json"
            bookmarks.write_text("{}", encoding="utf-8")
            env = {
                "BUNNIFY_BASE_URL": "http://127.0.0.1:9000",
                "BUNNIFY_BOOKMARKS": str(bookmarks),
                "BUNNIFY_MODE": "local",
                "XDG_CONFIG_HOME": str(root / "cfg"),
            }
            info = load_about_runtime_info(
                environ=env,
                origin_url_for=lambda _workdir: None,
            )
            self.assertTrue(info.bookmarks_uri.startswith("file:"))
            self.assertIn("bookmarks.json", info.bookmarks_display)
            self.assertIsNone(info.github_url)
            self.assertEqual(
                info.server_display,
                "Local server · http://127.0.0.1:9000",
            )
            self.assertEqual(info.server_url, "http://127.0.0.1:9000")

    def test_load_about_runtime_info_marks_server_skew(self) -> None:
        from unittest.mock import patch

        from app.client import HealthStatus
        from app.spotty_bunny_about_info import load_about_runtime_info

        health = HealthStatus(ok=True, version="0.9.0", commit="oldoldoldold")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            bookmarks = root / "bookmarks.json"
            bookmarks.write_text("{}", encoding="utf-8")
            env = {
                "BUNNIFY_BASE_URL": "http://127.0.0.1:8000",
                "BUNNIFY_BOOKMARKS": str(bookmarks),
                "BUNNIFY_MODE": "local",
                "XDG_CONFIG_HOME": str(root / "cfg"),
            }
            with (
                patch("app.spotty_bunny_about_info.fetch_health", return_value=health),
                patch("app.spotty_bunny_about_info.builds_match", return_value=False),
            ):
                info = load_about_runtime_info(
                    environ=env,
                    origin_url_for=lambda _workdir: None,
                )
            self.assertTrue(info.server_skewed)
            self.assertEqual(info.server_build_label, "0.9.0 (oldoldoldold)")

    def test_load_about_runtime_info_remote_server_and_github(self) -> None:
        from app.spotty_bunny_about_info import load_about_runtime_info

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            bookmarks = root / "bookmarks.json"
            bookmarks.write_text("{}", encoding="utf-8")
            env = {
                "BUNNIFY_BASE_URL": "https://bun.example.com",
                "BUNNIFY_BOOKMARKS": str(bookmarks),
                "BUNNIFY_MODE": "remote",
                "XDG_CONFIG_HOME": str(root / "cfg"),
            }
            info = load_about_runtime_info(
                environ=env,
                origin_url_for=lambda _workdir: "https://github.com/acme/dots.git",
            )
            self.assertEqual(info.github_url, "https://github.com/acme/dots")
            self.assertEqual(info.github_display, "github.com/acme/dots")
            self.assertEqual(
                info.server_display,
                "Remote server · https://bun.example.com",
            )
            self.assertEqual(info.server_url, "https://bun.example.com")

    def test_about_details_text_and_links(self) -> None:
        from app.spotty_bunny_about_info import (
            AboutRuntimeInfo,
            about_details_text_and_links,
        )

        runtime = AboutRuntimeInfo(
            bookmarks_display="~/.config/bunnify/bookmarks.json",
            bookmarks_uri="file:///Users/me/.config/bunnify/bookmarks.json",
            github_display="github.com/acme/repo",
            github_url="https://github.com/acme/repo",
            server_build_label="0.10.0 (abc123456789)",
            server_display="Local server · http://127.0.0.1:8000",
            server_skewed=False,
            server_url="http://127.0.0.1:8000",
        )
        text, links = about_details_text_and_links(runtime)
        self.assertEqual(
            text,
            "Repository: github.com/the-hcma/bunnify\n"
            "License: MIT License\n"
            "Bookmarks: ~/.config/bunnify/bookmarks.json\n"
            "GitHub: github.com/acme/repo\n"
            "Local server · http://127.0.0.1:8000\n"
            "Server build: 0.10.0 (abc123456789)",
        )
        self.assertEqual(
            links,
            (
                (
                    "github.com/the-hcma/bunnify",
                    "https://github.com/the-hcma/bunnify",
                ),
                (
                    "MIT License",
                    "https://github.com/the-hcma/bunnify/blob/main/LICENSE",
                ),
                (
                    "~/.config/bunnify/bookmarks.json",
                    "file:///Users/me/.config/bunnify/bookmarks.json",
                ),
                ("github.com/acme/repo", "https://github.com/acme/repo"),
                ("http://127.0.0.1:8000", "http://127.0.0.1:8000"),
                ("0.10.0 (abc123456789)", "http://127.0.0.1:8000"),
            ),
        )

    def test_about_version_text_and_links(self) -> None:
        from app.spotty_bunny_about_info import about_version_text_and_links

        text, links = about_version_text_and_links("0.7.1", "3222872ccd01")
        self.assertEqual(text, "Version 0.7.1 · commit 3222872ccd01")
        self.assertEqual(
            links,
            (
                ("0.7.1", "https://pypi.org/project/bunnify/0.7.1/"),
                (
                    "3222872ccd01",
                    "https://github.com/the-hcma/bunnify/commit/3222872ccd01",
                ),
            ),
        )
        unknown_text, unknown_links = about_version_text_and_links("0.7.1", "unknown")
        self.assertEqual(unknown_text, "Version 0.7.1 · commit unknown")
        self.assertEqual(
            unknown_links,
            (("0.7.1", "https://pypi.org/project/bunnify/0.7.1/"),),
        )

    def test_open_path_in_text_editor_uses_open_t(self) -> None:
        from app.spotty_bunny_about_info import open_path_in_text_editor

        calls: list[list[str]] = []

        def run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, "", "")

        path = Path("/tmp/bookmarks.json")
        self.assertTrue(open_path_in_text_editor(path, run=run))
        self.assertEqual(calls, [["open", "-t", str(path)]])

    def test_path_from_file_uri_decodes_path(self) -> None:
        from app.spotty_bunny_about_info import path_from_file_uri

        self.assertEqual(
            path_from_file_uri("file:///tmp/bookmarks.json"),
            Path("/tmp/bookmarks.json"),
        )
        self.assertIsNone(path_from_file_uri("https://example.com/x"))


class SpottyBunnyAgentTests(SimpleTestCase):
    def test_bootout_loaded_agent_issues_bootout_when_loaded(self) -> None:
        from app.spotty_bunny_agent import bootout_loaded_agent

        ctl = _FakeLaunchctl()
        ctl.loaded = True
        self.assertTrue(bootout_loaded_agent(launchctl=ctl))
        self.assertTrue(any(call[1] == "bootout" for call in ctl.calls))
        self.assertFalse(ctl.loaded)

    def test_bootout_loaded_agent_skips_when_not_loaded(self) -> None:
        from app.spotty_bunny_agent import bootout_loaded_agent

        ctl = _FakeLaunchctl()
        ctl.loaded = False
        self.assertFalse(bootout_loaded_agent(launchctl=ctl))
        self.assertFalse(any(call[1] == "bootout" for call in ctl.calls))

    def test_format_agent_plist_matches_example_placeholders(self) -> None:
        from app.spotty_bunny_agent import (
            AGENT_LABEL,
            format_agent_plist,
            launchd_path_for_home,
        )

        root = Path(__file__).resolve().parents[1]
        example = (
            root / "etc" / "launchd" / "com.thehcma.bunnify.spotty-bunny.plist.example"
        ).read_text(encoding="utf-8")
        home = Path("/Users/test")
        expected = (
            example.replace(
                "    <string>__SPOTTY_BUNNY__</string>",
                "    <string>/opt/spotty-bunny</string>",
            )
            .replace("__HOME__", "/Users/test")
            .replace("__LAUNCHD_PATH__", launchd_path_for_home(home))
        )
        self.assertEqual(
            format_agent_plist(
                home=home,
                program_arguments=["/opt/spotty-bunny"],
            ),
            expected,
        )
        self.assertIn(AGENT_LABEL, expected)
        self.assertIn("<key>KeepAlive</key>", expected)
        self.assertIn("<key>RunAtLoad</key>", expected)
        self.assertIn("<key>EnvironmentVariables</key>", expected)
        self.assertIn("/opt/homebrew/bin", expected)

    def test_format_agent_plist_supports_module_argv(self) -> None:
        from app.spotty_bunny_agent import format_agent_plist

        text = format_agent_plist(
            home=Path("/Users/test"),
            program_arguments=[
                "/usr/bin/python3",
                "-m",
                "app.spotty_bunny_cli",
            ],
        )
        self.assertIn("<string>/usr/bin/python3</string>", text)
        self.assertIn("<string>-m</string>", text)
        self.assertIn("<string>app.spotty_bunny_cli</string>", text)

    def test_status_handles_missing_macos_extra(self) -> None:
        from app.spotty_bunny_agent import AGENT_LABEL, format_agent_plist, status_agent

        def _raise_import(_program: Path) -> TccStatus:
            raise ImportError("PyObjC")

        ctl = _FakeLaunchctl()
        stderr = StringIO()
        stdout = StringIO()
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            plist = home / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
            plist.parent.mkdir(parents=True)
            program = home / "spotty-bunny"
            _write_executable(program)
            plist.write_text(
                format_agent_plist(
                    home=home,
                    program_arguments=[str(program)],
                ),
                encoding="utf-8",
            )
            with patch(
                "app.spotty_bunny_agent.spotty_bunny_is_running",
                return_value=False,
            ):
                code = status_agent(
                    home=home,
                    launchctl=ctl,
                    platform="darwin",
                    print_err=stderr.write,
                    print_fn=lambda line: stdout.write(line + "\n"),
                    probe_tcc=_raise_import,
                    program=program,
                )
            self.assertEqual(code, 1)
            self.assertIn("macos", stderr.getvalue().lower())
            self.assertIn("accessibility: no", stdout.getvalue())

    def test_install_bootstraps_when_tcc_is_current(self) -> None:
        from app.spotty_bunny_agent import AGENT_LABEL, install_agent

        ctl = _FakeLaunchctl()
        tcc = _FakeTcc(TccStatus(True, True))
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            program = home / "bin" / "spotty-bunny"
            _write_executable(program, content="#!/usr/bin/env python3\n")
            stderr = StringIO()
            code = install_agent(
                home=home,
                launchctl=ctl,
                platform="darwin",
                print_err=stderr.write,
                probe_tcc=tcc.probe,
                program=program,
                request_tcc=tcc.request,
                skip_chord_confirm=True,
            )
            plist = home / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
            self.assertEqual(code, 0)
            self.assertTrue(plist.is_file())
            text = plist.read_text(encoding="utf-8")
            self.assertIn(str(program), text)
            self.assertIn("<key>KeepAlive</key>", text)
            self.assertEqual(tcc.probes, 1)
            self.assertEqual(tcc.requests, 0)
            self.assertTrue(any(call[1] == "bootstrap" for call in ctl.calls))

    def test_install_skips_chord_prompt_when_not_tty(self) -> None:
        from unittest.mock import patch

        from app.spotty_bunny_agent import install_agent

        ctl = _FakeLaunchctl()
        tcc = _FakeTcc(TccStatus(True, True))
        prompts: list[str] = []

        def ask(message: str) -> str:
            prompts.append(message)
            return "y"

        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            program = home / "spotty-bunny"
            _write_executable(program, content="#!/opt/venv/bin/python\n")
            with (
                patch("app.spotty_bunny_agent.sys.stdin") as stdin,
                patch("app.spotty_bunny_agent.sys.stdout") as stdout,
            ):
                stdin.isatty.return_value = False
                stdout.isatty.return_value = False
                code = install_agent(
                    home=home,
                    launchctl=ctl,
                    platform="darwin",
                    print_err=lambda _m: None,
                    probe_tcc=tcc.probe,
                    program=program,
                    prompt_fn=ask,
                    request_tcc=tcc.request,
                    skip_chord_confirm=False,
                )
            self.assertEqual(code, 0)
            self.assertEqual(prompts, [])
            self.assertEqual(sum(1 for call in ctl.calls if call[1] == "bootstrap"), 1)

    def test_install_does_not_bootstrap_when_tcc_missing(self) -> None:
        from app.spotty_bunny_agent import AGENT_LABEL, install_agent

        ctl = _FakeLaunchctl()
        tcc = _FakeTcc(TccStatus(False, False), TccStatus(False, False))
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            program = home / "spotty-bunny"
            _write_executable(program, content="#!/opt/venv/bin/python\n")
            stderr = StringIO()
            code = install_agent(
                home=home,
                launchctl=ctl,
                platform="darwin",
                print_err=stderr.write,
                probe_tcc=tcc.probe,
                program=program,
                request_tcc=tcc.request,
            )
            self.assertEqual(code, 1)
            self.assertFalse(
                (home / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist").exists()
            )
            self.assertGreaterEqual(tcc.probes, 2)
            self.assertEqual(tcc.requests, 1)
            self.assertFalse(any(call[1] == "bootstrap" for call in ctl.calls))
            self.assertIn("Privacy & Security", stderr.getvalue())

    def test_install_interactive_tcc_recheck_ctrl_c_cancels(self) -> None:
        from unittest.mock import patch

        from app.spotty_bunny_agent import AGENT_LABEL, install_agent

        ctl = _FakeLaunchctl()
        tcc = _FakeTcc(TccStatus(False, False), TccStatus(False, False))
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            program = home / "spotty-bunny"
            _write_executable(program, content="#!/opt/venv/bin/python\n")
            with (
                patch("app.spotty_bunny_agent.sys.stdin") as stdin,
                patch("app.spotty_bunny_agent.sys.stdout") as stdout,
                patch("builtins.input", side_effect=KeyboardInterrupt),
            ):
                stdin.isatty.return_value = True
                stdout.isatty.return_value = True
                code = install_agent(
                    home=home,
                    launchctl=ctl,
                    platform="darwin",
                    print_err=lambda _m: None,
                    probe_tcc=tcc.probe,
                    program=program,
                    request_tcc=tcc.request,
                )
            self.assertEqual(code, 1)
            self.assertEqual(tcc.probes, 2)
            self.assertFalse(
                (home / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist").exists()
            )

    def test_install_interactive_tcc_recheck_still_missing_after_enter(self) -> None:
        from unittest.mock import patch

        from app.spotty_bunny_agent import AGENT_LABEL, install_agent

        ctl = _FakeLaunchctl()
        tcc = _FakeTcc(
            TccStatus(False, False),
            TccStatus(False, False),
            TccStatus(False, False),
        )
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            program = home / "spotty-bunny"
            _write_executable(program, content="#!/opt/venv/bin/python\n")
            stderr = StringIO()
            with (
                patch("app.spotty_bunny_agent.sys.stdin") as stdin,
                patch("app.spotty_bunny_agent.sys.stdout") as stdout,
                patch("builtins.input", side_effect=["", KeyboardInterrupt]),
            ):
                stdin.isatty.return_value = True
                stdout.isatty.return_value = True
                code = install_agent(
                    home=home,
                    launchctl=ctl,
                    platform="darwin",
                    print_err=stderr.write,
                    probe_tcc=tcc.probe,
                    program=program,
                    request_tcc=tcc.request,
                )
            self.assertEqual(code, 1)
            self.assertGreaterEqual(tcc.probes, 3)
            self.assertFalse(
                (home / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist").exists()
            )

    def test_install_interactive_tcc_recheck_succeeds_after_enter(self) -> None:
        from unittest.mock import patch

        from app.spotty_bunny_agent import install_agent

        ctl = _FakeLaunchctl()
        tcc = _FakeTcc(
            TccStatus(False, False),
            TccStatus(False, False),
            TccStatus(True, True),
        )
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            program = home / "spotty-bunny"
            _write_executable(program, content="#!/opt/venv/bin/python\n")
            with (
                patch("app.spotty_bunny_agent.sys.stdin") as stdin,
                patch("app.spotty_bunny_agent.sys.stdout") as stdout,
                patch("builtins.input", side_effect=["", "y"]),
            ):
                stdin.isatty.return_value = True
                stdout.isatty.return_value = True
                code = install_agent(
                    home=home,
                    launchctl=ctl,
                    platform="darwin",
                    print_err=lambda _m: None,
                    probe_tcc=tcc.probe,
                    program=program,
                    request_tcc=tcc.request,
                )
            self.assertEqual(code, 0)
            self.assertEqual(tcc.probes, 3)
            self.assertEqual(tcc.requests, 1)

    def test_install_interactive_tcc_recheck_with_prompt_fn(self) -> None:
        from unittest.mock import patch

        from app.spotty_bunny_agent import (
            TCC_RECHECK_PROMPT,
            install_agent,
        )

        ctl = _FakeLaunchctl()
        tcc = _FakeTcc(
            TccStatus(False, False),
            TccStatus(False, False),
            TccStatus(True, True),
        )
        prompts: list[str] = []

        def ask(message: str) -> str:
            prompts.append(message)
            return ""

        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            program = home / "spotty-bunny"
            _write_executable(program, content="#!/opt/venv/bin/python\n")
            with (
                patch("app.spotty_bunny_agent.sys.stdin") as stdin,
                patch("app.spotty_bunny_agent.sys.stdout") as stdout,
            ):
                stdin.isatty.return_value = True
                stdout.isatty.return_value = True
                code = install_agent(
                    home=home,
                    launchctl=ctl,
                    platform="darwin",
                    print_err=lambda _m: None,
                    probe_tcc=tcc.probe,
                    program=program,
                    prompt_fn=ask,
                    request_tcc=tcc.request,
                    skip_chord_confirm=True,
                )
            self.assertEqual(code, 0)
            self.assertEqual(prompts, [TCC_RECHECK_PROMPT])

    def test_install_interactive_chord_retry_bounces_until_confirmed(self) -> None:
        from unittest.mock import patch

        from app.spotty_bunny_agent import AGENT_LABEL, install_agent

        ctl = _FakeLaunchctl()
        tcc = _FakeTcc(TccStatus(True, True))
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            program = home / "spotty-bunny"
            _write_executable(program, content="#!/opt/venv/bin/python\n")
            with (
                patch("app.spotty_bunny_agent.sys.stdin") as stdin,
                patch("app.spotty_bunny_agent.sys.stdout") as stdout,
                patch("builtins.input", side_effect=["n", "y"]),
            ):
                stdin.isatty.return_value = True
                stdout.isatty.return_value = True
                code = install_agent(
                    home=home,
                    launchctl=ctl,
                    platform="darwin",
                    print_err=lambda _m: None,
                    probe_tcc=tcc.probe,
                    program=program,
                    request_tcc=tcc.request,
                )
            self.assertEqual(code, 0)
            bootouts = sum(1 for call in ctl.calls if call[1] == "bootout")
            bootstraps = sum(1 for call in ctl.calls if call[1] == "bootstrap")
            self.assertGreaterEqual(bootouts, 2)
            self.assertGreaterEqual(bootstraps, 2)
            self.assertTrue(
                (home / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist").is_file()
            )

    def test_install_rechecks_tcc_after_prompt(self) -> None:
        from app.spotty_bunny_agent import install_agent

        ctl = _FakeLaunchctl()
        tcc = _FakeTcc(TccStatus(False, False), TccStatus(True, True))
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            program = home / "spotty-bunny"
            _write_executable(program, content="#!/opt/venv/bin/python\n")
            code = install_agent(
                home=home,
                launchctl=ctl,
                platform="darwin",
                print_err=lambda _m: None,
                probe_tcc=tcc.probe,
                program=program,
                request_tcc=tcc.request,
                skip_chord_confirm=True,
            )
            self.assertEqual(code, 0)
            self.assertEqual(tcc.requests, 1)
            self.assertEqual(tcc.probes, 2)

    def test_install_not_macos(self) -> None:
        from app.spotty_bunny_agent import install_agent

        stderr = StringIO()
        self.assertEqual(
            install_agent(platform="linux", print_err=stderr.write),
            1,
        )
        self.assertIn("only available on macOS", stderr.getvalue())

    def test_interpreter_for_program_reads_shebang(self) -> None:
        from app.spotty_bunny_agent import interpreter_for_program

        with TemporaryDirectory() as tmp:
            script = Path(tmp) / "spotty-bunny"
            script.write_text(
                "#!/opt/pipx/venvs/bunnify/bin/python\n", encoding="utf-8"
            )
            self.assertEqual(
                interpreter_for_program(script),
                Path("/opt/pipx/venvs/bunnify/bin/python"),
            )

    def test_interpreter_for_program_reads_bash_exec_wrapper(self) -> None:
        from app.spotty_bunny_agent import interpreter_for_program

        with TemporaryDirectory() as tmp:
            script = Path(tmp) / "spotty-bunny"
            script.write_text(
                "#!/usr/bin/env bash\n"
                'exec "/opt/venvs/bunnify/bin/python" -m app.spotty_bunny_cli "$@"\n',
                encoding="utf-8",
            )
            self.assertEqual(
                interpreter_for_program(script),
                Path("/opt/venvs/bunnify/bin/python"),
            )

    def test_interpreter_for_program_reads_pipx_sh_wrapper(self) -> None:
        from app.spotty_bunny_agent import interpreter_for_program

        with TemporaryDirectory() as tmp:
            script = Path(tmp) / "spotty-bunny"
            script.write_text(
                "#!/bin/sh\n"
                "'''exec' '/opt/pipx/venvs/bunnify/bin/python' \"$0\" \"$@\"\n"
                "' '''\n",
                encoding="utf-8",
            )
            self.assertEqual(
                interpreter_for_program(script),
                Path("/opt/pipx/venvs/bunnify/bin/python"),
            )

    def test_interpreter_for_program_expands_home_in_exec_line(self) -> None:
        from app.spotty_bunny_agent import interpreter_for_program

        with TemporaryDirectory() as tmp:
            script = Path(tmp) / "spotty-bunny"
            script.write_text(
                "#!/usr/bin/env bash\n"
                'exec "$HOME/.local/share/uv/python/cpython-3.14/bin/python" '
                '-m app.spotty_bunny_cli "$@"\n',
                encoding="utf-8",
            )
            self.assertEqual(
                interpreter_for_program(script),
                Path.home() / ".local/share/uv/python/cpython-3.14/bin/python",
            )

    def test_interpreter_for_program_expands_longest_assignment_name_first(
        self,
    ) -> None:
        from app.spotty_bunny_agent import interpreter_for_program

        with TemporaryDirectory() as tmp:
            script = Path(tmp) / "spotty-bunny"
            script.write_text(
                "#!/usr/bin/env bash\n"
                "a=/x\n"
                "ab=/y\n"
                'exec "$ab/.venv/bin/python" -m app.spotty_bunny_cli "$@"\n',
                encoding="utf-8",
            )
            self.assertEqual(
                interpreter_for_program(script),
                Path("/y/.venv/bin/python"),
            )

    def test_interpreter_for_program_expands_nested_home_assignment(self) -> None:
        from app.spotty_bunny_agent import interpreter_for_program

        with TemporaryDirectory() as tmp:
            script = Path(tmp) / "spotty-bunny"
            script.write_text(
                "#!/usr/bin/env bash\n"
                'UV_DIR="$HOME/.local/share/uv"\n'
                'exec "$UV_DIR/python/cpython-3.14/bin/python" '
                '-m app.spotty_bunny_cli "$@"\n',
                encoding="utf-8",
            )
            self.assertEqual(
                interpreter_for_program(script),
                Path.home()
                / ".local"
                / "share"
                / "uv"
                / "python"
                / "cpython-3.14"
                / "bin"
                / "python",
            )

    def test_interpreter_for_program_expands_shell_var_assignment(self) -> None:
        from app.spotty_bunny_agent import interpreter_for_program

        with TemporaryDirectory() as tmp:
            script = Path(tmp) / "spotty-bunny"
            script.write_text(
                "#!/usr/bin/env bash\n"
                "wt=/opt/bunnify-wt\n"
                'exec "$wt/.venv/bin/python" "$wt/.venv/bin/spotty-bunny" "$@"\n',
                encoding="utf-8",
            )
            self.assertEqual(
                interpreter_for_program(script),
                Path("/opt/bunnify-wt/.venv/bin/python"),
            )

    def test_interpreter_for_program_ignores_commented_exec_line(self) -> None:
        from app.spotty_bunny_agent import interpreter_for_program

        with TemporaryDirectory() as tmp:
            script = Path(tmp) / "spotty-bunny"
            script.write_text(
                "#!/usr/bin/env bash\n"
                "# old: exec /usr/local/bin/python2.7\n"
                'exec "/opt/venvs/bunnify/bin/python" -m app.spotty_bunny_cli "$@"\n',
                encoding="utf-8",
            )
            self.assertEqual(
                interpreter_for_program(script),
                Path("/opt/venvs/bunnify/bin/python"),
            )

    def test_install_rejects_missing_binary(self) -> None:
        from app.spotty_bunny_agent import install_agent

        stderr = StringIO()
        code = install_agent(
            platform="darwin",
            print_err=stderr.write,
            program=Path("/no/such/spotty-bunny"),
            probe_tcc=lambda _p: TccStatus(True, True),
        )
        self.assertEqual(code, 1)
        self.assertIn("missing or not executable", stderr.getvalue())

    def test_is_agent_installed_checks_plist(self) -> None:
        from app.spotty_bunny_agent import AGENT_LABEL, is_agent_installed

        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.assertFalse(is_agent_installed(home=home))
            plist = home / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
            plist.parent.mkdir(parents=True)
            plist.write_text("plist", encoding="utf-8")
            self.assertTrue(is_agent_installed(home=home))

    def test_status_reports_log_version_and_tcc(self) -> None:
        from app.spotty_bunny_agent import AGENT_LABEL, format_agent_plist, status_agent
        from app.version import build_version

        ctl = _FakeLaunchctl()
        ctl.loaded = True
        stdout = StringIO()
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            plist = home / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
            plist.parent.mkdir(parents=True)
            program = home / "spotty-bunny"
            _write_executable(program)
            plist.write_text(
                format_agent_plist(
                    home=home,
                    program_arguments=[str(program)],
                ),
                encoding="utf-8",
            )
            pid_dir = home / "run"
            pid_dir.mkdir()
            (pid_dir / ".spotty-bunny.pid").write_text("99\n", encoding="utf-8")
            with patch(
                "app.spotty_bunny_agent.spotty_bunny_is_running",
                return_value=True,
            ):
                code = status_agent(
                    home=home,
                    launchctl=ctl,
                    pid_dir=pid_dir,
                    platform="darwin",
                    print_fn=lambda line: stdout.write(line + "\n"),
                    probe_tcc=lambda _p: TccStatus(True, False),
                    program=program,
                )
            text = stdout.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("running: yes", text)
            self.assertIn("pid: 99", text)
            self.assertIn("launchd: loaded", text)
            self.assertIn("binary: ", text)
            self.assertIn(str(program), text)
            self.assertIn("interpreter:", text)
            self.assertIn("application_log:", text)
            self.assertIn("follow_logs: tail --follow=name --retry", text)
            self.assertIn("launchd_stdout:", text)
            self.assertIn("version: " + build_version(), text)
            self.assertIn("accessibility: yes", text)
            self.assertIn("input_monitoring: no", text)

    def test_status_fails_when_plist_binary_missing(self) -> None:
        from app.spotty_bunny_agent import AGENT_LABEL, format_agent_plist, status_agent

        ctl = _FakeLaunchctl()
        ctl.loaded = True
        stdout = StringIO()
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            plist = home / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
            plist.parent.mkdir(parents=True)
            stale = home / "removed-spotty-bunny"
            plist.write_text(
                format_agent_plist(
                    home=home,
                    program_arguments=[str(stale)],
                ),
                encoding="utf-8",
            )
            with patch(
                "app.spotty_bunny_agent.spotty_bunny_is_running",
                return_value=True,
            ):
                code = status_agent(
                    home=home,
                    launchctl=ctl,
                    platform="darwin",
                    print_fn=lambda line: stdout.write(line + "\n"),
                    probe_tcc=lambda _p: TccStatus(True, True),
                )
            text = stdout.getvalue()
            self.assertEqual(code, 1)
            self.assertIn("missing or not executable", text)
            self.assertIn(str(stale), text)

    def test_uninstall_bootout_removes_plist_and_pid(self) -> None:
        from app.spotty_bunny_agent import AGENT_LABEL, uninstall_agent

        ctl = _FakeLaunchctl()
        ctl.loaded = True
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            plist = home / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
            plist.parent.mkdir(parents=True)
            plist.write_text("plist", encoding="utf-8")
            pid_dir = home / "run"
            pid_dir.mkdir()
            pid_path = pid_dir / ".spotty-bunny.pid"
            pid_path.write_text("7\n", encoding="utf-8")
            with patch("app.spotty_bunny_agent.stop_spotty_bunny") as stop:
                code = uninstall_agent(
                    home=home,
                    launchctl=ctl,
                    pid_dir=pid_dir,
                    platform="darwin",
                    print_err=lambda _m: None,
                )
            self.assertEqual(code, 0)
            self.assertFalse(plist.exists())
            self.assertFalse(pid_path.exists())
            stop.assert_called_once()
            self.assertTrue(any(call[1] == "bootout" for call in ctl.calls))

    def test_uninstall_succeeds_when_never_installed(self) -> None:
        from app.spotty_bunny_agent import uninstall_agent

        ctl = _FakeLaunchctl()
        with TemporaryDirectory() as tmp:
            code = uninstall_agent(
                home=Path(tmp),
                launchctl=ctl,
                platform="darwin",
                print_err=lambda _m: None,
            )
        self.assertEqual(code, 0)

    def test_upgrade_rewrites_plist_when_binary_changes(self) -> None:
        from app.spotty_bunny_agent import (
            AGENT_LABEL,
            format_agent_plist,
            upgrade_agent,
        )

        ctl = _FakeLaunchctl()
        ctl.loaded = True
        tcc = _FakeTcc(TccStatus(True, True))
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            plist = home / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
            plist.parent.mkdir(parents=True)
            plist.write_text(
                format_agent_plist(
                    home=home,
                    program_arguments=["/old/spotty-bunny"],
                ),
                encoding="utf-8",
            )
            _write_executable(home / "old-spotty-bunny")
            new_program = _write_executable(home / "new-spotty-bunny")
            code = upgrade_agent(
                home=home,
                launchctl=ctl,
                platform="darwin",
                print_err=lambda _m: None,
                probe_tcc=tcc.probe,
                program=new_program,
                request_tcc=tcc.request,
                skip_chord_confirm=True,
            )
            self.assertEqual(code, 0)
            self.assertIn(str(new_program), plist.read_text(encoding="utf-8"))
            self.assertNotIn("/old/spotty-bunny", plist.read_text(encoding="utf-8"))
            self.assertTrue(any(call[1] == "bootout" for call in ctl.calls))
            self.assertTrue(any(call[1] == "bootstrap" for call in ctl.calls))
            self.assertFalse(any(call[1] == "kickstart" for call in ctl.calls))

    def test_upgrade_rechecks_tcc(self) -> None:
        from app.spotty_bunny_agent import (
            AGENT_LABEL,
            format_agent_plist,
            upgrade_agent,
        )

        ctl = _FakeLaunchctl()
        tcc = _FakeTcc(TccStatus(False, True), TccStatus(False, True))
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            plist = home / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
            plist.parent.mkdir(parents=True)
            plist.write_text(
                format_agent_plist(
                    home=home,
                    program_arguments=["/opt/spotty-bunny"],
                ),
                encoding="utf-8",
            )
            program = _write_executable(home / "spotty-bunny")
            code = upgrade_agent(
                home=home,
                launchctl=ctl,
                platform="darwin",
                print_err=lambda _m: None,
                probe_tcc=tcc.probe,
                program=program,
                request_tcc=tcc.request,
            )
            self.assertEqual(code, 1)
            self.assertEqual(tcc.requests, 1)
            self.assertGreaterEqual(tcc.probes, 2)
            self.assertFalse(any(call[1] == "kickstart" for call in ctl.calls))

    def test_refresh_agent_plist_rewrites_without_bootout(self) -> None:
        from app.spotty_bunny_agent import (
            AGENT_LABEL,
            format_agent_plist,
            refresh_agent_plist,
        )

        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            plist = home / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
            plist.parent.mkdir(parents=True)
            plist.write_text(
                format_agent_plist(
                    home=home,
                    program_arguments=["/old/spotty-bunny"],
                ),
                encoding="utf-8",
            )
            new_program = Path("/new/spotty-bunny")
            code = refresh_agent_plist(
                home=home,
                platform="darwin",
                print_err=lambda _m: None,
                program=new_program,
            )
            self.assertEqual(code, 0)
            self.assertIn(str(new_program), plist.read_text(encoding="utf-8"))
            self.assertNotIn("/old/spotty-bunny", plist.read_text(encoding="utf-8"))

    def test_uninstall_removes_plist_before_bootout(self) -> None:
        from app.spotty_bunny_agent import AGENT_LABEL, uninstall_agent

        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            plist = home / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
            plist.parent.mkdir(parents=True)
            plist.write_text("plist", encoding="utf-8")

            class _OrderLaunchctl(_FakeLaunchctl):
                def __call__(
                    self, argv: list[str], **kwargs: object
                ) -> subprocess.CompletedProcess[str]:
                    if len(argv) >= 2 and argv[1] == "bootout":
                        self.plist_existed_at_bootout = plist.exists()
                    return super().__call__(argv, **kwargs)

            ctl = _OrderLaunchctl()
            ctl.loaded = True
            ctl.plist_existed_at_bootout = True
            with patch("app.spotty_bunny_agent.stop_spotty_bunny"):
                code = uninstall_agent(
                    home=home,
                    launchctl=ctl,
                    platform="darwin",
                    print_err=lambda _m: None,
                )
            self.assertEqual(code, 0)
            self.assertFalse(plist.exists())
            self.assertIs(ctl.plist_existed_at_bootout, False)


def _write_executable(path: Path, *, content: str = "#!/bin/sh\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path


class _FakeLaunchctl:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.loaded = False

    def __call__(
        self, argv: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        if len(argv) >= 2 and argv[1] == "print":
            return subprocess.CompletedProcess(argv, 0 if self.loaded else 1, "", "")
        if len(argv) >= 2 and argv[1] == "bootstrap":
            self.loaded = True
        if len(argv) >= 2 and argv[1] == "bootout":
            self.loaded = False
        return subprocess.CompletedProcess(argv, 0, "", "")


class _FakeTcc:
    def __init__(self, *results: TccStatus) -> None:
        self._results = list(results)
        self.probes = 0
        self.requests = 0

    def probe(self, _interpreter: Path) -> TccStatus:
        self.probes += 1
        if not self._results:
            raise AssertionError("unexpected TCC probe")
        return self._results.pop(0)

    def request(self, _interpreter: Path) -> TccStatus:
        self.requests += 1
        return TccStatus(False, False)


class SpottyBunnyCompleteTests(SimpleTestCase):
    def test_apply_completion_appends_when_start_position_is_zero(self) -> None:
        from app.spotty_bunny_complete import CompletionRow, apply_completion

        row = CompletionRow(insert="the-hcma/bunnify", meta="", start_position=0)
        self.assertEqual(apply_completion("pr ", row), "pr the-hcma/bunnify")

    def test_apply_completion_replaces_prefix(self) -> None:
        from app.spotty_bunny_complete import CompletionRow, apply_completion

        row = CompletionRow(insert="gh", meta="GitHub", start_position=-1)
        self.assertEqual(apply_completion("g", row), "gh")

    def test_github_param_completion_blocked_message_when_unauthenticated(
        self,
    ) -> None:
        import logging
        import subprocess
        from unittest.mock import patch

        from app.client import KeyEntry
        from app.completion_spec import ParamCompleteSpec
        from app.github_complete import (
            GITHUB_AUTH_NEEDED_MESSAGE,
            clear_github_completion_cache,
        )
        from app.spotty_bunny_complete import github_param_completion_blocked_message

        clear_github_completion_cache()
        entries = [
            KeyEntry(
                key="prh",
                description="pulls",
                url="https://github.com/the-hcma/#{repo}/pulls",
                params=("repo",),
                complete={
                    "repo": ParamCompleteSpec(kind="github_repo", org="the-hcma"),
                },
            )
        ]

        def gh_runner(*, args, **_kwargs):
            return subprocess.CompletedProcess(
                args=list(args), returncode=1, stdout="", stderr=""
            )

        with (
            patch("app.github_complete.gh_is_available", return_value=True),
            self.assertLogs("app.github_complete", level=logging.WARNING),
        ):
            message = github_param_completion_blocked_message(
                "prh dom",
                entries,
                environ={"PATH": "/usr/bin"},
                runner=gh_runner,
            )
        self.assertEqual(message, GITHUB_AUTH_NEEDED_MESSAGE)
        clear_github_completion_cache()

    def test_github_param_completion_blocked_message_none_when_authed(
        self,
    ) -> None:
        import subprocess

        from app.client import KeyEntry
        from app.completion_spec import ParamCompleteSpec
        from app.github_complete import clear_github_completion_cache
        from app.spotty_bunny_complete import github_param_completion_blocked_message

        clear_github_completion_cache()
        entries = [
            KeyEntry(
                key="prh",
                description="pulls",
                url="https://github.com/the-hcma/#{repo}/pulls",
                params=("repo",),
                complete={
                    "repo": ParamCompleteSpec(kind="github_repo", org="the-hcma"),
                },
            )
        ]

        def gh_runner(*, args, **_kwargs):
            return subprocess.CompletedProcess(
                args=list(args), returncode=0, stdout="tok\n", stderr=""
            )

        message = github_param_completion_blocked_message(
            "prh dom",
            entries,
            environ={"PATH": "/usr/bin"},
            runner=gh_runner,
        )
        self.assertIsNone(message)
        clear_github_completion_cache()

    def test_show_completions_captures_prefix_before_hide(self) -> None:
        """Regression: hide clears _completion_prefix; blocked message needs a copy."""
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1] / "app" / "spotty_bunny_app.py"
        ).read_text(encoding="utf-8")
        marker = "def _show_completions("
        start = source.index(marker)
        chunk = source[start : start + 1100]
        prefix_idx = chunk.index("prefix = self._completion_prefix")
        hide_idx = chunk.index("self._hide_completions()")
        self.assertLess(prefix_idx, hide_idx)
        self.assertIn("surface_blocked_github_completion(", chunk)
        self.assertIn(
            "github_param_completion_blocked_message(text, entries)",
            source,
        )

    def test_surface_blocked_github_completion_sets_status_and_warns(self) -> None:
        import logging

        from app.github_complete import (
            GITHUB_AUTH_NEEDED_MESSAGE,
            clear_github_completion_cache,
        )
        from app.spotty_bunny_complete import surface_blocked_github_completion

        clear_github_completion_cache()
        statuses: list[str] = []
        with self.assertLogs("app.github_complete", level=logging.WARNING) as logged:
            surfaced = surface_blocked_github_completion(
                "prh dom",
                GITHUB_AUTH_NEEDED_MESSAGE,
                set_status=statuses.append,
            )
        self.assertTrue(surfaced)
        self.assertEqual(statuses, [GITHUB_AUTH_NEEDED_MESSAGE])
        self.assertTrue(any("blocked" in line.lower() for line in logged.output))
        # Second call within throttle window should not add another WARNING.
        with self.assertRaises(AssertionError):
            with self.assertLogs("app.github_complete", level=logging.WARNING):
                surface_blocked_github_completion(
                    "prh bun",
                    GITHUB_AUTH_NEEDED_MESSAGE,
                    set_status=statuses.append,
                )
        self.assertEqual(
            statuses,
            [GITHUB_AUTH_NEEDED_MESSAGE, GITHUB_AUTH_NEEDED_MESSAGE],
        )
        clear_github_completion_cache()

    def test_surface_blocked_github_completion_noop_without_message(self) -> None:
        from app.spotty_bunny_complete import surface_blocked_github_completion

        statuses: list[str] = []
        self.assertFalse(
            surface_blocked_github_completion(
                "prh dom",
                None,
                set_status=statuses.append,
            )
        )
        self.assertEqual(statuses, [])

    def test_completion_still_current_requires_matching_seq_and_field(self) -> None:
        from app.spotty_bunny_complete import completion_still_current

        self.assertTrue(
            completion_still_current(expected_seq=2, field="gh", prefix="gh", seq=2)
        )
        self.assertFalse(
            completion_still_current(expected_seq=2, field="gho", prefix="gh", seq=2)
        )
        self.assertFalse(
            completion_still_current(expected_seq=2, field="gh", prefix="gh", seq=3)
        )

    def test_completion_row_after_selector_supports_page_keys(self) -> None:
        from app.spotty_bunny_complete import (
            completion_row_after_selector,
            is_completion_navigation_selector,
        )

        self.assertEqual(
            completion_row_after_selector(7, row_count=20, selector="pageUp:"),
            2,
        )
        self.assertEqual(
            completion_row_after_selector(7, row_count=20, selector="pageDown:"),
            12,
        )
        self.assertEqual(
            completion_row_after_selector(7, row_count=20, selector="scrollPageUp:"),
            2,
        )
        self.assertEqual(
            completion_row_after_selector(7, row_count=20, selector="scrollPageDown:"),
            12,
        )
        self.assertEqual(
            completion_row_after_selector(0, row_count=3, selector="moveDown:"),
            1,
        )
        self.assertTrue(is_completion_navigation_selector("scrollPageUp:"))
        self.assertTrue(is_completion_navigation_selector("pageDown:"))

    def test_completion_navigation_disposition_scopes_page_visibility(self) -> None:
        from app.spotty_bunny_complete import completion_navigation_disposition

        self.assertEqual(
            completion_navigation_disposition(
                "moveDown:", has_rows=True, table_visible=False
            ),
            "consume",
        )
        self.assertEqual(
            completion_navigation_disposition(
                "moveUp:", has_rows=True, table_visible=True
            ),
            "move",
        )
        self.assertEqual(
            completion_navigation_disposition(
                "scrollPageDown:", has_rows=True, table_visible=False
            ),
            "ignore",
        )
        self.assertEqual(
            completion_navigation_disposition(
                "pageUp:", has_rows=True, table_visible=True
            ),
            "move",
        )
        self.assertIsNone(
            completion_navigation_disposition(
                "moveDown:", has_rows=False, table_visible=False
            )
        )

    def test_edit_action_for_key_maps_command_chords(self) -> None:
        from app.spotty_bunny_edit import (
            edit_action_for_key,
            edit_command_modifiers_ok,
            is_line_end_selector,
            is_line_navigation_selector,
            is_line_start_selector,
            line_navigation_modifies_selection,
            line_navigation_selected_range,
        )

        self.assertEqual(
            edit_action_for_key("v", command=True, shift=False),
            "paste:",
        )
        self.assertEqual(
            edit_action_for_key("c", command=True, shift=False),
            "copy:",
        )
        self.assertEqual(
            edit_action_for_key("x", command=True, shift=False),
            "cut:",
        )
        self.assertEqual(
            edit_action_for_key("a", command=True, shift=False),
            "selectAll:",
        )
        self.assertEqual(
            edit_action_for_key("z", command=True, shift=False),
            "undo:",
        )
        self.assertEqual(
            edit_action_for_key("z", command=True, shift=True),
            "redo:",
        )
        self.assertIsNone(edit_action_for_key("v", command=False, shift=False))
        self.assertIsNone(edit_action_for_key("b", command=True, shift=False))
        self.assertTrue(
            edit_command_modifiers_ok(command=True, control=False, option=False)
        )
        self.assertFalse(
            edit_command_modifiers_ok(command=True, control=True, option=False)
        )
        self.assertFalse(
            edit_command_modifiers_ok(command=True, control=False, option=True)
        )
        self.assertFalse(
            edit_command_modifiers_ok(command=False, control=False, option=False)
        )
        self.assertTrue(is_line_start_selector("scrollToBeginningOfDocument:"))
        self.assertTrue(is_line_start_selector("moveToBeginningOfLine:"))
        self.assertTrue(is_line_end_selector("scrollToEndOfDocument:"))
        self.assertTrue(is_line_end_selector("moveToEndOfLine:"))
        self.assertTrue(is_line_navigation_selector("moveToBeginningOfLine:"))
        self.assertFalse(is_line_navigation_selector("moveUp:"))
        self.assertTrue(
            line_navigation_modifies_selection(
                "moveToBeginningOfLineAndModifySelection:"
            )
        )
        self.assertFalse(line_navigation_modifies_selection("moveToBeginningOfLine:"))
        self.assertEqual(
            line_navigation_selected_range(
                text_length=8,
                selected_location=6,
                selected_length=2,
                to_start=True,
                modify=True,
                affinity_upstream=True,
            ),
            (0, 8),
        )
        self.assertEqual(
            line_navigation_selected_range(
                text_length=8,
                selected_location=6,
                selected_length=2,
                to_start=False,
                modify=True,
                affinity_upstream=True,
            ),
            (8, 0),
        )
        self.assertEqual(
            line_navigation_selected_range(
                text_length=8,
                selected_location=0,
                selected_length=2,
                to_start=True,
                modify=True,
                affinity_upstream=False,
            ),
            (0, 0),
        )
        self.assertEqual(
            line_navigation_selected_range(
                text_length=8,
                selected_location=0,
                selected_length=2,
                to_start=False,
                modify=True,
                affinity_upstream=False,
            ),
            (0, 8),
        )
        self.assertEqual(
            line_navigation_selected_range(
                text_length=8,
                selected_location=5,
                selected_length=0,
                to_start=True,
                modify=False,
                affinity_upstream=False,
            ),
            (0, 0),
        )
        self.assertEqual(
            line_navigation_selected_range(
                text_length=8,
                selected_location=5,
                selected_length=0,
                to_start=False,
                modify=False,
                affinity_upstream=False,
            ),
            (8, 0),
        )

    def test_empty_prefix_tab_lists_without_auto_insert(self) -> None:
        from app.spotty_bunny_complete import (
            CompletionRow,
            completion_browse_all,
            completion_table_should_show,
            should_auto_insert_completion,
        )

        rows = [
            CompletionRow(insert="gh", meta="GitHub", start_position=0),
            CompletionRow(insert="gm", meta="Gmail", start_position=0),
        ]
        self.assertTrue(completion_browse_all(""))
        self.assertFalse(completion_browse_all("   "))
        self.assertFalse(completion_browse_all("g"))
        self.assertFalse(should_auto_insert_completion("", rows))
        self.assertTrue(should_auto_insert_completion("g", rows))
        self.assertTrue(completion_table_should_show("", rows))
        self.assertTrue(completion_table_should_show("", rows[:1]))
        self.assertFalse(completion_table_should_show("g", rows[:1]))
        self.assertTrue(completion_table_should_show("g", rows))

    def test_field_editor_selector_name_normalizes_forms(self) -> None:
        from app.spotty_bunny_complete import field_editor_selector_name

        self.assertEqual(field_editor_selector_name("insertTab:"), "insertTab:")
        self.assertEqual(field_editor_selector_name(b"insertTab:"), "insertTab:")
        self.assertEqual(
            field_editor_selector_name("<unbound selector insertTab: at 0x10ccfd840>"),
            "insertTab:",
        )

        class _Sel:
            selector = b"selectNextKeyView:"

        self.assertEqual(field_editor_selector_name(_Sel()), "selectNextKeyView:")

    def test_first_token_fuzzy_matches_description(self) -> None:
        from app.client import KeyEntry
        from app.spotty_bunny_complete import completions_for, make_spotty_completer

        completer = make_spotty_completer(
            entries=[
                KeyEntry(key="gh", description="GitHub"),
                KeyEntry(key="g", description="Google"),
            ]
        )
        rows = completions_for("hub", completer)
        self.assertEqual([row.insert for row in rows], ["gh"])

    def test_is_tab_completion_selector_accepts_key_view_loop(self) -> None:
        from app.spotty_bunny_complete import is_tab_completion_selector

        self.assertTrue(is_tab_completion_selector("insertTab:"))
        self.assertTrue(is_tab_completion_selector(b"selectNextKeyView:"))
        self.assertTrue(is_tab_completion_selector("insertBacktab:"))
        self.assertFalse(is_tab_completion_selector("insertNewline:"))

    def test_meta_commands_are_excluded(self) -> None:
        from app.spotty_bunny_complete import completions_for, make_spotty_completer

        rows = completions_for("q", make_spotty_completer(entries=[]))
        self.assertEqual(rows, [])

    def test_open_search_uses_suggestions_fn(self) -> None:
        from app.client import KeyEntry
        from app.spotty_bunny_complete import completions_for, make_spotty_completer

        def suggestions(query: str) -> list[str]:
            if query.startswith("g "):
                return [f"{query} news"]
            return []

        completer = make_spotty_completer(
            entries=[KeyEntry(key="g", description="Google")],
            suggestions_fn=suggestions,
        )
        rows = completions_for("g hello", completer)
        self.assertEqual([row.insert for row in rows], ["g hello news"])

    def test_param_suggest_fn_is_used(self) -> None:
        from app.client import KeyEntry
        from app.spotty_bunny_complete import (
            apply_completion,
            completions_for,
            make_spotty_completer,
        )

        completer = make_spotty_completer(
            entries=[
                KeyEntry(key="pr", description="PR", params=("org/repo", "n")),
            ],
            param_suggest_fn=lambda **_kwargs: ["the-hcma/bunnify"],
        )
        rows = completions_for("pr ", completer)
        self.assertEqual([row.insert for row in rows], ["the-hcma/bunnify"])
        self.assertEqual(rows[0].start_position, 0)
        self.assertEqual(apply_completion("pr ", rows[0]), "pr the-hcma/bunnify")

    def test_wrapper_asks_first_token_fuzzy_completer(self) -> None:
        from prompt_toolkit.completion import Completion

        from app.spotty_bunny_complete import completions_for

        completer = MagicMock()
        completer.get_completions.return_value = [
            Completion("gh", start_position=-1, display_meta="GitHub"),
        ]
        rows = completions_for("g", completer)
        completer.get_completions.assert_called_once()
        document = completer.get_completions.call_args[0][0]
        self.assertEqual(document.text, "g")
        self.assertEqual([row.insert for row in rows], ["gh"])
        self.assertEqual(rows[0].meta, "GitHub")


class SpottyBunnyHistoryTests(SimpleTestCase):
    def test_append_round_trips_prompt_toolkit_file_history(self) -> None:
        from prompt_toolkit.history import FileHistory

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "repl_history"
            append_history_line("g hello", path=path)
            append_history_line("  gh  ", path=path)
            append_history_line("", path=path)
            self.assertEqual(load_history_lines(path=path), ["g hello", "gh"])
            self.assertEqual(
                list(FileHistory(str(path)).load_history_strings()),
                ["gh", "g hello"],
            )

    def test_append_unwritable_parent_is_ignored(self) -> None:
        with TemporaryDirectory() as tmp:
            parent = Path(tmp) / "blocked"
            parent.write_text("not-a-dir")
            append_history_line("gh", path=parent / "repl_history")

    def test_apply_history_selector_ignores_return(self) -> None:
        navigator = HistoryNavigator(["gh"])
        self.assertIsNone(apply_history_selector(navigator, "", "insertNewline:"))

    def test_down_at_live_line_keeps_current(self) -> None:
        navigator = HistoryNavigator(["gh"])
        self.assertEqual(navigator.down("typed"), "typed")

    def test_down_restores_draft_after_up(self) -> None:
        navigator = HistoryNavigator(["gh", "g hello"])
        self.assertEqual(navigator.up("draft"), "g hello")
        self.assertEqual(navigator.up("g hello"), "gh")
        self.assertEqual(navigator.down("gh"), "g hello")
        self.assertEqual(navigator.down("g hello"), "draft")

    def test_edit_recalled_line_becomes_draft(self) -> None:
        navigator = HistoryNavigator(["gh", "g hello"])
        self.assertEqual(navigator.up("abc"), "g hello")
        self.assertEqual(navigator.up("g hello!"), "gh")
        self.assertEqual(navigator.down("gh"), "g hello")
        self.assertEqual(navigator.down("g hello"), "g hello!")

    def test_load_invalid_utf8_returns_empty(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "repl_history"
            path.write_bytes(b"\xff\xfe")
            self.assertEqual(load_history_lines(path=path), [])

    def test_load_missing_file_returns_empty(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing" / "repl_history"
            self.assertEqual(load_history_lines(path=path), [])

    def test_up_at_oldest_stays_at_oldest(self) -> None:
        navigator = HistoryNavigator(["gh", "g hello"])
        self.assertEqual(navigator.up("draft"), "g hello")
        self.assertEqual(navigator.up("g hello"), "gh")
        self.assertEqual(navigator.up("gh"), "gh")

    def test_up_on_empty_history_keeps_current(self) -> None:
        navigator = HistoryNavigator()
        self.assertEqual(navigator.up("typed"), "typed")
        self.assertEqual(
            apply_history_selector(navigator, "typed", "moveUp:"),
            "typed",
        )
        self.assertEqual(
            apply_history_selector(navigator, "typed", "moveDown:"),
            "typed",
        )


class SpottyBunnyHotkeyTests(SimpleTestCase):
    def test_batched_hid_both_down_fires_on_completing_keycode(self) -> None:
        tracker = ChordTracker()
        self.assertTrue(
            apply_hid_snapshot(
                tracker,
                keycode=CONTROL_RIGHT_KEYCODE,
                left_down=True,
                right_down=True,
            )
        )
        tracker = ChordTracker()
        self.assertTrue(
            apply_hid_snapshot(
                tracker,
                keycode=CONTROL_LEFT_KEYCODE,
                left_down=True,
                right_down=True,
            )
        )

    def test_both_from_idle_does_not_fire(self) -> None:
        tracker = ChordTracker()
        self.assertFalse(tracker.sync(left_down=True, right_down=True))

    def test_describe_key_ctrl_a(self) -> None:
        self.assertEqual(describe_key(0, control=True), "CTRL-A")

    def test_describe_key_ctrl_shift_a(self) -> None:
        self.assertEqual(
            describe_key(0, control=True, shift=True),
            "CTRL-SHIFT-A",
        )

    def test_describe_key_escape(self) -> None:
        self.assertEqual(ESCAPE_KEYCODE, 53)
        self.assertEqual(describe_key(ESCAPE_KEYCODE), "Escape")

    def test_describe_key_tab(self) -> None:
        self.assertEqual(TAB_KEYCODE, 48)
        self.assertEqual(describe_key(TAB_KEYCODE), "Tab")

    def test_describe_key_letter_a(self) -> None:
        self.assertEqual(describe_key(0), "A")

    def test_describe_key_letter_d(self) -> None:
        self.assertEqual(describe_key(2), "D")

    def test_describe_key_left_control_not_prefixed(self) -> None:
        self.assertEqual(
            describe_key(CONTROL_LEFT_KEYCODE, control=True),
            "leftControl",
        )

    def test_describe_key_unknown_with_modifiers(self) -> None:
        self.assertEqual(
            describe_key(200, control=True, shift=True),
            "CTRL-SHIFT-keycode:200",
        )

    def test_page_selector_for_keycode(self) -> None:
        self.assertEqual(page_selector_for_keycode(PAGE_UP_KEYCODE), "pageUp:")
        self.assertEqual(page_selector_for_keycode(PAGE_DOWN_KEYCODE), "pageDown:")
        self.assertIsNone(page_selector_for_keycode(TAB_KEYCODE))

    def test_device_flag_sees_right_control_without_hid(self) -> None:
        left, right = resolve_control_snapshot(
            keycode=CONTROL_RIGHT_KEYCODE,
            hid_left=True,
            hid_right=False,
            flag_left=True,
            flag_right=True,
            held_left=True,
            held_right=False,
        )
        self.assertEqual((left, right), (True, True))

    def test_hid_misses_right_control_keycode_edge_fires(self) -> None:
        tracker = ChordTracker()
        left, right = resolve_control_snapshot(
            keycode=CONTROL_LEFT_KEYCODE,
            hid_left=True,
            hid_right=False,
            flag_left=True,
            flag_right=False,
            held_left=False,
            held_right=False,
        )
        self.assertFalse(
            apply_hid_snapshot(
                tracker,
                keycode=CONTROL_LEFT_KEYCODE,
                left_down=left,
                right_down=right,
            )
        )
        left, right = resolve_control_snapshot(
            keycode=CONTROL_RIGHT_KEYCODE,
            hid_left=True,
            hid_right=False,
            flag_left=True,
            flag_right=False,
            held_left=tracker.held_left,
            held_right=tracker.held_right,
        )
        self.assertEqual((left, right), (True, True))
        self.assertTrue(
            apply_hid_snapshot(
                tracker,
                keycode=CONTROL_RIGHT_KEYCODE,
                left_down=left,
                right_down=right,
            )
        )

    def test_hid_miss_key_down_flags_key_up_fires_once(self) -> None:
        tracker = ChordTracker()
        self.assertFalse(
            apply_control_event(
                tracker,
                keycode=CONTROL_LEFT_KEYCODE,
                hid_left=True,
                hid_right=False,
                flag_left=True,
                flag_right=False,
                control_flag=True,
                flags_changed=True,
            )
        )
        right_kwargs = {
            "keycode": CONTROL_RIGHT_KEYCODE,
            "hid_left": True,
            "hid_right": False,
            "flag_left": True,
            "flag_right": False,
            "control_flag": True,
        }
        self.assertFalse(
            apply_control_event(tracker, flags_changed=False, **right_kwargs)
        )
        self.assertTrue(
            apply_control_event(tracker, flags_changed=True, **right_kwargs)
        )
        self.assertFalse(
            apply_control_event(tracker, flags_changed=True, **right_kwargs)
        )
        self.assertFalse(
            apply_control_event(tracker, flags_changed=False, **right_kwargs)
        )
        self.assertTrue(tracker.held_left)
        self.assertTrue(tracker.held_right)

    def test_hid_miss_right_release_then_repress_fires(self) -> None:
        clock = _FakeClock()
        tracker = ChordTracker(monotonic=clock)
        held_left = {
            "hid_left": True,
            "hid_right": False,
            "flag_left": True,
            "flag_right": False,
            "control_flag": True,
        }
        self.assertFalse(
            apply_control_event(
                tracker,
                keycode=CONTROL_LEFT_KEYCODE,
                flags_changed=True,
                **held_left,
            )
        )
        self.assertTrue(
            apply_control_event(
                tracker,
                keycode=CONTROL_RIGHT_KEYCODE,
                flags_changed=True,
                **held_left,
            )
        )
        clock.advance(0.001)
        self.assertFalse(
            apply_control_event(
                tracker,
                keycode=CONTROL_RIGHT_KEYCODE,
                flags_changed=True,
                **held_left,
            )
        )
        self.assertTrue(tracker.held_right)
        clock.advance(0.029)
        self.assertFalse(
            apply_control_event(
                tracker,
                keycode=CONTROL_RIGHT_KEYCODE,
                flags_changed=True,
                **held_left,
            )
        )
        self.assertTrue(tracker.held_left)
        self.assertFalse(tracker.held_right)
        clock.advance(0.07)
        self.assertTrue(
            apply_control_event(
                tracker,
                keycode=CONTROL_RIGHT_KEYCODE,
                flags_changed=True,
                **held_left,
            )
        )

    def test_hid_misses_both_controls_press_release_repress(self) -> None:
        tracker = ChordTracker()
        miss = {
            "hid_left": False,
            "hid_right": False,
            "flag_left": False,
            "flag_right": False,
        }
        self.assertFalse(
            apply_control_event(
                tracker,
                keycode=CONTROL_LEFT_KEYCODE,
                control_flag=True,
                flags_changed=True,
                **miss,
            )
        )
        self.assertTrue(tracker.held_left)
        self.assertFalse(tracker.held_right)
        self.assertTrue(
            apply_control_event(
                tracker,
                keycode=CONTROL_RIGHT_KEYCODE,
                control_flag=True,
                flags_changed=True,
                **miss,
            )
        )
        self.assertFalse(
            apply_control_event(
                tracker,
                keycode=CONTROL_LEFT_KEYCODE,
                control_flag=False,
                flags_changed=True,
                **miss,
            )
        )
        self.assertFalse(tracker.held_left)
        self.assertFalse(tracker.held_right)
        self.assertFalse(
            apply_control_event(
                tracker,
                keycode=CONTROL_LEFT_KEYCODE,
                control_flag=True,
                flags_changed=True,
                **miss,
            )
        )
        self.assertTrue(
            apply_control_event(
                tracker,
                keycode=CONTROL_RIGHT_KEYCODE,
                control_flag=True,
                flags_changed=True,
                **miss,
            )
        )

    def test_hid_misses_left_control_keycode_edge_fires(self) -> None:
        tracker = ChordTracker()
        left, right = resolve_control_snapshot(
            keycode=CONTROL_RIGHT_KEYCODE,
            hid_left=False,
            hid_right=True,
            flag_left=False,
            flag_right=True,
            held_left=False,
            held_right=False,
            control_flag=True,
        )
        self.assertFalse(
            apply_hid_snapshot(
                tracker,
                keycode=CONTROL_RIGHT_KEYCODE,
                left_down=left,
                right_down=right,
            )
        )
        left, right = resolve_control_snapshot(
            keycode=CONTROL_LEFT_KEYCODE,
            hid_left=False,
            hid_right=True,
            flag_left=False,
            flag_right=True,
            held_left=tracker.held_left,
            held_right=tracker.held_right,
            control_flag=True,
        )
        self.assertEqual((left, right), (True, True))
        self.assertTrue(
            apply_hid_snapshot(
                tracker,
                keycode=CONTROL_LEFT_KEYCODE,
                left_down=left,
                right_down=right,
            )
        )

    def test_hold_left_then_right_fires_once(self) -> None:
        tracker = ChordTracker()
        self.assertFalse(tracker.sync(left_down=True, right_down=False))
        self.assertTrue(tracker.sync(left_down=True, right_down=True))
        self.assertFalse(tracker.sync(left_down=True, right_down=True))

    def test_hold_right_then_left_fires_once(self) -> None:
        tracker = ChordTracker()
        self.assertFalse(tracker.sync(left_down=False, right_down=True))
        self.assertTrue(tracker.sync(left_down=True, right_down=True))

    def test_release_one_then_press_again_fires(self) -> None:
        tracker = ChordTracker()
        tracker.sync(left_down=True, right_down=False)
        tracker.sync(left_down=True, right_down=True)
        self.assertFalse(tracker.sync(left_down=True, right_down=False))
        self.assertTrue(tracker.sync(left_down=True, right_down=True))

    def test_sequential_singles_do_not_fire(self) -> None:
        tracker = ChordTracker()
        self.assertFalse(tracker.sync(left_down=True, right_down=False))
        self.assertFalse(tracker.sync(left_down=False, right_down=False))
        self.assertFalse(tracker.sync(left_down=False, right_down=True))

    def test_keycode_edge_skipped_when_not_flags_changed(self) -> None:
        left, right = resolve_control_snapshot(
            keycode=CONTROL_RIGHT_KEYCODE,
            hid_left=True,
            hid_right=False,
            flag_left=True,
            flag_right=False,
            held_left=True,
            held_right=False,
            control_flag=True,
            flags_changed=False,
        )
        self.assertEqual((left, right), (True, False))

    def test_shift_flags_changed_does_not_drop_held_right(self) -> None:
        left, right = resolve_control_snapshot(
            keycode=56,
            hid_left=True,
            hid_right=False,
            flag_left=True,
            flag_right=False,
            held_left=True,
            held_right=True,
            control_flag=True,
            flags_changed=True,
        )
        self.assertEqual((left, right), (True, True))


class SpottyBunnyQuitTests(SimpleTestCase):
    def test_post_application_wake_event_posts_at_start(self) -> None:
        ns_app = MagicMock()
        other_event = MagicMock(return_value="wake")
        post_application_wake_event(
            event_type=15,
            ns_app=ns_app,
            other_event=other_event,
        )
        other_event.assert_called_once_with(
            15,
            (0.0, 0.0),
            0,
            0.0,
            0,
            None,
            0,
            0,
            0,
        )
        ns_app.postEvent_atStart_.assert_called_once_with("wake", True)

    def test_quit_ns_app_stops_then_wakes(self) -> None:
        order: list[str] = []
        ns_app = MagicMock()
        ns_app.stop_.side_effect = lambda _sender: order.append("stop")

        def post_wake() -> None:
            order.append("wake")

        quit_ns_app(ns_app=ns_app, post_wake=post_wake)
        self.assertEqual(order, ["stop", "wake"])

    def test_wake_event_selector_is_wired_in_app_module(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "app" / "spotty_bunny_app.py"
        ).read_text(encoding="utf-8")
        self.assertIn("WAKE_EVENT_SELECTOR", source)
        self.assertEqual(
            WAKE_EVENT_SELECTOR,
            "otherEventWithType_location_modifierFlags_timestamp_windowNumber"
            "_context_subtype_data1_data2_",
        )


class SpottyBunnyLaunchTests(SimpleTestCase):
    def test_ensure_spotty_bunny_running_skips_when_already_running(self) -> None:
        from app.spotty_bunny_launch import (
            SPOTTY_BUNNY_PID_FILE,
            ensure_spotty_bunny_running,
        )

        with TemporaryDirectory() as tmp:
            pid_dir = Path(tmp)
            (pid_dir / SPOTTY_BUNNY_PID_FILE).write_text(f"{os.getpid()}\n")
            with (
                patch("app.spotty_bunny_launch.sys.platform", "darwin"),
                patch(
                    "app.spotty_bunny_launch._spotty_bunny_process_alive",
                    return_value=True,
                ),
            ):
                self.assertTrue(
                    ensure_spotty_bunny_running(
                        pid_dir=pid_dir,
                        spawn=lambda _cmd: self.fail("should not spawn"),
                    )
                )

    def test_ensure_spotty_bunny_running_spawns_on_darwin(self) -> None:
        from app.spotty_bunny_launch import (
            SPOTTY_BUNNY_PID_FILE,
            ensure_spotty_bunny_running,
        )

        with TemporaryDirectory() as tmp:
            pid_dir = Path(tmp)
            with (
                patch("app.spotty_bunny_launch.sys.platform", "darwin"),
                patch(
                    "app.spotty_bunny_launch.git_commit",
                    return_value="abc1234",
                ),
                patch(
                    "app.spotty_bunny_launch._spotty_bunny_process_alive",
                    return_value=True,
                ),
            ):
                self.assertTrue(
                    ensure_spotty_bunny_running(
                        pid_dir=pid_dir,
                        spawn=lambda _cmd: 4242,
                    )
                )
            self.assertEqual(
                (pid_dir / SPOTTY_BUNNY_PID_FILE).read_text(encoding="utf-8"),
                "4242\nabc1234\n",
            )

    def test_ensure_spotty_bunny_running_honors_cli_commit_override(self) -> None:
        from app.spotty_bunny_launch import (
            SPOTTY_BUNNY_PID_FILE,
            ensure_spotty_bunny_running,
        )

        with TemporaryDirectory() as tmp:
            pid_dir = Path(tmp)
            with (
                patch("app.spotty_bunny_launch.sys.platform", "darwin"),
                patch(
                    "app.spotty_bunny_launch.git_commit",
                    return_value="stalecommit",
                ),
                patch(
                    "app.spotty_bunny_launch._spotty_bunny_process_alive",
                    return_value=True,
                ),
            ):
                self.assertTrue(
                    ensure_spotty_bunny_running(
                        cli_commit="newcommit9",
                        pid_dir=pid_dir,
                        spawn=lambda _cmd: 4242,
                    )
                )
            self.assertEqual(
                (pid_dir / SPOTTY_BUNNY_PID_FILE).read_text(encoding="utf-8"),
                "4242\nnewcommit9\n",
            )

    def test_ensure_spotty_bunny_running_keeps_mismatch_when_declined(
        self,
    ) -> None:
        from app.spotty_bunny_launch import (
            SPOTTY_BUNNY_PID_FILE,
            ensure_spotty_bunny_running,
        )

        with TemporaryDirectory() as tmp:
            pid_dir = Path(tmp)
            (pid_dir / SPOTTY_BUNNY_PID_FILE).write_text(
                "4242\noldcommit\n",
                encoding="utf-8",
            )
            with (
                patch("app.spotty_bunny_launch.sys.platform", "darwin"),
                patch(
                    "app.spotty_bunny_launch.git_commit",
                    return_value="newcommit",
                ),
                patch(
                    "app.spotty_bunny_launch._spotty_bunny_process_alive",
                    return_value=True,
                ),
            ):
                self.assertTrue(
                    ensure_spotty_bunny_running(
                        pid_dir=pid_dir,
                        restart=lambda _recorded, _current: False,
                        spawn=lambda _cmd: self.fail("should not spawn"),
                    )
                )

    def test_ensure_spotty_bunny_running_restarts_on_commit_mismatch(
        self,
    ) -> None:
        from app.spotty_bunny_launch import (
            SPOTTY_BUNNY_PID_FILE,
            ensure_spotty_bunny_running,
        )

        spawned: list[int] = []

        def spawn(_cmd: object) -> int:
            spawned.append(99)
            return 99

        with TemporaryDirectory() as tmp:
            pid_dir = Path(tmp)
            (pid_dir / SPOTTY_BUNNY_PID_FILE).write_text(
                "4242\noldcommit\n",
                encoding="utf-8",
            )
            with (
                patch("app.spotty_bunny_launch.sys.platform", "darwin"),
                patch(
                    "app.spotty_bunny_launch.git_commit",
                    return_value="newcommit",
                ),
                patch(
                    "app.spotty_bunny_launch._spotty_bunny_process_alive",
                    return_value=True,
                ),
                patch("app.spotty_bunny_launch._terminate_pid"),
            ):
                self.assertTrue(
                    ensure_spotty_bunny_running(
                        pid_dir=pid_dir,
                        restart=lambda recorded, current: (
                            recorded == "oldcommit" and current == "newcommit"
                        ),
                        spawn=spawn,
                    )
                )
            self.assertEqual(spawned, [99])
            self.assertEqual(
                (pid_dir / SPOTTY_BUNNY_PID_FILE).read_text(encoding="utf-8"),
                "99\nnewcommit\n",
            )

    def test_ensure_spotty_bunny_running_bootout_then_installs(self) -> None:
        from app.spotty_bunny_launch import (
            SPOTTY_BUNNY_PID_FILE,
            ensure_spotty_bunny_running,
        )

        with TemporaryDirectory() as tmp:
            pid_dir = Path(tmp)
            (pid_dir / SPOTTY_BUNNY_PID_FILE).write_text(
                "4242\noldcommit\n",
                encoding="utf-8",
            )
            with (
                patch("app.spotty_bunny_launch.sys.platform", "darwin"),
                patch(
                    "app.spotty_bunny_launch.git_commit",
                    return_value="newcommit",
                ),
                patch(
                    "app.spotty_bunny_launch._spotty_bunny_process_alive",
                    return_value=True,
                ),
                patch("app.spotty_bunny_launch._terminate_pid"),
                patch("app.spotty_bunny_agent.bootout_loaded_agent") as bootout,
                patch("app.spotty_bunny_agent.install_agent", return_value=0),
                patch(
                    "app.spotty_bunny_launch.spotty_bunny_is_running",
                    return_value=True,
                ),
            ):
                self.assertTrue(
                    ensure_spotty_bunny_running(
                        pid_dir=pid_dir,
                        installed=True,
                        loaded=True,
                        restart=lambda _recorded, _current: True,
                        spawn=lambda _cmd: self.fail("should not spawn"),
                    )
                )
            bootout.assert_called_once()

    def test_ensure_spotty_bunny_running_does_not_spawn_after_install_timeout(
        self,
    ) -> None:
        from app.spotty_bunny_launch import ensure_spotty_bunny_running

        with TemporaryDirectory() as tmp:
            pid_dir = Path(tmp)
            with (
                patch("app.spotty_bunny_launch.sys.platform", "darwin"),
                patch("app.spotty_bunny_agent.install_agent", return_value=0),
                patch(
                    "app.spotty_bunny_launch.SPOTTY_BUNNY_LAUNCHD_WAIT_S",
                    0,
                ),
                patch(
                    "app.spotty_bunny_launch.spotty_bunny_is_running",
                    return_value=False,
                ),
            ):
                self.assertFalse(
                    ensure_spotty_bunny_running(
                        pid_dir=pid_dir,
                        installed=True,
                        loaded=False,
                        spawn=lambda _cmd: self.fail("should not spawn"),
                    )
                )

    def test_ensure_spotty_bunny_running_installs_when_agent_present(self) -> None:
        from app.spotty_bunny_launch import ensure_spotty_bunny_running

        with TemporaryDirectory() as tmp:
            pid_dir = Path(tmp)
            with (
                patch("app.spotty_bunny_launch.sys.platform", "darwin"),
                patch(
                    "app.spotty_bunny_agent.install_agent",
                    return_value=0,
                ) as install,
                patch(
                    "app.spotty_bunny_launch.spotty_bunny_is_running",
                    return_value=True,
                ),
            ):
                self.assertTrue(
                    ensure_spotty_bunny_running(
                        pid_dir=pid_dir,
                        installed=True,
                        loaded=False,
                        spawn=lambda _cmd: self.fail("should not spawn"),
                    )
                )
            install.assert_called_once_with(skip_chord_confirm=True)

    def test_ensure_spotty_bunny_running_polls_until_launchd_overlay_is_live(
        self,
    ) -> None:
        from app.spotty_bunny_launch import ensure_spotty_bunny_running

        with TemporaryDirectory() as tmp:
            pid_dir = Path(tmp)
            with (
                patch("app.spotty_bunny_launch.sys.platform", "darwin"),
                patch("app.spotty_bunny_agent.install_agent", return_value=0),
                patch(
                    "app.spotty_bunny_launch.SPOTTY_BUNNY_LAUNCHD_WAIT_S",
                    1.0,
                ),
                patch(
                    "app.spotty_bunny_launch.SPOTTY_BUNNY_STARTUP_WAIT_S",
                    0,
                ),
                patch(
                    "app.spotty_bunny_launch.spotty_bunny_is_running",
                    side_effect=[False, False, True],
                ),
            ):
                self.assertTrue(
                    ensure_spotty_bunny_running(
                        pid_dir=pid_dir,
                        installed=True,
                        loaded=False,
                        spawn=lambda _cmd: self.fail("should not spawn"),
                    )
                )

    def test_ensure_spotty_bunny_running_spawns_when_install_fails(self) -> None:
        from app.spotty_bunny_launch import (
            SPOTTY_BUNNY_PID_FILE,
            ensure_spotty_bunny_running,
        )

        spawned: list[int] = []

        def spawn(_cmd: object) -> int:
            spawned.append(99)
            return 99

        with TemporaryDirectory() as tmp:
            pid_dir = Path(tmp)
            with (
                patch("app.spotty_bunny_launch.sys.platform", "darwin"),
                patch(
                    "app.spotty_bunny_launch.git_commit",
                    return_value="abc1234",
                ),
                patch(
                    "app.spotty_bunny_launch._spotty_bunny_process_alive",
                    return_value=True,
                ),
                patch("app.spotty_bunny_agent.install_agent", return_value=1),
            ):
                self.assertTrue(
                    ensure_spotty_bunny_running(
                        pid_dir=pid_dir,
                        installed=True,
                        loaded=False,
                        spawn=spawn,
                    )
                )
            self.assertEqual(spawned, [99])
            self.assertEqual(
                (pid_dir / SPOTTY_BUNNY_PID_FILE).read_text(encoding="utf-8"),
                "99\nabc1234\n",
            )

    def test_ensure_spotty_bunny_running_fails_when_child_exits(self) -> None:
        from app.spotty_bunny_launch import (
            SPOTTY_BUNNY_PID_FILE,
            ensure_spotty_bunny_running,
        )

        with TemporaryDirectory() as tmp:
            pid_dir = Path(tmp)
            with (
                patch("app.spotty_bunny_launch.sys.platform", "darwin"),
                patch(
                    "app.spotty_bunny_launch._spotty_bunny_process_alive",
                    return_value=False,
                ),
            ):
                self.assertFalse(
                    ensure_spotty_bunny_running(
                        pid_dir=pid_dir,
                        spawn=lambda _cmd: 4242,
                    )
                )
            self.assertFalse((pid_dir / SPOTTY_BUNNY_PID_FILE).exists())

    def test_spotty_bunny_command_prefers_executable_local_bin(self) -> None:
        from app.spotty_bunny_launch import spotty_bunny_command

        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            local_bin = home / ".local" / "bin"
            local_bin.mkdir(parents=True)
            preferred = local_bin / "spotty-bunny"
            _write_executable(preferred)
            path_bin = home / "path-bin"
            path_bin.mkdir()
            other = path_bin / "spotty-bunny"
            _write_executable(other)
            with (
                patch("app.spotty_bunny_launch.Path.home", return_value=home),
                patch(
                    "app.spotty_bunny_launch.shutil.which",
                    return_value=str(other),
                ),
            ):
                self.assertEqual(spotty_bunny_command(), [str(preferred)])

    def test_spotty_bunny_command_skips_non_executable_local_bin(self) -> None:
        from app.spotty_bunny_launch import spotty_bunny_command

        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            local_bin = home / ".local" / "bin"
            local_bin.mkdir(parents=True)
            stale = local_bin / "spotty-bunny"
            stale.write_text("stale wrapper\n", encoding="utf-8")
            path_bin = home / "path-bin"
            path_bin.mkdir()
            other = path_bin / "spotty-bunny"
            _write_executable(other)
            with (
                patch("app.spotty_bunny_launch.Path.home", return_value=home),
                patch(
                    "app.spotty_bunny_launch.shutil.which",
                    return_value=str(other),
                ),
            ):
                self.assertEqual(spotty_bunny_command(), [str(other)])

    def test_spotty_bunny_is_running_clears_stale_pid(self) -> None:
        from app.spotty_bunny_launch import (
            SPOTTY_BUNNY_PID_FILE,
            ensure_spotty_bunny_running,
            spotty_bunny_is_running,
        )

        with TemporaryDirectory() as tmp:
            pid_dir = Path(tmp)
            pid_path = pid_dir / SPOTTY_BUNNY_PID_FILE
            pid_path.write_text("999999999\n", encoding="utf-8")
            self.assertFalse(spotty_bunny_is_running(pid_dir=pid_dir))
            self.assertFalse(pid_path.exists())

            spawned: list[object] = []

            def spawn(_cmd: object) -> int:
                spawned.append(_cmd)
                return 4242

            with (
                patch("app.spotty_bunny_launch.sys.platform", "darwin"),
                patch(
                    "app.spotty_bunny_launch.git_commit",
                    return_value="abc1234",
                ),
                patch(
                    "app.spotty_bunny_launch._spotty_bunny_process_alive",
                    return_value=True,
                ),
            ):
                self.assertTrue(
                    ensure_spotty_bunny_running(pid_dir=pid_dir, spawn=spawn)
                )
            self.assertEqual(len(spawned), 1)
            self.assertEqual(pid_path.read_text(encoding="utf-8"), "4242\nabc1234\n")

    def test_clear_spotty_bunny_pid_leaves_successor(self) -> None:
        from app.spotty_bunny_launch import (
            SPOTTY_BUNNY_PID_FILE,
            clear_spotty_bunny_pid,
        )

        with TemporaryDirectory() as tmp:
            pid_dir = Path(tmp)
            pid_path = pid_dir / SPOTTY_BUNNY_PID_FILE
            pid_path.write_text("99\nnewcommit\n", encoding="utf-8")
            clear_spotty_bunny_pid(only_pid=1, pid_dir=pid_dir)
            self.assertTrue(pid_path.exists())
            clear_spotty_bunny_pid(only_pid=99, pid_dir=pid_dir)
            self.assertFalse(pid_path.exists())

    def test_stop_spotty_bunny_clears_pid_file(self) -> None:
        from app.spotty_bunny_launch import (
            SPOTTY_BUNNY_PID_FILE,
            stop_spotty_bunny,
        )

        with TemporaryDirectory() as tmp:
            pid_dir = Path(tmp)
            pid_path = pid_dir / SPOTTY_BUNNY_PID_FILE
            pid_path.write_text("4242\n", encoding="utf-8")
            with (
                patch(
                    "app.spotty_bunny_launch._spotty_bunny_process_alive",
                    return_value=True,
                ),
                patch("app.spotty_bunny_launch._terminate_pid") as terminate,
            ):
                self.assertTrue(stop_spotty_bunny(pid_dir=pid_dir))
            terminate.assert_called_once_with(4242)
            self.assertFalse(pid_path.exists())

    def test_perform_install_skips_chord_confirm(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "app" / "spotty_bunny_app.py"
        ).read_text(encoding="utf-8")
        self.assertIn("def _perform_install(self) -> None:", source)
        self.assertIn("install_agent(skip_chord_confirm=True)", source)

    def test_placeholder_documents_examples(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "app" / "spotty_bunny_app.py"
        ).read_text(encoding="utf-8")
        self.assertIn("gh, c, yt, docs", source)
        self.assertIn("Tab is your friend :)", source)

    def test_primary_screen_uses_menu_bar_display(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "app" / "spotty_bunny_app.py"
        ).read_text(encoding="utf-8")
        self.assertIn("screens[0]", source)
        self.assertNotIn("mainScreen()", source)

    def test_about_panel_constants(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "app" / "spotty_bunny_about.py"
        ).read_text(encoding="utf-8")
        self.assertIn("Copyright © 2026 Henrique Andrade (GitHub's thehcma)", source)
        self.assertIn("https://github.com/thehcma", source)
        self.assertIn("Search and open your Bunnify shortcuts", source)
        self.assertNotIn("Quick shortcut overlay for Bunnify", source)
        self.assertIn("about_version_text_and_links", source)
        self.assertIn("ABOUT_PANEL_MAX_WIDTH", source)
        self.assertIn("ABOUT_FILL_RGB", source)
        self.assertIn("ABOUT_FRAME_RGB", source)
        self.assertIn("ABOUT_LABEL_RGB", source)
        self.assertIn("ABOUT_LINK_RGB", source)
        self.assertIn("ABOUT_WARN_RGB", source)
        self.assertIn("Update available:", source)
        self.assertIn("SpottyBunnyAboutPanel", source)
        self.assertIn("cancelOperation_", source)
        self.assertIn("performKeyEquivalent_", source)
        self.assertIn("releaseEscape_", source)
        self.assertIn("dismissWithEscape_", source)
        self.assertIn("control_textView_doCommandBySelector_", source)
        self.assertIn("setDelegate_(field)", source)
        self.assertIn("apply_spotty_chrome", source)
        self.assertIn("setUsesSingleLineMode_(False)", source)
        self.assertIn("NSLineBreakByWordWrapping", source)
        self.assertIn("pointingHandCursor", source)
        self.assertIn("NSTrackingActiveAlways", source)
        self.assertIn("_AboutLinkField", source)
        self.assertIn("load_about_runtime_info", source)
        self.assertIn("about_details_text_and_links", source)
        self.assertIn("about_version_text_and_links", source)
        self.assertIn("_multi_link_field", source)
        self.assertIn("textView_clickedOnLink_atIndex_", source)
        self.assertIn("handle_about_link_click", source)
        info_source = (
            Path(__file__).resolve().parents[1] / "app" / "spotty_bunny_about_info.py"
        ).read_text(encoding="utf-8")
        self.assertIn("Local server", info_source)
        self.assertIn("Remote server", info_source)
        license_url = "https://github.com/the-hcma/bunnify/blob/main/LICENSE"
        self.assertIn(license_url, info_source)
        self.assertIn("Bookmarks:", info_source)
        self.assertIn("GitHub:", info_source)
        self.assertIn("License:", info_source)
        self.assertIn("Repository:", info_source)
        self.assertIn("SPOTTY_BUNNY_REPO_URL", info_source)
        self.assertIn("PYPI_PROJECT_URL", info_source)
        self.assertIn('["open", "-t", str(path)]', info_source)
        self.assertIn("def about_details_text_and_links", info_source)
        self.assertIn("def about_link_spans", info_source)
        self.assertIn("def about_version_text_and_links", info_source)
        self.assertIn("def handle_about_link_click", info_source)

    def test_search_field_is_centered_with_logo_on_right(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "app" / "spotty_bunny_app.py"
        ).read_text(encoding="utf-8")
        self.assertIn("NSTextAlignmentLeft", source)
        self.assertIn("_CenteredFieldCell", source)
        self.assertIn("FIELD_TEXT_INSET", source)
        self.assertIn("editWithFrame_inView_editor_delegate_event_", source)
        self.assertIn("selectWithFrame_inView_editor_delegate_start_length_", source)
        self.assertIn("NSColor.blackColor()", source)
        self.assertIn("setBezeled_(False)", source)
        self.assertIn("NSFocusRingTypeNone", source)
        self.assertIn("PANEL_INSET", source)
        self.assertIn("LOGO_LEFT = PANEL_WIDTH - FIELD_LEFT - LOGO_SIZE", source)

    def test_search_panel_can_become_key_for_typing(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "app" / "spotty_bunny_app.py"
        ).read_text(encoding="utf-8")
        self.assertIn("class SpottyBunnyPanel", source)
        self.assertIn("canBecomeKeyWindow", source)
        self.assertIn("SpottyBunnyPanel.alloc()", source)
        self.assertIn("class SpottyBunnySearchField", source)
        self.assertIn("SpottyBunnySearchField.alloc()", source)
        self.assertIn("_install_edit_menu", source)
        self.assertIn("_dispatch_edit_key_equivalent", source)
        self.assertIn("edit_action_for_key", source)
        self.assertIn("completion_navigation_disposition", source)
        self.assertIn("PAGE_UP_KEYCODE", source)
        self.assertIn("PAGE_DOWN_KEYCODE", source)
        complete_source = (
            Path(__file__).resolve().parents[1] / "app" / "spotty_bunny_complete.py"
        ).read_text(encoding="utf-8")
        self.assertIn("scrollPageUp:", complete_source)
        self.assertIn("scrollPageDown:", complete_source)
        self.assertIn("edit_command_modifiers_ok", source)
        self.assertIn("_completion_table_visible", source)
        self.assertIn("completion_navigation_disposition", source)
        self.assertIn("page_selector_for_keycode", source)
        self.assertIn("dismissWithEscape_", source)
        self.assertIn("releaseEscape_", source)
        self.assertIn("ESCAPE_KEYCODE", source)
        self.assertIn("TAB_KEYCODE", source)
        self.assertIn("completeWithTab_", source)
        self.assertIn("is_tab_completion_selector", source)
        self.assertNotIn("tap Tab → complete", source)
        self.assertIn("_maybe_offer_gh_install", source)
        self.assertIn("_confirm_install_gh", source)
        self.assertIn("setRefusesFirstResponder_(True)", source)
        self.assertIn("_escape_held", source)
        self.assertNotIn("ESCAPE_DISMISS_WINDOW_S", source)
        self.assertIn('{"cancel:", "cancelOperation:"}', source)
        self.assertIn("tap Escape → dismiss", source)

    def test_search_panel_has_no_title_bar_label(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "app" / "spotty_bunny_app.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn('setTitle_("spotty-bunny")', source)
        self.assertIn("showAbout:", source)
        self.assertIn("SpottyBunnyLogoButton", source)
        self.assertIn("def installSpottyBunny_", source)
        self.assertIn("def quitSpottyBunny_", source)
        self.assertIn("def uninstallSpottyBunny_", source)
        self.assertIn("def upgradeSpottyBunny_", source)
        self.assertIn("menuNeedsUpdate_", source)
        self.assertIn("installed=is_agent_installed()", source)
        self.assertIn("outdated=self._update_status.outdated", source)
        menu_source = (
            Path(__file__).resolve().parents[1] / "app" / "spotty_bunny_menu.py"
        ).read_text(encoding="utf-8")
        self.assertIn("Install Spotty Bunny", menu_source)
        self.assertIn("Quit Spotty Bunny", menu_source)
        self.assertIn("Uninstall Spotty Bunny", menu_source)
        self.assertIn("Upgrade Spotty Bunny", menu_source)
        self.assertIn("installSpottyBunny:", menu_source)
        self.assertIn("quitSpottyBunny:", menu_source)
        self.assertIn("uninstallSpottyBunny:", menu_source)
        self.assertIn("upgradeSpottyBunny:", menu_source)
        self.assertIn("setMenu_(menu)", source)
        self.assertIn("rightMouseDown_", source)
        self.assertIn('refresh_launch_agents="server"', source)
        self.assertIn("refresh_agent_plist", source)
        self.assertIn("if refresh_agent_plist() != 0", source)
        self.assertIn("bootout_loaded_agent", source)
        self.assertIn("self._about_panel.close()", source)

    def test_about_panel_build_info_prewarmed(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "app" / "spotty_bunny_app.py"
        ).read_text(encoding="utf-8")
        self.assertIn("self._io.submit(get_build_info", source)

    def test_about_panel_resign_does_not_dismiss_main_while_visible(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "app" / "spotty_bunny_app.py"
        ).read_text(encoding="utf-8")
        self.assertIn("if self._about_open:", source)
        self.assertIn("def hideAbout_", source)
        self.assertIn("self._about_panel.setDelegate_(self)", source)
        self.assertIn("self._about_open", source)

    def test_license_names_copyright_holder(self) -> None:
        root = Path(__file__).resolve().parents[1]
        license_text = (root / "LICENSE").read_text(encoding="utf-8")
        self.assertIn(
            "Copyright (c) 2026 Henrique Andrade (GitHub's thehcma)",
            license_text,
        )
        pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('name = "Henrique Andrade"', pyproject)


class SpottyBunnyResolveTests(SimpleTestCase):
    def test_failure_does_not_append_history(self) -> None:
        from app.client import ClientError
        from app.spotty_bunny_resolve import resolve_query

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "repl_history"

            def append(line: str) -> None:
                append_history_line(line, path=path)

            def boom(*_args: object, **_kwargs: object) -> object:
                raise ClientError("unknown shortcut")

            with self.assertRaises(ClientError):
                resolve_query(
                    "nope",
                    base_url="http://127.0.0.1:9",
                    append_fn=append,
                    open_fn=lambda _url: None,
                    resolve_fn=boom,
                )
            self.assertEqual(load_history_lines(path=path), [])

    def test_lookup_does_not_open_or_append(self) -> None:
        from app.client import ResolvedShortcut
        from app.spotty_bunny_resolve import lookup_resolved_url

        seen: dict[str, object] = {}

        def resolve_fn(query: str, **kwargs: object) -> ResolvedShortcut:
            seen.update(kwargs)
            return ResolvedShortcut(
                url="https://github.com",
                kind="shortcut",
                key=query,
            )

        url = lookup_resolved_url(
            "  gh  ",
            base_url="http://127.0.0.1:8000",
            resolve_fn=resolve_fn,
        )
        self.assertEqual(url, "https://github.com")
        self.assertIs(seen.get("strict"), False)

    def test_lookup_google_fallback_for_unknown_shortcut(self) -> None:
        from app.client import ResolvedShortcut
        from app.spotty_bunny_resolve import lookup_resolved_url

        seen: dict[str, object] = {}

        def resolve_fn(query: str, **kwargs: object) -> ResolvedShortcut:
            seen.update(kwargs)
            return ResolvedShortcut(
                url=f"https://www.google.com/search?q={query}",
                kind="google_fallback",
                key=query.split()[0],
            )

        url = lookup_resolved_url(
            "asdfasdf",
            base_url="http://127.0.0.1:8000",
            resolve_fn=resolve_fn,
        )
        self.assertEqual(url, "https://www.google.com/search?q=asdfasdf")
        self.assertIs(seen.get("strict"), False)

    def test_open_failure_does_not_append_history(self) -> None:
        from app.client import ClientError, ResolvedShortcut
        from app.spotty_bunny_resolve import resolve_query

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "repl_history"

            def append(line: str) -> None:
                append_history_line(line, path=path)

            def boom_open(_url: str) -> None:
                raise ClientError("no browser")

            with self.assertRaises(ClientError):
                resolve_query(
                    "gh",
                    base_url="http://127.0.0.1:8000",
                    append_fn=append,
                    open_fn=boom_open,
                    resolve_fn=lambda query, **_kwargs: ResolvedShortcut(
                        url="https://github.com",
                        kind="shortcut",
                        key=query,
                    ),
                )
            self.assertEqual(load_history_lines(path=path), [])

    def test_resolve_still_current_requires_matching_seq(self) -> None:
        from app.spotty_bunny_resolve import resolve_still_current

        self.assertTrue(resolve_still_current(expected_seq=4, seq=4))
        self.assertFalse(resolve_still_current(expected_seq=4, seq=5))

    def test_success_appends_shared_history_and_opens(self) -> None:
        from app.client import ResolvedShortcut
        from app.spotty_bunny_resolve import resolve_query

        opened: list[str] = []
        seen: dict[str, object] = {}
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "repl_history"

            def append(line: str) -> None:
                append_history_line(line, path=path)

            def resolve_fn(query: str, **kwargs: object) -> ResolvedShortcut:
                seen.update(kwargs)
                return ResolvedShortcut(
                    url="https://github.com",
                    kind="shortcut",
                    key=query,
                )

            url = resolve_query(
                "  gh  ",
                base_url="http://127.0.0.1:8000",
                append_fn=append,
                open_fn=opened.append,
                resolve_fn=resolve_fn,
            )
            self.assertEqual(url, "https://github.com")
            self.assertEqual(opened, ["https://github.com"])
            self.assertEqual(load_history_lines(path=path), ["gh"])
            self.assertIs(seen.get("strict"), False)


class SpottyBunnyStatusTests(SimpleTestCase):
    def test_connection_error_tells_user_to_start_server(self) -> None:
        from app.spotty_bunny_status import (
            SHORTCUTS_LOAD_FAILED,
            format_spotty_bunny_status,
        )

        line = format_spotty_bunny_status(
            "Cannot reach Bunnify server at 'http://127.0.0.1:8000/api/keys/': "
            "Connection refused. Is `./scripts/bunnify-server` running?"
        )
        self.assertEqual(line, SHORTCUTS_LOAD_FAILED)
        self.assertIn("`bunnify setup`", line)

    def test_empty_error_uses_shortcuts_load_copy(self) -> None:
        from app.spotty_bunny_status import (
            SHORTCUTS_LOAD_FAILED,
            format_spotty_bunny_status,
        )

        self.assertEqual(format_spotty_bunny_status(""), SHORTCUTS_LOAD_FAILED)

    def test_timeout_client_error_uses_timeout_copy(self) -> None:
        from app.client import ClientError
        from app.spotty_bunny_status import (
            TIMEOUT_CONTACTING_SERVER,
            format_spotty_bunny_status,
        )

        line = format_spotty_bunny_status(
            ClientError(
                "Timed out contacting Bunnify server at "
                "'http://127.0.0.1:8000/api/keys/'"
            )
        )
        self.assertEqual(line, TIMEOUT_CONTACTING_SERVER)

    def test_timeout_error_instance_uses_timeout_copy(self) -> None:
        from app.spotty_bunny_status import (
            TIMEOUT_CONTACTING_SERVER,
            format_spotty_bunny_status,
        )

        self.assertEqual(
            format_spotty_bunny_status(TimeoutError("timed out")),
            TIMEOUT_CONTACTING_SERVER,
        )

    def test_unknown_shortcut_suggests_tab(self) -> None:
        from app.spotty_bunny_status import (
            UNKNOWN_SHORTCUT_HINT,
            format_spotty_bunny_status,
        )

        self.assertEqual(
            format_spotty_bunny_status("Unknown shortcut"),
            UNKNOWN_SHORTCUT_HINT,
        )

    def test_canned_status_lines_cover_known_errors(self) -> None:
        from app.spotty_bunny_status import (
            SHORTCUTS_LOAD_FAILED,
            canned_spotty_bunny_status_lines,
        )

        lines = canned_spotty_bunny_status_lines()
        self.assertIn(SHORTCUTS_LOAD_FAILED, lines)
        self.assertGreaterEqual(len(lines), 3)

    def test_status_commands_use_courier_markup(self) -> None:
        from app.spotty_bunny_status import (
            SHORTCUTS_LOAD_FAILED,
            TIMEOUT_CONTACTING_SERVER,
            status_text_runs,
        )

        self.assertIn(
            ("bunnify setup", True),
            status_text_runs(SHORTCUTS_LOAD_FAILED),
        )
        self.assertIn(
            ("bunnify setup", True),
            status_text_runs(TIMEOUT_CONTACTING_SERVER),
        )
        source = (
            Path(__file__).resolve().parents[1] / "app" / "spotty_bunny_app.py"
        ).read_text(encoding="utf-8")
        self.assertIn('STATUS_COMMAND_FONT = "Courier"', source)

    def test_status_wrap_prefers_punctuation(self) -> None:
        from app.spotty_bunny_status import (
            SHORTCUTS_LOAD_FAILED,
            status_punctuation_chunks,
            wrap_status_preferring_punctuation,
        )

        chunks = status_punctuation_chunks(SHORTCUTS_LOAD_FAILED)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(chunks[0].endswith("—"))

        def fits(text: str) -> bool:
            return len(text) <= len(chunks[0])

        wrapped = wrap_status_preferring_punctuation(SHORTCUTS_LOAD_FAILED, fits=fits)
        self.assertTrue(wrapped.split("\n", 1)[0].endswith("—"))
        self.assertEqual(
            wrap_status_preferring_punctuation(
                SHORTCUTS_LOAD_FAILED, fits=lambda _text: True
            ),
            SHORTCUTS_LOAD_FAILED,
        )

    def test_status_layout_is_centered_and_sized_to_copy(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "app" / "spotty_bunny_app.py"
        ).read_text(encoding="utf-8")
        self.assertIn("STATUS_INSET", source)
        self.assertIn("STATUS_ERROR_RGB", source)
        self.assertNotIn("systemRedColor", source)
        self.assertIn("wrap_status_preferring_punctuation", source)
        self.assertIn("NSTextAlignmentCenter", source)
        self.assertIn("_CenteredWrappingFieldCell", source)
        self.assertIn("drawWithRect_options_", source)
        self.assertIn("hideAbout_", source)
        self.assertIn("str(self.status.stringValue())", source)
        self.assertIn("_status_text_height", source)
        self.assertIn("apply_spotty_chrome", source)
        self.assertIn("fill_rgb=PANEL_FILL_RGB", source)
        self.assertIn("frame_rgb=PANEL_FRAME_RGB", source)


class SpottyBunnyUpdateTests(SimpleTestCase):
    def test_cache_is_stale_after_a_day(self) -> None:
        from app.spotty_bunny_update import CHECK_INTERVAL_S, cache_is_stale

        self.assertTrue(cache_is_stale(None, now=100.0))
        self.assertFalse(cache_is_stale(100.0, now=100.0 + CHECK_INTERVAL_S - 1))
        self.assertTrue(cache_is_stale(100.0, now=100.0 + CHECK_INTERVAL_S))

    def test_is_version_outdated_compares_pep440(self) -> None:
        from app.spotty_bunny_update import is_version_outdated

        self.assertTrue(is_version_outdated("0.6.1", "0.7.0"))
        self.assertFalse(is_version_outdated("0.7.0", "0.7.0"))
        self.assertFalse(is_version_outdated("0.7.0", "0.6.1"))
        self.assertFalse(is_version_outdated("0.6.1", None))

    def test_is_version_outdated_unparseable_current_is_not_outdated(self) -> None:
        from app.spotty_bunny_update import is_version_outdated

        self.assertFalse(is_version_outdated("unknown", "0.7.0"))
        self.assertFalse(is_version_outdated("0.7.0", "not-a-version"))

    def test_logo_menu_specs_are_sorted_and_hide_upgrade_when_current(self) -> None:
        from app.spotty_bunny_menu import (
            INSTALL_MENU_TITLE,
            QUIT_MENU_TITLE,
            UNINSTALL_MENU_TITLE,
            UPGRADE_MENU_TITLE,
            logo_menu_specs,
        )

        missing = logo_menu_specs(installed=False, outdated=True)
        missing_titles = [title for title, _action in missing]
        self.assertEqual(missing_titles, sorted(missing_titles))
        self.assertEqual(missing_titles, [INSTALL_MENU_TITLE, QUIT_MENU_TITLE])
        current = logo_menu_specs(installed=True, outdated=False)
        titles = [title for title, _action in current]
        self.assertEqual(titles, sorted(titles))
        self.assertEqual(
            titles,
            [QUIT_MENU_TITLE, UNINSTALL_MENU_TITLE],
        )
        outdated = logo_menu_specs(installed=True, outdated=True)
        outdated_titles = [title for title, _action in outdated]
        self.assertEqual(outdated_titles, sorted(outdated_titles))
        self.assertEqual(
            outdated_titles,
            [QUIT_MENU_TITLE, UNINSTALL_MENU_TITLE, UPGRADE_MENU_TITLE],
        )

    def test_pypi_latest_version_reads_info_version(self) -> None:
        from app.pypi import pypi_latest_version

        class _Response:
            def __enter__(self) -> _Response:
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

            def read(self) -> bytes:
                return b'{"info": {"version": "1.2.3"}}'

        latest = pypi_latest_version(urlopen=lambda *_a, **_k: _Response())
        self.assertEqual(latest, "1.2.3")

    def test_read_cached_update_status_malformed_cache(self) -> None:
        from app.spotty_bunny_update import read_cached_update_status

        with TemporaryDirectory() as tmp:
            cache = Path(tmp) / "pypi-latest.json"
            cache.write_text("{not json", encoding="utf-8")
            status = read_cached_update_status(cache_path=cache, current="1.0.0")
            self.assertIsNone(status.checked_at)
            self.assertIsNone(status.latest)
            self.assertFalse(status.outdated)

    def test_read_cached_update_status_round_trip(self) -> None:
        from app.spotty_bunny_update import (
            read_cached_update_status,
            refresh_update_status,
        )

        with TemporaryDirectory() as tmp:
            cache = Path(tmp) / "pypi-latest.json"
            refresh_update_status(
                cache_path=cache,
                current="1.0.0",
                fetch=lambda: "2.0.0",
                now=10.0,
            )
            status = read_cached_update_status(cache_path=cache, current="1.0.0")
            self.assertEqual(status.checked_at, 10.0)
            self.assertEqual(status.latest, "2.0.0")
            self.assertTrue(status.outdated)

    def test_refresh_update_status_caches_and_skips_fresh_fetch(self) -> None:
        from app.spotty_bunny_update import (
            CHECK_INTERVAL_S,
            refresh_update_status,
        )

        fetches: list[int] = []

        def fetch() -> str:
            fetches.append(1)
            return "9.9.9"

        with TemporaryDirectory() as tmp:
            cache = Path(tmp) / "pypi-latest.json"
            first = refresh_update_status(
                cache_path=cache,
                current="0.1.0",
                fetch=fetch,
                now=1_000.0,
            )
            self.assertTrue(first.outdated)
            self.assertEqual(first.latest, "9.9.9")
            self.assertEqual(len(fetches), 1)
            second = refresh_update_status(
                cache_path=cache,
                current="0.1.0",
                fetch=fetch,
                now=1_000.0 + CHECK_INTERVAL_S - 1,
            )
            self.assertEqual(len(fetches), 1)
            self.assertTrue(second.outdated)
            third = refresh_update_status(
                cache_path=cache,
                current="0.1.0",
                fetch=fetch,
                now=1_000.0 + CHECK_INTERVAL_S,
            )
            self.assertEqual(len(fetches), 2)
            self.assertTrue(third.outdated)

    def test_refresh_keeps_cache_when_fetch_fails(self) -> None:
        from app.spotty_bunny_update import refresh_update_status

        with TemporaryDirectory() as tmp:
            cache = Path(tmp) / "pypi-latest.json"
            refresh_update_status(
                cache_path=cache,
                current="0.1.0",
                fetch=lambda: "2.0.0",
                now=50.0,
            )
            failed = refresh_update_status(
                cache_path=cache,
                current="0.1.0",
                fetch=lambda: None,
                force=True,
                now=99.0,
            )
            self.assertEqual(failed.latest, "2.0.0")
            self.assertEqual(failed.checked_at, 99.0)
            self.assertTrue(failed.outdated)

    def test_refresh_throttles_after_failed_fetch(self) -> None:
        from app.spotty_bunny_update import (
            CHECK_INTERVAL_S,
            refresh_update_status,
        )

        fetches: list[int] = []

        def fetch() -> str | None:
            fetches.append(1)
            return None

        with TemporaryDirectory() as tmp:
            cache = Path(tmp) / "pypi-latest.json"
            first = refresh_update_status(
                cache_path=cache,
                current="0.1.0",
                fetch=fetch,
                now=10.0,
            )
            self.assertIsNone(first.latest)
            self.assertEqual(first.checked_at, 10.0)
            self.assertFalse(first.outdated)
            self.assertEqual(len(fetches), 1)
            second = refresh_update_status(
                cache_path=cache,
                current="0.1.0",
                fetch=fetch,
                now=10.0 + CHECK_INTERVAL_S - 1,
            )
            self.assertEqual(len(fetches), 1)
            self.assertEqual(second.checked_at, 10.0)


class _FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds

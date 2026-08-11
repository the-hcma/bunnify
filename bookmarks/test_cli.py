"""Tests for the Bunnify CLI client and resolve/keys APIs."""

from __future__ import annotations

import importlib
import sys
from io import StringIO
from unittest.mock import patch

from django.test import Client, TestCase, override_settings

from app import interactive
from app.cli import _run, matching_keys
from app.client import ClientError, KeyEntry, ResolvedShortcut, parse_keys_payload

from .models import Bookmark


class ResolveApiTests(TestCase):
    def setUp(self) -> None:
        self.client = Client()
        Bookmark.objects.create(
            key="gh", description="GitHub", url="https://github.com"
        )
        Bookmark.objects.create(
            key="pr",
            description="Pull Request",
            url="https://github.com/#{repo}/pull/#{pr_number}",
            defaults={"repo": "default-org/default-repo"},
        )

    def test_resolve_bookmark(self) -> None:
        response = self.client.get("/api/resolve/", {"q": "gh", "strict": "1"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["url"], "https://github.com")
        self.assertEqual(data["kind"], "bookmark")
        self.assertEqual(data["key"], "gh")

    def test_resolve_strict_unknown(self) -> None:
        response = self.client.get("/api/resolve/", {"q": "nope", "strict": "1"})
        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertIn("Unknown shortcut", data["error"])

    def test_resolve_strict_rejects_htt_prefix_without_scheme(self) -> None:
        response = self.client.get("/api/resolve/", {"q": "htt", "strict": "1"})
        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertIn("Unknown shortcut", data["error"])

    def test_resolve_direct_https_url(self) -> None:
        response = self.client.get(
            "/api/resolve/", {"q": "https://example.com/x", "strict": "1"}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["url"], "https://example.com/x")
        self.assertEqual(data["kind"], "direct_url")

    def test_resolve_direct_url_normalizes_uppercase_scheme(self) -> None:
        response = self.client.get(
            "/api/resolve/", {"q": "HTTP://Example.COM/Path", "strict": "1"}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["url"], "http://Example.COM/Path")
        self.assertEqual(data["kind"], "direct_url")

    def test_resolve_bookmark_preserves_absolute_non_http_scheme(self) -> None:
        Bookmark.objects.create(
            key="ftp",
            description="FTP example",
            url="ftp://example.com/file.txt",
        )
        response = self.client.get("/api/resolve/", {"q": "ftp", "strict": "1"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["url"], "ftp://example.com/file.txt")
        self.assertEqual(data["kind"], "bookmark")
        self.assertEqual(data["key"], "ftp")

    def test_resolve_special_absolute(self) -> None:
        response = self.client.get("/api/resolve/", {"q": "h", "strict": "1"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["url"].endswith("/list/"))
        self.assertEqual(data["kind"], "special")

    @override_settings(FORCE_SCRIPT_NAME="/bunnify")
    def test_resolve_special_preserves_script_prefix(self) -> None:
        response = self.client.get(
            "/api/resolve/",
            {"q": "h", "strict": "1"},
            SCRIPT_NAME="/bunnify",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["url"], "http://testserver/bunnify/list/")

    def test_keys_endpoint(self) -> None:
        response = self.client.get("/api/keys/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("h", data["keys"])
        self.assertIn("cmd", data["keys"])
        self.assertIn("gh", data["keys"])
        self.assertIn("pr", data["keys"])
        entries = {item["key"]: item for item in data["entries"]}
        self.assertEqual(entries["gh"]["description"], "GitHub")
        self.assertEqual(entries["gh"]["url"], "https://github.com")
        self.assertEqual(entries["gh"]["params"], [])
        self.assertEqual(entries["pr"]["params"], ["repo", "pr_number"])
        self.assertEqual(entries["pr"]["optional_params"], ["repo"])
        self.assertNotIn("defaults", entries["pr"])
        self.assertEqual(entries["h"]["url"], "/list/")
        self.assertEqual(entries["cmd"]["description"], "Command palette")


class CliUnitTests(TestCase):
    def test_matching_keys(self) -> None:
        keys = ["g", "gh", "pr", "printer"]
        self.assertEqual(matching_keys(keys, "g"), ["g", "gh"])
        self.assertEqual(matching_keys(keys, "pr"), ["pr", "printer"])
        self.assertEqual(matching_keys(keys, "PR"), ["pr", "printer"])

    @patch("app.cli.resolve_shortcut")
    @patch("app.cli.fetch_keys")
    def test_direct_open(
        self,
        mock_fetch_keys,
        mock_resolve,
    ) -> None:
        mock_fetch_keys.return_value = ["gh", "pr"]
        mock_resolve.return_value = ResolvedShortcut(
            url="https://github.com", kind="bookmark", key="gh"
        )
        opened: list[str] = []

        def opener(url: str) -> bool:
            opened.append(url)
            return True

        with patch("sys.stdout", new_callable=StringIO):
            with patch("sys.stderr", new_callable=StringIO):
                _run(
                    shortcut_args=("gh",),
                    base_url="http://127.0.0.1:8000",
                    list_keys=False,
                    use_fzf=False,
                    fzf_query="",
                    print_url=False,
                    open_browser=True,
                    opener=opener,
                )

        self.assertEqual(opened, ["https://github.com"])
        mock_resolve.assert_called_once_with(
            "gh", base_url="http://127.0.0.1:8000", strict=True
        )

    @patch("app.cli.resolve_shortcut")
    @patch("app.cli.fetch_key_entries")
    def test_interactive_open(
        self,
        mock_fetch_entries,
        mock_resolve,
    ) -> None:
        mock_fetch_entries.return_value = [KeyEntry(key="gh")]
        mock_resolve.return_value = ResolvedShortcut(
            url="https://github.com", kind="bookmark", key="gh"
        )
        opened: list[str] = []
        responses = iter(["gh", "quit"])

        def opener(url: str) -> bool:
            opened.append(url)
            return True

        with patch("sys.stdout", new_callable=StringIO):
            with patch("sys.stderr", new_callable=StringIO):
                _run(
                    shortcut_args=(),
                    base_url="http://127.0.0.1:8000",
                    list_keys=False,
                    use_fzf=False,
                    fzf_query="",
                    print_url=False,
                    open_browser=True,
                    opener=opener,
                    input_fn=lambda _prompt: next(responses),
                )

        self.assertEqual(opened, ["https://github.com"])
        mock_resolve.assert_called_once_with(
            "gh", base_url="http://127.0.0.1:8000", strict=True
        )

    @patch("app.cli.resolve_shortcut")
    @patch("app.cli.fetch_key_entries")
    def test_interactive_loop_runs_multiple_commands(
        self,
        mock_fetch_entries,
        mock_resolve,
    ) -> None:
        mock_fetch_entries.return_value = [
            KeyEntry(key="gh"),
            KeyEntry(key="pr"),
        ]
        mock_resolve.side_effect = [
            ResolvedShortcut(url="https://github.com", kind="bookmark", key="gh"),
            ResolvedShortcut(
                url="https://github.com/org/repo/pull/1",
                kind="bookmark",
                key="pr",
            ),
        ]
        opened: list[str] = []
        responses = iter(["gh", "pr 1", "quit"])

        def opener(url: str) -> bool:
            opened.append(url)
            return True

        with patch("sys.stdout", new_callable=StringIO):
            with patch("sys.stderr", new_callable=StringIO):
                _run(
                    shortcut_args=(),
                    base_url="http://127.0.0.1:8000",
                    list_keys=False,
                    use_fzf=False,
                    fzf_query="",
                    print_url=False,
                    open_browser=True,
                    opener=opener,
                    input_fn=lambda _prompt: next(responses),
                )

        self.assertEqual(
            opened,
            ["https://github.com", "https://github.com/org/repo/pull/1"],
        )
        self.assertEqual(mock_resolve.call_count, 2)

    @patch("app.cli.resolve_shortcut")
    @patch("app.cli.fetch_key_entries")
    def test_interactive_error_continues_loop(
        self,
        mock_fetch_entries,
        mock_resolve,
    ) -> None:
        mock_fetch_entries.return_value = [KeyEntry(key="gh")]
        mock_resolve.side_effect = [
            ClientError("Unknown shortcut"),
            ResolvedShortcut(url="https://github.com", kind="bookmark", key="gh"),
        ]
        opened: list[str] = []
        responses = iter(["nope", "gh", "quit"])

        def opener(url: str) -> bool:
            opened.append(url)
            return True

        stderr = StringIO()
        with patch("sys.stdout", new_callable=StringIO):
            with patch("sys.stderr", stderr):
                _run(
                    shortcut_args=(),
                    base_url="http://127.0.0.1:8000",
                    list_keys=False,
                    use_fzf=False,
                    fzf_query="",
                    print_url=False,
                    open_browser=True,
                    opener=opener,
                    input_fn=lambda _prompt: next(responses),
                )

        self.assertEqual(opened, ["https://github.com"])
        self.assertIn("Unknown shortcut", stderr.getvalue())

    @patch("app.cli.resolve_shortcut")
    @patch("app.cli.fetch_keys")
    def test_ambiguous_prefix_uses_fzf(
        self,
        mock_fetch_keys,
        mock_resolve,
    ) -> None:
        mock_fetch_keys.return_value = ["pr", "printer"]
        mock_resolve.return_value = ResolvedShortcut(
            url="http://printer.example", kind="bookmark", key="printer"
        )
        opened: list[str] = []

        def opener(url: str) -> bool:
            opened.append(url)
            return True

        def fake_fzf(keys: list[str], query: str = "") -> str | None:
            self.assertEqual(keys, ["pr", "printer"])
            self.assertEqual(query, "p")
            return "printer"

        with patch("sys.stdout", new_callable=StringIO):
            with patch("sys.stderr", new_callable=StringIO):
                _run(
                    shortcut_args=("p",),
                    base_url="http://127.0.0.1:8000",
                    list_keys=False,
                    use_fzf=False,
                    fzf_query="",
                    print_url=False,
                    open_browser=True,
                    opener=opener,
                    fzf_picker=fake_fzf,
                )

        self.assertEqual(opened, ["http://printer.example"])
        mock_resolve.assert_called_once_with(
            "printer", base_url="http://127.0.0.1:8000", strict=True
        )

    @patch("app.cli.resolve_shortcut")
    @patch("app.cli.fetch_keys")
    def test_unique_prefix_expands(
        self,
        mock_fetch_keys,
        mock_resolve,
    ) -> None:
        mock_fetch_keys.return_value = ["pr", "printer"]
        mock_resolve.return_value = ResolvedShortcut(
            url="http://printer.example", kind="bookmark", key="printer"
        )
        opened: list[str] = []

        def opener(url: str) -> bool:
            opened.append(url)
            return True

        with patch("sys.stdout", new_callable=StringIO):
            with patch("sys.stderr", new_callable=StringIO):
                _run(
                    shortcut_args=("pri",),
                    base_url="http://127.0.0.1:8000",
                    list_keys=False,
                    use_fzf=False,
                    fzf_query="",
                    print_url=False,
                    open_browser=True,
                    opener=opener,
                    fzf_picker=lambda *_a, **_k: self.fail("fzf should not run"),
                )

        self.assertEqual(opened, ["http://printer.example"])
        mock_resolve.assert_called_once_with(
            "printer", base_url="http://127.0.0.1:8000", strict=True
        )

    @patch("app.cli.fetch_keys")
    def test_list_keys(self, mock_fetch_keys) -> None:
        mock_fetch_keys.return_value = ["h", "gh"]
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            _run(
                shortcut_args=(),
                base_url="http://127.0.0.1:8000",
                list_keys=True,
                use_fzf=False,
                fzf_query="",
                print_url=False,
                open_browser=False,
            )
        self.assertEqual(stdout.getvalue().splitlines(), ["h", "gh"])

    @patch("app.cli.resolve_shortcut")
    @patch("app.cli.fetch_keys")
    def test_fzf_mode_preserves_params(
        self,
        mock_fetch_keys,
        mock_resolve,
    ) -> None:
        mock_fetch_keys.return_value = ["gh", "pr"]
        mock_resolve.return_value = ResolvedShortcut(
            url="https://github.com/org/repo/pull/12345",
            kind="bookmark",
            key="pr",
        )

        def fake_fzf(keys: list[str], query: str = "") -> str | None:
            self.assertEqual(keys, ["gh", "pr"])
            self.assertEqual(query, "")
            return "pr"

        with patch("sys.stdout", new_callable=StringIO):
            with patch("sys.stderr", new_callable=StringIO):
                _run(
                    shortcut_args=("12345",),
                    base_url="http://127.0.0.1:8000",
                    list_keys=False,
                    use_fzf=True,
                    fzf_query="",
                    print_url=True,
                    open_browser=False,
                    fzf_picker=fake_fzf,
                )

        mock_resolve.assert_called_once_with(
            "pr 12345", base_url="http://127.0.0.1:8000", strict=True
        )

    @patch("app.cli.resolve_shortcut")
    @patch("app.cli.fetch_keys")
    def test_fzf_mode_uses_explicit_query_seed(
        self,
        mock_fetch_keys,
        mock_resolve,
    ) -> None:
        mock_fetch_keys.return_value = ["gh", "pr"]
        mock_resolve.return_value = ResolvedShortcut(
            url="https://github.com", kind="bookmark", key="gh"
        )

        def fake_fzf(keys: list[str], query: str = "") -> str | None:
            self.assertEqual(keys, ["gh", "pr"])
            self.assertEqual(query, "g")
            return "gh"

        with patch("sys.stdout", new_callable=StringIO):
            with patch("sys.stderr", new_callable=StringIO):
                _run(
                    shortcut_args=(),
                    base_url="http://127.0.0.1:8000",
                    list_keys=False,
                    use_fzf=True,
                    fzf_query="g",
                    print_url=True,
                    open_browser=False,
                    fzf_picker=fake_fzf,
                )

        mock_resolve.assert_called_once_with(
            "gh", base_url="http://127.0.0.1:8000", strict=True
        )

    @patch("app.cli.fetch_key_entries")
    def test_cancel_interactive(self, mock_fetch_entries) -> None:
        mock_fetch_entries.return_value = [KeyEntry(key="gh")]

        def eof(_prompt: str) -> str:
            raise EOFError

        # EOF leaves the REPL; empty lines are skipped (same as real REPL).
        with patch("sys.stdout", new_callable=StringIO):
            with patch("sys.stderr", new_callable=StringIO):
                _run(
                    shortcut_args=(),
                    base_url="http://127.0.0.1:8000",
                    list_keys=False,
                    use_fzf=False,
                    fzf_query="",
                    print_url=False,
                    open_browser=True,
                    input_fn=eof,
                )

    @patch("app.cli.fetch_key_entries")
    def test_interactive_skips_empty_lines(self, mock_fetch_entries) -> None:
        mock_fetch_entries.return_value = [KeyEntry(key="gh")]
        responses = iter(["", "   ", "quit"])

        with patch("sys.stdout", new_callable=StringIO):
            with patch("sys.stderr", new_callable=StringIO):
                _run(
                    shortcut_args=(),
                    base_url="http://127.0.0.1:8000",
                    list_keys=False,
                    use_fzf=False,
                    fzf_query="",
                    print_url=False,
                    open_browser=True,
                    input_fn=lambda _prompt: next(responses),
                )

    def test_read_shortcut_query_falls_back_without_readline(self) -> None:
        with patch("app.interactive.readline_module", None):
            with patch("builtins.input", return_value="gh"):
                self.assertEqual(
                    interactive.read_shortcut_query(keys=["gh"]),
                    "gh",
                )

    def test_cli_imports_without_readline(self) -> None:
        original_import = __import__

        def fake_import(
            name: str,
            globals=None,
            locals=None,
            fromlist=(),
            level: int = 0,
        ):
            if name == "readline":
                raise ModuleNotFoundError(name)
            return original_import(name, globals, locals, fromlist, level)

        original_modules = {
            name: sys.modules.get(name) for name in ("app.cli", "app.interactive")
        }
        try:
            for name in original_modules:
                sys.modules.pop(name, None)
            with patch("builtins.__import__", side_effect=fake_import):
                cli_module = importlib.import_module("app.cli")
            self.assertTrue(hasattr(cli_module, "_run"))
        finally:
            for name in ("app.cli", "app.interactive"):
                sys.modules.pop(name, None)
            for name, module in original_modules.items():
                if module is not None:
                    sys.modules[name] = module


class ConfigUnitTests(TestCase):
    def test_config_dir_respects_xdg_config_home(self) -> None:
        import tempfile
        from pathlib import Path

        from app.config import config_dir

        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                config_dir(environ={"XDG_CONFIG_HOME": tmp}),
                Path(tmp) / "bunnify",
            )

    def test_default_env_file_under_xdg_resolves_base_url(self) -> None:
        import tempfile
        from pathlib import Path

        from app.config import (
            env_file_path,
            resolve_base_url,
            write_base_url_to_env_file,
        )

        with tempfile.TemporaryDirectory() as tmp:
            environ = {"XDG_CONFIG_HOME": tmp}
            path = Path(tmp) / "bunnify" / "config.env"
            self.assertEqual(env_file_path(environ=environ), path)
            write_base_url_to_env_file(path, "http://from-xdg:9000")
            self.assertEqual(
                resolve_base_url(environ=environ, persist=False),
                "http://from-xdg:9000",
            )

    def test_ensure_user_bookmarks_copies_legacy_noninteractive(self) -> None:
        import tempfile
        from pathlib import Path

        from app.config import ensure_user_bookmarks

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            target = root / "config" / "bookmarks.json"
            legacy.write_text('{"legacy": true}\n', encoding="utf-8")

            result = ensure_user_bookmarks(
                dest=target,
                legacy=legacy,
                allow_prompt=False,
            )

            self.assertEqual(result, target)
            self.assertEqual(target.read_bytes(), legacy.read_bytes())

    def test_ensure_user_bookmarks_seeds_without_legacy(self) -> None:
        import tempfile
        from pathlib import Path

        from app.config import ensure_user_bookmarks

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "config" / "bookmarks.json"
            with patch(
                "app.config.example_bookmarks_bytes",
                return_value=b'{"example": true}\n',
            ):
                result = ensure_user_bookmarks(
                    dest=target,
                    legacy=root / "missing.json",
                    allow_prompt=False,
                )

            self.assertEqual(result, target)
            self.assertEqual(target.read_bytes(), b'{"example": true}\n')

    def test_seed_bookmarks_does_not_overwrite(self) -> None:
        import tempfile
        from pathlib import Path

        from app.config import seed_bookmarks_from_example

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "bookmarks.json"
            target.write_text('{"personal": true}\n', encoding="utf-8")

            with self.assertRaises(FileExistsError):
                seed_bookmarks_from_example(target)

            self.assertEqual(
                target.read_text(encoding="utf-8"),
                '{"personal": true}\n',
            )

    def test_resolve_prefers_cli_then_env_then_file(self) -> None:
        import tempfile
        from pathlib import Path

        from app.config import ENV_VAR, resolve_base_url, write_base_url_to_env_file

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bunnify.env"
            write_base_url_to_env_file(path, "http://from-file:9000")
            self.assertEqual(
                resolve_base_url(
                    cli_value="http://from-cli:1",
                    environ={ENV_VAR: "http://from-env:2"},
                    env_path=path,
                    persist=False,
                ),
                "http://from-cli:1",
            )
            self.assertEqual(
                resolve_base_url(
                    cli_value=None,
                    environ={ENV_VAR: "http://from-env:2"},
                    env_path=path,
                    persist=False,
                ),
                "http://from-env:2",
            )
            self.assertEqual(
                resolve_base_url(
                    cli_value=None,
                    environ={},
                    env_path=path,
                    persist=False,
                ),
                "http://from-file:9000",
            )

    def test_resolve_uses_legacy_env_when_xdg_file_is_missing(self) -> None:
        import tempfile
        from pathlib import Path

        from app.config import resolve_base_url, write_base_url_to_env_file

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "checkout" / "bunnify.env"
            write_base_url_to_env_file(legacy, "http://from-legacy:9000")

            with patch(
                "app.config.legacy_env_file_path",
                return_value=legacy,
            ):
                self.assertEqual(
                    resolve_base_url(
                        environ={"XDG_CONFIG_HOME": str(root / "xdg")},
                        persist=False,
                    ),
                    "http://from-legacy:9000",
                )

    def test_prompt_persists_env_file(self) -> None:
        import tempfile
        from pathlib import Path

        from app.config import read_base_url_from_env_file, resolve_base_url

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bunnify.env"
            url = resolve_base_url(
                cli_value=None,
                environ={},
                env_path=path,
                persist=True,
                allow_prompt=True,
                prompt_fn=lambda _msg: "http://prompted:8000/",
            )
            self.assertEqual(url, "http://prompted:8000")
            self.assertEqual(read_base_url_from_env_file(path), "http://prompted:8000")

    def test_env_file_strips_inline_comments(self) -> None:
        import tempfile
        from pathlib import Path

        from app.config import read_base_url_from_env_file

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bunnify.env"
            path.write_text(
                "BUNNIFY_BASE_URL=http://127.0.0.1:8000  # local\n",
                encoding="utf-8",
            )
            self.assertEqual(
                read_base_url_from_env_file(path),
                "http://127.0.0.1:8000",
            )

    @patch("app.cli.resolve_shortcut")
    @patch("app.cli.fetch_key_entries")
    def test_repl_quit_key_collision_opens_shortcut(
        self,
        mock_fetch_entries,
        mock_resolve,
    ) -> None:
        mock_fetch_entries.return_value = [KeyEntry(key="quit")]
        mock_resolve.return_value = ResolvedShortcut(
            url="https://example.com/quit", kind="bookmark", key="quit"
        )
        opened: list[str] = []
        calls = {"n": 0}

        def input_fn(_prompt: str) -> str:
            calls["n"] += 1
            if calls["n"] == 1:
                return "quit"
            raise EOFError

        def opener(url: str) -> bool:
            opened.append(url)
            return True

        with patch("sys.stdout", new_callable=StringIO):
            with patch("sys.stderr", new_callable=StringIO):
                _run(
                    shortcut_args=(),
                    base_url="http://127.0.0.1:8000",
                    list_keys=False,
                    use_fzf=False,
                    fzf_query="",
                    print_url=False,
                    open_browser=True,
                    opener=opener,
                    input_fn=input_fn,
                )

        self.assertEqual(opened, ["https://example.com/quit"])
        mock_resolve.assert_called_once_with(
            "quit", base_url="http://127.0.0.1:8000", strict=True
        )

    def test_noninteractive_falls_back_to_default(self) -> None:
        import tempfile
        from pathlib import Path

        from app.client import DEFAULT_BASE_URL
        from app.config import read_base_url_from_env_file, resolve_base_url

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bunnify.env"
            url = resolve_base_url(
                cli_value=None,
                environ={},
                env_path=path,
                persist=True,
                allow_prompt=False,
            )
            self.assertEqual(url, DEFAULT_BASE_URL)
            self.assertIsNone(read_base_url_from_env_file(path))

    def test_base_url_prepends_http_scheme(self) -> None:
        from app.config import resolve_base_url

        self.assertEqual(
            resolve_base_url(cli_value="localhost:8000", persist=False),
            "http://localhost:8000",
        )
        with self.assertRaises(ValueError):
            resolve_base_url(cli_value="ftp://example.com", persist=False)

    def test_theme_respects_never(self) -> None:
        from app.theme import Theme, stdout_color_enabled

        self.assertFalse(stdout_color_enabled("never"))
        theme = Theme(enabled=False)
        self.assertEqual(theme.ok("opened"), "opened")

    def test_normalize_edit_mode(self) -> None:
        from app.interactive import normalize_edit_mode_choice

        self.assertEqual(normalize_edit_mode_choice(None), "vim")
        self.assertEqual(normalize_edit_mode_choice("emacs"), "emacs")
        self.assertEqual(normalize_edit_mode_choice("E"), "emacs")
        self.assertEqual(normalize_edit_mode_choice("vi"), "vim")
        self.assertEqual(normalize_edit_mode_choice("weird"), "vim")

    def test_completer_styles_meta_vs_keys(self) -> None:
        from prompt_toolkit.document import Document

        from app.interactive import ShortcutCompleter
        from app.theme import Theme

        theme = Theme(enabled=True)
        completer = ShortcutCompleter(["gh", "pr"], theme=theme)
        completions = list(
            completer.get_completions(Document("g"), complete_event=None)  # type: ignore[arg-type]
        )
        texts = [c.text for c in completions]
        self.assertIn("gh", texts)
        help_c = next((c for c in completions if c.text == "help"), None)
        # "help" does not start with "g"; meta still listed only on matching prefix.
        self.assertIsNone(help_c)
        # Broaden to empty prefix for meta + key style check.
        all_completions = list(
            completer.get_completions(Document(""), complete_event=None)  # type: ignore[arg-type]
        )
        help_c = next(c for c in all_completions if c.text == "help")
        gh_c = next(c for c in all_completions if c.text == "gh")
        self.assertIn("yellow", help_c.style)
        self.assertIn("cyan", gh_c.style)

    def test_completer_meta_includes_args_and_description(self) -> None:
        from prompt_toolkit.document import Document

        from app.interactive import ShortcutCompleter
        from app.theme import Theme
        from app.usage import format_completion_meta

        self.assertEqual(
            format_completion_meta(
                params=("repo",),
                description="Open org pull requests",
            ),
            "<repo> — Open org pull requests",
        )
        self.assertEqual(
            format_completion_meta(description="Just help"),
            "Just help",
        )

        entry = KeyEntry(
            key="prh",
            description="Open org pull requests",
            url="https://github.com/the-hcma/#{repo}/pulls",
            params=("repo",),
        )
        completer = ShortcutCompleter(
            ["prh"],
            theme=Theme(enabled=False),
            entries=[entry],
        )
        metas = [
            c.display_meta_text
            for c in completer.get_completions(Document("pr"), complete_event=None)  # type: ignore[arg-type]
        ]
        self.assertEqual(metas, ["<repo> — Open org pull requests"])

    def test_fuzzy_completer_excludes_meta_blurbs(self) -> None:
        from prompt_toolkit.document import Document

        from app.interactive import FirstTokenFuzzyCompleter, ShortcutCompleter
        from app.theme import Theme

        completer = FirstTokenFuzzyCompleter(
            ShortcutCompleter(
                ["gh"],
                theme=Theme(enabled=False),
                entries=[KeyEntry(key="gh", description="GitHub")],
            )
        )
        completions = list(
            completer.get_completions(Document("vim"), complete_event=None)  # type: ignore[arg-type]
        )
        self.assertNotIn("edit-mode", [completion.text for completion in completions])

    def test_fuzzy_completer_matches_description_shows_keys(self) -> None:
        from prompt_toolkit.document import Document

        from app.interactive import FirstTokenFuzzyCompleter, ShortcutCompleter
        from app.theme import Theme

        entries = [
            KeyEntry(
                key="gtre",
                description="Google Translate - English to Portuguese",
                url="https://translate.google.com/?sl=en&tl=pt&text=#{phrase}",
                params=("phrase",),
            ),
            KeyEntry(
                key="gtrp",
                description="Google Translate - Portuguese to English",
                url="https://translate.google.com/?sl=pt&tl=en&text=#{phrase}",
                params=("phrase",),
            ),
            KeyEntry(
                key="gh",
                description="GitHub",
                url="https://github.com",
            ),
        ]
        completer = FirstTokenFuzzyCompleter(
            ShortcutCompleter(
                [entry.key for entry in entries],
                theme=Theme(enabled=False),
                include_meta=False,
                entries=entries,
            )
        )
        completions = list(
            completer.get_completions(Document("translate"), complete_event=None)  # type: ignore[arg-type]
        )
        texts = sorted(c.text for c in completions)
        self.assertEqual(texts, ["gtre", "gtrp"])
        # Alternatives must be command keys only (never description text).
        self.assertTrue(all(c.text in {"gtre", "gtrp"} for c in completions))

        for needle in ("Translate", "TRANSLATE", "TrAnSlAtE"):
            cased = list(
                completer.get_completions(Document(needle), complete_event=None)  # type: ignore[arg-type]
            )
            self.assertEqual(
                sorted(c.text for c in cased),
                ["gtre", "gtrp"],
                msg=f"expected case-insensitive match for {needle!r}",
            )

    def test_fuzzy_completer_prefers_key_matches(self) -> None:
        from prompt_toolkit.document import Document

        from app.interactive import FirstTokenFuzzyCompleter, ShortcutCompleter
        from app.theme import Theme

        entries = [
            KeyEntry(
                key="tr",
                description="Something else",
                url="https://example.com/tr",
            ),
            KeyEntry(
                key="gtre",
                description="Google Translate",
                url="https://translate.google.com/",
            ),
        ]
        completer = FirstTokenFuzzyCompleter(
            ShortcutCompleter(
                [entry.key for entry in entries],
                theme=Theme(enabled=False),
                include_meta=False,
                entries=entries,
            )
        )
        completions = list(
            completer.get_completions(Document("tr"), complete_event=None)  # type: ignore[arg-type]
        )
        texts = [c.text for c in completions]
        self.assertEqual(texts[0], "tr")
        self.assertIn("gtre", texts)

    @patch("app.cli.fetch_key_entries")
    def test_interactive_refresh_updates_keys(self, mock_fetch_entries) -> None:
        mock_fetch_entries.side_effect = [
            [KeyEntry(key="gh")],
            [KeyEntry(key="gh"), KeyEntry(key="pr")],
        ]
        responses = iter(["refresh", "quit"])
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            with patch("sys.stderr", new_callable=StringIO):
                _run(
                    shortcut_args=(),
                    base_url="http://127.0.0.1:8000",
                    list_keys=False,
                    use_fzf=False,
                    fzf_query="",
                    print_url=False,
                    open_browser=False,
                    input_fn=lambda _prompt: next(responses),
                )
        self.assertIn("refreshed", stdout.getvalue())
        self.assertEqual(mock_fetch_entries.call_count, 2)


class KeyUsageAndCompletionTests(TestCase):
    def test_parse_keys_payload_prefers_entries(self) -> None:
        entries = parse_keys_payload(
            {
                "keys": ["old"],
                "entries": [
                    {
                        "key": "pr",
                        "description": "Pull Request",
                        "url": "https://github.com/#{repo}/pull/#{pr_number}",
                        "params": ["repo", "pr_number"],
                    }
                ],
            }
        )
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].key, "pr")
        self.assertEqual(entries[0].params, ("repo", "pr_number"))

    def test_format_key_usage_lines(self) -> None:
        from app.usage import format_key_usage_lines

        lines = format_key_usage_lines(
            [
                KeyEntry(
                    key="pr",
                    description="Pull Request",
                    url="https://github.com/#{repo}/pull/#{pr_number}",
                    params=("repo", "pr_number"),
                    optional_params=frozenset({"repo"}),
                ),
                KeyEntry(key="gh", description="GitHub", url="https://github.com"),
            ]
        )
        self.assertEqual(len(lines), 2)
        self.assertIn("pr", lines[0])
        self.assertIn("[repo] <pr_number>", lines[0])
        self.assertIn("Pull Request", lines[0])
        self.assertIn("https://github.com/#{repo}/pull/#{pr_number}", lines[0])
        self.assertIn("gh", lines[1])

    @patch("app.cli.fetch_key_entries")
    def test_list_usage(self, mock_fetch_entries) -> None:
        mock_fetch_entries.return_value = [
            KeyEntry(
                key="prh",
                description="PRs",
                url="https://github.com/the-hcma/#{repo}/pulls",
                params=("repo",),
            )
        ]
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            _run(
                shortcut_args=(),
                base_url="http://127.0.0.1:8000",
                list_keys=False,
                list_usage=True,
                use_fzf=False,
                fzf_query="",
                print_url=False,
                open_browser=False,
            )
        text = stdout.getvalue()
        self.assertIn("prh", text)
        self.assertIn("repo", text)
        self.assertIn("PRs", text)

    @patch("app.cli.fetch_key_entries")
    def test_repl_keys_prints_usage(self, mock_fetch_entries) -> None:
        mock_fetch_entries.return_value = [
            KeyEntry(
                key="pr",
                description="Pull Request",
                url="https://github.com/#{repo}/pull/#{pr_number}",
                params=("repo", "pr_number"),
            )
        ]
        responses = iter(["keys", "quit"])
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            with patch("sys.stderr", new_callable=StringIO):
                _run(
                    shortcut_args=(),
                    base_url="http://127.0.0.1:8000",
                    list_keys=False,
                    use_fzf=False,
                    fzf_query="",
                    print_url=False,
                    open_browser=False,
                    input_fn=lambda _prompt: next(responses),
                )
        text = stdout.getvalue()
        self.assertIn("pr", text)
        self.assertIn("<repo> <pr_number>", text)
        self.assertIn("1 keys", text)

    def test_completion_token_state(self) -> None:
        from app.interactive import completion_token_state

        self.assertEqual(
            completion_token_state("pr "),
            ("pr", [], "", 0),
        )
        self.assertEqual(
            completion_token_state("pr the-hcma/bun"),
            ("pr", [], "the-hcma/bun", 0),
        )
        self.assertEqual(
            completion_token_state("pr the-hcma/bunnify "),
            ("pr", ["the-hcma/bunnify"], "", 1),
        )
        self.assertEqual(
            completion_token_state("pr the-hcma/bunnify 24"),
            ("pr", ["the-hcma/bunnify"], "24", 1),
        )

    def test_infer_fixed_github_org(self) -> None:
        from app.github_complete import infer_fixed_github_org

        self.assertEqual(
            infer_fixed_github_org("https://github.com/the-hcma/#{repo}/pulls"),
            "the-hcma",
        )
        self.assertIsNone(
            infer_fixed_github_org("https://github.com/#{repo}/pull/#{pr_number}")
        )

    def test_param_completer_repos_and_prs(self) -> None:
        from prompt_toolkit.document import Document

        from app.interactive import ShortcutCompleter
        from app.theme import Theme

        entry = KeyEntry(
            key="pr",
            description="Pull Request",
            url="https://github.com/#{repo}/pull/#{pr_number}",
            params=("repo", "pr_number"),
        )

        def fake_suggest(*, param_name, url_template, filled_args, prefix):
            del url_template
            if param_name == "repo":
                return [
                    name
                    for name in ("the-hcma/bunnify", "the-hcma/other")
                    if name.startswith(prefix)
                ]
            if param_name == "pr_number":
                self.assertEqual(filled_args, ["the-hcma/bunnify"])
                return [num for num in ("242", "245") if num.startswith(prefix)]
            return []

        completer = ShortcutCompleter(
            ["pr"],
            theme=Theme(enabled=False),
            entries=[entry],
            param_suggest_fn=fake_suggest,
        )
        repos = [
            c.text
            for c in completer.get_completions(
                Document("pr the-hcma/bun"), complete_event=None
            )  # type: ignore[arg-type]
        ]
        self.assertEqual(repos, ["the-hcma/bunnify"])
        prs = [
            c.text
            for c in completer.get_completions(
                Document("pr the-hcma/bunnify 24"), complete_event=None
            )  # type: ignore[arg-type]
        ]
        self.assertEqual(prs, ["242", "245"])

    def test_param_completer_repos_and_issues(self) -> None:
        """Issue shortcuts complete repo + issue_number the same way as PRs."""
        from prompt_toolkit.document import Document

        from app.interactive import ShortcutCompleter
        from app.theme import Theme

        entry = KeyEntry(
            key="i",
            description="GitHub Issue",
            url="https://github.com/#{repo}/issues/#{issue_number}",
            params=("repo", "issue_number"),
        )

        def fake_suggest(*, param_name, url_template, filled_args, prefix):
            del url_template
            if param_name == "repo":
                return [
                    name
                    for name in ("the-hcma/bunnify", "the-hcma/other")
                    if name.startswith(prefix)
                ]
            if param_name == "issue_number":
                self.assertEqual(filled_args, ["the-hcma/bunnify"])
                return [num for num in ("42", "45") if num.startswith(prefix)]
            return []

        completer = ShortcutCompleter(
            ["i"],
            theme=Theme(enabled=False),
            entries=[entry],
            param_suggest_fn=fake_suggest,
        )
        repos = [
            c.text
            for c in completer.get_completions(
                Document("i the-hcma/bun"), complete_event=None
            )  # type: ignore[arg-type]
        ]
        self.assertEqual(repos, ["the-hcma/bunnify"])
        issues = [
            c.text
            for c in completer.get_completions(
                Document("i the-hcma/bunnify 4"), complete_event=None
            )  # type: ignore[arg-type]
        ]
        self.assertEqual(issues, ["42", "45"])

    def test_exact_key_tab_completes_first_param_for_issues_list(self) -> None:
        from prompt_toolkit.document import Document

        from app.interactive import ShortcutCompleter
        from app.theme import Theme

        entry = KeyEntry(
            key="ih",
            description="Issues",
            url="https://github.com/the-hcma/#{repo}/issues",
            params=("repo",),
        )

        def fake_suggest(*, param_name, url_template, filled_args, prefix):
            del url_template, filled_args
            self.assertEqual(param_name, "repo")
            self.assertEqual(prefix, "")
            return ["bunnify", "fpdf"]

        completer = ShortcutCompleter(
            ["ih", "ihh"],
            theme=Theme(enabled=False),
            entries=[
                entry,
                KeyEntry(
                    key="ihh",
                    description="other",
                    url="https://github.com/x/#{repo}/issues",
                    params=("repo",),
                ),
            ],
            param_suggest_fn=fake_suggest,
        )
        texts = [
            c.text
            for c in completer.get_completions(Document("ih"), complete_event=None)  # type: ignore[arg-type]
        ]
        self.assertIn("ih bunnify", texts)
        self.assertIn("ih fpdf", texts)
        self.assertIn("ihh", texts)

    def test_exact_key_tab_completes_first_param(self) -> None:
        from prompt_toolkit.document import Document

        from app.interactive import ShortcutCompleter
        from app.theme import Theme

        entry = KeyEntry(
            key="prh",
            description="PRs",
            url="https://github.com/the-hcma/#{repo}/pulls",
            params=("repo",),
        )

        def fake_suggest(*, param_name, url_template, filled_args, prefix):
            del url_template, filled_args
            self.assertEqual(param_name, "repo")
            self.assertEqual(prefix, "")
            return ["bunnify", "fpdf"]

        completer = ShortcutCompleter(
            ["prh", "prhh"],
            theme=Theme(enabled=False),
            entries=[
                entry,
                KeyEntry(
                    key="prhh",
                    description="other",
                    url="https://github.com/x/#{repo}/pulls",
                    params=("repo",),
                ),
            ],
            param_suggest_fn=fake_suggest,
            suggestions_fn=lambda _q: ["should-not-appear"],
        )
        texts = [
            c.text
            for c in completer.get_completions(Document("prh"), complete_event=None)  # type: ignore[arg-type]
        ]
        self.assertIn("prh bunnify", texts)
        self.assertIn("prh fpdf", texts)
        self.assertIn("prhh", texts)
        self.assertNotIn("should-not-appear", texts)

    def test_param_slot_does_not_fallback_to_key_suggestions(self) -> None:
        from prompt_toolkit.document import Document

        from app.interactive import ShortcutCompleter
        from app.theme import Theme

        entry = KeyEntry(
            key="prh",
            description="PRs",
            url="https://github.com/the-hcma/#{repo}/pulls",
            params=("repo",),
        )
        completer = ShortcutCompleter(
            ["prh", "gh"],
            theme=Theme(enabled=False),
            entries=[entry, KeyEntry(key="gh")],
            param_suggest_fn=lambda **_kwargs: [],
            suggestions_fn=lambda _q: ["gh", "prh"],
        )
        texts = [
            c.text
            for c in completer.get_completions(Document("prh "), complete_event=None)  # type: ignore[arg-type]
        ]
        self.assertEqual(texts, [])

    def test_edit_mode_subarg_completion(self) -> None:
        from prompt_toolkit.document import Document

        from app.interactive import ShortcutCompleter
        from app.theme import Theme

        completer = ShortcutCompleter(
            ["gh"],
            theme=Theme(enabled=False),
            entries=[KeyEntry(key="gh")],
        )
        texts = [
            c.text
            for c in completer.get_completions(
                Document("edit-mode e"), complete_event=None
            )  # type: ignore[arg-type]
        ]
        self.assertEqual(texts, ["emacs"])

    def test_suggestions_fallback_outside_param_slot(self) -> None:
        from prompt_toolkit.document import Document

        from app.interactive import ShortcutCompleter
        from app.theme import Theme

        completer = ShortcutCompleter(
            ["gh"],
            theme=Theme(enabled=False),
            entries=[KeyEntry(key="gh")],
            suggestions_fn=lambda _q: ["foobar"],
        )
        texts = [
            c.text
            for c in completer.get_completions(Document("ggg foo"), complete_event=None)  # type: ignore[arg-type]
        ]
        self.assertEqual(texts, ["foobar"])

    def test_param_suggest_exceptions_are_logged(self) -> None:
        from prompt_toolkit.document import Document

        from app.interactive import ShortcutCompleter
        from app.theme import Theme

        entry = KeyEntry(
            key="prh",
            url="https://github.com/the-hcma/#{repo}/pulls",
            params=("repo",),
        )

        def boom(**_kwargs):
            raise OSError("network down")

        completer = ShortcutCompleter(
            ["prh"],
            theme=Theme(enabled=False),
            entries=[entry],
            param_suggest_fn=boom,
        )
        with self.assertLogs("app.interactive", level="DEBUG") as captured:
            texts = [
                c.text
                for c in completer.get_completions(
                    Document("prh "), complete_event=None
                )  # type: ignore[arg-type]
            ]
        self.assertEqual(texts, [])
        self.assertTrue(
            any("param suggestion failed" in line for line in captured.output)
        )

    def test_list_github_repos_uses_rest_api(self) -> None:
        from app.github_complete import clear_github_completion_cache, list_github_repos

        clear_github_completion_cache()
        seen: list[str] = []

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self) -> bytes:
                return b'[{"name":"bunnify"},{"name":"fpdf"}]'

        def opener(request, timeout=0):  # noqa: ARG001
            seen.append(request.full_url)
            return FakeResponse()

        names = list_github_repos(
            org="the-hcma",
            prefix="bun",
            token="test-token",
            opener=opener,
        )
        self.assertEqual(names, ["bunnify"])
        self.assertTrue(any("/orgs/the-hcma/repos" in url for url in seen))

    def test_filter_completion_names_substring_and_rank(self) -> None:
        from app.github_complete import filter_completion_names

        names = [
            "other",
            "domesti-bot",
            "the-hcma/domesti-bot",
            "domesday",
            "my-domesti-tools",
            "bunnify",
        ]
        matched = filter_completion_names(names, "domes")
        self.assertEqual(
            matched,
            ["domesti-bot", "domesday", "the-hcma/domesti-bot", "my-domesti-tools"],
        )
        # Prefix on the full name beats segment / substring hits.
        self.assertEqual(
            filter_completion_names(
                ["zzz-domesti", "domesti-bot", "x/domesti-bot"],
                "domesti",
            ),
            ["domesti-bot", "zzz-domesti", "x/domesti-bot"],
        )

    def test_suggest_pr_numbers_for_fixed_org(self) -> None:
        from app.github_complete import (
            clear_github_completion_cache,
            suggest_param_values,
        )

        clear_github_completion_cache()
        seen: list[str] = []

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self) -> bytes:
                return b'[{"number":242,"title":"cli"},{"number":100,"title":"other"}]'

        def opener(request, timeout=0):  # noqa: ARG001
            seen.append(request.full_url)
            return FakeResponse()

        values = suggest_param_values(
            param_name="pr_number",
            url_template="https://github.com/the-hcma/#{repo}/pull/#{pr_number}",
            filled_args=["bunnify"],
            prefix="24",
            token="test-token",
            opener=opener,
        )
        self.assertEqual(values, ["242"])
        self.assertTrue(any("/repos/the-hcma/bunnify/pulls" in url for url in seen))

    def test_suggest_issue_numbers_for_fixed_org(self) -> None:
        from app.github_complete import (
            clear_github_completion_cache,
            suggest_param_values,
        )

        clear_github_completion_cache()
        seen: list[str] = []

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self) -> bytes:
                return (
                    b'[{"number":242,"title":"bug"},'
                    b'{"number":100,"title":"pr","pull_request":{}},'
                    b'{"number":99,"title":"docs"}]'
                )

        def opener(request, timeout=0):  # noqa: ARG001
            seen.append(request.full_url)
            return FakeResponse()

        values = suggest_param_values(
            param_name="issue_number",
            url_template="https://github.com/the-hcma/#{repo}/issues/#{issue_number}",
            filled_args=["bunnify"],
            prefix="2",
            token="test-token",
            opener=opener,
        )
        self.assertEqual(values, ["242"])
        self.assertTrue(any("/repos/the-hcma/bunnify/issues" in url for url in seen))

    def test_failed_api_fetch_does_not_poison_cache(self) -> None:
        import urllib.error

        from app.github_complete import clear_github_completion_cache, list_github_repos

        clear_github_completion_cache()
        calls = {"n": 0}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self) -> bytes:
                return b'[{"name":"bunnify"}]'

        def opener(_request, timeout=0):  # noqa: ARG001
            calls["n"] += 1
            if calls["n"] == 1:
                raise urllib.error.URLError("boom")
            return FakeResponse()

        self.assertEqual(
            list_github_repos(org="the-hcma", token="t", opener=opener),
            [],
        )
        names = list_github_repos(
            org="the-hcma", prefix="bun", token="t", opener=opener
        )
        self.assertEqual(names, ["bunnify"])
        self.assertEqual(calls["n"], 2)

    def test_resolve_github_token_prefers_env_over_gh(self) -> None:
        import subprocess

        from app.github_complete import (
            clear_github_completion_cache,
            resolve_github_token,
        )

        clear_github_completion_cache()

        def boom_runner(**_kwargs):
            raise AssertionError("gh should not be called when env token is set")

        token = resolve_github_token(
            environ={"GITHUB_TOKEN": "env-token", "PATH": "/usr/bin"},
            runner=boom_runner,
        )
        self.assertEqual(token, "env-token")

        clear_github_completion_cache()

        def gh_runner(*, args, **_kwargs):
            self.assertEqual(args[:3], ["gh", "auth", "token"])
            return subprocess.CompletedProcess(
                args=list(args), returncode=0, stdout="gh-token\n", stderr=""
            )

        token = resolve_github_token(
            environ={"PATH": "/usr/bin"},
            runner=gh_runner,
        )
        self.assertEqual(token, "gh-token")

    def test_ensure_github_authenticated_runs_login_when_needed(self) -> None:
        import subprocess

        from app.github_complete import (
            clear_github_completion_cache,
            ensure_github_authenticated,
        )

        clear_github_completion_cache()
        calls: list[list[str]] = []

        def runner(*, args, **_kwargs):
            calls.append(list(args))
            if args[1:3] == ["auth", "token"]:
                # First probe: logged out. After login: token available.
                if any(c[1:3] == ["auth", "login"] for c in calls):
                    return subprocess.CompletedProcess(
                        args=list(args),
                        returncode=0,
                        stdout="fresh-token\n",
                        stderr="",
                    )
                return subprocess.CompletedProcess(
                    args=list(args), returncode=1, stdout="", stderr="not logged in"
                )
            if args[1:3] == ["auth", "login"]:
                return subprocess.CompletedProcess(
                    args=list(args), returncode=0, stdout="", stderr=""
                )
            raise AssertionError(args)

        token = ensure_github_authenticated(
            interactive=True,
            environ={"PATH": "/usr/bin"},
            runner=runner,
        )
        self.assertEqual(token, "fresh-token")
        self.assertTrue(any(c[1:3] == ["auth", "login"] for c in calls))

    def test_warm_github_completion_cache_lists_orgs_and_repos(self) -> None:
        from app.github_complete import (
            clear_github_completion_cache,
            warm_github_completion_cache,
        )

        clear_github_completion_cache()
        seen: list[str] = []

        class FakeResponse:
            def __init__(self, body: bytes) -> None:
                self._body = body

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self) -> bytes:
                return self._body

        def opener(request, timeout=0):  # noqa: ARG001
            url = request.full_url
            seen.append(url)
            if "/user/orgs" in url:
                return FakeResponse(b'[{"login":"the-hcma"}]')
            if "/user/repos" in url:
                return FakeResponse(b'[{"full_name":"me/dotfiles"}]')
            if "/orgs/the-hcma/repos" in url:
                return FakeResponse(b'[{"name":"bunnify"},{"name":"fpdf"}]')
            raise AssertionError(url)

        warmed = warm_github_completion_cache(
            url_templates=["https://github.com/the-hcma/#{repo}/pulls"],
            token="test-token",
            opener=opener,
            persist=False,
        )
        self.assertEqual(warmed["orgs"], 1)
        self.assertGreaterEqual(warmed["repos"], 3)
        self.assertTrue(any("/user/orgs" in url for url in seen))
        self.assertTrue(any("/user/repos" in url for url in seen))
        self.assertTrue(any("/orgs/the-hcma/repos" in url for url in seen))

    def test_completion_cache_persists_under_scratch_bunnify(self) -> None:
        import tempfile
        from pathlib import Path

        from app.github_complete import (
            clear_github_completion_cache,
            default_github_completion_cache_path,
            list_github_repos,
            load_github_completion_cache,
            save_github_completion_cache,
        )

        clear_github_completion_cache()
        self.assertEqual(
            default_github_completion_cache_path(),
            Path.home() / "scratch" / "bunnify" / "github-completions.json",
        )

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self) -> bytes:
                return b'[{"name":"bunnify"},{"name":"fpdf"}]'

        def opener(_request, timeout=0):  # noqa: ARG001
            return FakeResponse()

        names = list_github_repos(org="the-hcma", token="t", opener=opener)
        self.assertEqual(names, ["bunnify", "fpdf"])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "scratch" / "bunnify"
            path = root / "github-completions.json"
            self.assertFalse(root.exists())
            saved = save_github_completion_cache(path=path)
            self.assertEqual(saved, path)
            self.assertTrue(path.is_file())

            clear_github_completion_cache()

            import urllib.error

            def empty_opener(_request, timeout=0):  # noqa: ARG001
                raise urllib.error.URLError("offline — cache should be empty")

            self.assertEqual(
                list_github_repos(org="the-hcma", token="t", opener=empty_opener),
                [],
            )

            loaded = load_github_completion_cache(path=path)
            self.assertGreaterEqual(loaded["repos"], 2)
            self.assertEqual(
                list_github_repos(org="the-hcma", prefix="bun", token="t"),
                ["bunnify"],
            )

    def test_completion_cache_does_not_persist_pr_keys(self) -> None:
        import json
        import tempfile
        from pathlib import Path

        from app.github_complete import (
            clear_github_completion_cache,
            list_open_pull_requests,
            load_github_completion_cache,
            save_github_completion_cache,
        )

        clear_github_completion_cache()

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self) -> bytes:
                return b'[{"number":42}]'

        list_open_pull_requests(
            "the-hcma/bunnify", token="t", opener=lambda *_a, **_k: FakeResponse()
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scratch" / "bunnify" / "github-completions.json"
            save_github_completion_cache(path=path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(
                all(not key.startswith("prs:") for key in payload["entries"])
            )
            clear_github_completion_cache()
            # Even a legacy file with prs: keys must not restore them.
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "entries": {"prs:the-hcma/bunnify:50": ["99"]},
                    }
                ),
                encoding="utf-8",
            )
            load_github_completion_cache(path=path)
            self.assertEqual(
                list_open_pull_requests(
                    "the-hcma/bunnify",
                    token="t",
                    opener=lambda *_a, **_k: FakeResponse(),
                ),
                ["42"],
            )

    def test_completion_cache_does_not_persist_issue_keys(self) -> None:
        import json
        import tempfile
        from pathlib import Path

        from app.github_complete import (
            clear_github_completion_cache,
            list_open_issues,
            load_github_completion_cache,
            save_github_completion_cache,
        )

        clear_github_completion_cache()

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self) -> bytes:
                return b'[{"number":7}]'

        list_open_issues(
            "the-hcma/bunnify", token="t", opener=lambda *_a, **_k: FakeResponse()
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scratch" / "bunnify" / "github-completions.json"
            save_github_completion_cache(path=path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(
                all(not key.startswith("issues:") for key in payload["entries"])
            )
            clear_github_completion_cache()
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "entries": {"issues:the-hcma/bunnify:50": ["99"]},
                    }
                ),
                encoding="utf-8",
            )
            load_github_completion_cache(path=path)
            self.assertEqual(
                list_open_issues(
                    "the-hcma/bunnify",
                    token="t",
                    opener=lambda *_a, **_k: FakeResponse(),
                ),
                ["7"],
            )

    def test_bootstrap_loads_disk_across_invocations_without_blocking(self) -> None:
        """Disk snapshot survives restart; refresh is off the start path."""
        import tempfile
        import time
        from pathlib import Path

        from app.github_complete import (
            bootstrap_github_completion_cache,
            clear_github_completion_cache,
            list_github_repos,
            save_github_completion_cache,
        )

        clear_github_completion_cache()

        class SeedResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self) -> bytes:
                return b'[{"name":"old-repo"}]'

        # Invocation 1: populate + persist (simulates a prior REPL session).
        list_github_repos(
            org="the-hcma", token="t", opener=lambda *_a, **_k: SeedResponse()
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scratch" / "bunnify" / "github-completions.json"
            save_github_completion_cache(path=path)

            # Simulate a new process: memory empty, disk still has the snapshot.
            clear_github_completion_cache()
            network_calls = {"n": 0}

            class Resp:
                def __init__(self, body: bytes) -> None:
                    self._body = body

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

                def read(self) -> bytes:
                    return self._body

            def opener(request, timeout=0):  # noqa: ARG001
                network_calls["n"] += 1
                # Slow refresh so the bootstrap return path cannot have waited on it.
                time.sleep(0.2)
                url = request.full_url
                if "/user/orgs" in url:
                    return Resp(b'[{"login":"the-hcma"}]')
                if "/user/repos" in url:
                    return Resp(b"[]")
                if "/orgs/the-hcma/repos" in url:
                    return Resp(b'[{"name":"bunnify"}]')
                raise AssertionError(url)

            # Invocation 2: load disk immediately; kick refresh but do not join.
            started = time.monotonic()
            boot = bootstrap_github_completion_cache(
                url_templates=["https://github.com/the-hcma/#{repo}/pulls"],
                token="t",
                opener=opener,
                persist_path=path,
                refresh=True,
                join_refresh=False,
            )
            elapsed = time.monotonic() - started
            self.assertLess(elapsed, 0.15)
            self.assertTrue(boot["refreshing"])
            self.assertGreaterEqual(boot["repos"], 1)
            # Still the prior-session data — startup did not wait on GitHub.
            self.assertEqual(
                list_github_repos(org="the-hcma", token="t"),
                ["old-repo"],
            )

            # Background refresh eventually updates memory + disk.
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                try:
                    if "bunnify" in path.read_text(encoding="utf-8"):
                        break
                except OSError:
                    pass
                time.sleep(0.05)
            self.assertIn("bunnify", path.read_text(encoding="utf-8"))
            self.assertEqual(
                list_github_repos(org="the-hcma", token="t"),
                ["bunnify"],
            )
            self.assertGreater(network_calls["n"], 0)
            # Join before TemporaryDirectory teardown so the daemon cannot
            # recreate paths under the deleted tmp root.
            from app.github_complete import wait_for_github_completion_refresh

            self.assertTrue(wait_for_github_completion_refresh(timeout=5.0))

    def test_desc_truncation_respects_width(self) -> None:
        from app.usage import format_key_usage_lines

        lines = format_key_usage_lines(
            [
                KeyEntry(key="a", description="A" * 40, url="u"),
                KeyEntry(key="b", description="H" * 50, url="u"),
            ]
        )
        # Cap is 40; truncated description must not exceed that width.
        self.assertIn("…", lines[1])
        # Extract the description column between padded key and URL.
        body = lines[1].strip()
        # "b" + spaces + desc(40) + spaces + "u"
        self.assertRegex(body, r"^b\s+.{40}\s+u$")

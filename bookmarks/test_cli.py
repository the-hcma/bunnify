"""Tests for the Bunnify CLI client and resolve/keys APIs."""

from __future__ import annotations

import importlib
import sys
from io import StringIO
from unittest.mock import patch

from django.test import Client, TestCase, override_settings

from app import interactive
from app.cli import _run, matching_keys
from app.client import ClientError, ResolvedShortcut

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
    @patch("app.cli.fetch_keys")
    def test_interactive_open(
        self,
        mock_fetch_keys,
        mock_resolve,
    ) -> None:
        mock_fetch_keys.return_value = ["gh"]
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
    @patch("app.cli.fetch_keys")
    def test_interactive_loop_runs_multiple_commands(
        self,
        mock_fetch_keys,
        mock_resolve,
    ) -> None:
        mock_fetch_keys.return_value = ["gh", "pr"]
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
    @patch("app.cli.fetch_keys")
    def test_interactive_error_continues_loop(
        self,
        mock_fetch_keys,
        mock_resolve,
    ) -> None:
        mock_fetch_keys.return_value = ["gh"]
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

    @patch("app.cli.fetch_keys")
    def test_cancel_interactive(self, mock_fetch_keys) -> None:
        mock_fetch_keys.return_value = ["gh"]

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

    @patch("app.cli.fetch_keys")
    def test_interactive_skips_empty_lines(self, mock_fetch_keys) -> None:
        mock_fetch_keys.return_value = ["gh"]
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
    @patch("app.cli.fetch_keys")
    def test_repl_quit_key_collision_opens_shortcut(
        self,
        mock_fetch_keys,
        mock_resolve,
    ) -> None:
        mock_fetch_keys.return_value = ["quit"]
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

    @patch("app.cli.fetch_keys")
    def test_interactive_refresh_updates_keys(self, mock_fetch_keys) -> None:
        mock_fetch_keys.side_effect = [
            ["gh"],
            ["gh", "pr"],
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
        self.assertEqual(mock_fetch_keys.call_count, 2)

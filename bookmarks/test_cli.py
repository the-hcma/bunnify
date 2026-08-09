"""Tests for the Bunnify CLI client and resolve/keys APIs."""

from __future__ import annotations

import importlib
import sys
from io import StringIO
from unittest.mock import patch

from django.test import Client, TestCase, override_settings

from bunnify import interactive
from bunnify.cli import _run, matching_keys
from bunnify.client import ClientError, ResolvedShortcut

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

    @patch("bunnify.cli.resolve_shortcut")
    @patch("bunnify.cli.fetch_keys")
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

    @patch("bunnify.cli.resolve_shortcut")
    @patch("bunnify.cli.fetch_keys")
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
                    input_fn=lambda _prompt: "gh",
                )

        self.assertEqual(opened, ["https://github.com"])

    @patch("bunnify.cli.resolve_shortcut")
    @patch("bunnify.cli.fetch_keys")
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

    @patch("bunnify.cli.resolve_shortcut")
    @patch("bunnify.cli.fetch_keys")
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

    @patch("bunnify.cli.fetch_keys")
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

    @patch("bunnify.cli.resolve_shortcut")
    @patch("bunnify.cli.fetch_keys")
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

    @patch("bunnify.cli.resolve_shortcut")
    @patch("bunnify.cli.fetch_keys")
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

    @patch("bunnify.cli.fetch_keys")
    def test_cancel_interactive(self, mock_fetch_keys) -> None:
        mock_fetch_keys.return_value = ["gh"]
        with self.assertRaises(ClientError):
            _run(
                shortcut_args=(),
                base_url="http://127.0.0.1:8000",
                list_keys=False,
                use_fzf=False,
                fzf_query="",
                print_url=False,
                open_browser=True,
                input_fn=lambda _prompt: "",
            )

    def test_read_shortcut_query_falls_back_without_readline(self) -> None:
        with patch("bunnify.interactive.readline_module", None):
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
            name: sys.modules.get(name)
            for name in ("bunnify.cli", "bunnify.interactive")
        }
        try:
            for name in original_modules:
                sys.modules.pop(name, None)
            with patch("builtins.__import__", side_effect=fake_import):
                cli_module = importlib.import_module("bunnify.cli")
            self.assertTrue(hasattr(cli_module, "_run"))
        finally:
            for name in ("bunnify.cli", "bunnify.interactive"):
                sys.modules.pop(name, None)
            for name, module in original_modules.items():
                if module is not None:
                    sys.modules[name] = module

"""Tests for declared bookmark completion specs."""

from __future__ import annotations

from types import MappingProxyType

from django.test import SimpleTestCase, TestCase

from app.client import parse_key_entry
from app.completion_spec import (
    ParamCompleteSpec,
    parse_complete_map,
    repo_arg_from_filled,
    validate_complete_map,
)
from app.github_complete import (
    clear_github_completion_cache,
    resolve_repo_for_pr,
    suggest_param_values,
)


class CompletionSpecTests(SimpleTestCase):
    def test_parse_complete_map_accepts_github_kinds(self) -> None:
        parsed = parse_complete_map(
            {
                "repo": {"kind": "github_repo", "org": "the-hcma"},
                "pr_number": {
                    "kind": "github_pull_request",
                    "repo_param": "repo",
                },
            }
        )
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["repo"].kind, "github_repo")
        self.assertEqual(parsed["repo"].org, "the-hcma")
        self.assertEqual(parsed["pr_number"].repo_param, "repo")

    def test_validate_complete_map_rejects_unknown_placeholder(self) -> None:
        spec = ParamCompleteSpec(kind="github_repo", org="the-hcma")
        errors = validate_complete_map(
            {"repo": spec},
            url="https://github.com/the-hcma/#{name}",
        )
        self.assertTrue(errors)

    def test_parse_key_entry_reads_complete(self) -> None:
        entry = parse_key_entry(
            {
                "key": "repoh",
                "url": "https://github.com/the-hcma/#{repo}",
                "params": ["repo"],
                "complete": {
                    "repo": {"kind": "github_repo", "org": "the-hcma"},
                },
            }
        )
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.complete["repo"].kind, "github_repo")

    def test_suggest_param_values_uses_declared_org_scoped_repos(self) -> None:
        clear_github_completion_cache()
        complete = MappingProxyType(
            {
                "repo": ParamCompleteSpec(kind="github_repo", org="the-hcma"),
            }
        )
        values = suggest_param_values(
            param_name="repo",
            url_template="https://github.com/#{repo}",
            filled_args=[],
            prefix="",
            complete=complete,
            token="test-token",
            opener=lambda _req, timeout=8.0: _FakeResponse(
                [
                    {"name": "bunnify"},
                    {"name": "domesti-bot"},
                ]
            ),
        )
        self.assertEqual(values, ["bunnify", "domesti-bot"])

    def test_resolve_repo_for_pr_uses_declared_org(self) -> None:
        complete = MappingProxyType(
            {
                "repo": ParamCompleteSpec(kind="github_repo", org="the-hcma"),
            }
        )
        self.assertEqual(
            resolve_repo_for_pr(
                url_template="https://github.com/#{repo}/pull/#{pr_number}",
                repo_arg="bunnify",
                complete=complete,
                repo_param="repo",
            ),
            "the-hcma/bunnify",
        )

    def test_suggest_param_values_falls_back_to_heuristics(self) -> None:
        clear_github_completion_cache()
        values = suggest_param_values(
            param_name="repo",
            url_template="https://github.com/the-hcma/#{repo}",
            filled_args=[],
            prefix="",
            complete=None,
            token="test-token",
            opener=lambda _req, timeout=8.0: _FakeResponse([{"name": "bunnify"}]),
        )
        self.assertEqual(values, ["bunnify"])

    def test_suggest_param_values_org_wide_repos(self) -> None:
        clear_github_completion_cache()
        complete = MappingProxyType(
            {"repo": ParamCompleteSpec(kind="github_repo")},
        )
        values = suggest_param_values(
            param_name="repo",
            url_template="https://github.com/#{repo}",
            filled_args=[],
            prefix="the-hc",
            complete=complete,
            token="test-token",
            opener=lambda _req, timeout=8.0: _FakeResponse(
                [
                    {"full_name": "the-hcma/bunnify"},
                    {"full_name": "other-org/widget"},
                ]
            ),
        )
        self.assertEqual(values, ["the-hcma/bunnify"])

    def test_suggest_param_values_github_org_kind(self) -> None:
        clear_github_completion_cache()
        complete = MappingProxyType(
            {"org": ParamCompleteSpec(kind="github_org")},
        )
        values = suggest_param_values(
            param_name="org",
            url_template="https://github.com/#{org}",
            filled_args=[],
            prefix="the-h",
            complete=complete,
            token="test-token",
            opener=lambda _req, timeout=8.0: _FakeResponse(
                [{"login": "the-hcma"}, {"login": "other"}]
            ),
        )
        self.assertEqual(values, ["the-hcma"])

    def test_suggest_param_values_pull_request_with_short_repo(self) -> None:
        clear_github_completion_cache()
        complete = MappingProxyType(
            {
                "pr_number": ParamCompleteSpec(
                    kind="github_pull_request",
                    repo_param="repo",
                ),
                "repo": ParamCompleteSpec(kind="github_repo", org="the-hcma"),
            }
        )
        values = suggest_param_values(
            param_name="pr_number",
            url_template="https://github.com/#{repo}/pull/#{pr_number}",
            filled_args=["bunnify"],
            prefix="32",
            complete=complete,
            token="test-token",
            opener=lambda _req, timeout=8.0: _FakeResponse(
                [{"number": 328}, {"number": 42}]
            ),
        )
        self.assertEqual(values, ["328"])

    def test_suggest_param_values_issue_with_short_repo(self) -> None:
        clear_github_completion_cache()
        complete = MappingProxyType(
            {
                "issue_number": ParamCompleteSpec(
                    kind="github_issue",
                    repo_param="repo",
                ),
                "repo": ParamCompleteSpec(kind="github_repo", org="the-hcma"),
            }
        )
        values = suggest_param_values(
            param_name="issue_number",
            url_template="https://github.com/#{repo}/issues/#{issue_number}",
            filled_args=["bunnify"],
            prefix="3",
            complete=complete,
            token="test-token",
            opener=lambda _req, timeout=8.0: _FakeResponse(
                [{"number": 324}, {"number": 42, "pull_request": {}}]
            ),
        )
        self.assertEqual(values, ["324"])

    def test_repo_arg_from_filled_uses_declared_repo_param_position(self) -> None:
        url = "https://github.com/the-hcma/#{repo}/tree/#{branch}/pull/#{pr_number}"
        self.assertEqual(
            repo_arg_from_filled(
                url_template=url,
                filled_args=["bunnify", "main"],
                repo_param="repo",
            ),
            "bunnify",
        )

    def test_suggest_param_values_pull_request_with_intervening_param(self) -> None:
        clear_github_completion_cache()
        url = "https://github.com/the-hcma/#{repo}/tree/#{branch}/pull/#{pr_number}"
        complete = MappingProxyType(
            {
                "branch": ParamCompleteSpec(kind="github_repo", org="the-hcma"),
                "pr_number": ParamCompleteSpec(
                    kind="github_pull_request",
                    repo_param="repo",
                ),
                "repo": ParamCompleteSpec(kind="github_repo", org="the-hcma"),
            }
        )
        values = suggest_param_values(
            param_name="pr_number",
            url_template=url,
            filled_args=["bunnify", "main"],
            prefix="32",
            complete=complete,
            token="test-token",
            opener=lambda _req, timeout=8.0: _FakeResponse(
                [{"number": 328}, {"number": 42}]
            ),
        )
        self.assertEqual(values, ["328"])


class LoadBookmarksCompleteTests(TestCase):
    def test_invalid_complete_map_preserves_existing_bookmarks(self) -> None:
        import json
        import tempfile
        from pathlib import Path

        from django.core.management import call_command
        from django.core.management.base import CommandError

        from bookmarks.models import Bookmark

        Bookmark.objects.create(
            key="keep",
            description="Keep",
            url="https://example.com",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bookmarks.json"
            path.write_text(
                json.dumps(
                    {
                        "good": {
                            "description": "Good",
                            "url": "https://github.com/#{repo}",
                            "complete": {"repo": {"kind": "github_repo"}},
                        },
                        "bad": {
                            "description": "Bad",
                            "url": ("https://github.com/#{repo}/pull/#{pr_number}"),
                            "complete": {
                                "pr_number": {"kind": "github_pull_request"},
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(CommandError):
                call_command("load_bookmarks", file=str(path))
        self.assertEqual(Bookmark.objects.count(), 1)
        self.assertTrue(Bookmark.objects.filter(key="keep").exists())


class HcmaBookmarksExampleTests(SimpleTestCase):
    def test_hcma_example_complete_maps_validate(self) -> None:
        import json
        from pathlib import Path

        path = Path(__file__).resolve().parents[1] / "bunnify.hcma.json.example"
        data = json.loads(path.read_text(encoding="utf-8"))
        github_keys = {
            "gpr",
            "hgpr",
            "hpr",
            "i",
            "ih",
            "ihh",
            "mqh",
            "pr",
            "prh",
            "prhh",
            "repo",
            "repoh",
            "repohh",
        }
        for key in github_keys:
            self.assertIn(key, data, msg=f"missing shortcut {key!r}")
            bookmark = data[key]
            complete = parse_complete_map(bookmark.get("complete"))
            self.assertIsNotNone(complete, msg=f"{key!r} complete map invalid")
            assert complete is not None
            errors = validate_complete_map(complete, url=bookmark["url"])
            self.assertEqual(errors, [], msg=f"{key!r}: {errors}")


class _FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def read(self) -> bytes:
        import json

        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

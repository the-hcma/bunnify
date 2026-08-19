"""Tests for declared bookmark completion specs."""

from __future__ import annotations

from types import MappingProxyType

from django.test import SimpleTestCase

from app.client import parse_key_entry
from app.completion_spec import (
    ParamCompleteSpec,
    parse_complete_map,
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

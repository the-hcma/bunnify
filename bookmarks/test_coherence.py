"""Tests for app.coherence."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.client import HealthStatus
from app.coherence import (
    LocalCoherenceReport,
    assess_local_coherence,
    builds_match,
    offer_remote_build_mismatch,
    parse_build_label,
)
from app.theme import Theme

BUILD_INFO = ("1.0.0", "abc123456789")
NEW_BUILD = ("0.10.0", "newnewnewnew")
OLD_BUILD = ("0.9.0", "oldoldoldold")


class ParseBuildLabelTests(unittest.TestCase):
    def test_parse_build_label_extracts_version_and_commit(self) -> None:
        self.assertEqual(
            parse_build_label("0.10.0 (abc123456789)"),
            ("0.10.0", "abc123456789"),
        )

    def test_parse_build_label_rejects_malformed(self) -> None:
        self.assertIsNone(parse_build_label("0.10.0"))
        self.assertIsNone(parse_build_label(""))
        self.assertIsNone(parse_build_label("0.10.0 (missing paren"))


class BuildsMatchTests(unittest.TestCase):
    def test_builds_match_requires_version_and_commit(self) -> None:
        health = HealthStatus(ok=True, version="1.0.0", commit="abc123456789")
        with patch("app.coherence.get_build_info", return_value=BUILD_INFO):
            self.assertTrue(builds_match(health))

    def test_builds_match_false_when_commit_differs(self) -> None:
        health = HealthStatus(ok=True, version="0.10.0", commit="oldoldoldold")
        with patch("app.coherence.get_build_info", return_value=NEW_BUILD):
            self.assertFalse(builds_match(health))


class OfferRemoteBuildMismatchTests(unittest.TestCase):
    def test_skips_when_builds_match(self) -> None:
        health = HealthStatus(ok=True, version="1.0.0", commit="abc123456789")
        with patch("app.coherence.get_build_info", return_value=BUILD_INFO):
            allowed = offer_remote_build_mismatch(
                lambda _message: "n",
                base_url="http://127.0.0.1:8000",
                health=health,
                print_fn=lambda _line: None,
                theme=Theme(enabled=False),
            )
        self.assertTrue(allowed)

    def test_decline_mismatch_aborts(self) -> None:
        health = HealthStatus(ok=True, version="0.9.0", commit="oldoldoldold")
        with patch("app.coherence.get_build_info", return_value=NEW_BUILD):
            allowed = offer_remote_build_mismatch(
                lambda _message: "",
                base_url="https://remote.example/",
                health=health,
                print_fn=lambda _line: None,
                theme=Theme(enabled=False),
            )
        self.assertFalse(allowed)


class AssessLocalCoherenceTests(unittest.TestCase):
    def test_report_marks_spotty_skew(self) -> None:
        health = HealthStatus(ok=True, version="0.10.0", commit="localcommit1")
        with (
            patch("app.coherence.fetch_health", return_value=health),
            patch(
                "app.coherence.get_build_info",
                return_value=("0.10.0", "localcommit1"),
            ),
            patch(
                "app.coherence._spotty_runtime_commit",
                return_value=(True, "oldspotty1"),
            ),
        ):
            report = assess_local_coherence(base_url="http://127.0.0.1:8000")
        self.assertIsInstance(report, LocalCoherenceReport)
        self.assertFalse(report.coherent)
        self.assertEqual(report.spotty_commit, "oldspotty1")

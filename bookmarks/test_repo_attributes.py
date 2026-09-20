from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import skipUnless

from django.test import SimpleTestCase

REPO_ROOT = Path(__file__).resolve().parent.parent
GITATTRIBUTES = REPO_ROOT / ".gitattributes"

# Files that break on CRLF: shell scripts (`#!/usr/bin/env bash\r`, shellcheck
# SC1017) and a marker file compared after `cat`.
LF_ONLY_PATHS = (
    ".github/ci/shellcheck",
    ".github/stacking-tool",
    "etc/bunnify-completion",
    "scripts/bunnify-server",
    "scripts/checks",
    "test_bunnify",
    "test_integration",
    "test_packaging",
)

_GIT = shutil.which("git")


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run git with signing and identity pinned, so a contributor's global
    config (commit.gpgsign, user.*, core.autocrlf) cannot change the result."""
    return subprocess.run(
        [
            _GIT or "git",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.invalid",
            *args,
        ],
        cwd=cwd,
        capture_output=True,
        check=True,
        text=True,
        timeout=60,
    )


def _starts_with_shebang(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(2) == b"#!"


# Keyed on the checkout, not on .gitattributes itself: a deleted attributes file
# must fail these tests, not skip them.
@skipUnless(
    _GIT and (REPO_ROOT / ".git").exists(), "needs git and a repository checkout"
)
class GitAttributesTests(SimpleTestCase):
    def test_every_script_and_marker_file_is_pinned_to_lf(self) -> None:
        for relative in LF_ONLY_PATHS:
            with self.subTest(path=relative):
                self.assertTrue((REPO_ROOT / relative).exists(), relative)
                result = _git(REPO_ROOT, "check-attr", "eol", "--", relative)
                self.assertTrue(
                    result.stdout.strip().endswith("eol: lf"),
                    f"{relative}: {result.stdout.strip()}",
                )

    def test_every_tracked_script_with_a_shebang_is_pinned_to_lf(self) -> None:
        """Discovered rather than listed, so a new (or forgotten) script cannot
        slip past a narrowed .gitattributes."""
        tracked = _git(REPO_ROOT, "ls-files", "-z").stdout.split("\0")
        scripts = [
            relative
            for relative in tracked
            if relative
            and (REPO_ROOT / relative).is_file()
            and _starts_with_shebang(REPO_ROOT / relative)
        ]
        # A discovery that finds nothing would pass vacuously.
        self.assertGreater(len(scripts), len(LF_ONLY_PATHS) // 2, scripts)
        for relative in scripts:
            with self.subTest(path=relative):
                result = _git(REPO_ROOT, "check-attr", "eol", "--", relative)
                self.assertTrue(
                    result.stdout.strip().endswith("eol: lf"),
                    f"{relative}: {result.stdout.strip()}",
                )

    def _checkout_bytes(
        self,
        *,
        with_attributes: bool,
        content: bytes = b"#!/usr/bin/env bash\nset -euo pipefail\n",
    ) -> bytes:
        """Commit *content*, then re-checkout it under core.autocrlf=true --
        what a Git for Windows clone does -- and return the file's bytes."""
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _git(repo, "init", "--quiet")
            _git(repo, "config", "core.autocrlf", "true")
            if with_attributes:
                shutil.copy(GITATTRIBUTES, repo / ".gitattributes")
            script = repo / "scripts" / "example"
            script.parent.mkdir()
            script.write_bytes(content)
            _git(repo, "add", "--all")
            _git(repo, "commit", "--quiet", "--message", "add script")
            script.unlink()
            _git(repo, "checkout", "--", "scripts/example")
            return script.read_bytes()

    def test_a_windows_style_checkout_keeps_lf(self) -> None:
        checked_out = self._checkout_bytes(with_attributes=True)
        self.assertNotIn(b"\r", checked_out)

    def test_without_the_attributes_the_same_checkout_gets_crlf(self) -> None:
        # The control: proves the test above would notice the problem, i.e.
        # that core.autocrlf=true really does rewrite line endings here.
        checked_out = self._checkout_bytes(with_attributes=False)
        self.assertIn(b"\r\n", checked_out)

    def test_binary_files_are_left_alone(self) -> None:
        """text=auto, not a bare eol=lf: content that looks binary (a NUL byte)
        must come back byte for byte, CRLF pairs included."""
        payload = b"\x00\r\nbinary\r\n\x00"
        self.assertEqual(
            self._checkout_bytes(with_attributes=True, content=payload), payload
        )

    def test_the_rule_is_text_auto_not_a_bare_eol(self) -> None:
        result = _git(REPO_ROOT, "check-attr", "text", "--", "test_bunnify")
        self.assertTrue(result.stdout.strip().endswith("text: auto"), result.stdout)

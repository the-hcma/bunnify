from __future__ import annotations

import os
import shutil
import stat
import sys
from pathlib import Path
from subprocess import CompletedProcess, run
from tempfile import TemporaryDirectory
from unittest import skipUnless

from django.test import SimpleTestCase

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / ".github" / "ci" / "python-static"

# The wrapper is bash and calls a stub ``uv`` from PATH, so it needs POSIX bash.
_BASH = shutil.which("bash")


def _executable(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@skipUnless(sys.platform != "win32" and _BASH, "needs POSIX bash to run the CI wrapper")
class PythonStaticTmpLayoutTests(SimpleTestCase):
    """The wrapper re-execs through with-tmp-layout (repository-helpers#832)."""

    def _run(self, tmp: Path, helpers: Path, **env_extra: str) -> CompletedProcess[str]:
        stub_dir = tmp / "stub"
        stub_dir.mkdir()
        _executable(
            stub_dir / "uv",
            '#!/usr/bin/env bash\nprintf \'uv %s\\n\' "$*" >> "$STUB_LOG"\n',
        )
        home = tmp / "home"
        home.mkdir()
        env = {
            "HOME": str(home),
            "PATH": f"{stub_dir}{os.pathsep}/usr/bin{os.pathsep}/bin",
            "REPOSITORY_HELPERS_DIR": str(helpers),
            "STUB_LOG": str(tmp / "log"),
            "TMPDIR": str(tmp),
            **env_extra,
        }
        return run(
            [_BASH or "bash", str(SCRIPT)],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def _log(self, tmp: Path) -> str:
        log = tmp / "log"
        return log.read_text(encoding="utf-8") if log.exists() else ""

    def test_ci_without_the_layout_helper_fails_with_a_pointer_to_the_action(
        self,
    ) -> None:
        with TemporaryDirectory() as raw:
            tmp = Path(raw)
            result = self._run(tmp, tmp / "none", GITHUB_ACTIONS="true")
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("setup-tmp-layout", result.stderr)
            self.assertEqual(self._log(tmp), "")

    def test_a_host_without_the_layout_helper_runs_the_checks_unchanged(
        self,
    ) -> None:
        with TemporaryDirectory() as raw:
            tmp = Path(raw)
            result = self._run(tmp, tmp / "none")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("uv run pyright --warnings", self._log(tmp))

    def test_the_layout_helper_wraps_the_run_in_the_uv_layout(self) -> None:
        with TemporaryDirectory() as raw:
            tmp = Path(raw)
            helpers = tmp / "helpers"
            (helpers / "scripts" / "dev").mkdir(parents=True)
            _executable(
                helpers / "scripts" / "dev" / "with-tmp-layout",
                "#!/usr/bin/env bash\n"
                'printf \'%s\\n\' "$1" >> "$TMPDIR/layout-tools"\n'
                "shift 2\n"
                'exec "$@"\n',
            )
            result = self._run(tmp, helpers)
            self.assertEqual(result.returncode, 0, result.stderr)
            tools = (tmp / "layout-tools").read_text(encoding="utf-8").split()
            self.assertEqual(tools, ["uv"])
            self.assertIn("uv run pyright --warnings", self._log(tmp))

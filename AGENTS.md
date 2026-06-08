# AGENTS.md — Ground Rules for bunnify

This file defines the non-negotiable standards for all contributors (human or AI) working on this codebase. Every change must comply with these rules before it is considered complete.

---


## Session Startup & Cleanup

- **Mandatory Action**: At the beginning of every session (before starting any task), run `~/work/ai/repository-helpers/scripts/dev/start-development` from [repository-helpers](https://github.com/the-hcma/repository-helpers).
- This script cleans up merged worktrees, prunes stale metadata, and runs `gt sync --force` to keep your local environment synchronized with the remote.
- By default it prompts for a new stack name and creates a new worktree under `.worktrees/<stack-name>-wt` ready for work.
- Non-interactive alternative: bypass the prompt by passing a worktree name:
  ```bash
  ~/work/ai/repository-helpers/scripts/dev/start-development --worktree <stack-name> --no-interactive
  ```
- Pass `--resume` to instead pick up an existing in-progress worktree: it lists pending worktrees and lets you select one (or creates a new one if none exist).


## Language & Runtime

- Target **Python 3.14+** and **Django 6.0+**. No deprecated APIs.
- Use `uv` as the project dependency manager and runner.
- Rely on modern Python features and type hinting whenever possible.

---

## Formatting & Linting

- **Imports**: We use `isort` configured with the "black" profile. Run `uv run isort .` to organize imports.
- **Type Checking**: We use **pyright** in basic mode for static analysis, configured in `pyproject.toml`.
  - The web framework has dynamic attributes, so certain pyright rules (e.g., `reportAttributeAccessIssue`, `reportOptionalMemberAccess`) are disabled to avoid false positives.
  - Run `uv run pyright` and ensure there are zero errors before submitting a PR.
- Keep the codebase clean and descriptive.

---

## Testing

- The project relies on built-in unit test suites.
- Use `./test_bunnify` to run all tests.
- For targeting specific tests, you can append the test module or class:
  ```bash
  ./test_bunnify bookmarks.tests.SmokeTests
  ```
- All new functionality should include relevant test coverage. 
- Code must not be merged if `./test_bunnify` fails.

---

## Repository

- Remote: `https://github.com/thehcma/bunnify.git`
- Never commit secrets, credentials, or API keys.

---

## Commits, Stacking & Pull Requests

- This project uses **Graphite** (`gt`) for branch stacking.
- **Worktree-per-Stack**: Every new stack/PR must be created in its own Git worktree to ensure isolation. Use `~/work/ai/repository-helpers/scripts/dev/start-development` from [repository-helpers](https://github.com/the-hcma/repository-helpers) — it handles worktree creation and Graphite tracking automatically.
- All work is done in stacked branches via `gt create`, `gt modify`, and `gt submit`.
- Never work directly on `main`. Always create a stack branch: `gt create -m "feat: description"`.
- Submit stacks with `gt submit` — do not open PRs manually via the GitHub UI.
- After submitting, mark PRs as ready for review: `gh pr ready <number>`. `gt submit --no-interactive` creates drafts by default.
- To merge a PR, add the `merge-it` label: `gh pr edit <number> --add-label merge-it`. Never use `gh pr merge` directly.
- **Always ask the user for confirmation before adding the `merge-it` label.** Adding it triggers the Graphite merge queue; it must not be applied without explicit user approval.
- Follow **Conventional Commits**: `feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`.
- Keep commits focused. One logical change per commit.
- **Always run the full local pre-PR checklist (see below) before calling `gt submit`.** Do not rely on CI to catch issues that can be caught locally.

---

## Shell Scripts

 - Do not use `.sh` extensions for shell script files.
 - **`shellcheck`** is strongly recommended for all shell scripts.
 - Non-exported variables must be lowercase; only exported environment variables should be UPPERCASE.
 - Use `local` for all function-scoped variables in bash scripts and prefer `readonly` for values that must not change.
 - Prefer long, verbose command-line arguments (e.g. `curl --silent` over `curl -s`) when composing shell scripts, as they are intrinsically self-documenting.
 - Always add explicit timeouts for network or long-running external commands: use `curl --max-time <s>` for HTTP requests and `timeout <s>` for commands that may hang.
 - When writing server scripts that accept a `--port` argument, support `0` as a valid value to let the OS choose an ephemeral port (useful for tests and CI).

---

## Dependencies

- All dependencies are managed via `uv` in `pyproject.toml`.
- Separate runtime dependencies from `dependency-groups.dev` correctly.
- Run `uv sync` to install/update the environment.
- Do not pull in dependencies for functionality that can be trivially recreated using standard Python or built-in framework features natively.

---

## Dependency release age (dep-updater 9 days, Dependabot 10 days)

New dependency versions are adopted on a staggered schedule so **dep-updater** (repository-helpers) lands updates before Dependabot (aligned with [repository-helpers](https://github.com/the-hcma/repository-helpers) `AGENTS.md`). This repo has no npm/pnpm frontend; policy applies to **pip** and **GitHub Actions** only.

| Layer | Mechanism |
|-------|-----------|
| **dep-updater** | 9-day gate for Python/PyPI and GitHub Actions bumps (`scripts/dep-updater` from repository-helpers). |
| **Dependabot** | `cooldown: default-days: 10` on version-update PRs in `.github/dependabot.yml` (pip and github-actions; one day after dep-updater). |

### CVE and security exceptions

- **Dependabot security updates** are not subject to the version-update cooldown.
- **dep-updater:** when **pip-audit** reports CVE IDs with an available fix, dep-updater skips the 9-day gate for that package; otherwise use the audit-driven security path (`py_security_update`).
- **CI:** `pip-audit` (or equivalent) remains the source of truth for known CVEs on runtime deps.

**Day-to-day:** no grandfathering steps (this repo has no pnpm). Review Dependabot and dep-updater PRs as usual.

---

## CI Checks / Pre-PR (all must pass)

```bash
uv run isort --check .
uv run pyright
./test_bunnify
```

No PR may be merged if the above commands fail.

### Pre-PR Local Checklist (recommended)

- **Run the unified preflight script:** Prefer using `scripts/checks` which runs formatting, linters, unit tests and (optionally) integration tests with sensible timeouts.
- **Formatting & linting:** `uv run isort --check-only --diff .` and `uv run black --check .` and `uv run pyright --warnings` must pass locally before creating a PR.
- **Shell linting:** Run `shellcheck bunnify-server test_integration scripts/*` and ensure there are no new errors or warnings.
- **Unit tests:** Run `./test_bunnify` and ensure all tests pass.
- **Integration tests (required pre-PR):** Run `./test_integration` — this script uses OS-chosen ephemeral ports when passed `--port 0` and includes explicit timeouts; run it locally to validate end-to-end behavior.
- **Parallelization guidance:** When possible, run formatting and static checks in parallel to reduce feedback time (our CI runs `isort`, `black`, and `pyright` in a separate job from shellcheck and tests). Locally, `scripts/checks` can be used as a single-entrypoint; CI runs jobs in parallel automatically.

If any of the above fail locally, fix the issues before opening a PR. The CI will re-run these checks in parallel and block merges on failures.

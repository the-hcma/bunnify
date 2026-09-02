# AGENTS.md — Ground Rules for bunnify

This file defines the non-negotiable standards for all contributors (human or AI) working on this codebase. Every change must comply with these rules before it is considered complete.

---


## Session Startup & Cleanup

- At the **start of every agent session**, before acting from assumed conventions, read this `AGENTS.md` in full, then read every `alwaysApply: true` rule under `.cursor/rules/*.mdc` (plus any whose `globs` match files you will touch) — `AGENTS.md` and `.cursor/rules/` together are the contract. `CLAUDE.md` (a `@AGENTS.md` import) and `.github/copilot-instructions.md` are thin shims so Claude Code and Copilot reach the same guidance.
- **Mandatory Action**: At the beginning of every session (before starting any task), run `~/work/ai/repository-helpers/scripts/dev/start-development` from [repository-helpers](https://github.com/the-hcma/repository-helpers).
- This script cleans up merged worktrees, prunes stale metadata, and syncs via the stacking backend in `.github/stacking-tool` (`gh-stack` — `gh stack sync` / rebase as needed).
- By default it prompts for a new stack name and creates a new worktree under `.worktrees/<stack-name>-wt` ready for work.
- Non-interactive alternative: bypass the prompt by passing a worktree name:
  ```bash
  ~/work/ai/repository-helpers/scripts/dev/start-development --worktree <stack-name> --no-interactive
  ```
- Pass `--resume` to instead pick up an existing in-progress worktree: it lists pending worktrees and lets you select one (or creates a new one if none exist).
- After `start-development` finishes, **`cd` into the stack worktree** (`.worktrees/<stack-name>-wt`) before any other work. Do not stay in the primary clone.

### Main worktree is off-limits (agents)

The **primary clone** (repo root — first entry in `git worktree list`, usually on branch `main`) is the **main worktree**. Treat it as **read-only** unless the user explicitly authorizes touching it in the current conversation.

**Never on the main worktree** (without explicit user authorization):

- Edit, create, or delete source files, config, or lockfiles
- Run `uv sync`, tests, builds, or formatters
- Run `dep-updater` with `--dir` pointing at the primary clone (it may fast-forward `main` and mutate git state)
- Run `gh stack …`, commits, checkouts, or other git write operations
- Leave uncommitted changes, stray branches, or detached HEAD state

**Always** do implementation, investigation that mutates state, and validation in a **stack worktree** under `.worktrees/<stack-name>-wt`. Pass that path to tools (`--dir`, `cd`, etc.).

`start-development` may update the main worktree for environment sync only; that is not permission to work there. If you need to inspect `main` without changing it, use read-only commands (`git log`, `git show`, `gh pr view`) or a **detached temporary worktree** — not the primary clone.

## Language & Runtime

- Target **Python 3.14+** and **Django 6.0+**. No deprecated APIs.
- Use `uv` as the project dependency manager and runner.
- Rely on modern Python features and type hinting whenever possible.
- **Remote timeouts and bounded retries:** `.cursor/rules/remote-timeouts-retries.mdc`
  (`alwaysApply`, org rule — template sync
  [repository-helpers#570](https://github.com/the-hcma/repository-helpers/issues/570)).
  Every `urllib.request` call passes `timeout=` (reuse `DEFAULT_TIMEOUT_SECONDS` /
  `PYPI_TIMEOUT_S`); any retry is capped/budgeted, backed off, transient-only
  (never blanket `HTTPError`), and never re-sends a non-idempotent write.

---

## Formatting & Linting

- **Lint + format**: We use **Ruff** (`[tool.ruff]` in `pyproject.toml`). Run `uv run ruff check .` and `uv run ruff format .` (or `--check` in CI). Ruff replaces black/isort — it does **not** replace type checking.
- **Type checking**: We use **pyright** in basic mode for static analysis, configured in `pyproject.toml`.
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

- Stacking backend is **`gh-stack`** (see `.github/stacking-tool`). Do **not** use Graphite (`gt`) on this repo.
- Full non-interactive reference: [gh-stack skill](https://github.com/the-hcma/repository-helpers/blob/main/.cursor/skills/gh-stack/SKILL.md) (or `${REPOSITORY_HELPERS_DIR:-$HOME/work/ai/repository-helpers}/.cursor/skills/gh-stack/SKILL.md`).
- **Worktree-per-Stack**: Every new stack/PR must be created in its own Git worktree. Use `~/work/ai/repository-helpers/scripts/dev/start-development` from [repository-helpers](https://github.com/the-hcma/repository-helpers) — it creates the worktree and is marker-aware for `gh-stack`.
- Never work directly on `main`. Create layers with `gh stack init <branch>` / `gh stack add <branch>`, then `git add` / `git commit` as usual.
- Prefer **`scripts/dev/submit-stack`** from repository-helpers (runs pre-pr checks, then `gh stack submit --auto --open`). Agents must always pass `--auto` (and prefer `--open`) — never interactive `gh stack submit` / `gh stack view` without `--json`.
- Merge path is **GitHub’s merge queue**: enable auto-merge with `gh pr merge --auto --squash` when the operator asks to merge. Do **not** use the leftover `merge-it` label. **Always ask the user before enabling auto-merge.**
- Follow **Conventional Commits**: `feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`.
- Keep commits focused. One logical change per commit.
- **Always run the full local pre-PR checklist (see below) before submitting.** Do not rely on CI to catch issues that can be caught locally.

---

## Shell Scripts

 - Do not use `.sh` extensions for shell script files.
 - **`shellcheck`** is **required** for all shell scripts (local `scripts/checks` and CI both fail if it is missing or reports issues).
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
| **Dependabot** | Weekly scan + `cooldown: default-days: 10` on version-update PRs in `.github/dependabot.yml` (pip and github-actions; one day after dep-updater). Do **not** set `open-pull-requests-limit: 0` — version updates stay enabled as a backup. |

### Dependabot: version bumps vs security

- **Version updates** — Dependabot checks on the weekly schedule; each proposed bump must pass the **10-day cooldown** (release age). dep-updater usually lands the same bump first (9-day gate); Dependabot version PRs after that are redundant and can be closed.
- **Security updates** — **not** subject to the version-update cooldown. Dependabot may open a security PR as soon as GitHub has an alert and a fix; merge these promptly.
- **dep-updater CVE bypass** — when **pip-audit** reports CVE IDs with an available fix, dep-updater skips the 9-day gate for that package; otherwise use the audit-driven security path (`py_security_update`).
- **CI:** `pip-audit` (or equivalent) remains the source of truth for known CVEs on runtime deps.

**Day-to-day:** merge dep-updater batch PRs for routine bumps; close duplicate Dependabot version PRs when dep-updater already has the change (no pnpm grandfathering in this repo).

---

## CI Checks / Pre-PR (all must pass)

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright --warnings
./test_bunnify
```

No PR may be merged if the above commands fail.

### Pre-PR Local Checklist (recommended)

- **Run the unified preflight script:** Prefer using `scripts/checks` which runs formatting, linters, unit tests and (optionally) integration tests with sensible timeouts.
- **Formatting & linting:** `uv run ruff check .`, `uv run ruff format --check .`, and `uv run pyright --warnings` must pass locally before creating a PR.
- **Shell linting:** `shellcheck` must be installed locally. `scripts/checks` runs `.github/ci/shellcheck` (same targets as CI) and **fails** if shellcheck is missing.
- **Unit tests:** Run `./test_bunnify` and ensure all tests pass.
- **Integration tests (required pre-PR):** Run `./test_integration` — this script uses OS-chosen ephemeral ports when passed `--port 0` and includes explicit timeouts; run it locally to validate end-to-end behavior.
- **Parallelization guidance:** When possible, run formatting and static checks in parallel to reduce feedback time (our CI runs `ruff check`, `ruff format --check`, and `pyright` in a separate job from shellcheck and tests). Locally, `scripts/checks` can be used as a single-entrypoint; CI runs jobs in parallel automatically.

If any of the above fail locally, fix the issues before opening a PR. The CI will re-run these checks in parallel and block merges on failures.

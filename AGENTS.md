# AGENTS.md — Ground Rules for bunnify

This file defines the non-negotiable standards for all contributors (human or AI) working on this codebase. Every change must comply with these rules before it is considered complete.

---

## Language & Runtime

- Target **Python 3.14+** and **Django 6.0+**. No deprecated APIs.
- Use `uv` as the project dependency manager and runner.
- Rely on modern Python features and type hinting whenever possible.

---

## Formatting & Linting

- **Imports**: We use `isort` configured with the "black" profile. Run `uv run isort .` to organize imports.
- **Type Checking**: We use **pyright** in basic mode for static analysis, configured in `pyproject.toml`.
  - Django has dynamic attributes, so certain pyright rules (e.g., `reportAttributeAccessIssue`, `reportOptionalMemberAccess`) are disabled to avoid false positives.
  - Run `uv run pyright` and ensure there are zero errors before submitting a PR.
- Keep the codebase clean and descriptive.

---

## Testing

- The project relies on Django unit test suites.
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
- Do not commit your local `bunnify.json` bookmarks file.

---

## Commits, Stacking & Pull Requests

- This project uses **Graphite** (`gt`) for branch stacking.
- All work is done in stacked branches via `gt create`, `gt modify`, and `gt submit`.
- Never work directly on `main`. Always create a stack branch: `gt create -m "feat: description"`.
- Submit stacks with `gt submit` — do not open PRs manually via the GitHub UI.
- Follow **Conventional Commits**: `feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`.
- Keep commits focused. One logical change per commit.

---

## Shell Scripts

- **`shellcheck`** is strongly recommended for all shell scripts.
- Non-exported variables must be lowercase.
- Use `local` for all function-scoped variables in bash scripts.

---

## Dependencies

- All dependencies are managed via `uv` in `pyproject.toml`.
- Separate runtime dependencies from `dependency-groups.dev` correctly.
- Run `uv sync` to install/update the environment.
- Do not pull in dependencies for functionality that can be trivially recreated using standard Python or Django natively.

---

## CI Checks / Pre-PR (all must pass)

```bash
uv run isort --check .
uv run pyright
./test_bunnify
```

No PR may be merged if the above commands fail.

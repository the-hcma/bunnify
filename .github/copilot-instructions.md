# Copilot Instructions for Bunnify

## Python Version Policy

**Always use the latest stable Python version.** As of the last update, this is Python 3.14.

When making changes:
- Ensure `pyproject.toml` specifies `requires-python` with the latest stable Python version
- Ensure `.github/workflows/bunnify.yml` tests only the latest stable Python version
- Do not add support for older Python versions

## Package Management

This project uses **uv** exclusively for Python dependency management:
- Use `uv sync` to install dependencies
- Use `uv run python` to execute Python commands
- Use `uv add <package>` to add new dependencies
- Never use pip, poetry, or other package managers

## Git Configuration

For this repository:
- Use the `thehcma` GitHub account
- Ensure all commits are GPG signed

## Pull Request Workflow

After creating a PR:
1. Wait for GitHub Actions CI to complete
2. Verify all checks pass
3. Ask the developer for manual validation before merging

## Code Style

- Follow PEP 8 guidelines
- Use type hints where appropriate
- Use pathlib for file operations
- Add docstrings to functions and classes

## Code Quality Checks

Before committing, always run these checks locally:

```bash
# Check import sorting (must pass with no changes needed)
uv run isort --check-only --diff .

# Fix import sorting if needed
uv run isort .

# Type checking (must be 0 errors, 0 warnings)
uv run pyright --warnings

# Shell script linting (must pass with no errors or warnings)
shellcheck bunnify-server test_integration
find scripts -type f | xargs shellcheck
```

All checks (`isort`, `pyright`, and `shellcheck`) must pass with zero issues before committing. The CI workflow enforces this - PRs with any issues will fail.

## Shell Script Guidelines

When writing or modifying bash scripts:
- Always use `shellcheck` to validate scripts before committing
- Use `cd ... || exit` instead of bare `cd` commands
- Declare local variables separately from assignment: `local var; var=$(cmd)`
- Quote variables that contain special characters like `"[::]:8000"`
- Check exit codes directly with `if cmd; then` instead of `if [ $? -eq 0 ]; then`
- Use lowercase for local/script variables (e.g., `server_pid`, `watcher_pid`)
- Use UPPERCASE only for exported environment variables (e.g., `BUNNIFY_LOG_LEVEL`)

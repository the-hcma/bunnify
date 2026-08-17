# Contributing to Bunnify

Thank you for contributing. This document is for **development checkouts**;
end users install with `pipx install bunnify` (see [README](README.md)).

## Getting started

1. Fork the repository on GitHub
2. Clone your fork and create a feature branch in a [stack worktree](AGENTS.md)
3. Run `./scripts/checks` before opening a PR
4. Follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`,
   `fix:`, `docs:`, …)

## Development setup

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/YOUR_USERNAME/bunnify.git
cd bunnify
uv sync
uv run python manage.py migrate

mkdir -p ~/.config/bunnify
cp bunnify.json.example ~/.config/bunnify/bookmarks.json
# edit bookmarks as needed

./scripts/bunnify setup
./scripts/bunnify-server --console --log-level DEBUG   # optional
```

Personal bookmarks belong in **`~/.config/bunnify/bookmarks.json`**, not in a
tracked repo-root `bunnify.json`. See [docs/CONFIG.md](docs/CONFIG.md).

## Code quality

Run before every PR:

```bash
./scripts/checks
```

Individual gates: `uv run ruff check .`, `uv run ruff format --check .`,
`uv run pyright --warnings`, `./test_bunnify`, `./test_integration`.

## Pull requests

- One logical change per PR; use `gh stack` stacking when appropriate
  (see `.github/stacking-tool` and [AGENTS.md](AGENTS.md))
- Update user-facing docs when behavior or install paths change
- Keep `./scripts/bunnify`, `./scripts/bunnify-server`, and
  `./scripts/bunnify-overlay` as thin wrappers around the installed entry
  points

## Questions

Open a GitHub issue for discussion.

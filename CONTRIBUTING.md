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

## Contributing on Windows

The scripts (`./test_bunnify`, `./scripts/checks`, the
[repository-helpers](https://github.com/the-hcma/repository-helpers) tooling)
are bash, so work from **Git Bash**. Run them from a Git Bash prompt: the
`bash` first on `PATH` may be the WSL launcher, which sees a different
filesystem.

- **Python and dependencies:** Python 3.14+ and `uv`. A plain `uv sync`
  installs the Windows-only packages (pywin32) on Windows, so no extra is
  needed and `uv run` will not remove them. Use `uv sync --all-groups` to also
  get the dev tools.
- **Line endings:** `.gitattributes` keeps text files LF, which shellcheck
  needs. It overrides `core.autocrlf`, so no git setting is required.
- **Tools the helpers do not install on Windows:** `shellcheck`, `jq` and
  `gitleaks` (CI pins 8.30.1; see `.github/ci/secret-scan`). Put them on
  `PATH` as ordinary executables, for example with `winget`, `scoop` or a
  manual download.
- **`gh stack`:** `gh extension install github/gh-stack`.
- **Signed commits:** the `verified-commits` check requires them. Gpg4win
  works: `git config gpg.program` to the `gpg.exe` it installs, `git config
  user.signingkey <key id>` and `git config commit.gpgsign true`. Setting
  `default-cache-ttl` and `max-cache-ttl` in `%APPDATA%\gnupg\gpg-agent.conf`
  avoids a passphrase prompt on every commit.
- **Symlink test:** one test needs the symlink privilege (Developer Mode, or
  an elevated shell) and is skipped without it.
- **Real-Win32 tests** create real windows, so they run only on Windows with
  pywin32 installed and are skipped elsewhere.

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
  `./scripts/spotty-bunny` as thin wrappers around the installed entry
  points

## Questions

Open a GitHub issue for discussion.

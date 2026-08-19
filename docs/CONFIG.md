# Bunnify configuration

`bunnify.json.example` (and the packaged `app/data/bookmarks.example.json`) is
the template for creating your personal bookmarks file. It ships Google
properties (Search, Gmail, Calendar, YouTube, Drive, Docs, and related),
generic GitHub shortcuts, and a `bun` key for this repository’s source.

## XDG layout

Bunnify stores user configuration under `$XDG_CONFIG_HOME/bunnify`, defaulting
to `~/.config/bunnify` when `XDG_CONFIG_HOME` is unset:

- `bookmarks.json` contains personal shortcuts (required before server start).
- `config.env` contains persistent CLI server preferences:
  `BUNNIFY_MODE`, `BUNNIFY_BASE_URL`, and `BUNNIFY_LOCAL_PORT`.
- `run/` contains PID and selected-port files for the CLI-managed local server.

Writable data (logs, SQLite, Spotty Bunny’s daily PyPI check cache
`pypi-latest.json`) lives under `$XDG_DATA_HOME/bunnify` or `BUNNIFY_DATA_DIR`.

These files are user data and are not tracked by Git.

## Setup

When `bookmarks.json` is missing, interactive `bunnify setup` (and other
prompting CLI paths) offer to install the example bookmarks. Decline that
prompt if you prefer to create the file yourself:

```bash
mkdir -p ~/.config/bunnify
curl -fsSL https://raw.githubusercontent.com/the-hcma/bunnify/main/bunnify.json.example \
  -o ~/.config/bunnify/bookmarks.json
```

In a development checkout you can instead `cp bunnify.json.example` from the
repo root.

After install, edit that file directly to personalize shortcuts. The managed
local server watches the bookmarks file and reloads on change
(`watch_bookmarks`). The CLI resolves shortcuts through the server, so edits
apply once the watcher reloads; in the interactive REPL run `refresh` to update
Tab completion. Non-interactive starts (`bunnify-server --noninteractive`, CI,
etc.) never seed automatically — create the file first.

Run `bunnify setup` to write verified settings. Existing base-URL-only files
remain supported; they are interpreted as remote mode.

## Environment variables

- `XDG_CONFIG_HOME` changes the configuration root.
- `BUNNIFY_BOOKMARKS` overrides the bookmarks file path.
- `BUNNIFY_BASE_URL` overrides the server URL.
- `BUNNIFY_LOCAL_PORT` remembers the managed local server's listening port.
- `BUNNIFY_MODE` selects `local` or `remote`.
- `BUNNIFY_EDIT_MODE` selects `vim` or `emacs` CLI editing keys.
- `BUNNIFY_LOG_LEVEL`, `BUNNIFY_LOG_CONSOLE`, and `BUNNIFY_LOG_FILE` configure
  server logging.
- `BUNNIFY_SPOTTY_BUNNY_LOG_FILE` overrides the Spotty Bunny log path (default
  `$BUNNIFY_DATA_DIR/spotty-bunny.log`, or `~/.local/share/bunnify/spotty-bunny.log`).
  `spotty-bunny --log-file` also sets it. Rotation matches the server
  (10 MiB, 5 backups).

## Bookmark schema

Each entry in `bookmarks.json` is an object with:

- `description` — short label shown in the REPL and web UI.
- `url` — target URL or path template. Placeholders use `#{name}` (for example
  `https://github.com/#{repo}/pull/#{pr_number}`).
- `defaults` (optional) — map of placeholder names to default values. Keys listed
  here are optional at the CLI/REPL.
- `complete` (optional) — declares Tab-completion behavior per placeholder instead
  of relying on parameter-name heuristics alone. Loaded with bookmarks, validated
  on import, and exposed through `/api/keys/` for the CLI and shell wrappers.

### `complete` map

Keys in `complete` must match placeholder names in `url`. Each value is an object
with a required `kind` and optional fields depending on the kind:

| Kind | Completes | Optional fields |
|------|-----------|-------------------|
| `github_org` | org/login names | — |
| `github_repo` | repo short name or `owner/name` | `org` — fixed org → short repo names; omitted → `owner/name` from the authenticated user's repos |
| `github_pull_request` | open PR numbers | `repo_param` — prior argument holding the repo (required when the URL has a repo placeholder); `org` when the repo argument is a short name under a fixed org |
| `github_issue` | open issue numbers | same as `github_pull_request` |

When `complete.<param>` is absent, the CLI falls back to legacy heuristics
(parameter names like `repo`, `pr_number`, `issue_number`, plus URL-based org
inference) so older bookmarks keep working.

Example (from `bunnify.json.example`):

```json
"repoh": {
  "description": "the-hcma GitHub repo (Usage: repoh <repo>)",
  "url": "https://github.com/the-hcma/#{repo}",
  "complete": {
    "repo": { "kind": "github_repo", "org": "the-hcma" }
  }
},
"pr": {
  "description": "GitHub Pull Request (Usage: pr <org/repo> <pr_number>)",
  "url": "https://github.com/#{repo}/pull/#{pr_number}",
  "complete": {
    "pr_number": { "kind": "github_pull_request", "repo_param": "repo" },
    "repo": { "kind": "github_repo" }
  }
}
```

GitHub-backed completion requires a token (`GITHUB_TOKEN`, `GH_TOKEN`, or
`gh auth login`). Results are cached under `~/scratch/bunnify/github-completions.json`.

### Shell Tab completion

For bash/fish/zsh wrappers, emit candidates for the parameter currently being
typed:

```bash
bunnify --complete-param repoh --prefix bun
# → one candidate per line (bunnify, domesti-bot, …)

bunnify --complete-param pr the-hcma/bunnify --prefix 1
# → open PR numbers starting with 1
```

Positional arguments after `--complete-param KEY` are already-filled parameters;
`--prefix` filters the next parameter's candidates.

## Operator bookmark template

`bunnify.hcma.json.example` is an optional, richer bookmark set (Google
variants, GitHub org shortcuts, Graphite links, and related) with `complete`
markers on GitHub-backed placeholders. It is **not** used by `bunnify setup`
automatically — copy or merge into your personal file when upgrading an
existing install:

```bash
cp bunnify.hcma.json.example ~/.config/bunnify/bookmarks.json
# or merge selected keys / complete blocks into an existing bookmarks.json
```

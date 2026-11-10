# Bunnify configuration

`bunnify.json.example` at the repository root is the single source of truth for the template for creating your personal bookmarks file. It ships Google properties (Search, Gmail, Calendar, YouTube, Drive, Docs, and related), generic GitHub shortcuts, and a `bun` key for this repository’s source.

## XDG layout

Bunnify stores user configuration under `$XDG_CONFIG_HOME/bunnify`, defaulting to `~/.config/bunnify` when `XDG_CONFIG_HOME` is unset:

- `bookmarks.json` contains personal shortcuts (required before server start).
- `config.toml` contains persistent CLI/server preferences (`mode`, `base_url`, `local_port`) and the Spotty Bunny hotkey chord (`spotty_bunny_hotkey`). Not environment variables — edit the file directly, or use `bunnify setup` / `bunnify spotty-bunny hotkey`. A legacy `config.env` (or the old `BUNNIFY_MODE`/`BUNNIFY_BASE_URL`/ `BUNNIFY_LOCAL_PORT` environment variables) is migrated into `config.toml` once, automatically, the first time it's read. See [`config.example.toml`](../config.example.toml) at the repository root for an annotated example of every key.
- `run/` contains PID and port files for CLI-managed servers. On macOS the server LaunchAgent uses `run/launchd/` (see [LOCAL.md](LOCAL.md)).

Writable data (logs, SQLite, Spotty Bunny’s daily PyPI check cache `pypi-latest.json`) lives under `$XDG_DATA_HOME/bunnify` or `BUNNIFY_DATA_DIR`.

These files are user data and are not tracked by Git.

## Setup

When `bookmarks.json` is missing, interactive `bunnify setup` (and other prompting CLI paths) offer to install the example bookmarks. Decline that prompt if you prefer to create the file yourself:

```bash
mkdir -p ~/.config/bunnify
curl -fsSL https://raw.githubusercontent.com/the-hcma/bunnify/main/bunnify.json.example \
  -o ~/.config/bunnify/bookmarks.json
```

In a development checkout you can instead `cp bunnify.json.example` from the repo root.

After install, edit that file directly to personalize shortcuts. The managed local server watches the bookmarks file and reloads on change (`watch_bookmarks`). The CLI resolves shortcuts through the server, so edits apply once the watcher reloads; in the interactive REPL run `refresh` to update Tab completion. Non-interactive starts (`bunnify-server --noninteractive`, CI, etc.) never seed automatically — create the file first.

Run `bunnify setup` to write verified settings. Existing base-URL-only files remain supported; they are interpreted as remote mode.

## Environment variables

- `XDG_CONFIG_HOME` changes the configuration root.
- `BUNNIFY_BOOKMARKS` overrides the bookmarks file path.
- `BUNNIFY_EDIT_MODE` selects `vim` or `emacs` CLI editing keys.
- `BUNNIFY_LOG_LEVEL`, `BUNNIFY_LOG_CONSOLE`, and `BUNNIFY_LOG_FILE` configure server logging.
- `BUNNIFY_SPOTTY_BUNNY_LOG_FILE` overrides the Spotty Bunny log path (default `$BUNNIFY_DATA_DIR/spotty-bunny.log`, or `~/.local/share/bunnify/spotty-bunny.log`). `spotty-bunny --log-file` also sets it. Rotation matches the server (10 MiB, 5 backups).

`BUNNIFY_MODE`, `BUNNIFY_BASE_URL`, and `BUNNIFY_LOCAL_PORT` are **not** read at runtime anymore — set `mode` / `base_url` / `local_port` in `config.toml` instead (`bunnify setup` writes it for you). Those variables are still recognized once, read-only, to migrate an old `config.env` (or bare environment variables from very old installs) into `config.toml`.

## Spotty Bunny hotkey chord

`spotty_bunny_hotkey` in `config.toml` selects the modifier chord that shows the overlay: `auto` (default — Option on laptops with no external keyboard attached, Control when one is), `control`, `option`, or `command`. View or change it with:

```bash
bunnify spotty-bunny hotkey
bunnify spotty-bunny hotkey option
```

Each chord is held-left-tap-right (or the reverse) of the *same* modifier — e.g. hold left Control, tap right Control. Default (`auto`) keystrokes:

| Keyboard attached | Chord used | Keystroke |
|---|---|---|
| Built-in only (no external keyboard) | Option | Hold left Option, tap right Option (or the reverse) |
| External keyboard present (USB/Bluetooth) | Control | Hold left Control, tap right Control (or the reverse) |

Auto-detection is re-checked on each periodic tap health check, so plugging in (or unplugging) an external keyboard is picked up without a restart. Pinning a choice (`control` / `option` / `command`) always uses both copies of that modifier regardless of what's attached.

On **Windows**, only dual-Control actually works: `auto`/`control` resolve to it, and `option`/`command` fall back to Control with a warning logged rather than inventing an Alt or Windows-key chord.

## Bookmark schema

Each entry in `bookmarks.json` is an object with:

- `description` — short label shown in the REPL and web UI.
- `url` — target URL or path template. Placeholders use `#{name}` (for example `https://github.com/#{repo}/pull/#{pr_number}`).
- `defaults` (optional) — map of placeholder names to default values. Keys listed here are optional at the CLI/REPL.
- `complete` (optional) — declares Tab-completion behavior per placeholder instead of relying on parameter-name heuristics alone. Loaded with bookmarks, validated on import, and exposed through `/api/keys/` for the CLI and shell wrappers.
- `browser` (optional) — open this shortcut in a specific Edge/Chrome browser and/or profile instead of the system default. See [Browser and profile](#browser-and-profile).

### Browser and profile

Without a `browser` block a shortcut opens in the system default browser with its default profile. Add one only for shortcuts that must open somewhere specific:

```json
"brk-dash": {
  "description": "BRK dashboard",
  "url": "https://example.com/dashboard",
  "browser": { "app": "edge", "profile": "Work-BRK" }
}
```

- `app` — `edge` or `chrome`. Omitted means the system default browser.
- `profile` — the profile's exact display name as shown in the browser's profile picker (case-sensitive). Directory names such as `Profile 1` are not accepted because they differ between machines.
- At least one of the two is required inside the block.

| Set | Opens in |
|-----|----------|
| `app` only | that browser, in the profile it opens by default (Bunnify passes no profile, so this is usually the last-used one) |
| `app` + `profile` | that browser and profile |
| `profile` only | the system default browser, which must be Edge or Chrome, in that profile |

The default browser is read from macOS LaunchServices (`https` handler) or the Windows `UserChoice` registry key.

There is no fallback: if the browser is not installed, the profile does not exist (the error lists the available profile names), two profiles share the name, or a profile-only shortcut finds a default browser that is not Edge or Chrome, Bunnify reports the error and opens nothing.

`bunnify --dry-run` (and `--print-url`) does not launch anything but still validates the browser and profile and prints `browser: Edge, profile "Work-BRK"` on stderr.

Supported on macOS and Windows, from the `bunnify` CLI and Spotty Bunny. Typing a shortcut into the browser address bar cannot honor `browser`: the server only returns a redirect to whichever browser sent the request.

### `complete` map

Keys in `complete` must match placeholder names in `url`. Each value is an object with a required `kind` and optional fields depending on the kind:

| Kind | Completes | Optional fields |
|------|-----------|-------------------|
| `github_org` | org/login names | — |
| `github_repo` | repo short name or `owner/name` | `org` — fixed org → short repo names; omitted → `owner/name` from the authenticated user's repos |
| `github_pull_request` | open PR numbers | `repo_param` — prior argument holding the repo (required when the URL has a repo placeholder); `org` when the repo argument is a short name under a fixed org |
| `github_issue` | open issue numbers | same as `github_pull_request` |

When `complete.<param>` is absent, the CLI falls back to legacy heuristics (parameter names like `repo`, `pr_number`, `issue_number`, plus URL-based org inference) so older bookmarks keep working.

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

GitHub-backed completion needs auth **and** a way to talk to GitHub:

- Prefer `GITHUB_TOKEN` or `GH_TOKEN` in the environment, **or**
- install the GitHub CLI (`gh`) and run `gh auth login` (`brew install gh` on macOS/Linux with Homebrew).

The interactive CLI and Spotty Bunny surface this when `gh` is missing. On macOS, **admin** users with Homebrew are offered an in-app / REPL confirm to run `brew install gh` and then verify the binary. Without a token, `github_repo` / `github_pull_request` / `github_issue` completions stay empty (fail-soft). Spotty Bunny’s LaunchAgent PATH includes Homebrew and `~/.local/bin` so a typical install is found after setup. Results are cached under `~/scratch/bunnify/github-completions.json`.

### Shell Tab completion

For bash/fish/zsh wrappers, emit candidates for the parameter currently being typed:

```bash
bunnify --complete-param repoh --prefix bun
# → one candidate per line (bunnify, domesti-bot, …)

bunnify --complete-param pr the-hcma/bunnify --prefix 1
# → open PR numbers starting with 1
```

Positional arguments after `--complete-param KEY` are already-filled parameters; `--prefix` filters the next parameter's candidates.

## Bookmark examples

Shipped example (`bunnify.json.example`, bundled into installed wheels as `app/data/bookmarks.example.json`) includes GitHub shortcuts with `complete` markers (org-scoped repos, PRs, issues, merge queue, and Graphite review links). Copy or merge into your personal file when upgrading an existing install:

```bash
cp bunnify.json.example ~/.config/bunnify/bookmarks.json
# or merge selected keys / complete blocks into an existing bookmarks.json
```

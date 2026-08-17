# ⚡ Quick reference

Assumes `pipx install bunnify`, `pipx ensurepath` (so `~/.local/bin` is on
`PATH`), bookmarks at `~/.config/bunnify/bookmarks.json` (install via
`bunnify setup` or from `bunnify.json.example`), and a completed
`bunnify setup`. Prefer **local** mode on a laptop; use **remote** for a
home-server install. Your base URL is in `~/.config/bunnify/config.env` as
`BUNNIFY_BASE_URL` — Chrome must use the same URL.

## Bookmarks file

```bash
bunnify setup   # offers to install example bookmarks when missing
# or:
mkdir -p ~/.config/bunnify
curl -fsSL https://raw.githubusercontent.com/the-hcma/bunnify/main/bunnify.json.example \
  -o ~/.config/bunnify/bookmarks.json
```

## CLI

```bash
bunnify                         # interactive REPL
bunnify onboard                 # post-install / upgrade checklist
bunnify setup                   # configure local or remote server
bunnify stop                    # stop the managed local server
bunnify upgrade                 # preferred: pipx upgrade; prints from/to versions
bunnify --version               # package version, commit, and install path
bunnify gh                      # open a shortcut (example key from bunnify.json.example)
bunnify bun                     # Bunnify source on GitHub
bunnify pr the-hcma/bunnify 272 # parameterized shortcut (repo + PR number)
bunnify --fzf                   # fuzzy-pick a shortcut (requires fzf on PATH)
bunnify --print-url gh          # print resolved URL instead of opening browser
bunnify --list-keys             # list keys from the running server
bunnify overlay                 # macOS search box (requires extra macos)
bunnify overlay --verbose       # overlay DEBUG logs on stderr and log file
```

## Server

```bash
bunnify stop                    # stop the managed local server (local mode)
bunnify-server --help
bunnify-server --foreground --noninteractive --port 8000   # foreground (systemd/debug)
bunnify-server --port 8000 --noninteractive --pid-dir ~/.local/share/bunnify/run
bunnify-server --stop --pid-dir ~/.local/share/bunnify/run
curl -sf "$(grep '^BUNNIFY_BASE_URL=' ~/.config/bunnify/config.env | cut -d= -f2-)/health"
```

Development checkout: prefix with `./scripts/` (e.g. `./scripts/bunnify-server`).

## Chrome

Use `BUNNIFY_BASE_URL` from `~/.config/bunnify/config.env` (set by `bunnify setup`):

1. Server running → visit `<BUNNIFY_BASE_URL>/` (OpenSearch auto-detect)
2. Or add manually: keyword `b`, URL `<BUNNIFY_BASE_URL>/search/?q=%s`

Full guide: [CHROME_SETUP.md](CHROME_SETUP.md)

## Web

| Path | Use |
|------|-----|
| `/cmd/` | Command palette |
| `/list/` | Browse bookmarks |
| `/search/?q=…` | Smart search |
| `/<key>/` | Redirect |

## Config files

| File | Purpose |
|------|---------|
| `~/.config/bunnify/bookmarks.json` | Shortcuts |
| `~/.config/bunnify/config.env` | Mode, base URL, port |
| `~/.local/share/bunnify/` | DB, logs, managed run state |

More: [docs/CONFIG.md](docs/CONFIG.md), [docs/LOCAL.md](docs/LOCAL.md)

## Linux service host

Run `setup-service` from a [repository-helpers](https://github.com/the-hcma/repository-helpers)
clone (see [docs/SYSTEMD.md](docs/SYSTEMD.md)).

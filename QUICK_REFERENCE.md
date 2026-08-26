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
bunnify stop                    # stop server (macOS: boot out server LaunchAgent)
bunnify upgrade                 # pipx upgrade; macOS refreshes LaunchAgents
bunnify --version               # package version, commit, and install path
bunnify gh                      # open a shortcut (example key from bunnify.json.example)
bunnify bun                     # Bunnify source on GitHub
bunnify pr the-hcma/bunnify 272 # parameterized shortcut (repo + PR number)
bunnify --fzf                   # fuzzy-pick a shortcut (requires fzf on PATH)
bunnify --print-url gh          # print resolved URL instead of opening browser
bunnify --list-keys             # list keys from the running server
bunnify spotty-bunny            # macOS search box (requires extra macos)
bunnify spotty-bunny --verbose  # DEBUG logs on stderr and log file
bunnify spotty-bunny install    # login LaunchAgent (TCC + KeepAlive)
bunnify spotty-bunny status     # process, launchd, logs, TCC
bunnify spotty-bunny upgrade    # manual Spotty plist bounce (optional on macOS)
bunnify spotty-bunny uninstall
```

## Spotty Bunny (macOS)

Requires `pipx install 'bunnify[macos]'`. Hold one Control, tap the other.

```bash
bunnify spotty-bunny install     # login LaunchAgent (TCC + KeepAlive)
bunnify spotty-bunny status
bunnify upgrade                  # refreshes both LaunchAgents on macOS
bunnify spotty-bunny uninstall
spotty-bunny                     # foreground (debug)
```

Left-click the bunny for About (bookmarks file, GitHub repo if that file is in
a GitHub checkout, local vs remote server + URL, update available). Right-click
for **Quit**, **Uninstall**, and **Upgrade** (Upgrade only when PyPI is newer).
An up-arrow badge on the bunny means this install is behind PyPI.

Details: [docs/LOCAL.md](docs/LOCAL.md)

## Server

```bash
bunnify stop                         # local mode; macOS boots out server agent
bunnify-server install --port 8000   # macOS: server LaunchAgent only
bunnify-server status
bunnify-server upgrade
bunnify-server uninstall
bunnify-server --help
bunnify-server --foreground --noninteractive --port 8000   # foreground (debug)
bunnify-server --port 8000 --noninteractive --pid-dir ~/.local/share/bunnify/run
bunnify-server --stop --pid-dir ~/.local/share/bunnify/run
curl -sf "$(grep '^BUNNIFY_BASE_URL=' ~/.config/bunnify/config.env | cut -d= -f2-)/health"
```

On macOS, **local** `bunnify setup` installs the server LaunchAgent; Linux and
manual installs use the managed `--pid-dir` path above. Details:
[docs/LOCAL.md](docs/LOCAL.md).

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
| `~/.local/share/bunnify/` | DB, logs, managed run state (`run/`, `run/launchd/` on macOS LaunchAgent) |

More: [docs/CONFIG.md](docs/CONFIG.md), [docs/LOCAL.md](docs/LOCAL.md)

## Linux service host

Run `setup-service` from a [repository-helpers](https://github.com/the-hcma/repository-helpers)
clone (see [docs/SYSTEMD.md](docs/SYSTEMD.md)).

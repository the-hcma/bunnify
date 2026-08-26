# Bunnify

[![PyPI version](https://img.shields.io/pypi/v/bunnify.svg)](https://pypi.org/project/bunnify/)
[![Python 3.14+](https://img.shields.io/badge/python-3.14%2B-blue.svg)](https://pypi.org/project/bunnify/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](https://github.com/the-hcma/bunnify/blob/main/LICENSE)
[![CI](https://github.com/the-hcma/bunnify/actions/workflows/ci.yml/badge.svg)](https://github.com/the-hcma/bunnify/actions/workflows/ci.yml)

A Python bookmark manager and URL shortcut system: terminal CLI, web command
palette, Chrome OpenSearch integration, and parameterized redirects.

## Install

[pipx](https://pipx.pypa.io/) is the recommended path for end users:

```bash
pipx install bunnify
pipx ensurepath   # adds ~/.local/bin to PATH if needed (restart the shell)
bunnify --version
bunnify onboard   # print bookmarks / setup / Chrome next steps
```

pipx installs `bunnify` and `bunnify-server` under **`~/.local/bin`** by default
(or `$PIPX_BIN_DIR` when set). Ensure that directory is on your `PATH` before
running either command. Prefer the pipx apps over any checkout
`./scripts/bunnify` still on `PATH`.

The wheel installs **`bunnify`** (CLI), **`bunnify-server`** (Django
server), and **`spotty-bunny`** (macOS search box; needs extra
`macos`). No repository checkout or `uv` is required at runtime.

Package on PyPI: [pypi.org/project/bunnify](https://pypi.org/project/bunnify/).

### After install or upgrade

pipx does not print package docs after install. Run:

```bash
bunnify onboard
```

That prints the ready-to-go checklist (bookmarks path, `bunnify setup`,
Chrome/Edge, and upgrade). Same text:

```bash
bunnify --onboard
```

Summary of what it covers:

1. **Bookmarks** at `~/.config/bunnify/bookmarks.json` (required before the
   server starts) — `bunnify setup` can install the example shortcuts, or seed
   from
   [bunnify.json.example](https://github.com/the-hcma/bunnify/blob/main/bunnify.json.example)
2. **`bunnify setup`** — local on a laptop; remote for a home/always-on host  
   [LOCAL.md](https://github.com/the-hcma/bunnify/blob/main/docs/LOCAL.md)
3. **Chrome / Edge** — match `BUNNIFY_BASE_URL` from `config.env`  
   [CHROME_SETUP.md](https://github.com/the-hcma/bunnify/blob/main/CHROME_SETUP.md)
4. **Try it:** `bunnify gh` or address-bar keyword (e.g. `b gh`)
5. **macOS Spotty Bunny** (optional) — `pipx install 'bunnify[macos]'` then
   `bunnify spotty-bunny install`
   ([LOCAL.md](https://github.com/the-hcma/bunnify/blob/main/docs/LOCAL.md))

### Upgrade

Preferred:

```bash
bunnify upgrade
```

That prints the version/commit you are running **from**, the PyPI target, then
the pipx app version/commit **to** after `pipx upgrade`. Use this instead of
bare `pipx upgrade bunnify` so you can see when PATH is still a git checkout.

On **macOS**, `bunnify upgrade` also refreshes installed server and Spotty Bunny
LaunchAgents when their plists are present (or run `bunnify-server upgrade` /
`bunnify spotty-bunny upgrade` manually).

`pipx upgrade` only updates `~/.local/bin/bunnify`. If `bunnify --version` still
shows a checkout SHA, PATH is hitting `./scripts/bunnify` or a repo `.venv`.
After `pipx ensurepath`, `command -v bunnify` should be `~/.local/bin/bunnify`.

Bookmarks and `~/.config/bunnify/config.env` are user data — upgrades do not
overwrite them. After a major server change, re-run `bunnify setup` only if
docs or release notes say so. Setup will offer to stop a different local
Bunnify build and start this CLI's build when the port is already in use.

Source and docs: [github.com/the-hcma/bunnify](https://github.com/the-hcma/bunnify).

## Quick start

### 1. Bookmarks file

`bunnify setup` offers to install the example bookmarks when none exist yet.
You can also create the file yourself from the
[documented example](https://github.com/the-hcma/bunnify/blob/main/bunnify.json.example)
into XDG config:

```bash
mkdir -p ~/.config/bunnify
curl -fsSL https://raw.githubusercontent.com/the-hcma/bunnify/main/bunnify.json.example \
  -o ~/.config/bunnify/bookmarks.json
# edit ~/.config/bunnify/bookmarks.json with your shortcuts
```

See [Configuration](https://github.com/the-hcma/bunnify/blob/main/docs/CONFIG.md)
for overrides (`BUNNIFY_BOOKMARKS`, `XDG_CONFIG_HOME`).

### 2. Configure local or remote mode

```bash
bunnify setup
```

**Laptop / daily machine:** choose **local** (default). On **macOS**, setup
installs the **server LaunchAgent** (`com.thehcma.bunnify`), verifies
`/health`, records the port, and saves settings to `~/.config/bunnify/config.env`.
Elsewhere it starts a managed background server the same way as before. Point
Chrome or Edge at the same `BUNNIFY_BASE_URL`
([Chrome / Edge setup](https://github.com/the-hcma/bunnify/blob/main/CHROME_SETUP.md)).

**Home server / always-on host:** choose **remote** on client devices and enter
that host’s URL. Setup probes `/health`; if the host is unreachable it warns
and asks before saving. Prefer a centralized remote install when several
machines share one server — not as a laptop’s only dependency if you often go
offline.

One-time override without saving: `bunnify --base-url https://… shortcut`.

Details:
[Local and remote setup](https://github.com/the-hcma/bunnify/blob/main/docs/LOCAL.md).

### 3. Run shortcuts

```bash
bunnify              # interactive REPL (Tab completion, history)
bunnify gh           # open a shortcut in the browser
bunnify bun          # Bunnify source on GitHub
bunnify pr the-hcma/bunnify 272   # parameterized shortcut
bunnify --fzf        # fuzzy picker
bunnify --print-url gh
```

Unknown keys exit non-zero in direct mode (no search-engine fallback).

## Features

- **CLI / REPL** — fuzzy Tab completion, fzf mode, Vim/Emacs edit keys
- **Spotty Bunny** — dual-Control search box (`spotty-bunny`; extra `macos`;
  login LaunchAgent via `install` / `upgrade` / `uninstall`)
- **macOS server LaunchAgent** — local setup installs `bunnify-server` under
  launchd (`bunnify-server install|status|upgrade|uninstall`)
- **Web** — `/cmd/` command palette, `/list/` browser, smart `/search/`
- **Chrome / Edge** — OpenSearch at `/opensearch.xml`
  ([setup guide](https://github.com/the-hcma/bunnify/blob/main/CHROME_SETUP.md))
- **Parameters** — URLs with `#{name}` placeholders and optional defaults
- **Validation** — JSON Schema on load; reserved keys `h` / `help`

## Spotty Bunny (macOS)

Optional Spotlight-style search box. Hold one Control and tap the other to
type a shortcut. Needs the `macos` extra (PyObjC).

### Install

```bash
pipx install 'bunnify[macos]'
pipx ensurepath
bunnify spotty-bunny install    # login LaunchAgent (TCC + KeepAlive)
bunnify spotty-bunny status
```

`install` grants Accessibility and Input Monitoring to the **interpreter
launchd will exec** (typically the pipx venv Python), writes
`~/Library/LaunchAgents/com.thehcma.bunnify.spotty-bunny.plist`, and bootstraps
it. Bare `spotty-bunny` (or `bunnify spotty-bunny` with no subcommand) still
runs in the **foreground** for debugging.

### Upgrade

```bash
bunnify upgrade                 # pipx package; on macOS refreshes LaunchAgents
bunnify spotty-bunny upgrade    # manual plist bounce when needed
```

On macOS, `bunnify upgrade` rewrites both LaunchAgents when installed. Use
`bunnify spotty-bunny upgrade` only when you need to refresh Spotty without
upgrading the pipx package.

### Uninstall

```bash
bunnify spotty-bunny uninstall
```

That boots the agent out, removes the plist, and stops a leftover overlay
process. Bookmarks and `config.env` are unchanged. Right-click the bunny icon
for **Install Spotty Bunny** (when the LaunchAgent is missing), **Quit Spotty
Bunny**, **Uninstall Spotty Bunny**, and (when installed and a newer PyPI
version is known) **Upgrade Spotty Bunny**. An up-arrow badge on the
icon and an About line mark an outdated install (PyPI is checked at most
once a day).

Left-click the bunny for About: bookmarks file, GitHub repo when that file
lives in a GitHub checkout, and whether the CLI is talking to a local or
remote server (with its URL).

Details:
[Local and remote setup](https://github.com/the-hcma/bunnify/blob/main/docs/LOCAL.md).

## Server lifecycle

Installed users manage the server with **`bunnify-server`**:

```bash
bunnify-server --help
bunnify-server install --port 8000   # macOS: server LaunchAgent only
bunnify-server status
bunnify-server upgrade               # rewrite plist for current binary
# Foreground (systemd, debugging):
bunnify-server --foreground --noninteractive --port 8000
# Background managed daemon (non-macOS or manual):
bunnify-server --port 8000 --noninteractive --pid-dir ~/.local/share/bunnify/run
bunnify-server --stop --pid-dir ~/.local/share/bunnify/run
curl --max-time 2 http://127.0.0.1:8000/health
```

**Local setup:** `bunnify setup` (macOS installs the server LaunchAgent; other
platforms start a managed background server). Stop with:

```bash
bunnify stop    # macOS: boot out server LaunchAgent; else stop managed server
```

That prints the URL and runtime directory before stopping. Details:
[Local and remote setup](https://github.com/the-hcma/bunnify/blob/main/docs/LOCAL.md).

**Linux production:**
[systemd user service](https://github.com/the-hcma/bunnify/blob/main/docs/SYSTEMD.md)
via `setup-service` from
[repository-helpers](https://github.com/the-hcma/repository-helpers).

**macOS:** prefer `bunnify setup` (local) or the commands above. Manual plist
copy is optional — see
[LaunchAgent example](https://github.com/the-hcma/bunnify/blob/main/etc/launchd/com.thehcma.bunnify.plist.example)
and [LOCAL.md](https://github.com/the-hcma/bunnify/blob/main/docs/LOCAL.md).

## Web usage

With the server running (default `http://127.0.0.1:8000` after setup):

| URL | Purpose |
|-----|---------|
| `/cmd/` | Command palette (recommended) |
| `/search/?q=pr+12345` | Smart search |
| `/list/` | Browse all bookmarks |
| `/<key>/` | Direct redirect |
| `/opensearch.xml` | Chrome search engine descriptor |

## Bookmarks format

```json
{
  "gh": {
    "description": "GitHub",
    "url": "https://github.com/"
  },
  "pr": {
    "description": "Pull request",
    "url": "https://github.com/#{repo}/pull/#{pr_number}",
    "defaults": { "repo": "org/repo" }
  }
}
```

Required fields: `description`, `url`. Placeholders use `#{parameter_name}`.
Reload after edits: the server watches the JSON file, or run
`load_bookmarks` in a development checkout.

## Development checkout

Contributors clone the repo and use `uv` — separate from the pipx path above.

```bash
git clone https://github.com/the-hcma/bunnify.git
cd bunnify
uv sync
uv run python manage.py migrate

mkdir -p ~/.config/bunnify
cp bunnify.json.example ~/.config/bunnify/bookmarks.json

./scripts/bunnify setup
./scripts/bunnify-server --console --log-level DEBUG   # optional
./test_bunnify
```

Full guidelines:
[CONTRIBUTING.md](https://github.com/the-hcma/bunnify/blob/main/CONTRIBUTING.md).
Quality gates: `./scripts/checks`.

Wrappers under `./scripts/` prefer `uv run` when `uv` is on `PATH`, otherwise
the checkout `.venv` (same entry points systemd uses on service hosts).

## Documentation

| Doc | Audience |
|-----|----------|
| [CONFIG.md](https://github.com/the-hcma/bunnify/blob/main/docs/CONFIG.md) | XDG paths and environment variables |
| [LOCAL.md](https://github.com/the-hcma/bunnify/blob/main/docs/LOCAL.md) | Local vs remote setup, ports, Spotty Bunny |
| [SYSTEMD.md](https://github.com/the-hcma/bunnify/blob/main/docs/SYSTEMD.md) | Linux user service |
| [CHROME_SETUP.md](https://github.com/the-hcma/bunnify/blob/main/CHROME_SETUP.md) | Browser search engine |
| [QUICK_REFERENCE.md](https://github.com/the-hcma/bunnify/blob/main/QUICK_REFERENCE.md) | Cheat sheet |
| [RELEASING.md](https://github.com/the-hcma/bunnify/blob/main/docs/RELEASING.md) | Maintainers: PyPI releases |

## Troubleshooting

**Server won't start**

```bash
bunnify-server --console --log-level DEBUG
# or in a checkout: ./scripts/bunnify-server --console
```

**Bookmarks missing**

```bash
ls -l ~/.config/bunnify/bookmarks.json
# run `bunnify setup` (offers the example), or copy bunnify.json.example
```

**CLI can't reach server**

```bash
bunnify setup
curl -sf "$(grep BUNNIFY_BASE_URL ~/.config/bunnify/config.env | cut -d= -f2-)/health"
```

**Stale managed process**

```bash
bunnify-server --stop --pid-dir ~/.local/share/bunnify/run
```

## Releasing

Maintainers:
[docs/RELEASING.md](https://github.com/the-hcma/bunnify/blob/main/docs/RELEASING.md)
(Release Please + PyPI).

## License

MIT © 2026 Henrique Andrade (GitHub's thehcma) — see
[LICENSE](https://github.com/the-hcma/bunnify/blob/main/LICENSE).

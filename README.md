# Bunnify 🐰

A Python bookmark manager and URL shortcut system: terminal CLI, web command
palette, Chrome OpenSearch integration, and parameterized redirects.

## Install

[pipx](https://pipx.pypa.io/) is the recommended path for end users:

```bash
pipx install bunnify
pipx ensurepath   # adds ~/.local/bin to PATH if needed (restart the shell)
bunnify --version
```

pipx installs `bunnify` and `bunnify-server` under **`~/.local/bin`** by default
(or `$PIPX_BIN_DIR` when set). Ensure that directory is on your `PATH` before
running either command.

The wheel installs **`bunnify`** (CLI) and **`bunnify-server`** (Django
server). No repository checkout or `uv` is required at runtime.

## Quick start

### 1. Create your bookmarks file

Download the [documented example](https://github.com/the-hcma/bunnify/blob/main/bunnify.json.example)
into XDG config (required before the server starts):

```bash
mkdir -p ~/.config/bunnify
curl -fsSL https://raw.githubusercontent.com/the-hcma/bunnify/main/bunnify.json.example \
  -o ~/.config/bunnify/bookmarks.json
# edit ~/.config/bunnify/bookmarks.json with your shortcuts
```

See [Configuration](docs/CONFIG.md) for overrides (`BUNNIFY_BOOKMARKS`,
`XDG_CONFIG_HOME`).

### 2. Configure local or remote mode

```bash
bunnify setup
```

**Laptop / daily machine:** choose **local** (default). Setup starts a managed
server, verifies `/health`, records the port, and saves settings to
`~/.config/bunnify/config.env`. Point Chrome at the same `BUNNIFY_BASE_URL`
([Chrome setup](CHROME_SETUP.md)).

**Home server / always-on host:** choose **remote** on client devices and enter
that host’s URL. Prefer a centralized remote install when several machines share
one server — not as a laptop’s only dependency if you often go offline.

One-time override without saving: `bunnify --base-url https://… shortcut`.

Details: [Local and remote setup](docs/LOCAL.md).

### 3. Run shortcuts

```bash
bunnify              # interactive REPL (Tab completion, history)
bunnify gh           # open a shortcut in the browser
bunnify pr the-hcma/bunnify 272   # parameterized shortcut
bunnify --fzf        # fuzzy picker
bunnify --print-url gh
```

Unknown keys exit non-zero in direct mode (no search-engine fallback).

## Features

- **CLI / REPL** — fuzzy Tab completion, fzf mode, Vim/Emacs edit keys
- **Web** — `/cmd/` command palette, `/list/` browser, smart `/search/`
- **Chrome** — OpenSearch at `/opensearch.xml` ([setup guide](CHROME_SETUP.md))
- **Parameters** — URLs with `#{name}` placeholders and optional defaults
- **Copilot reviews** — `rpr` shortcut streams in-app PR reviews
- **Validation** — JSON Schema on load; reserved keys `h` / `help`

## Server lifecycle

Installed users manage the server with **`bunnify-server`**:

```bash
bunnify-server --help
# Foreground (systemd, LaunchAgent, debugging):
bunnify-server --foreground --noninteractive --port 8000
# Background managed daemon (returns after fork):
bunnify-server --port 8000 --noninteractive --pid-dir ~/.local/share/bunnify/run
bunnify-server --stop --pid-dir ~/.local/share/bunnify/run
curl --max-time 2 http://127.0.0.1:8000/health
```

`bunnify setup` starts a managed local server for daily CLI use. Details:
[Local and remote setup](docs/LOCAL.md).

**Linux production:** [systemd user service](docs/SYSTEMD.md) via
`setup-service` from [repository-helpers](https://github.com/the-hcma/repository-helpers).

**macOS:** [LaunchAgent example](etc/launchd/com.thehcma.bunnify.plist.example).

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
git clone https://github.com/thehcma/bunnify.git
cd bunnify
uv sync
uv run python manage.py migrate

mkdir -p ~/.config/bunnify
cp bunnify.json.example ~/.config/bunnify/bookmarks.json

./scripts/bunnify setup
./scripts/bunnify-server --console --log-level DEBUG   # optional
./test_bunnify
```

Full guidelines: [CONTRIBUTING.md](CONTRIBUTING.md). Quality gates:
`./scripts/checks`.

Wrappers under `./scripts/` prefer `uv run` when `uv` is on `PATH`, otherwise
the checkout `.venv` (same entry points systemd uses on service hosts).

## Documentation

| Doc | Audience |
|-----|----------|
| [CONFIG.md](docs/CONFIG.md) | XDG paths and environment variables |
| [LOCAL.md](docs/LOCAL.md) | Local vs remote setup, ports, LaunchAgent |
| [SYSTEMD.md](docs/SYSTEMD.md) | Linux user service |
| [CHROME_SETUP.md](CHROME_SETUP.md) | Browser search engine |
| [QUICK_REFERENCE.md](QUICK_REFERENCE.md) | Cheat sheet |
| [RELEASING.md](docs/RELEASING.md) | Maintainers: PyPI releases |

## Troubleshooting

**Server won't start**

```bash
bunnify-server --console --log-level DEBUG
# or in a checkout: ./scripts/bunnify-server --console
```

**Bookmarks missing**

```bash
ls -l ~/.config/bunnify/bookmarks.json
# create from bunnify.json.example if absent — see Quick start
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

Maintainers: [docs/RELEASING.md](docs/RELEASING.md) (Release Please + PyPI).

## License

MIT — see [LICENSE](LICENSE).

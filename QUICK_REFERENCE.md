# ⚡ Quick reference

Assumes `pipx install bunnify` and a completed `bunnify setup`. Default local
base URL is usually `http://127.0.0.1:8000` — check
`~/.config/bunnify/config.env`.

## Bookmarks file

```bash
mkdir -p ~/.config/bunnify
curl -fsSL https://raw.githubusercontent.com/thehcma/bunnify/main/bunnify.json.example \
  -o ~/.config/bunnify/bookmarks.json
```

## CLI

```bash
bunnify                    # REPL
bunnify setup              # reconfigure local/remote
bunnify gh                 # open shortcut
bunnify pr 12345           # parameterized
bunnify --fzf              # fuzzy pick
bunnify --print-url vault  # print URL only
bunnify --list-keys        # all keys
```

## Server

```bash
bunnify-server --help
bunnify-server --foreground --noninteractive --port 8000   # stay in foreground
bunnify-server --port 8000 --noninteractive --pid-dir ~/.local/share/bunnify/run
bunnify-server --stop --pid-dir ~/.local/share/bunnify/run
curl -sf http://127.0.0.1:8000/health
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

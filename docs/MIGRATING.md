# Migrating from a git checkout

Use this guide when you previously ran Bunnify from a cloned repository with a
repo-local `bunnify.json` or legacy paths under `~/work/bunnify/`.

## Bookmarks

Personal shortcuts now live under XDG config, not in the repository:

```bash
mkdir -p ~/.config/bunnify
cp /path/to/your/old/bunnify.json ~/.config/bunnify/bookmarks.json
# or seed from the documented example:
cp bunnify.json.example ~/.config/bunnify/bookmarks.json
```

The server and CLI read `~/.config/bunnify/bookmarks.json` by default (or
`$BUNNIFY_BOOKMARKS` when set). They do **not** auto-copy from legacy paths.

## CLI server preference

Checkout installs often used a gitignored `bunnify.env` in the repo root. Pipx
and XDG installs use `~/.config/bunnify/config.env` instead:

```bash
bunnify setup
```

Or copy values manually, for example:

```dotenv
BUNNIFY_MODE=remote
BUNNIFY_BASE_URL=https://bunnify.example.com
```

See [Configuration](CONFIG.md) for all environment variables.

## Local server and data files

| Old (checkout) | New (default) |
|----------------|---------------|
| `./scripts/bunnify-server` | `bunnify-server` (pipx) or `./scripts/bunnify-server` (dev) |
| Repo `db.sqlite3` | `~/.local/share/bunnify/db.sqlite3` (`$BUNNIFY_DATA_DIR`) |
| Repo or legacy JSON | `~/.config/bunnify/bookmarks.json` |
| Ad hoc PID files | `~/.local/share/bunnify/run/` (managed local server) |

On a **systemd service host**, `setup-service` migrates the database into
`~/scratch/bunnify/data/` and uses paths documented in [SYSTEMD](SYSTEMD.md).

## Development vs end-user install

- **End users:** `pipx install bunnify` — no clone required. See the
  [README](../README.md) quick start.
- **Contributors:** keep a git checkout with `uv sync` and `./scripts/*`
  wrappers. See [CONTRIBUTING](../CONTRIBUTING.md).

# Local and remote server setup

Run the interactive setup after installing with pipx:

```bash
bunnify setup
# equivalent: bunnify --setup
```

In a development checkout, `./scripts/bunnify` and
`./scripts/bunnify-server` are thin `uv` wrappers around the same installed
entry points.

Setup defaults to **local** mode. It creates the user bookmarks file when
needed, starts a managed server, verifies `/health`, and records the selected
port. Remote mode prompts for a URL and saves it only after its `/health`
response is HTTP 200 with body `ok`. If a configured remote server later
becomes unavailable, the interactive CLI offers to use the managed local
server for that run without replacing the saved remote preference.

Verified settings are stored in `~/.config/bunnify/config.env` (or
`$XDG_CONFIG_HOME/bunnify/config.env`):

```dotenv
BUNNIFY_MODE=local
BUNNIFY_BASE_URL=http://127.0.0.1:8000
BUNNIFY_LOCAL_PORT=8000
```

`setup` is a reserved CLI shortcut name. Use `--base-url URL` for a one-time
server override that is not persisted.

## Manual local workflow

```bash
mkdir -p ~/.local/share/bunnify/run
bunnify-server \
  --port 8000 \
  --pid-dir ~/.local/share/bunnify/run \
  --noninteractive

curl --max-time 2 http://127.0.0.1:8000/health

bunnify-server --stop --pid-dir ~/.local/share/bunnify/run
```

If port 8000 belongs to another service, use `--port 0`; the chosen port is
written to `~/.local/share/bunnify/run/.bunnify.port`. Set
`BUNNIFY_DATA_DIR` to relocate the SQLite database, logs, and managed runtime
files together.

Before upgrading from a checkout that stored PID files under
`~/.config/bunnify/run`, stop that server explicitly:

```bash
bunnify-server --stop --pid-dir ~/.config/bunnify/run
```

## macOS LaunchAgent

Copy `etc/launchd/com.thehcma.bunnify.plist.example` to
`~/Library/LaunchAgents/com.thehcma.bunnify.plist`. Replace
`__BUNNIFY_SERVER__` with the absolute path from `command -v bunnify-server`
and `__HOME__` with your absolute home directory, then load it:

```bash
launchctl bootstrap "gui/$(id -u)" \
  ~/Library/LaunchAgents/com.thehcma.bunnify.plist
launchctl kickstart -k "gui/$(id -u)/com.thehcma.bunnify"

# Unload before editing or removing it:
launchctl bootout "gui/$(id -u)/com.thehcma.bunnify"
```

The template runs the server in the foreground with `KeepAlive` enabled. It
uses the default user bookmarks path, seeding the file from the packaged
example when needed. Confirm that port 8000 is free before loading the agent.

## Troubleshooting

- Health check fails: inspect
  `~/.local/share/bunnify/bunnify.log` and the managed run directory's
  `bunnify-startup.log`, then retry `bunnify setup`.
- Port occupied: stop that service or accept the interactive retry to choose an
  ephemeral port. Noninteractive mode never kills an unrelated process.
- Stale managed process: run the manual `--stop --pid-dir` command above and
  rerun setup.

# Local and remote server setup

Run the interactive setup from a development checkout:

```bash
./scripts/bunnify setup
# equivalent: ./scripts/bunnify --setup
```

Setup defaults to **local** mode. It creates the user bookmarks file when
needed, starts a managed server, verifies `/health`, and records the selected
port. Remote mode prompts for a URL and saves it only after its `/health`
response is HTTP 200 with body `ok`. If a configured remote server later
becomes unavailable, the interactive CLI offers to start and switch to the
managed local server.

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
mkdir -p ~/.config/bunnify/run
./scripts/bunnify-server \
  --port 8000 \
  --pid-dir ~/.config/bunnify/run \
  --noninteractive

curl --max-time 2 http://127.0.0.1:8000/health

./scripts/bunnify-server --stop --pid-dir ~/.config/bunnify/run
```

If port 8000 belongs to another service, use `--port 0`; the chosen port is
written to `~/.config/bunnify/run/.bunnify.port`.

## macOS LaunchAgent

Copy `etc/launchd/com.thehcma.bunnify.plist.example` to
`~/Library/LaunchAgents/com.thehcma.bunnify.plist`, replace every placeholder
with an absolute path, then load it:

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

- `scripts/bunnify-server` missing: managed local mode is not packaged in the
  CLI wheel yet; run from a development checkout.
- Health check fails: inspect `/tmp/bunnify.log` and
  `/tmp/bunnify_startup.log`, then retry `bunnify setup`.
- Port occupied: stop that service or choose an unused port. Noninteractive
  mode never kills an unrelated process.
- Stale managed process: run the manual `--stop --pid-dir` command above and
  rerun setup.

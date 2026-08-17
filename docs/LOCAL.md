# Local and remote server setup

## Which mode to choose

| Situation | Mode |
|-----------|------|
| Laptop / desktop you carry or use daily | **local** (default) — run `bunnify-server` on the same machine as Chrome and the CLI |
| Always-on home lab or shared household host | **remote** — one centralized server; other devices point at its URL |

On a laptop, prefer **local**. Chrome OpenSearch and the CLI both talk to the same
base URL from `~/.config/bunnify/config.env`. If that URL is a remote host and
the host is unreachable, both the CLI and the browser fail — there is no
automatic fallback to a local server. Re-run `bunnify setup` and choose local
(or restore the remote) when that happens.

Remote mode fits a **home server** (or similar) that stays up on the LAN/VPN so
phones, desktops, and laptops can share one bookmark install.

## Setup

```bash
bunnify setup
# equivalent: bunnify --setup
```

In a development checkout, `./scripts/bunnify` and
`./scripts/bunnify-server` prefer `uv run` when `uv` is on ``PATH``, otherwise
they fall back to the checkout ``.venv`` (same entry points systemd uses).

Setup defaults to **local** mode. When `bookmarks.json` is missing, it offers
to install the example shortcuts (see [Configuration](CONFIG.md)). It then
prompts for a free non-privileged listening port
(default `8000`, or `0` for an OS-assigned port). If that port already serves
a **different** Bunnify build, setup asks whether to stop it and start this
CLI's build (even when the process was started with a different run directory). It then
starts a managed server, verifies `/health`, and records the selected port in
`config.env` and under `$BUNNIFY_DATA_DIR/run/` (for example
`~/scratch/bunnify/run` on service hosts).
Remote mode prompts for a URL and saves it only after its `/health` response is
HTTP 200 with body `ok`.

Verified settings are stored in `~/.config/bunnify/config.env` (or
`$XDG_CONFIG_HOME/bunnify/config.env`):

```dotenv
BUNNIFY_MODE=local
BUNNIFY_BASE_URL=http://127.0.0.1:8000
BUNNIFY_LOCAL_PORT=8000
```

`setup` is a reserved CLI shortcut name. Use `--base-url URL` for a one-time
server override that is not persisted.

To stop the managed local server:

```bash
bunnify stop
# equivalent: bunnify --stop
```

That prints the URL and runtime directory, then stops the process recorded for
this CLI install. Remote mode is unchanged — stop the host service there
instead.

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

## macOS overlay

Foreground process (no login agent yet). Needs the optional `macos` extra
(PyObjC):

```bash
# pipx
pipx install 'bunnify[macos]'
bunnify-overlay

# development checkout
uv sync --extra macos
./scripts/bunnify-overlay
```

Hold **one** Control, then press the **other** to show the search box. Esc
(or the same chord again) hides it. Ctrl-C in the terminal quits.

If the chord does nothing, grant **Accessibility** and **Input Monitoring**
to the Python interpreter (or Terminal) in System Settings → Privacy &
Security, then re-run.

Tab completion and opening shortcuts are not wired yet; this is a no-op
panel for assessing the hotkey and window.

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

The template runs the server in the foreground with `KeepAlive` enabled. Ensure
`~/.config/bunnify/bookmarks.json` exists before loading the agent. Confirm that
port 8000 is free unless you override `--port`.

## Troubleshooting

- Health check fails: inspect
  `~/.local/share/bunnify/bunnify.log` and the managed run directory's
  `bunnify-startup.log`, then retry `bunnify setup`.
- Port occupied: stop that service or accept the interactive retry to choose an
  ephemeral port. Noninteractive mode never kills an unrelated process.
- Stale managed process: run the manual `--stop --pid-dir` command above and
  rerun setup.
- Remote unreachable: the CLI does not switch to local automatically. Fix the
  network/server or run `bunnify setup` and choose **local** (laptop) or a
  healthy remote URL. Update Chrome’s search engine to the same
  `BUNNIFY_BASE_URL` (see [CHROME_SETUP](../CHROME_SETUP.md)).

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

## Spotty Bunny (macOS)

Needs the optional `macos` extra (PyObjC). Bare `spotty-bunny` still runs the
overlay **in the foreground**. The login LaunchAgent is a distinct label from
the server agent (`com.thehcma.bunnify`).

### Install

Requires [pipx](https://pipx.pypa.io/) on ``PATH`` (for example ``brew install pipx``).
Then install the macOS extra and start the local server before the overlay agent:

```bash
# pipx
pipx install 'bunnify[macos]'
bunnify setup                      # local server LaunchAgent + /health (interactive)
# or manual server (see Manual local workflow below)

spotty-bunny                     # foreground overlay
bunnify spotty-bunny             # same (reserved CLI token)
bunnify spotty-bunny install     # LaunchAgent (KeepAlive + RunAtLoad)
bunnify spotty-bunny status

# development checkout (wrapper syncs extra macos)
./scripts/spotty-bunny
./scripts/spotty-bunny --verbose          # DEBUG: every tap event, chord, show/hide
./scripts/spotty-bunny --log-level INFO   # default; chord complete, show/hide, SIGINT
# same values as bunnify-server:
./scripts/spotty-bunny --log-level DEBUG
# rotating file (10 MiB × 5), same verbose format as bunnify-server:
# default ~/.local/share/bunnify/spotty-bunny.log
./scripts/spotty-bunny --log-file /tmp/spotty-bunny.log --verbose
```

`install` writes
`~/Library/LaunchAgents/com.thehcma.bunnify.spotty-bunny.plist` from
[`etc/launchd/com.thehcma.bunnify.spotty-bunny.plist.example`](https://github.com/the-hcma/bunnify/blob/main/etc/launchd/com.thehcma.bunnify.spotty-bunny.plist.example)
with **ProgramArguments** set to the absolute path from `command -v spotty-bunny`,
then `launchctl bootstrap "gui/$(id -u)"` that plist. It does **not** write the
plist or bootstrap until **Accessibility** and **Input Monitoring** are granted
to the **Python interpreter behind the pipx/venv console script** (the venv
``python`` the wrapper ``exec``s), not only Terminal.app or iTerm. Missing grants
trigger the system prompts where the APIs allow it, then the checks run again.
When run from an interactive terminal and either grant is still missing, the
command prompts you to press **Enter** after granting so it can re-check before
exiting. If either is still missing, it prints System Settings → Privacy &
Security instructions and exits non-zero.

After granting permissions, run `bunnify spotty-bunny install` again (or
`bunnify spotty-bunny upgrade`) so launchd starts a fresh process with the new
grants. A process that started before TCC was granted may not receive Control
chord events until it is restarted.

`status` prints running/pid, whether launchd has loaded the agent, the binary
path, the **Python interpreter** launchd will exec (real path for TCC lookups),
the application log
(`~/.local/share/bunnify/spotty-bunny.log` or `BUNNIFY_SPOTTY_BUNNY_LOG_FILE` /
`$BUNNIFY_DATA_DIR`), a suggested log-follow command
(`tail --follow=name --retry "<application_log>"`), launchd stdout/stderr paths
from the plist, version, and Accessibility / Input Monitoring yes/no. Exit `0`
only when the plist exists, the agent is loaded, the process is running, and
the plist binary path still exists and is executable.

`install` / `upgrade` prefer `~/.local/bin/spotty-bunny` when present (stable
operator wrapper), validate that the plist target exists before bootstrap, warn
when the interpreter identity changes (for example pipx → local clone), and
remind you to test the Control chord after a successful reload.

### Upgrade

```bash
bunnify upgrade                  # pipx package (preferred)
bunnify spotty-bunny upgrade     # rewrite plist + bounce launchd
```

`upgrade` rewrites the plist when `spotty-bunny` moved (pipx uninstall, venv
path / shebang, or `~/.local/bin` wrapper), re-verifies TCC for the new
interpreter, warns when the interpreter real path changed, then reloads the
agent with `launchctl bootout` and `launchctl bootstrap` so launchd picks up the
new ProgramArguments.
After moving off pipx or changing Python builds, re-grant Accessibility and
Input Monitoring to the interpreter shown by `bunnify spotty-bunny status`,
then run `bunnify spotty-bunny upgrade`.
Package updates stay on `bunnify upgrade` (`pipx upgrade bunnify`); run that
first, then `bunnify spotty-bunny upgrade` so launchd does not keep a stale
binary path.

### Uninstall

```bash
bunnify spotty-bunny uninstall
```

`uninstall` boots the agent out, removes the plist, stops a leftover overlay
process, and clears the pid file. It does not delete the application log or
your bookmarks. If the agent was never installed, it still succeeds.

To stop the overlay **without** removing the LaunchAgent, right-click the bunny
icon and choose **Quit Spotty Bunny**. That exits the process and boots the
agent out so KeepAlive cannot immediately respawn it. The plist stays; the
agent starts again at next login (`RunAtLoad`) until you `uninstall`.

The same menu lists **Install Spotty Bunny** when the LaunchAgent is missing
(then quits so launchd owns the overlay). When the agent is installed it
offers **Uninstall Spotty Bunny** (confirms, then removes the plist before
booting the agent out) and, when a newer PyPI release is known, **Upgrade
Spotty Bunny** (`pipx upgrade`, rewrite the plist, then quit so KeepAlive
relaunches). Items are listed A–Z by title.

Invoking `bunnify` reuses a running local server and Spotty Bunny overlay
when they match this CLI's commit. If either is missing it is started; if
either is running an older or different commit, the CLI offers to restart
it.

Spotty Bunny checks PyPI at most once per day (cached as
`pypi-latest.json` under the data directory). When this install is behind,
the bunny icon shows a small up-arrow badge and About includes
“Update available: …”.

### Using the overlay

Hold **one** Control, then press the **other** to show the search box. Esc
(or the same chord again) hides it. Up/down walks the CLI REPL history file
(`platformdirs` cache `bunnify/repl_history`). Tab uses the same completers as
the CLI (`FirstTokenFuzzyCompleter` / `ShortcutCompleter`) and lists matches
under the field. GitHub-backed parameter completions (e.g. `repoh <repo>`) need
`gh` installed (or `GITHUB_TOKEN`/`GH_TOKEN`). If `gh` is missing, the overlay
shows install guidance; macOS admins with Homebrew are offered
`brew install gh`. See `docs/CONFIG.md`. Enter resolves via `/api/resolve/` (same as browser search:
unknown text opens a Google query) and opens the URL in the default browser.
Ctrl-C in a foreground terminal quits. Startup prints the log file path on stderr
(`spotty-bunny: logging to …`). Default log level is **INFO** (use `--verbose`
for per-key tap debug). Launchd stdout/stderr under `~/Library/Logs/` are
separate from that application log.

The search box is centered on the **main display** (menu-bar monitor), with a
small bunny icon to the right of the field. **Left-click** the icon for the
About card: version, commit, license, Bunnify source, a hyperlink to your
bookmarks file (`BUNNIFY_BOOKMARKS` or `~/.config/bunnify/bookmarks.json`), the
GitHub repo when that file lives in a git checkout whose `origin` is GitHub,
whether Spotty Bunny is using a **local** or **remote** server (with its
URL from `config.env`), and an **Update available** line when PyPI is newer.
An up-arrow badge on the bunny also marks an outdated install. **Right-click**
the icon for **Quit**, **Uninstall**, and (when outdated) **Upgrade**.

If the chord does nothing, run with `--verbose` and watch stderr (or the
application log). Lines named `tap …` show whether key events arrive. If none
appear while you press keys, grant **Accessibility** and **Input Monitoring**
to the Python that `uv run` / pipx uses (often `.venv/bin/python` or the pipx
venv interpreter), not only Terminal.app, in System Settings → Privacy &
Security, then re-run. If events arrive but `fired=True` never appears, HID may
still miss right Control (`hid R=False`); Spotty Bunny also uses device flag
bits and the event keycode. Re-run `--verbose` after this fix.

On macOS, starting the **`bunnify` interactive REPL** (no query args) also
starts `spotty-bunny` in the background when it is not already running.

## macOS LaunchAgent

The **server** agent (`com.thehcma.bunnify`) is separate from Spotty Bunny
(`com.thehcma.bunnify.spotty-bunny`). On macOS, **local** `bunnify setup` and
`bunnify onboard` install the server LaunchAgent (KeepAlive + RunAtLoad) so the
API comes back after login without a manual `bunnify-server`. Prefer the
commands below over copying the example plist by hand:

```bash
bunnify setup                      # local → server LaunchAgent + /health
bunnify-server install --port 8000 # refresh / install server agent only
bunnify-server status
bunnify-server upgrade             # rewrite plist for the current binary
bunnify stop                       # boot out the agent and stop the listener
bunnify-server uninstall           # remove the LaunchAgent plist
```

`install` writes `~/Library/LaunchAgents/com.thehcma.bunnify.plist` from
[`etc/launchd/com.thehcma.bunnify.plist.example`](https://github.com/the-hcma/bunnify/blob/main/etc/launchd/com.thehcma.bunnify.plist.example)
with **ProgramArguments** pointing at `bunnify-server --foreground
--noninteractive --port … --pid-dir …/run/launchd`, then bootstraps it and waits
for `/health`.

For a **remote** base URL, setup and onboard do **not** install the server
agent. They probe `/health`; if the host is unreachable they warn and ask
whether to continue saving prefs / installing Spotty Bunny anyway.

Prefer `bunnify spotty-bunny install` for the overlay agent. Manual `launchctl`
(only if you need it):

```bash
launchctl bootstrap "gui/$(id -u)" \
  ~/Library/LaunchAgents/com.thehcma.bunnify.plist
launchctl bootout "gui/$(id -u)/com.thehcma.bunnify"
launchctl bootstrap "gui/$(id -u)" \
  ~/Library/LaunchAgents/com.thehcma.bunnify.spotty-bunny.plist
launchctl bootout "gui/$(id -u)/com.thehcma.bunnify.spotty-bunny"
```

Ensure `~/.config/bunnify/bookmarks.json` exists before loading the server agent.
Confirm that the chosen port is free unless you override `--port`.

## Troubleshooting

- Health check fails: inspect
  `~/.local/share/bunnify/bunnify.log` and the managed run directory's
  `bunnify-startup.log`, then retry `bunnify setup`.
- Port occupied: stop that service or accept the interactive retry to choose an
  ephemeral port. Noninteractive mode never kills an unrelated process.
- Stale managed process: run the manual `--stop --pid-dir` command above and
  rerun setup.
- Remote unreachable: setup/onboard warn and ask for confirmation before saving
  a remote URL or installing Spotty Bunny. The CLI does not switch to local
  automatically. Fix the network/server or run `bunnify setup` and choose
  **local** (laptop) or a healthy remote URL. Update Chrome’s search engine to
  the same `BUNNIFY_BASE_URL` (see [CHROME_SETUP](../CHROME_SETUP.md)).

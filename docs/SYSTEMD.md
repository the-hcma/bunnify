# Running Bunnify as a systemd User Service

This guide covers how to install, manage, and troubleshoot Bunnify as a
persistent background service using systemd's user session support.

The service runs under your user account (no root required), starts on boot
via lingering, and is managed using the `setup-service` script from
[repository-helpers](https://github.com/the-hcma/repository-helpers).

## Prerequisites

- systemd user session available (`systemctl --user status` returns output)
- `~/work/ai/repository-helpers` cloned locally
- Bunnify dependencies installed (`uv sync`)
- `bunnify.json` bookmarks file present (copy from `bunnify.json.example` to get started)

## Install the Service

Run `setup-service` from the bunnify repo directory:

```bash
~/work/ai/repository-helpers/scripts/setup-service
```

This will:

1. Read `etc/systemd/bunnify.service` from the repo, substitute `@@REPO_DIR@@`
   with the actual repo path, and write the result to
   `~/.config/systemd/user/bunnify.service`.
2. Create the log directory at `~/scratch/bunnify/`.
3. Enable systemd lingering so the service starts on boot without a login session.
4. Run `scripts/on-deploy` — applies any pending database migrations.
5. Enable and start (or restart) the service.

## Check Status

```bash
~/work/ai/repository-helpers/scripts/setup-service --status
```

Or use systemctl directly:

```bash
systemctl --user status bunnify
```

## View Logs

Logs are written to `~/scratch/bunnify/bunnify.log`:

```bash
# Follow live
tail -f ~/scratch/bunnify/bunnify.log

# Last 100 lines via journal
journalctl --user -u bunnify -n 100

# Follow live via journal
journalctl --user -u bunnify -f
```

## Start / Stop / Restart Manually

```bash
systemctl --user start   bunnify
systemctl --user stop    bunnify
systemctl --user restart bunnify
```

## Update After Code Changes

Run `setup-service` again — it re-runs `on-deploy` (which applies pending
migrations) and restarts the service only if the git SHA changed:

```bash
~/work/ai/repository-helpers/scripts/setup-service
```

At the start of each development session, `start-development --refresh`
handles this automatically:

```bash
~/work/ai/repository-helpers/scripts/dev/start-development --refresh
```

## Service Configuration

The service template lives at
[etc/systemd/bunnify.service](../etc/systemd/bunnify.service).

Key settings:

| Setting         | Value                                                                   |
|-----------------|-------------------------------------------------------------------------|
| `ExecStart`     | `bunnify-server --foreground --listen-all --port 8001 --bookmarks bunnify.json` |
| `ExecStartPost` | polls `http://127.0.0.1:8001/health` (12 × 1 s) to confirm startup     |
| `Restart`       | `always`                                                                |
| `RestartSec`    | `5s`                                                                    |
| `StandardOutput`| `append:~/scratch/bunnify/bunnify.log`                                  |
| `WantedBy`      | `default.target` (user session)                                         |

To change startup flags (e.g. a different port), edit
`etc/systemd/bunnify.service` and re-run `setup-service`.

## Uninstall

```bash
systemctl --user stop    bunnify
systemctl --user disable bunnify
rm ~/.config/systemd/user/bunnify.service
systemctl --user daemon-reload
```

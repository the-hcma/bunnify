# Running Bunnify as a systemd User Service

This guide covers how to install, manage, and troubleshoot Bunnify as a
persistent background service using systemd's user session support.

The service runs under your user account (no root required), starts on boot
via lingering on the designated **service host** (matched by `ConditionMachineId`),
and is managed using
`setup-service` from
[repository-helpers](https://github.com/the-hcma/repository-helpers).

The unit **template** (with `@@REPO_DIR@@`) lives in this repo at
`etc/systemd/bunnify.service`. `setup-service` expands it into
`~/.config/systemd/user/` and mirrors the expanded unit under
`~/.config/share/systemd-units/`.

## Prerequisites

- systemd user session available (`systemctl --user status` returns output)
- `~/work/ai/repository-helpers` cloned locally
- Bunnify dependencies installed (`uv sync`)
- `bunnify.json` bookmarks file present (copy from `bunnify.json.example` to get started)
- `~/.config/user-services-host` — readable label for the service host (or pass
  `--condition-host` on first `setup-service` run). On that host, setup also
  captures `/etc/machine-id` into `~/.config/user-services-machine-id` and injects
  `ConditionMachineId=` into units.

## Install the Service

Run `setup-service` from the bunnify repo directory:

```bash
~/work/ai/repository-helpers/scripts/setup-service
```

This will:

1. Read `etc/systemd/bunnify.service`, substitute `@@REPO_DIR@@`, inject
   `ConditionMachineId=`, and install under `~/.config/systemd/user/`.
2. Mirror the expanded unit to `~/.config/share/systemd-units/bunnify.service`.
3. Create the log directory at `~/scratch/bunnify/`.
4. Enable systemd lingering on the service host (when machine-id matches).
5. Run `scripts/on-deploy` — applies any pending database migrations.
6. Enable and start (or restart) the service on the service host only.

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
tail -f ~/scratch/bunnify/bunnify.log
journalctl --user -u bunnify -f
```

## Start / Stop / Restart Manually

```bash
systemctl --user start   bunnify
systemctl --user stop    bunnify
systemctl --user restart bunnify
```

## Update After Code Changes

```bash
~/work/ai/repository-helpers/scripts/setup-service
```

## Service Configuration

Edit `etc/systemd/bunnify.service` in this repo and re-run `setup-service`.

## Uninstall

```bash
systemctl --user stop    bunnify
systemctl --user disable bunnify
rm ~/.config/systemd/user/bunnify.service
rm -f ~/.config/share/systemd-units/bunnify.service
systemctl --user daemon-reload
```

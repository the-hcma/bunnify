# Running Bunnify as a systemd User Service

This guide covers how to install, manage, and troubleshoot Bunnify as a persistent background service using systemd's user session support.

The service runs under your user account (no root required), starts on boot via lingering on the designated **service host** (guarded by `ConditionHost=|` short name, FQDN, and machine-id — see repository-helpers `docs/SYSTEMD.md`), and is managed using `setup-service` from [repository-helpers](https://github.com/the-hcma/repository-helpers).

The unit **template** (with `@@REPO_DIR@@`) lives in this repo at `etc/systemd/bunnify.service`. `setup-service` expands it into `~/.config/systemd/user/` and mirrors the expanded unit under `~/.config/share/systemd-units/`.

## Prerequisites

- systemd user session available (`systemctl --user status` returns output)
- `~/work/ai/repository-helpers` cloned locally
- Bunnify dependencies installed (`uv sync`)
- Bookmarks at `~/.config/bunnify/bookmarks.json` (from `bunnify setup` or `bunnify.json.example` before first start)
- `~/.config/user-services-host` — short hostname label for the service host (or pass `--condition-host` on first `setup-service` run)
- `~/.config/user-services-host-fqdn` — FQDN captured on the service host (or `--condition-host-fqdn`)
- `~/.config/user-services-machine-id` — machine-id from `/etc/machine-id` on the service host; `setup-service` injects `ConditionHost=|<machine-id>` guards (see repository-helpers `docs/SYSTEMD.md`)

## Install the Service

Run `setup-service` from the bunnify repo directory:

```bash
~/work/ai/repository-helpers/scripts/setup-service
```

This will:

1. Read `etc/systemd/bunnify.service`, substitute `@@REPO_DIR@@`, inject `ConditionHost=|` guards, and install under `~/.config/systemd/user/`.
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

- **Service stdout/stderr:** `~/scratch/bunnify/bunnify.log` (systemd capture; HTTP access lines)
- **Application log:** `~/scratch/bunnify/data/bunnify.log` (Django rotating handler)

```bash
tail -f ~/scratch/bunnify/bunnify.log
tail -f ~/scratch/bunnify/data/bunnify.log
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

### Hardening

The unit sets `NoNewPrivileges=true` and `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6`. Neither needs privileges or a mount namespace, so they should work in a user unit on any host with the usual seccomp support (standard kernels and systemd builds; some containers and older kernels lack it): the service can never gain privileges, and it can only open Unix, IPv4 and IPv6 sockets, which is all the server's own code uses (the listener, `api.github.com` and `pypi.org` over HTTPS, and the health check). That was checked against the server code only (it uses the `socket` module and `urllib`; a search finds no `AF_NETLINK`, packet or raw sockets), not against every library or helper process: if the service, a library or a helper process it runs ever needs another family, such as `AF_NETLINK`, what breaks depends on the caller (an error, or quiet degradation), so check `journalctl --user -u bunnify` and add the family to `RestrictAddressFamilies`.

`ProtectSystem=`, `ProtectHome=` and `PrivateTmp=` are deliberately not set. In a user unit they need unprivileged user namespaces, which some hosts disable or restrict (Ubuntu 24.04 does by default, and the unit then fails with `status=226/NAMESPACE`), and `ProtectHome=` would hide the data, logs and bookmarks the service keeps under `$HOME`. `CapabilityBoundingSet=` is also left out: an unprivileged service's effective and permitted capability sets are already empty, and `NoNewPrivileges=true` stops it gaining any, so it would add little. If your host supports namespaces and you want more, add `ProtectSystem=full` first (it makes `/usr`, `/boot`, `/efi` and `/etc` read-only, which this service never writes to) and check `journalctl --user -u bunnify` after restarting.

After changing the unit, re-run `setup-service` (restarting alone does not install the edited template), then check that the server still starts and answers: `curl --silent --fail --max-time 5 http://127.0.0.1:8001/health`, and look at `journalctl --user -u bunnify` if it does not.

## Uninstall

```bash
systemctl --user stop    bunnify
systemctl --user disable bunnify
rm ~/.config/systemd/user/bunnify.service
rm -f ~/.config/share/systemd-units/bunnify.service
systemctl --user daemon-reload
```

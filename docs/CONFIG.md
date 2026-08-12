# Bunnify configuration

`bunnify.json.example` is the template for creating your personal bookmarks file.

## XDG layout

Bunnify stores user configuration under `$XDG_CONFIG_HOME/bunnify`, defaulting
to `~/.config/bunnify` when `XDG_CONFIG_HOME` is unset:

- `bookmarks.json` contains personal shortcuts (required before server start).
- `config.env` contains persistent CLI server preferences:
  `BUNNIFY_MODE`, `BUNNIFY_BASE_URL`, and `BUNNIFY_LOCAL_PORT`.
- `run/` contains PID and selected-port files for the CLI-managed local server.

Create `bookmarks.json` manually — the server does not auto-migrate from legacy
paths or seed the example file. These files are user data and are not tracked
by Git.

## Setup

```bash
mkdir -p ~/.config/bunnify
cp bunnify.json.example ~/.config/bunnify/bookmarks.json
```

Run `bunnify setup` to write verified settings. Existing base-URL-only files
remain supported; they are interpreted as remote mode.

## Migrating from a git checkout

See [MIGRATING.md](MIGRATING.md).

## Environment variables

- `XDG_CONFIG_HOME` changes the configuration root.
- `BUNNIFY_BOOKMARKS` overrides the bookmarks file path.
- `BUNNIFY_BASE_URL` overrides the server URL.
- `BUNNIFY_LOCAL_PORT` remembers the managed local server's listening port.
- `BUNNIFY_MODE` selects `local` or `remote`.
- `BUNNIFY_EDIT_MODE` selects `vim` or `emacs` CLI editing keys.
- `BUNNIFY_LOG_LEVEL`, `BUNNIFY_LOG_CONSOLE`, and `BUNNIFY_LOG_FILE` configure
  server logging.

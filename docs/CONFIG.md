# Bunnify configuration

`bunnify.json.example` is the seed used when no existing bookmarks can be migrated.

## XDG layout

Bunnify stores user configuration under `$XDG_CONFIG_HOME/bunnify`, defaulting
to `~/.config/bunnify` when `XDG_CONFIG_HOME` is unset:

- `bookmarks.json` contains personal shortcuts.
- `config.env` contains persistent CLI server preferences:
  `BUNNIFY_MODE`, `BUNNIFY_BASE_URL`, and `BUNNIFY_LOCAL_PORT`.
- `run/` contains PID and selected-port files for the CLI-managed local server.

The server creates `bookmarks.json` from the packaged example on first use.
These files are user data and are not tracked by Git.

## Migration

When the XDG bookmarks file does not exist, non-interactive startup copies
`~/work/bunnify/bunnify.json` if that legacy file exists. Interactive callers
may instead copy it, symlink it, or seed the example. The previously tracked
repository-root `bunnify.json` has been removed; copy any personal version to
`~/.config/bunnify/bookmarks.json` or set `BUNNIFY_BOOKMARKS`.

Run `bunnify setup` to write verified settings. Existing base-URL-only files
remain supported; they are interpreted as remote mode.

## Environment variables

- `XDG_CONFIG_HOME` changes the configuration root.
- `BUNNIFY_BOOKMARKS` overrides the bookmarks file path.
- `BUNNIFY_BASE_URL` overrides the server URL.
- `BUNNIFY_LOCAL_PORT` remembers the managed local server's listening port.
- `BUNNIFY_MODE` selects `local` or `remote`.
- `BUNNIFY_EDIT_MODE` selects `vim` or `emacs` CLI editing keys.
- `BUNNIFY_LOG_LEVEL`, `BUNNIFY_LOG_CONSOLE`, and `BUNNIFY_LOG_FILE` configure
  server logging.

# Bunnify configuration

`bunnify.json.example` is the seed used when no existing bookmarks can be migrated.

## XDG layout

Bunnify stores user configuration under `$XDG_CONFIG_HOME/bunnify`, defaulting
to `~/.config/bunnify` when `XDG_CONFIG_HOME` is unset:

- `bookmarks.json` contains personal shortcuts.
- `config.env` contains persistent CLI settings such as `BUNNIFY_BASE_URL`.

The server creates `bookmarks.json` from the packaged example on first use.
These files are user data and are not tracked by Git.

## Migration

When the XDG bookmarks file does not exist, non-interactive startup copies
`~/work/bunnify/bunnify.json` if that legacy file exists. Interactive callers
may instead copy it, symlink it, or seed the example. The previously tracked
repository-root `bunnify.json` has been removed; copy any personal version to
`~/.config/bunnify/bookmarks.json` or set `BUNNIFY_BOOKMARKS`.

For the server URL, Bunnify reads the XDG `config.env` first and falls back to
the legacy repository-root `bunnify.env`.

## Environment variables

- `XDG_CONFIG_HOME` changes the configuration root.
- `BUNNIFY_BOOKMARKS` overrides the bookmarks file path.
- `BUNNIFY_BASE_URL` overrides the server URL.
- `BUNNIFY_EDIT_MODE` selects `vim` or `emacs` CLI editing keys.
- `BUNNIFY_LOG_LEVEL`, `BUNNIFY_LOG_CONSOLE`, and `BUNNIFY_LOG_FILE` configure
  server logging.

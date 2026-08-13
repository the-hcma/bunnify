# Bunnify configuration

`bunnify.json.example` (and the packaged `app/data/bookmarks.example.json`) is
the template for creating your personal bookmarks file. It ships Google
properties (Search, Gmail, Calendar, YouTube, Drive, Docs, and related),
generic GitHub shortcuts, and a `bun` key for this repository’s source.

## XDG layout

Bunnify stores user configuration under `$XDG_CONFIG_HOME/bunnify`, defaulting
to `~/.config/bunnify` when `XDG_CONFIG_HOME` is unset:

- `bookmarks.json` contains personal shortcuts (required before server start).
- `config.env` contains persistent CLI server preferences:
  `BUNNIFY_MODE`, `BUNNIFY_BASE_URL`, and `BUNNIFY_LOCAL_PORT`.
- `run/` contains PID and selected-port files for the CLI-managed local server.

These files are user data and are not tracked by Git.

## Setup

When `bookmarks.json` is missing, interactive `bunnify setup` (and other
prompting CLI paths) offer to install the example bookmarks in the correct
location. Decline that prompt if you prefer to create the file yourself:

```bash
mkdir -p ~/.config/bunnify
curl -fsSL https://raw.githubusercontent.com/the-hcma/bunnify/main/bunnify.json.example \
  -o ~/.config/bunnify/bookmarks.json
```

In a development checkout you can instead `cp bunnify.json.example` from the
repo root.

Non-interactive starts (`bunnify-server --noninteractive`, CI, etc.) never
seed automatically — create the file first.

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

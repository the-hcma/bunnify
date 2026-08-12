# Chrome search engine setup

Configure Bunnify as a Chrome search engine for fast bookmark access from the
address bar.

**Prerequisites:** Bunnify server running (via `bunnify setup`, `bunnify-server`,
or a remote `BUNNIFY_BASE_URL`). `bunnify setup` prompts for a local port and
saves the verified base URL to `~/.config/bunnify/config.env` as
`BUNNIFY_BASE_URL`.

Read your base URL (use it in the steps below instead of hard-coded `:8000`):

```bash
grep '^BUNNIFY_BASE_URL=' ~/.config/bunnify/config.env | cut -d= -f2-
```

## Recommended: manual OpenSearch URL

1. Open `chrome://settings/searchEngines`
2. Add a site search entry:
   - **Search engine:** `Bunnify`
   - **Keyword:** `b` (or your preference)
   - **URL:** `<BUNNIFY_BASE_URL>/search/?q=%s` (no trailing slash on the base)
3. Optional: set as default search engine

Examples in the address bar (with keyword `b`):

- `b c` → calendar shortcut
- `b gh` → GitHub
- `b g python` → Google search via `g` shortcut
- `b pr 12345` → parameterized PR shortcut

## Automatic detection

1. Start the server
2. Visit `<BUNNIFY_BASE_URL>/` in Chrome (same value as above)
3. Chrome may offer to add the engine from `/opensearch.xml`

Manual setup is more reliable across Chrome versions.

## IPv6 / localhost

If your server listens on a non-default host or port, adjust URLs accordingly.
Re-run `bunnify setup` to change the saved port, or edit `BUNNIFY_BASE_URL` in
`~/.config/bunnify/config.env`.

## Development checkout

Use the same URLs; start the server with:

```bash
./scripts/bunnify-server --console
```

## Troubleshooting

- **Engine missing:** visit the home page while the server is running
- **404 on search:** confirm `<BUNNIFY_BASE_URL>/health` returns `ok`
- **Wrong port:** read `BUNNIFY_BASE_URL` / `BUNNIFY_LOCAL_PORT` in
  `config.env`, or `.bunnify.port` under the managed run directory

More: [README](README.md), [docs/LOCAL.md](docs/LOCAL.md)

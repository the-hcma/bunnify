# Chrome search engine setup

Configure Bunnify as a Chrome search engine for fast bookmark access from the
address bar.

**Prerequisites:** Bunnify server running (via `bunnify setup`, `bunnify-server`,
or a remote `BUNNIFY_BASE_URL`). Default local URL: `http://127.0.0.1:8000`.

## Recommended: manual OpenSearch URL

1. Open `chrome://settings/searchEngines`
2. Add a site search entry:
   - **Search engine:** `Bunnify`
   - **Keyword:** `b` (or your preference)
   - **URL:** `http://127.0.0.1:8000/search/?q=%s`
3. Optional: set as default search engine

Examples in the address bar (with keyword `b`):

- `b c` → calendar shortcut
- `b gh` → GitHub
- `b g python` → Google search via `g` shortcut
- `b pr 12345` → parameterized PR shortcut

## Automatic detection

1. Start the server
2. Visit `http://127.0.0.1:8000/` in Chrome
3. Chrome may offer to add the engine from `/opensearch.xml`

Manual setup is more reliable across Chrome versions.

## IPv6 / localhost

If your server listens on a non-default host or port, adjust URLs accordingly.
Check `BUNNIFY_BASE_URL` in `~/.config/bunnify/config.env` after `bunnify setup`.

## Development checkout

Use the same URLs; start the server with:

```bash
./scripts/bunnify-server --console
```

## Troubleshooting

- **Engine missing:** visit the home page while the server is running
- **404 on search:** confirm `/health` returns `ok`
- **Wrong port:** read `.bunnify.port` under the managed run directory or
  `config.env` for the saved port

More: [README](README.md), [docs/LOCAL.md](docs/LOCAL.md)

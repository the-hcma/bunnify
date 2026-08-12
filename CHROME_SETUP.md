# Chrome / Edge search engine setup

Configure Bunnify as a Chrome or Edge search engine for fast bookmark access
from the address bar. Both browsers use the same OpenSearch / site-search URL
pattern.

**Prefer local on a laptop.** Point the browser at the same machine’s managed
server (`bunnify setup` → **local**). Use a remote URL only when you intentionally
share a centralized/home-server install — and keep that host reachable whenever
you use the address bar.

**Prerequisites:** Bunnify server running (local `bunnify-server` / `bunnify setup`,
or a reachable remote). Setup saves the verified base URL to
`~/.config/bunnify/config.env` as `BUNNIFY_BASE_URL`. The browser search-engine
URL must match that value; if you change mode or port, update the engine too.

Read your base URL (use it in the steps below instead of hard-coded `:8000`):

```bash
grep '^BUNNIFY_BASE_URL=' ~/.config/bunnify/config.env | cut -d= -f2-
```

## Recommended: manual OpenSearch URL

1. Open search-engine settings:
   - Chrome: `chrome://settings/searchEngines`
   - Edge: `edge://settings/searchEngines`
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
2. Visit `<BUNNIFY_BASE_URL>/` in Chrome or Edge (same value as above)
3. The browser may offer to add the engine from `/opensearch.xml`

Manual setup is more reliable across browser versions.

## IPv6 / localhost

If your server listens on a non-default host or port, adjust URLs accordingly.
Re-run `bunnify setup` to change the saved port, or edit `BUNNIFY_BASE_URL` in
`~/.config/bunnify/config.env`, then update the Chrome search-engine URL to match.

## Development checkout

Use the same URLs; start the server with:

```bash
./scripts/bunnify-server --console
```

## Troubleshooting

- **Engine missing:** visit the home page while the server is running
- **404 on search:** confirm `<BUNNIFY_BASE_URL>/health` returns `ok`
- **Wrong port / remote down:** Chrome keeps a fixed URL. Align it with
  `BUNNIFY_BASE_URL` in `config.env`, or switch to **local** with
  `bunnify setup` and update the engine. There is no automatic remote→local
  fallback in the CLI or the browser.

More: [README](README.md), [docs/LOCAL.md](docs/LOCAL.md)

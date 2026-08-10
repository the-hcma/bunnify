# ⚡ Quick Reference Card

## Chrome Setup (One-time)

### Manual Method (2 minutes):
1. Open `chrome://settings/searchEngines`
2. Click "Add" under "Site search"
3. Fill in:
   - **Name:** `Bookmarks`
   - **Keyword:** `b` (or your choice)
   - **URL:** `http://127.0.0.1:8000/%s/`
4. Click "Add"

### Automatic Method:
1. Visit `http://127.0.0.1:8000/` in Chrome
2. Chrome auto-detects the search engine
3. Check `chrome://settings/searchEngines` to verify

---

## Daily Usage

### In Chrome Address Bar:

**Simple Bookmarks:**
```
b c           → Calendar
b m           → Gmail
b vault       → Vault
b slack       → Slack
b gpt         → ChatGPT
```

**With One Parameter:**
Create these additional search engines:

| Keyword | URL Pattern | Example |
|---------|-------------|---------|
| `pr` | `http://127.0.0.1:8000/pr/?pr_id=%s` | `pr 12345` |
| `cm` | `http://127.0.0.1:8000/cw/?commit_id=%s` | `cm abc123` |
| `bmg` | `http://127.0.0.1:8000/g/?search_terms=%s` | `bmg django` |

---

## All Available Bookmarks (55 total)

### Most Common:
- `c` - Calendar
- `m` - Gmail  
- `slack` - Slack
- `gpt` - ChatGPT
- `vault` - Vault
- `pr` - Pull Request (needs `?pr_id=`)
- `w` - shop/world repo
- `mq` - Merge Queue

### View Full List:
`http://127.0.0.1:8000/list/`

---

## Server Management

**Start server:**
```bash
./scripts/bunnify-server
```

**Reload bookmarks:**
```bash
uv run python manage.py load_bookmarks
```

**Check if running:**
```bash
curl http://127.0.0.1:8000/c/
```

---

## Tips

✨ **Pro Tip:** Set up multiple Chrome search engines for your most-used parameterized bookmarks!

🔍 **Search bookmarks:** Visit `/list/` and use the search box

⚡ **Lightning fast:** `b vault` is faster than typing the full URL or clicking bookmarks!

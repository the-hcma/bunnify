# 🔍 Chrome Search Engine Setup Guide

Configure Bunnify as your primary Chrome search engine for ultra-fast bookmark access!

## ⭐ Recommended Method: OpenSearch (Works for ALL bookmarks)

This method automatically handles all your bookmarks - simple ones and parameterized ones.

### Step 1: Start the Server
```bash
./bunnify-server --bookmarks bunnify.json --console
```

### Step 2: Add to Chrome

Go to `chrome://settings/searchEngines` and add a new search engine:

**Fill in these fields:**
- **Search engine:** `Bunnify`
- **Keyword:** `b` (or your preference)
- **URL with %s in place of query:**
  ```
  http://127.0.0.1:8000/search/?q=%s
  ```

### Step 3: Set as Default (Optional)
1. Go back to `chrome://settings/searchEngines`
2. Find "Bunnify"
3. Click the three dots (⋮)
4. Select "Make default"

Now you can use it from Chrome's address bar:
- Type `c` → Opens Calendar
- Type `gh` → Opens GitHub
- Type `g django` → Google search for "django"
- Type `pr 12345` → Opens PR #12345 (with proper parameters)

---

## Alternative Method: Automatic Detection (Optional)

If you prefer, Chrome can auto-detect Bunnify:

1. Make sure the server is running: `./bunnify-server`
2. Open Chrome and visit: `http://127.0.0.1:8000/`
3. Chrome will automatically detect the OpenSearch descriptor

Chrome should offer to add it - but the manual method above is more reliable.

---

## Legacy Method: Manual Setup (Not Recommended)
### Step 1: Open Chrome Settings
1. Open Chrome
2. Go to `chrome://settings/searchEngines`
3. Click "Add" under "Site search"

### Step 2: Configure Search Engine

Fill in these fields:

**Search engine:**
```
Bunnify (Manual)
```

**Shortcut/Keyword:**
```
b
```
(You can use any keyword you prefer)

**URL with %s in place of query:**
```
http://127.0.0.1:8000/search/?q=%s
```

### Step 3: Click "Add"

This is the same setup as the recommended method above.

---

## Troubleshooting

### Search engine not appearing
- Make sure server is running: `./bunnify-server --bookmarks bunnify.json --console`
- Check the server is responding: Visit `http://127.0.0.1:8000/` in your browser
- Manual setup (above) always works if auto-detection fails

### Bookmarks not found
- Visit `http://127.0.0.1:8000/list/` to see all loaded bookmarks
- Make sure your `bunnify.json` is being loaded correctly
- Check the server console for errors

### OpenSearch XML not loading
- Visit: `http://127.0.0.1:8000/opensearch.xml`
- Should see XML with search configuration
- If it shows an error, restart the server

---

## 🚀 Usage Examples

Once configured, use from Chrome's address bar:

### Simple Bookmarks
- `b c` → Opens Google Calendar
- `b gh` → Opens GitHub
- `b slack` → Opens Slack (if configured)

### With Parameters
- `b g django tutorials` → Google search for "django tutorials"
- `b pr 12345` → Opens PR #12345
- `b commit abc123` → Opens commit abc123

---

## Pro Tips

### 1. Single Key Shortcuts
You can skip the `b` keyword entirely! Go to `chrome://settings/searchEngines` and:
1. Find your Bunnify search engine
2. Change the keyword to just a single letter (like `g` or `c`)
3. Now type just `c` → Calendar (no need for `b c`)

### 2. See All Your Bookmarks
Visit `http://127.0.0.1:8000/list/` to see all available bookmarks and their keys.

---

## For Production Deployment

If you deploy Bunnify to a server (e.g., `bookmarks.company.com`), update the URL:

```
http://bookmarks.company.com/search/?q=%s
```

---

**Enjoy lightning-fast bookmark access! ⚡**

# Bunnify 🐰

A powerful Python-based bookmark manager and URL shortcut system with advanced command palette, Chrome integration, and real-time GitHub Copilot code reviews.

## Prerequisites

- **Python 3.14+**
- **[uv](https://docs.astral.sh/uv/)** - Fast Python package manager

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Features

### Core Functionality
- **Smart Search**: Type "pr 12345" or "g search terms" directly in your browser
- **Dynamic URL Redirects**: Navigate to `/<key>/` to be redirected to the bookmark's URL
- **Parameter Substitution**: Supports URLs with placeholders (e.g., `#{pr_number}`, `#{search_terms}`)
- **Multi-Parameter Support**: Bookmarks can accept multiple parameters with optional defaults
- **JSON Schema Validation**: Validates the bookmark JSON file before loading
- **Web Interface**: Browse all bookmarks with search and filtering

### Command Palette (`/cmd/`)
- **Tab Completion**: Auto-complete shortcuts and commands
- **Command History**: Navigate previous commands with ↑/↓ arrows
- **Filtered History**: Type a prefix and use arrows to filter history
- **Reverse Search (Ctrl-R)**: Bash-style interactive history search
- **Special Commands**: Built-in shortcuts like `h` (help) to list all bookmarks
- **Autocomplete Suggestions**: Real-time suggestions as you type
- **Opens in New Tab**: All commands open in new tabs for quick workflows

### Chrome Integration
- **OpenSearch API**: Add Bunnify as a search engine in Chrome
- **Address Bar Suggestions**: Auto-complete suggestions in Chrome's omnibox
- **Seamless Navigation**: Type shortcuts directly in the address bar

### GitHub Copilot Integration
- **PR Code Reviews**: Use the `rpr` shortcut to request Copilot reviews on PRs
- **Streaming Responses**: Real-time progress updates during review generation
- **Private Reviews**: Reviews displayed in-app without public PR comments

### Infrastructure
- **Dual-Stack Networking**: IPv4 and IPv6 support (accessible via 127.0.0.1, [::1], or localhost)
- **Comprehensive Logging**: Detailed logs with PID/function/line numbers to `/tmp/bunnify.log`
- **File Watching**: Auto-reload bookmarks when JSON file changes
- **Daemonization**: Background process management with proper cleanup

## Quick Start

### 1. Clone and Setup

```bash
# Clone the repository
git clone https://github.com/thehcma/bunnify.git
cd bunnify

# Install dependencies with uv
uv sync

# Run migrations
uv run python manage.py migrate

# Create your bookmarks file
mkdir -p ~/work/bunnify
cp bunnify.json.example ~/work/bunnify/bunnify.json
# Edit ~/work/bunnify/bunnify.json with your bookmarks

# Load bookmarks
uv run python manage.py load_bookmarks
```

### 2. Start the Server

**Always use the bunnify-server script** to ensure proper setup:
```bash
./bunnify-server
```

This will:
- Start the server on port 8000 (dual-stack IPv4/IPv6 binding)
- Start the bookmark file watcher for auto-reload
- Daemonize both processes
- Show URLs for access

**Logging options:**
```bash
./bunnify-server --console          # Log to console instead of file
./bunnify-server --log-level DEBUG  # Change log level
./bunnify-server --help            # Show all options
```

**Note:** The bunnify-server script uses dual-stack binding (`[::]:8000`), making the server accessible via IPv4, IPv6, and localhost.

### 3. Access Bunnify

The server is accessible at:
- `http://127.0.0.1:8000/` (IPv4)
- `http://[::1]:8000/` (IPv6)
- `http://localhost:8000/` (auto)

### 4. Chrome Browser Integration

**Set up Bunnify as a search engine in Chrome:**

1. Visit `http://127.0.0.1:8000/` (or `http://[::1]:8000/` for IPv6) while the server is running
2. Go to Chrome Settings → Search engine → Manage search engines
3. Find "Bunnify" (added automatically via OpenSearch) or add manually:
   - **Search engine:** Bunnify
   - **Shortcut:** `s` (or any letter you prefer)
   - **URL (IPv4):** `http://127.0.0.1:8000/search/?q=%s`
   - **URL (IPv6):** `http://[::1]:8000/search/?q=%s`
   - **URL (localhost):** `http://localhost:8000/search/?q=%s`
4. Save

**Note:** Choose the URL that matches how you're running the server:
- Use IPv4 (`127.0.0.1`) if running with `127.0.0.1:8000`
- Use IPv6 (`[::1]`) if you prefer IPv6-only access
- Use `localhost` if running with `[::]:8000` (dual-stack) - Chrome will auto-select

**Optional: Set as Default Search Engine**
- Click the three dots next to "Bunnify" and select "Make default"
- Now you can type bookmarks directly without any prefix!

### 5. Persistent Bunnify Service (Linux)

To ensure Bunnify runs automatically across reboots and remains persistent even when you are logged out, you can set it up as a systemd user service.

1.  **Enable lingering** for your user (required for the service to run without an active session):
    ```bash
    sudo loginctl enable-linger $USER
    ```

2.  **Create the systemd user directory** (if it doesn't exist):
    ```bash
    mkdir -p ~/.config/systemd/user/
    ```

3.  **Symlink the service unit** to the systemd directory:
    ```bash
    ln -s ~/work/ai/bunnify/scripts/systemd/bunnify.service ~/.config/systemd/user/bunnify.service
    ```
    *Note: Adjust the path if your repository is located elsewhere.*

4.  **Manage the service**:
    ```bash
    # Reload systemd to recognize the new unit
    systemctl --user daemon-reload

    # Start and enable the service
    systemctl --user enable --now bunnify.service
    ```

### 6. Verification & Troubleshooting

To ensure the persistent service is running correctly:

1.  **Check Service Status**:
    ```bash
    systemctl --user status bunnify.service
    ```
    The status should be `active (running)`.

2.  **Verify Health Check**:
    ```bash
    # Run from the terminal to ensure the server is responsive
    curl http://localhost:8001/health
    ```
    *Expected output:* `ok`

3.  **Monitor Logs**:
    ```bash
    journalctl --user -u bunnify.service -f
    ```

4.  **Reset Failed State**:
    If the service fails to start multiple times (exceeding restart limits), it may enter a `failed` state. You can reset this with:
    ```bash
    systemctl --user reset-failed bunnify.service
    ```

## Usage

### Command Palette (Recommended)

Visit `http://127.0.0.1:8000/cmd/` for the enhanced command palette:

**Features:**
- **Type** to filter shortcuts with auto-complete
- **Tab** to complete suggestions
- **↑/↓** to navigate command history (with prefix filtering)
- **Ctrl-R** for bash-style reverse search through history
- **Enter** to execute (opens in new tab)
- **Esc** to cancel

**Examples:**
- Type `pr` then ↑ to see recent PR commands
- Type `pr` and ↑ to cycle through filtered history
- Press Ctrl-R and type `12345` to find commands with that PR number

### Browser Address Bar (with Chrome Integration)

Type in Chrome's address bar:
- `s pr 12345` → Opens PR #12345
- `s g python tutorial` → Google search for "python tutorial"
- `s vault` → Opens Vault
- `s h` → Shows all bookmarks

### Direct URL Access

**Simple redirects:**
- `http://127.0.0.1:8000/c/` → Google Calendar
- `http://127.0.0.1:8000/vault/` → Vault

**Parameterized redirects:**
- `http://127.0.0.1:8000/pr/?pr_id=12345` → PR #12345
- `http://127.0.0.1:8000/g/?search_terms=python+tutorial` → Google search

**Special endpoints:**
- `http://127.0.0.1:8000/list/` → Browse all bookmarks
- `http://127.0.0.1:8000/cmd/` → Command palette
- `http://127.0.0.1:8000/review-pr/?pr=12345` → Request Copilot review

## JSON File Format

The application expects a JSON file with the following structure:

```json
{
    "key": {
        "description": "Description of the bookmark",
        "url": "https://example.com/path",
        "old-url": "https://old-url.com/path"  // optional
    }
}
```

### Parameterized URLs

URLs can contain placeholders in the format `#{parameter_name}`:

**Single Parameter:**
```json
{
    "g": {
        "description": "Google search",
        "url": "https://www.google.com/search?q=#{search_terms}"
    }
}
```
Usage: `g python tutorial` → `https://www.google.com/search?q=python+tutorial`

**Multiple Parameters with Defaults:**
```json
{
    "pr": {
        "description": "GitHub Pull Request",
        "url": "https://github.com/#{repo}/pull/#{pr_number}",
        "defaults": {
            "repo": "your-org/your-repo"
        }
    }
}
```
Usage:
- `pr 12345` → Uses default repo → `https://github.com/your-org/your-repo/pull/12345`
- `pr 12345 Shopify/shopify-build` → Overrides default → `https://github.com/Shopify/shopify-build/pull/12345`

**Parameter Order:** Required parameters (no defaults) are mapped first, then optional parameters (with defaults).

## Project Structure

```
bunnify/
├── bookmarks/
│   ├── management/
│   │   └── commands/
│   │       └── load_bookmarks.py    # Command to load JSON data
│   ├── templates/
│   │   └── bookmarks/
│   │       ├── base.html            # Base template
│   │       ├── index.html           # Home page
│   │       ├── list.html            # Bookmark list
│   │       └── opensearch.xml       # OpenSearch descriptor
│   ├── models.py                    # Bookmark model
│   ├── views.py                     # View logic (includes search_redirect)
│   └── urls.py                      # URL routing
├── bunnify/
│   ├── settings.py                  # Application settings
│   └── urls.py                      # Main URL config
├── .venv/                           # Virtual environment (managed by uv)
├── manage.py                        # Management script
└── pyproject.toml                   # Project dependencies
```

## Schema Validation

The `load_bookmarks` command validates the JSON file against a schema that ensures:
- All keys match the pattern `^[a-zA-Z0-9_]+$`
- Each bookmark has required fields: `description` and `url`
- Optional fields: `old-url` or `oldurl`
- **Reserved keywords** "h" and "help" are blocked and will cause an error

## API Endpoints

- `GET /` - Home page with usage instructions
- `GET /search/?q=<query>` - Smart search endpoint (e.g., "pr 12345")
- `GET /list/` - List all bookmarks with search
- `GET /<key>/` - Redirect to bookmark URL
  - With parameters: `GET /<key>/?param1=value1&param2=value2`
- `GET /opensearch.xml` - OpenSearch descriptor for browser integration

## Reserved Keywords

The following keywords are reserved and cannot be used as bookmark keys:
- `h` - Shows all bookmarks (help shortcut)
- `help` - Shows all bookmarks (help shortcut)

## Development

### Running Tests

The project includes comprehensive smoke tests that verify core functionality.

**Run all tests:**
```bash
./test_bunnify
```

**Run specific test suite:**
```bash
# Run only smoke tests
./test_bunnify bookmarks.tests.SmokeTests

# Run with verbose output
./test_bunnify -v 2

# Run a specific test
./test_bunnify bookmarks.tests.SmokeTests.test_search_with_parameter
```

**Test coverage includes:**
- Page loading (index, list, command palette, OpenSearch XML)
- Search redirects with/without parameters
- Parameter substitution in URLs
- Direct bookmark redirects
- Help command functionality
- API suggestions endpoint
- Model methods and ordering
- Error handling (404, 400)

### Creating a Superuser

```bash
uv run python manage.py createsuperuser
```

Then access the admin interface at `http://127.0.0.1:8000/admin/`

### Reloading Bookmarks

To reload bookmarks after updating your JSON file:

```bash
uv run python manage.py load_bookmarks
```

This will clear existing bookmarks and load fresh data.

## Technologies Used

- **Django 6.0**: Web framework
- **jsonschema**: JSON validation
- **SQLite**: Database (default storage)
- **Python 3.14**: Programming language with type hints
- **uv**: Fast Python package manager
- **pathlib**: Modern file path handling
- **OpenSearch**: Browser integration protocol
- **localStorage**: Client-side command history
- **Streaming responses**: Real-time progress updates

## Project Structure

```
bunnify/
├── bookmarks/              # Core application logic
│   ├── management/
│   │   └── commands/      # Management commands
│   │       ├── load_bookmarks.py    # Load bookmarks from JSON
│   │       └── watch_bookmarks.py   # Auto-reload on file changes
│   ├── templates/         # HTML templates
│   │   └── bookmarks/
│   │       ├── cmd.html              # Command palette
│   │       ├── list.html             # Browse bookmarks
│   │       ├── opensearch.xml        # Chrome integration
│   │       └── copilot_review.html   # Copilot review UI
│   ├── models.py          # Bookmark model
│   ├── views.py           # View functions
│   └── urls.py            # URL routing
├── bunnify/               # Main configuration directory
│   ├── settings.py        # Configuration with logging
│   └── urls.py            # Root URL configuration
├── scripts/               # Helper scripts
│   ├── get_copilot_review.sh        # Copilot review helper
│   └── request_copilot_review.sh    # Legacy review script
├── manage.py              # Management script
├── start                  # Server startup script
├── requirements.txt       # Python dependencies
└── bunnify.json.example   # Example bookmark configuration
```

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Author

**thehcma** - [GitHub](https://github.com/thehcma)

## Acknowledgments

- Built with Django and modern Python features
- Inspired by browser bookmark management needs
- Enhanced with GitHub Copilot integration for code reviews

## Tips & Tricks

1. **Quick Access**: Set Bunnify as your default search engine for the fastest access
2. **Discover Bookmarks**: Type `h` to quickly see all available shortcuts
3. **Parameterized Shortcuts**: For frequently used parameterized bookmarks (like `pr`), you can create individual Chrome search engines for even faster access
4. **Auto-start**: Run `scripts/setup-service` to configure Bunnify as a persistent systemd service.


## Persistent Background Service

For production-like use, you should run Bunnify as a systemd user service. This ensures it starts on boot and restarts automatically if it crashes.

### Automated Setup

We provide a script to automate the systemd configuration and enable lingering:

```bash
./scripts/setup-service
```

### Manual Verification

You can check the service status with:

```bash
systemctl --user status bunnify.service
```

### Lingering

To ensure the service runs even when you are not logged in, lingering must be enabled (the setup script does this for you):

```bash
loginctl enable-linger $(whoami)
```

## Troubleshooting

### Server won't start
```bash
# Make sure you're in the right directory
cd ~/work/ai/bunnify

# Use the bunnify-server script
./bunnify-server
```

### Bookmarks not loading
```bash
# Check if the JSON file exists and is valid
cat ~/work/bunnify/bunnify.json

# Reload bookmarks
uv run python manage.py load_bookmarks
```

### Chrome not detecting Bunnify
1. Make sure the server is running at `http://127.0.0.1:8000/`
2. Visit the homepage to trigger OpenSearch detection
3. Manually add the search engine with URL: `http://127.0.0.1:8000/search/?q=%s`

## License

This project is created for managing bookmarks efficiently. 🐰✨

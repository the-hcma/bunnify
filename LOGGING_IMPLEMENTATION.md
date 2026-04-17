# Bunnify Logging Implementation

## Overview
Comprehensive logging has been implemented across the Bunnify bookmark manager to provide operational visibility and debugging capabilities.

## Configuration

### Log File Location
- **Default**: `/tmp/bunnify.log`
- **Rotation**: 10MB max size per file, 5 backup files maintained
- **Format**: `[timestamp] [level] [PID:process_id] [module:function:line] message`

### Log Levels
- **Default**: WARNING
- **Available levels**: DEBUG, INFO, WARNING, ERROR, CRITICAL

### Environment Variables
- `BUNNIFY_LOG_LEVEL`: Sets the logging level (default: WARNING)
- `BUNNIFY_LOG_CONSOLE`: Enable console output (default: false)

## Usage

### Command Line Options

#### Start with default settings (WARNING level, file only)
```bash
./bunnify-server
```

#### Start with console output
```bash
./bunnify-server --console
```

#### Start with specific log level
```bash
./bunnify-server --log-level DEBUG
./bunnify-server --log-level INFO
./bunnify-server --log-level WARNING
./bunnify-server --log-level ERROR
```

#### Combine options
```bash
./bunnify-server --console --log-level DEBUG
```

## What's Logged

### Views (bookmarks/views.py)
- **search_redirect**: Query handling, bookmark lookups, help redirects
- **redirect_bookmark**: Direct bookmark access, parameter substitution, special URLs
- **list_bookmarks**: Bookmark listing requests with count
- **cmd_palette**: Command palette requests with count
- **index**: Home page requests
- **opensearch**: OpenSearch XML requests
- **bookmark_status**: Status check requests with hash

### Management Commands

#### load_bookmarks
- File loading start
- JSON validation (start and completion)
- Reserved keyword violations
- Clearing existing bookmarks
- Individual bookmark creation (at DEBUG level)
- Final count of loaded bookmarks
- Errors (file not found, JSON decode, validation, unexpected)

#### watch_bookmarks
- File watcher initialization
- Initial file hash
- File change detection with hash values
- Bookmark reload initiation
- Reload success with count
- Reload errors with stack traces
- User interruption (Ctrl+C)

## Log Format Example

```
[2026-01-27 11:32:22] [INFO] [PID:33895] [bookmarks.management.commands.watch_bookmarks:handle:44] Starting file watcher for: /Users/hcma/work/bunnify/bunnify.json, interval: 2s
[2026-01-27 11:32:36] [INFO] [PID:33899] [bookmarks.views:redirect_bookmark:165] Direct bookmark redirect request: key='s'
[2026-01-27 11:32:36] [INFO] [PID:33899] [bookmarks.views:redirect_bookmark:193] Redirecting to: https://app.slack.com/client
[2026-01-27 11:33:09] [DEBUG] [PID:34836] [bookmarks.management.commands.watch_bookmarks:handle:59] Initial file hash: faff79d14c00979db11622f100f29c32
```

## Log Levels Guide

### DEBUG
- Use for: Detailed diagnostic information
- Examples: File hashes, parameter parsing, internal state
- Warning: Generates high volume of logs

### INFO
- Use for: General informational messages
- Examples: Request handling, successful operations
- Recommended for: Development and troubleshooting

### WARNING (Default)
- Use for: Unexpected situations that don't prevent operation
- Examples: Empty queries, missing bookmarks, invalid parameters
- Recommended for: Production

### ERROR
- Use for: Error conditions that prevent specific operations
- Examples: File not found, validation failures, reload errors
- Includes: Stack traces for unexpected exceptions

### CRITICAL
- Use for: System-level failures
- Examples: Configuration errors, database connection failures

## Viewing Logs

### Real-time monitoring
```bash
tail -f /tmp/bunnify.log
```

### Filter by log level
```bash
grep "\[ERROR\]" /tmp/bunnify.log
grep "\[WARNING\]" /tmp/bunnify.log
```

### View recent entries
```bash
tail -50 /tmp/bunnify.log
```

### Search for specific operations
```bash
grep "search_redirect" /tmp/bunnify.log
grep "File change detected" /tmp/bunnify.log
```

## Technical Details

### Configuration Location
- File: `bunnify/settings.py`
- Section: `LOGGING` dictionary at end of file

### Loggers Configured
- `bunnify`: Main application logger
- `bookmarks`: Bookmarks app logger
- `framework`: Core framework logger
- `root`: Catch-all logger

### Handlers
1. **file**: RotatingFileHandler to `/tmp/bunnify.log`
2. **console**: StreamHandler to stdout (conditional)

### Formatters
1. **verbose**: Includes PID, module, function, line number
2. **simple**: Basic level and message

## Benefits

1. **Operational Visibility**: Track all search queries and redirects
2. **Debugging**: Detailed context with PID, function, and line numbers
3. **Auto-reload Monitoring**: See exactly when bookmarks are reloaded
4. **Error Tracking**: Full stack traces for unexpected errors
5. **Performance**: File rotation prevents unlimited disk usage
6. **Flexibility**: Easy to adjust verbosity via command line

## Examples

### Development with full visibility
```bash
./bunnify-server --console --log-level DEBUG
```

### Production with quiet operation
```bash
./bunnify-server --log-level WARNING
```

### Troubleshooting specific issues
```bash
./bunnify-server --console --log-level INFO
# Then check /tmp/bunnify.log for details
```

# devpipe

Interactive browser monitoring and debugging toolkit for Chrome DevTools Protocol (CDP) based browsers.

## Features

- **Real-time Network Monitoring**: Track and deduplicate network requests with smart resource bundling
- **UI Click Scanner**: Automatically detect and log user interactions with full Shadow DOM support
- **Event-Driven Logging**: Efficient JSONL-based event logging with configurable output paths
- **WebRTC Privacy**: One-liner configuration for Brave browser WebRTC IP handling
- **Connection Management**: Robust CDP connection handling with reconnection support
- **Interactive CLI**: Pause/resume monitoring, switch between browser instances, create new logs on-the-fly

## Installation

### From PyPI (once published)

```bash
pip install devpipe
```

### Development Install (Editable)

From the parent directory containing `devpipe/`:

```bash
pip install -e devpipe/
```

Or from within the `devpipe/` directory:

```bash
pip install -e .
```

### From GitHub

```bash
pip install git+https://github.com/skyler14/devpipe.git
```

## Quick Start

### Command Line

```bash
# Connect to browser on CDP port 9222
devpipe --port 9222

# Or use short flag
devpipe -p 9223
```

### Interactive Commands

Once connected, you can use these commands:

- `run [prefix]` - Start or resume logging (optional: specify output file prefix)
- `wait` - Pause logging
- `new [prefix]` - Create a new log file and start logging
- `connect <port>` - Switch to a different CDP port
- `privacy` - Configure Brave WebRTC privacy settings
- `quit` - Exit the monitor

### Python API

```python
from devpipe import EventDrivenMonitor
import asyncio

async def main():
    monitor = EventDrivenMonitor(cdp_port=9222)
    await monitor.start()

asyncio.run(main())
```

### Standalone Components

Individual components can be imported and used independently:

```python
from devpipe.connection import CDPConnection
from devpipe.webrtcprivacy import configure_webrtc_privacy

# Connection management
conn = CDPConnection(cdp_port=9222)
await conn.connect()

# Configure WebRTC privacy
await configure_webrtc_privacy(page)
```

## Output Format

Logs are saved as JSONL files with the following event types:

### SESSION_START
```json
{
  "timestamp": "2025-10-03T10:30:00.123456",
  "type": "SESSION_START",
  "data": {"log_file": "/path/to/log.jsonl"}
}
```

### NETWORK_REQUEST (first occurrence)
```json
{
  "timestamp": "2025-10-03T10:30:01.234567",
  "type": "NETWORK_REQUEST",
  "data": {
    "requestId": "...",
    "method": "GET",
    "url": "https://example.com/api/data",
    "type": "XHR"
  }
}
```

### NETWORK_DIFF (subsequent similar requests)
```json
{
  "timestamp": "2025-10-03T10:30:02.345678",
  "type": "NETWORK_DIFF",
  "data": {
    "fingerprint": "GET::https://example.com/api/data",
    "method": "GET",
    "url": "https://example.com/api/data",
    "changes": {
      "root['request']['headers']['X-Request-ID']": "new-id-123"
    }
  }
}
```

### RESOURCE_BUNDLE (stylesheets, scripts, images, fonts)
```json
{
  "timestamp": "2025-10-03T10:30:03.456789",
  "type": "RESOURCE_BUNDLE",
  "data": {
    "scripts": [
      "https://cdn.example.com/app.js",
      "https://cdn.example.com/vendor.js"
    ],
    "stylesheets": [
      "https://cdn.example.com/main.css"
    ],
    "images": [
      "https://example.com/logo.png"
    ]
  }
}
```

### UI_CLICK
```json
{
  "timestamp": "2025-10-03T10:30:04.567890",
  "type": "UI_CLICK",
  "data": {
    "element_path": "nav > ul.menu > li.active > a",
    "target_text": "Dashboard",
    "document_url": "https://example.com/app",
    "tag_name": "a",
    "inner_content": [
      {"type": "text", "content": "Dashboard"},
      {"type": "link", "href": "/dashboard", "text": "Dashboard"}
    ]
  }
}
```

### PAGE_NAVIGATION
```json
{
  "timestamp": "2025-10-03T10:30:05.678901",
  "type": "PAGE_NAVIGATION",
  "data": {
    "url": "https://example.com/dashboard"
  }
}
```

## Architecture

### Network Deduplication

The `NetworkDeduplicator` class intelligently handles network traffic:

- **Fingerprinting**: Groups similar requests by method + URL (ignoring query params in fingerprint)
- **Diffing**: Only logs changes between similar requests using DeepDiff
- **Bundling**: Groups static resources (CSS, JS, images) into periodic bundles to reduce log noise
- **Simplification**: Truncates long values and removes verbose fields

### UI Click Scanner

The click scanner is resilient and supports:

- **Shadow DOM**: Penetrates shadow roots to detect clicks anywhere
- **Iframes**: Monitors cross-frame interactions (same-origin only)
- **Dynamic Content**: Observes DOM for new shadow roots and iframes
- **Rate Limiting**: Prevents log spam from rapid clicking (3 clicks per second max)
- **Rich Context**: Extracts links, forms, buttons, inputs, select dropdowns, checkboxes, and nested content

### Connection Resilience

The `CDPConnection` class provides:

- **Pre-flight Checks**: Validates browser accessibility before CDP connection
- **Graceful Errors**: Clear error messages with troubleshooting tips
- **Reconnection**: Easy switching between browser instances during runtime

## Browser Setup

The browser must be launched with CDP debugging enabled:

```bash
# Chrome/Chromium
google-chrome --remote-debugging-port=9222

# Brave
brave --remote-debugging-port=9222

# With specific profile
brave --remote-debugging-port=9222 --user-data-dir=/path/to/profile
```

## Use Cases

### Workflow Development
Monitor browser activity while developing automation scripts to understand:
- What network requests fire when you click a button
- How forms submit data
- What authentication tokens are used
- How SPAs navigate without page reloads

### Debugging
Troubleshoot issues by:
- Seeing exactly what changed in similar API requests
- Tracking UI interactions to replay user flows
- Monitoring WebRTC privacy to ensure no IP leaks

### Testing
Validate that:
- Expected network requests are made
- UI elements respond to interactions
- Navigation works correctly
- Resources load efficiently

## Requirements

- Python 3.8+
- playwright >= 1.40.0
- requests >= 2.31.0
- deepdiff >= 6.0.0

## Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

MIT License - see LICENSE file for details

## Author

Skyler Salebyan

## Acknowledgments

Built with:
- [Playwright](https://playwright.dev/) - Browser automation
- [DeepDiff](https://github.com/seperman/deepdiff) - Intelligent diffing
- Chrome DevTools Protocol

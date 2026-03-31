# mt-butterfly

Web service for chatting with OpenCode via web interface, managing multiple chat channels with independent OpenCode sessions, and scheduling periodic tasks that execute OpenCode prompts and email the results.

## Features

- **Setup Wizard**: Interactive first-run configuration
- **CLI Options**: Pass config via arguments, no wizard needed
- **Chat Interface**: Real-time WebSocket-based chat with OpenCode
- **Multiple Channels**: Each channel maintains its own OpenCode session/context
- **Scheduled Tasks**: Configure prompts to run on a schedule and receive results via email
- **Token Authentication**: Secure access via query string token

## Quick Start

### Installation

```bash
uv tool install git+https://github.com/lucha/mt-butterfly
```

### First Run

Run `mt-butterfly` — the setup wizard will guide you:

1. Generate or enter your AUTH_TOKEN
2. Set WORKSPACES_DIR (default: `~/mt-butterfly`)
3. Optionally configure Gmail for email notifications

The wizard creates the necessary directories automatically.

### CLI Options

```bash
mt-butterfly --token YOUR_TOKEN              # Skip wizard, use token
mt-butterfly -t YOUR_TOKEN -w /path         # Full config via args
mt-butterfly --config                        # Force wizard to run
mt-butterfly --clean-setup                   # Remove config file
```

All options:
- `-t, --token` — AUTH_TOKEN (required if no config exists)
- `-w, --workspaces-dir` — WORKSPACES_DIR
- `--gmail-user` — GMAIL_USER for email notifications
- `--gmail-password` — GMAIL_APP_PASSWORD

## Development

```bash
# Clone and install
uv sync

# Run tests
pytest tests/ -v

# Start dev server (skip wizard)
AUTH_TOKEN=dev-token python run.py
```

## Auto-start on Mac

```bash
cp extras/com.mt-butterfly.plist ~/Library/LaunchAgents/
# Edit the plist to replace USERNAME with your username
launchctl load ~/Library/LaunchAgents/com.mt-butterfly.plist
```

## Tech Stack

- FastAPI + Jinja2 templates + WebSockets
- SQLite + SQLAlchemy async
- APScheduler for task scheduling
- pytest + pytest-asyncio for testing

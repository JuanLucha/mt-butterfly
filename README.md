# mt-butterfly

Web service for chatting with OpenCode via web interface, managing multiple chat channels with independent OpenCode sessions, and scheduling periodic tasks that execute OpenCode prompts and email the results.

## Features

- **Chat Interface**: Real-time WebSocket-based chat with OpenCode
- **Multiple Channels**: Each channel maintains its own OpenCode session/context
- **Scheduled Tasks**: Configure prompts to run on a schedule and receive results via email
- **Token Authentication**: Secure access via query string token

## Quick Start

### Installation

```bash
uv tool install git+https://github.com/lucha/mt-butterfly
```

### Configuration

```bash
mkdir -p ~/Library/Application\ Support/mt-butterfly
cat > ~/Library/Application\ Support/mt-butterfly/.env <<EOF
AUTH_TOKEN=your-secret-token
GMAIL_USER=you@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
WORKSPACES_DIR=/Users/you/workspaces
EOF
```

### Run

```bash
mt-butterfly
```

Access at `http://localhost:8000/?t=your-secret-token`

## Development

```bash
# Clone and install
uv sync

# Run tests
pytest tests/ -v

# Start dev server
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

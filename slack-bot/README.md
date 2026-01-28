# IncidentFox Slack Bot

Slack bot for IncidentFox AI SRE agent using [Bolt framework](https://slack.dev/bolt-python/).

## Quick Start

```bash
cd slack-bot

# First time setup
make setup
source .venv/bin/activate
make install

# Configure
cp env.example .env
# Edit .env with your SLACK_BOT_TOKEN, SLACK_APP_TOKEN, SLACK_SIGNING_SECRET

# Run
make run
```

Or manually:

```bash
uv venv && source .venv/bin/activate
uv pip install -e .
cp env.example .env  # Edit with your tokens
python app.py
```

## Slack App Setup

1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Create new app → From scratch
3. Enable **Socket Mode** (Settings → Socket Mode → Enable)
4. Generate App-Level Token with `connections:write` scope → save as `SLACK_APP_TOKEN`
5. Add Bot Token Scopes (OAuth & Permissions):
   - `app_mentions:read`
   - `chat:write`
   - `channels:history` (for message listener)
6. Install to workspace → save Bot Token as `SLACK_BOT_TOKEN`
7. Subscribe to events (Event Subscriptions → Subscribe to bot events):
   - `app_mention`
   - `message.channels`

## Socket Mode vs HTTP Mode

| Feature | Socket Mode (Dev) | HTTP Mode (Production) |
|---------|------------------|----------------------|
| Public URL needed? | ❌ No | ✅ Yes |
| Signature verification | ❌ Skipped | ✅ Automatic (via Bolt) |
| Slack Marketplace | ❌ Not allowed | ✅ Required |
| Setup complexity | ✅ Simple | ⚠️ Moderate |

**Current mode: Socket Mode** (good for local dev)

Bolt automatically handles:
- ✅ Signature verification (when `signing_secret` provided in HTTP mode)
- ✅ URL verification challenges
- ✅ Request validation
- ✅ Retry logic

No manual checks needed - Orchestrator's manual verification is only needed if you're building webhooks from scratch!

## Current Features

- Responds to @mentions
- Responds to messages containing "hello"
- Button interaction example

## Architecture

```
Slack User
    │
    │ @mention
    ▼
Slack Bot (Socket Mode)
    │
    │ POST /investigate
    │ {"prompt": "...", "thread_id": "slack-{channel}-{thread}"}
    ▼
SRE Agent (http://localhost:8000)
    │
    │ Streaming response
    ▼
Slack User (with feedback buttons)
```

## Features

✅ **Streaming responses** - Real-time AI output using Slack's `chat_stream` API
✅ **Thread-based context** - Follow-up questions reuse the same sandbox
✅ **Feedback buttons** - Thumbs up/down on responses
✅ **Simple integration** - Just calls sre-agent's HTTP API

## Usage

1. **Start sre-agent** (in another terminal):
   ```bash
   cd sre-agent
   # For standalone (no K8s):
   source .venv/bin/activate
   python server.py
   
   # Or with K8s sandboxes:
   make dev
   ```

2. **Mention the bot in Slack**:
   ```
   @IncidentFox what pods are running in the default namespace?
   ```

3. **Follow-up in the same thread**:
   ```
   show me logs for the first pod
   ```

The bot will:
- Stream the response in real-time
- Reuse the same sandbox for follow-ups in the thread
- Add feedback buttons when done

## Next Steps

- [ ] Add interrupt button (stop current investigation)
- [ ] Add loading states with fun messages
- [ ] Switch to HTTP mode for production


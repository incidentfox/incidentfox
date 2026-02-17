# Slack Setup Guide

This guide walks you through setting up IncidentFox in your Slack workspace with detailed screenshots.

**Time required:** ~5 minutes

**Prerequisites:**
- Docker installed
- Slack workspace (admin access to install apps)
- An LLM API key (Anthropic recommended, or any [supported provider](DEPLOYMENT.md#using-a-different-ai-model))

---

## 1. Create a Slack App

1. **[Click here to create your app](https://api.slack.com/apps?new_app=1)** → Choose **"From an app manifest"**

   <img width="1355" alt="Create new app" src="https://github.com/user-attachments/assets/dfeadd58-a6c2-4b13-8df3-e7b8ac69c886" />

2. **Select your workspace**

   <img width="550" alt="Select workspace" src="https://github.com/user-attachments/assets/0eb2ee77-deb8-4959-841b-8e7d0ede91b2" />

3. **Copy the manifest** below and paste it into the JSON field:
```json
{
    "display_information": {
        "name": "IncidentFox(Local)",
        "description": "AI SRE copilot",
        "background_color": "#c96b28",
        "long_description": "IncidentFox — Your AI On-Call & Incident Response Agent in Slack\r\n\r\nIncidentFox is an AI-powered SRE and DevOps agent that lives in Slack.\r\n\r\nPing the IncidentFox bot to investigate alerts, diagnose incidents, and guide responders through resolution — without leaving your channel.\r\n\r\nReduce MTTR, cut through alert noise, and give your on-call engineers an always-available teammate.\r\n\r\n---\r\n\r\n🔔 Turn alerts into action\r\n\r\nIncidentFox connects your monitoring and infrastructure tools to Slack and helps you understand what's happening — fast.\r\n\r\n*Use IncidentFox to:*\r\n- Explain alerts in plain English\r\n- Investigate metrics, logs, and recent changes\r\n- Correlate signals across systems\r\n- Identify likely root causes\r\n- Suggest next steps during active incidents\r\n\r\nNo more copy-pasting dashboards. No more guessing.\r\n\r\n---\r\n\r\n🤖 An AI ops agent for real incidents\r\n\r\nIncidentFox isn't a generic chatbot. It's built specifically for incident management, on-call response, and production operations.\r\n\r\n*It understands:*\r\n- Alert context and history\r\n- System behavior over time\r\n- Dependencies across services\r\n- What usually breaks — and how teams fix it\r\n\r\nAsk operational questions during incidents or after, and get answers grounded in your environment.\r\n\r\n---\r\n\r\n🔌 Works with your existing monitoring stack\r\n\r\nIncidentFox integrates with popular DevOps and SRE tools, including:\r\n- Prometheus & VictoriaMetrics\r\n- Grafana\r\n- Elasticsearch\r\n- Major cloud platforms\r\n- Kubernetes\r\n- Temporal\r\n- And a lot more\r\n\r\nBring signals together in one place — Slack.\r\n\r\n---\r\n\r\n💬 Slack-first incident response\r\n\r\nIncidentFox is designed for how teams actually respond to incidents:\r\n- Trigger investigations from alerts\r\n- Ask questions in channels or DMs\r\n- Get step-by-step guidance during incidents\r\n- Share findings instantly with your team\r\n\r\nEverything happens where your team already collaborates.\r\n\r\n---\r\n\r\n🔐 Secure, transparent, and configurable\r\n\r\nIncidentFox only investigates when triggered by a user or an alert.\r\n\r\n*You control:*\r\n- Which data sources are connected\r\n- What the bot can access\r\n- How information is shared in Slack\r\n\r\nNo passive monitoring. No hidden behavior.\r\n\r\n---\r\n\r\n👥 Built for\r\n\r\n- SRE & DevOps teams\r\n- On-call engineers\r\n- Incident commanders\r\n- Platform & infrastructure teams\r\n\r\nIf Slack is your incident command center, IncidentFox fits right in."
    },
    "features": {
        "app_home": {
            "home_tab_enabled": true,
            "messages_tab_enabled": false,
            "messages_tab_read_only_enabled": false
        },
        "bot_user": {
            "display_name": "IncidentFox(Demo)",
            "always_online": true
        }
    },
    "oauth_config": {
        "redirect_urls": [
            "https://slack-staging.incidentfox.ai/slack/oauth_redirect"
        ],
        "scopes": {
            "bot": [
                "app_mentions:read",
                "channels:history",
                "channels:join",
                "channels:read",
                "chat:write",
                "files:read",
                "files:write",
                "groups:history",
                "groups:read",
                "im:history",
                "im:read",
                "im:write",
                "mpim:history",
                "mpim:read",
                "users:read",
                "reactions:read",
                "reactions:write",
                "links:read",
                "links:write",
                "chat:write.customize",
                "users:read.email",
                "usergroups:read",
                "metadata.message:read"
            ]
        }
    },
    "settings": {
        "event_subscriptions": {
            "bot_events": [
                "app_home_opened",
                "app_mention",
                "message.channels"
            ]
        },
        "interactivity": {
            "is_enabled": true,
            "request_url": "https://slack-staging.incidentfox.ai/slack/events"
        },
        "org_deploy_enabled": false,
        "socket_mode_enabled": true,
        "token_rotation_enabled": false
    }
}
```
<img width="531" height="687" alt="Paste manifest" src="https://github.com/user-attachments/assets/6dd03663-b148-4d1d-b52a-3981f305293c" />

4. **Click "Create"** → **"Install App"** → **"Install to Workspace"** → **"Allow"**

   <img width="989" alt="Install app" src="https://github.com/user-attachments/assets/54cdb087-497c-498a-86f9-31d133ec18c4" />

---

## 2. Get Your Tokens

### Bot Token (`SLACK_BOT_TOKEN`)

1. Go to **OAuth & Permissions** in your Slack app settings
2. Copy the **"Bot User OAuth Token"** (starts with `xoxb-`)

<img width="744" alt="Bot token" src="https://github.com/user-attachments/assets/0d7ea70c-394d-4787-a3b4-e32f395d44e1" />

### App Token (`SLACK_APP_TOKEN`)

1. Go to **Basic Information** → **App-Level Tokens**
2. Click **"Generate Token and Scopes"**
3. Add the `connections:write` scope
4. Copy the token (starts with `xapp-`)

<img width="697" alt="App token" src="https://github.com/user-attachments/assets/620bb92b-db49-4d50-8c22-70682ba008d2" />

### LLM API Key (`ANTHROPIC_API_KEY`)

Get your API key from the [Anthropic Console](https://console.anthropic.com).

To use a different model (OpenAI, Gemini, DeepSeek, etc.), see [Using a Different AI Model](DEPLOYMENT.md#using-a-different-ai-model).

---

## 3. Configure and Run

```bash
git clone https://github.com/incidentfox/incidentfox.git
cd incidentfox

# Create config file
cp .env.example .env
```

Edit `.env` and add your tokens:

```bash
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-token
ANTHROPIC_API_KEY=sk-ant-your-api-key

# Optional: use a different model (see .env.example for all options)
#LLM_MODEL=openai/gpt-4o-mini
#OPENAI_API_KEY=sk-your-openai-key
```

Start IncidentFox:

```bash
docker-compose up -d
```

---

## 4. Test It

In Slack:

```
/invite @IncidentFox
@IncidentFox what pods are running in my cluster?
```

You should see a streaming response from IncidentFox!

---

## Troubleshooting

### Bot not responding

1. Check the logs:
   ```bash
   docker-compose logs -f slack-bot
   ```

2. Verify your tokens are correct in `.env`

3. Make sure Socket Mode is enabled (it should be if you used the manifest)

### "not_authed" error

Your `SLACK_BOT_TOKEN` is invalid. Re-copy it from **OAuth & Permissions**.

### "invalid_auth" on App Token

Your `SLACK_APP_TOKEN` is invalid or missing the `connections:write` scope. Regenerate it from **Basic Information** → **App-Level Tokens**.

---

## Next Steps

- [Connect your observability tools](INTEGRATIONS.md) (Grafana, Datadog, Prometheus, etc.)
- [Deploy to Kubernetes](DEPLOYMENT.md) for production use
- [Configure for your team](../DEVELOPMENT_KNOWLEDGE.md) with custom prompts and tools

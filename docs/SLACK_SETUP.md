# Slack Setup Guide

Connect IncidentFox to your Slack workspace. Takes about 5 minutes.

**Prerequisites:**
- Docker installed and running
- Slack workspace where you have admin (or app installation) access
- An LLM API key — see `.env.example` for supported providers

---

## 1. Create a Slack App

1. **[Open the Slack app creation page](https://api.slack.com/apps?new_app=1)** → choose **"From an app manifest"**

   <img width="1355" alt="Create new app" src="https://github.com/user-attachments/assets/dfeadd58-a6c2-4b13-8df3-e7b8ac69c886" />

2. **Select your workspace**

   <img width="550" alt="Select workspace" src="https://github.com/user-attachments/assets/0eb2ee77-deb8-4959-841b-8e7d0ede91b2" />

3. **Paste the app manifest** from [`docs/slack-manifest.yaml`](slack-manifest.yaml):

   <img width="532" alt="Paste manifest" src="https://github.com/user-attachments/assets/2b926f88-9f2d-4f66-bb50-cc539b888353" />

4. **Create → Install to Workspace → Allow**

   <img width="989" alt="Install app" src="https://github.com/user-attachments/assets/54cdb087-497c-498a-86f9-31d133ec18c4" />

---

## 2. Get Your Tokens

### Bot Token (`SLACK_BOT_TOKEN`)

Go to **OAuth & Permissions** → copy the **Bot User OAuth Token** (starts with `xoxb-`).

<img width="744" alt="Bot token" src="https://github.com/user-attachments/assets/0d7ea70c-394d-4787-a3b4-e32f395d44e1" />

### App Token (`SLACK_APP_TOKEN`)

Go to **Basic Information → App-Level Tokens** → **Generate Token and Scopes** → add `connections:write` → copy the token (starts with `xapp-`).

<img width="697" alt="App token" src="https://github.com/user-attachments/assets/620bb92b-db49-4d50-8c22-70682ba008d2" />

---

## 3. Configure and Start

Add your tokens to `.env`:

```bash
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-token
ANTHROPIC_API_KEY=sk-ant-your-api-key
```

Start (or restart) the stack:

```bash
make dev       # first time
# or
make restart   # if already running
```

That's it. The slack-bot auto-connects via Socket Mode and registers your workspace — no additional configuration needed.

---

## 4. Test It

In Slack, invite the bot to a channel and try it:

```
/invite @IncidentFox
@IncidentFox what pods are running in my cluster?
```

You should see a streaming response.

---

## Troubleshooting

### Bot not responding

```bash
# Check logs
docker compose logs -f slack-bot

# Verify tokens are loaded
docker compose exec slack-bot env | grep SLACK
```

Common causes:
- Wrong token pasted (double-check `xoxb-` and `xapp-` prefixes)
- Socket Mode not enabled in your Slack app settings
- Slack app not installed to the workspace

### `not_authed` error

`SLACK_BOT_TOKEN` is invalid. Re-copy it from **OAuth & Permissions**.

### `invalid_auth` on App Token

`SLACK_APP_TOKEN` is missing the `connections:write` scope, or is invalid. Regenerate from **Basic Information → App-Level Tokens**.

### Bot exits on startup

If both `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` are not set, the bot exits gracefully — other services (sre-agent, config-service) still run. This is expected when developing without Slack.

---

## Next Steps

- [Connect your observability tools](INTEGRATIONS.md) — Grafana, Datadog, Prometheus, Coralogix, etc.
- [Configure AI model and integrations](../config_service/config/local.yaml) — edit `local.yaml`
- [Deploy to Kubernetes](DEPLOYMENT.md) — for production use

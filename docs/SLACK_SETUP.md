# Slack Setup Guide

This guide walks you through setting up IncidentFox in your Slack workspace with detailed screenshots.

**Time required:** ~5 minutes

**Prerequisites:**
- Docker installed
- Slack workspace (admin access to install apps)
- Anthropic API key

---

## 1. Create a Slack App

1. **[Click here to create your app](https://api.slack.com/apps?new_app=1)** → Choose **"From an app manifest"**

   <img width="1355" alt="Create new app" src="https://github.com/user-attachments/assets/dfeadd58-a6c2-4b13-8df3-e7b8ac69c886" />

2. **Select your workspace**

   <img width="550" alt="Select workspace" src="https://github.com/user-attachments/assets/0eb2ee77-deb8-4959-841b-8e7d0ede91b2" />

3. **Copy the manifest** from [docs/slack-manifest.yaml](slack-manifest.yaml) and paste it into the YAML field:

   <img width="532" alt="Paste manifest" src="https://github.com/user-attachments/assets/2b926f88-9f2d-4f66-bb50-cc539b888353" />

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

### Anthropic API Key (`ANTHROPIC_API_KEY`)

Get your API key from the [Anthropic Console](https://console.anthropic.com).

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

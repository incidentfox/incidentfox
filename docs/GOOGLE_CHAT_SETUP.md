# Google Chat Setup Guide

This guide walks you through adding IncidentFox to your Google Chat workspace.

**Time required:** ~2 minutes

**Prerequisites:**
- Google Workspace account (Gmail accounts are not supported)
- Access to Google Chat

---

## 1. Install IncidentFox

### Option A: Search in Google Chat

1. Open **Google Chat** (chat.google.com or the Chat tab in Gmail)
2. Click the **+** next to "Spaces" or "Chat"
3. Select **"Find apps"**
4. Search for **"IncidentFox"**
5. Click **"Add"**

### Option B: Direct Link

Your workspace admin may provide a direct install link. Click it and follow the prompts to add IncidentFox.

### Option C: Admin Installation (Organization-wide)

Google Workspace admins can install IncidentFox for the entire organization:

1. Go to **Google Admin Console** (admin.google.com)
2. Navigate to **Apps** → **Google Workspace Marketplace apps**
3. Click **Add app** → Search for **"IncidentFox"**
4. Choose installation settings (install for everyone or specific groups)
5. Click **Install**

---

## 2. Add to a Space

Once installed, add IncidentFox to a space where your team handles incidents:

1. Open the space in Google Chat
2. Click the space name at the top → **"Manage apps & integrations"**
3. Search for **"IncidentFox"** → Click **"Add"**

Or simply type `@IncidentFox` in any space and follow the prompt to add it.

---

## 3. Start Using IncidentFox

Mention IncidentFox in any message to start an investigation:

```
@IncidentFox why is checkout-service returning 500 errors?
```

```
@IncidentFox what changed in the last 30 minutes?
```

```
@IncidentFox check the health of the payment-api deployment
```

IncidentFox will analyze your connected observability tools (Datadog, PagerDuty, AWS, Kubernetes, etc.) and respond with actionable insights.

---

## 4. Available Commands

| Command | Description |
|---------|-------------|
| `@IncidentFox investigate <issue>` | Start an incident investigation |
| `@IncidentFox status <service>` | Check the status of a service |
| `@IncidentFox help` | Show available commands |

---

## Connecting Your Tools

IncidentFox needs access to your observability stack to investigate incidents. Connect your tools through the IncidentFox web dashboard:

1. Log in to your IncidentFox dashboard
2. Go to **Settings** → **Integrations**
3. Connect your tools (Datadog, PagerDuty, AWS, Kubernetes, Grafana, etc.)

See [INTEGRATIONS.md](INTEGRATIONS.md) for detailed setup instructions.

---

## Troubleshooting

### IncidentFox not responding

1. Make sure the app is added to the space (check **Manage apps & integrations**)
2. Verify you're using `@IncidentFox` to mention the bot
3. Contact your workspace admin to confirm the app is approved for your organization

### "App not available"

Your Google Workspace admin may need to approve IncidentFox. Ask your admin to:
1. Go to **Google Admin Console** → **Apps** → **Google Workspace Marketplace apps**
2. Find IncidentFox and approve it for your organization

### Messages not being processed

If IncidentFox acknowledges your message but doesn't return results, your observability tools may not be connected. Check your IncidentFox dashboard under **Settings** → **Integrations**.

---

## Next Steps

- [Connect your observability tools](INTEGRATIONS.md)
- [MS Teams Setup](TEAMS_SETUP.md) - Set up IncidentFox in Microsoft Teams
- [Slack Setup](SLACK_SETUP.md) - Set up IncidentFox in Slack

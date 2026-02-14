# Microsoft Teams Setup Guide

This guide walks you through adding IncidentFox to your Microsoft Teams workspace.

**Time required:** ~2 minutes

**Prerequisites:**
- Microsoft Teams account (work or school)
- Teams admin access (for organization-wide installation)

---

## 1. Install IncidentFox

### Option A: Teams App Store

1. Open **Microsoft Teams**
2. Click **"Apps"** in the left sidebar
3. Search for **"IncidentFox"**
4. Click **"Add"**

### Option B: Admin Installation (Organization-wide)

Teams admins can install IncidentFox for the entire organization:

1. Go to **Teams Admin Center** (admin.teams.microsoft.com)
2. Navigate to **Teams apps** → **Manage apps**
3. Search for **"IncidentFox"**
4. Click the app → **"Allow"**
5. Optionally, go to **Setup policies** to pin the app for specific users/groups

### Option C: Custom App (Sideload)

If IncidentFox is not yet on the Teams App Store, your admin can sideload it:

1. Obtain the `IncidentFox-Teams.zip` package from your IncidentFox account manager
2. In Teams, go to **Apps** → **Manage your apps** → **Upload an app**
3. Select **"Upload a custom app"**
4. Choose the `.zip` file
5. Click **"Add"**

---

## 2. Add to a Channel

Once installed, add IncidentFox to a channel where your team handles incidents:

1. Go to the channel
2. Click **"+"** at the top to add a tab (optional - for quick access)
3. Or simply `@mention` IncidentFox in any channel message

To add the bot to a channel directly:

1. Click **"..."** next to the channel name
2. Select **"Manage channel"**
3. Go to the **"Bots"** tab
4. Search for **"IncidentFox"** and add it

---

## 3. Start Using IncidentFox

Mention IncidentFox in any channel or direct message to start an investigation:

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

1. Make sure the bot is added to the channel or conversation
2. Verify you're using `@IncidentFox` to mention the bot
3. Check with your Teams admin that the app is allowed in your organization

### "App blocked by admin"

Your Teams admin needs to approve IncidentFox:
1. Go to **Teams Admin Center** → **Teams apps** → **Manage apps**
2. Find IncidentFox → Set status to **"Allowed"**

### "App not available in your region"

IncidentFox is available globally. If you see this error, contact your Teams admin to check app permission policies.

### Messages not being processed

If IncidentFox acknowledges your message but doesn't return results, your observability tools may not be connected. Check your IncidentFox dashboard under **Settings** → **Integrations**.

---

## Next Steps

- [Connect your observability tools](INTEGRATIONS.md)
- [Google Chat Setup](GOOGLE_CHAT_SETUP.md) - Set up IncidentFox in Google Chat
- [Slack Setup](SLACK_SETUP.md) - Set up IncidentFox in Slack

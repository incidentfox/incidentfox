---
name: incident-comms
description: Slack integration for incident communication. Use when searching for context in incident channels, posting status updates, or finding discussions about issues.
allowed-tools: Bash(python *)
---

# Incident Communications

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Do NOT check for `SLACK_BOT_TOKEN` in environment variables — it won't be visible to you. Just run the scripts directly; authentication is handled transparently.

## Bot Token Permissions

You authenticate as a **bot** (not a user). This means:

| Can do | Cannot do |
|--------|-----------|
| List channels (`conversations.list`) | **Search messages** (`search.messages` — requires user token) |
| Read channel history (if bot is a member) | Read channels the bot hasn't been added to |
| Read thread replies | Access DMs between other users |
| Post messages and thread replies | |
| Look up user profiles | |

**If search is requested**: Do NOT attempt `search_messages.py` — it will fail with a `missing_scope` error. Instead, use the channel-scanning workflow below.

---

## Available Scripts

All scripts are in `.claude/skills/incident-comms/scripts/`

### list_channels.py — List Channels
```bash
python .claude/skills/incident-comms/scripts/list_channels.py [--types TYPE] [--limit N] [--filter NAME]

# Examples:
python .claude/skills/incident-comms/scripts/list_channels.py
python .claude/skills/incident-comms/scripts/list_channels.py --filter incident
python .claude/skills/incident-comms/scripts/list_channels.py --types public_channel --limit 500
```

### get_channel_history.py — Read Channel Messages
```bash
python .claude/skills/incident-comms/scripts/get_channel_history.py --channel CHANNEL_ID [--limit N]

# Examples:
python .claude/skills/incident-comms/scripts/get_channel_history.py --channel C123ABC456
python .claude/skills/incident-comms/scripts/get_channel_history.py --channel C123ABC456 --limit 100
```

### get_thread_replies.py — Read Thread Replies
```bash
python .claude/skills/incident-comms/scripts/get_thread_replies.py --channel CHANNEL_ID --thread THREAD_TS [--limit N]

# Examples:
python .claude/skills/incident-comms/scripts/get_thread_replies.py --channel C123ABC456 --thread 1705320123.456789
```

### post_message.py — Post Status Updates
```bash
python .claude/skills/incident-comms/scripts/post_message.py --channel CHANNEL_ID --text MESSAGE [--thread THREAD_TS]

# Examples:
python .claude/skills/incident-comms/scripts/post_message.py --channel C123ABC456 --text "Investigation update: found root cause"
python .claude/skills/incident-comms/scripts/post_message.py --channel C123ABC456 --text "Rollback completed" --thread 1705320123.456789
```

---

## Workflows

### Finding Recent Activity (Bot-Compatible Search Alternative)

Since `search.messages` requires a user token, use this workflow instead:

```bash
# Step 1: Find relevant channels
python .claude/skills/incident-comms/scripts/list_channels.py --filter incident

# Step 2: Read recent history from channels the bot is in (★ in list)
python .claude/skills/incident-comms/scripts/get_channel_history.py --channel C_INCIDENTS --limit 50

# Step 3: Dive into interesting threads
python .claude/skills/incident-comms/scripts/get_thread_replies.py --channel C_INCIDENTS --thread 1705320123.456789
```

Scan multiple channels to build context. Focus on channels with names like `#incidents`, `#alerts`, `#engineering`, `#support`.

### Gather Context for New Incident

```bash
# Find incident-related channels
python .claude/skills/incident-comms/scripts/list_channels.py --filter incident

# Check the incident channel for recent activity
python .claude/skills/incident-comms/scripts/get_channel_history.py --channel C_INCIDENTS --limit 50

# Read a specific thread
python .claude/skills/incident-comms/scripts/get_thread_replies.py --channel C_INCIDENTS --thread 1705320123.456789
```

### Post Investigation Summary

```bash
python .claude/skills/incident-comms/scripts/post_message.py --channel C_INCIDENTS --thread 1705320123.456789 --text ":clipboard: *Investigation Summary*

*Timeline:*
• 14:00 - Alerts started firing
• 14:05 - Investigation began
• 14:15 - Root cause identified
• 14:20 - Fix deployed

*Root Cause:*
Connection pool exhaustion due to unclosed connections.

*Resolution:*
Rolled back to v2.3.4, deployed fix in v2.3.5."
```

---

## Quick Reference

| Goal | Command |
|------|---------|
| List channels | `list_channels.py` |
| Filter channels by name | `list_channels.py --filter incident` |
| Channel history | `get_channel_history.py --channel C123ABC` |
| Thread replies | `get_thread_replies.py --channel C123ABC --thread TS` |
| Post update | `post_message.py --channel C123ABC --text "Update"` |
| Reply to thread | `post_message.py --channel C123ABC --text "..." --thread TS` |

---

## Status Update Templates

**Investigation Started:**
```
:mag: *Investigation Started*

Investigating: [Brief description of symptoms]
Initial findings: [What you've found so far]
Current hypothesis: [What you think might be wrong]

Will update in 15 minutes.
```

**Root Cause Identified:**
```
:bulb: *Root Cause Identified*

Cause: [Clear explanation]
Impact: [What was affected]
Mitigation: [What we're doing to fix it]

ETA for resolution: [Time estimate]
```

**Resolved:**
```
:white_check_mark: *Incident Resolved*

Root cause: [Brief summary]
Resolution: [What fixed it]
Duration: [How long the incident lasted]

Follow-up: [Next steps, postmortem timing]
```

---

## Best Practices

### Reading Channels
- **List first**: Use `list_channels.py` to find channel IDs — don't guess
- **Check membership**: Only channels marked ★ can be read (bot must be a member)
- **Scan multiple**: Check `#incidents`, `#alerts`, `#engineering`, `#support`, etc.

### Posting Updates
- **Use threads**: Keep updates in the incident thread, not the main channel
- **Be concise**: Busy responders scan updates quickly
- **Include next steps**: Always say what's happening next

### Anti-Patterns
1. Do NOT use `search_messages.py` — it requires a user token and will fail
2. Do NOT post before reading — check what's already been discussed
3. Do NOT guess channel IDs — use `list_channels.py` to find them

---
name: incident-comms
description: Slack integration for incident communication. Use when searching for context in incident channels, posting status updates, or finding discussions about issues.
allowed-tools: Bash(python *)
---

# Incident Communications

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Do NOT check for `SLACK_BOT_TOKEN` in environment variables - it won't be visible to you. Just run the scripts directly; authentication is handled transparently.

---

## Why Slack Context Matters

Before diving into technical investigation:
- **Has anyone else seen this?** Search for related discussions
- **What's been tried already?** Check incident thread history
- **Who's working on it?** Find active responders
- **What's the impact?** Look for customer reports

## Available Scripts

All scripts are in `.claude/skills/incident-comms/scripts/`

### search_messages.py - Search Across Channels
> **Note**: Requires a Slack **user token** (xoxu-*), not a bot token. Bot tokens cannot use the search API.

```bash
python .claude/skills/incident-comms/scripts/search_messages.py --query SEARCH_QUERY [--count N]

# Examples:
python .claude/skills/incident-comms/scripts/search_messages.py --query "error timeout"
python .claude/skills/incident-comms/scripts/search_messages.py --query "in:#incidents api error"
python .claude/skills/incident-comms/scripts/search_messages.py --query "from:@oncall database" --count 30
```

### get_channel_history.py - Read Channel Messages
```bash
python .claude/skills/incident-comms/scripts/get_channel_history.py --channel CHANNEL_ID [--limit N]

# Examples:
python .claude/skills/incident-comms/scripts/get_channel_history.py --channel C123ABC456
python .claude/skills/incident-comms/scripts/get_channel_history.py --channel C123ABC456 --limit 100
```

### post_message.py - Post Status Updates
```bash
python .claude/skills/incident-comms/scripts/post_message.py --channel CHANNEL_ID --text MESSAGE [--thread THREAD_TS]

# Examples:
python .claude/skills/incident-comms/scripts/post_message.py --channel C123ABC456 --text "Investigation update: found root cause"
python .claude/skills/incident-comms/scripts/post_message.py --channel C123ABC456 --text "Rollback completed" --thread 1705320123.456789
```

---

## Slack Search Operators

| Operator | Example | Purpose |
|----------|---------|---------|
| `in:#channel` | `in:#incidents` | Search specific channel |
| `from:@user` | `from:@jane` | Messages from a user |
| `has:reaction` | `has::eyes:` | Messages with reactions |
| `after:date` | `after:2024-01-15` | After a date |
| `before:date` | `before:2024-01-16` | Before a date |

---

## Common Workflows

### 1. Gather Context for New Incident

```bash
# Step 1: Search for similar issues
python search_messages.py --query "api timeout in:#incidents"

# Step 2: Check the incident channel for recent activity
python get_channel_history.py --channel C_INCIDENTS --limit 50

# Step 3: Read a specific thread
python get_thread_replies.py --channel C_INCIDENTS --thread 1705320123.456789
```

### 2. Find What's Been Tried

```bash
# Search for actions taken during this incident
python search_messages.py --query "in:#incident-123 (restart OR rollback OR revert OR tried)"
```

### 3. Check Customer Impact

```bash
# Search support/customer channels
python search_messages.py --query "in:#support error OR issue"
```

### 4. Post Investigation Summary

```bash
python post_message.py --channel C_INCIDENTS --thread 1705320123.456789 --text ":clipboard: *Investigation Summary*

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

## Quick Commands Reference

| Goal | Command |
|------|---------|
| Search messages | `search_messages.py --query "error"` |
| Channel history | `get_channel_history.py --channel C123ABC` |
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

### Searching
- **Be specific**: Use channel filters (`in:#channel`) to reduce noise
- **Use operators**: Combine `from:`, `after:`, `has:` for precision
- **Check multiple channels**: Incidents might be discussed in #support, #engineering, etc.

### Posting Updates
- **Use threads**: Keep updates in the incident thread, not the main channel
- **Be concise**: Busy responders scan updates quickly
- **Include next steps**: Always say what's happening next

### Finding Channel IDs
- Channel IDs look like `C123ABC456`
- Get them from channel settings or by right-clicking → "Copy link"

---

## Anti-Patterns to Avoid

1. ❌ **Posting before reading** - Check what's already been discussed
2. ❌ **Top-posting in threads** - Reply in the thread, not the channel
3. ❌ **Vague updates** - "Working on it" tells responders nothing
4. ❌ **Missing timestamps** - Include when things happened

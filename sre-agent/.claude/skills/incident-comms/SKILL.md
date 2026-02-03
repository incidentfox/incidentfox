---
name: incident-comms
description: Slack integration for incident communication. Use when searching for context in incident channels, posting status updates, or finding discussions about issues.
---

# Incident Communications

## Why Slack Context Matters

Before diving into technical investigation:
- **Has anyone else seen this?** Search for related discussions
- **What's been tried already?** Check incident thread history
- **Who's working on it?** Find active responders
- **What's the impact?** Look for customer reports

## Available Tools

| Tool | Purpose |
|------|---------|
| `slack_search_messages` | Search across channels |
| `slack_get_channel_history` | Get recent messages in a channel |
| `slack_get_thread_replies` | Get all replies in a thread |
| `slack_post_message` | Post status updates |

---

## Searching for Context

### Find Related Discussions

```python
# Search for error messages
slack_search_messages(query="NullPointerException", count=20)

# Search in specific channel
slack_search_messages(query="in:#incidents api timeout", count=20)

# Search by user
slack_search_messages(query="from:@oncall-engineer database", count=20)

# Search by time range (natural language)
slack_search_messages(query="deployment after:2024-01-15 before:2024-01-16", count=20)
```

### Slack Search Operators

| Operator | Example | Purpose |
|----------|---------|---------|
| `in:#channel` | `in:#incidents` | Search specific channel |
| `from:@user` | `from:@jane` | Messages from a user |
| `has:reaction` | `has::eyes:` | Messages with reactions |
| `after:date` | `after:2024-01-15` | After a date |
| `before:date` | `before:2024-01-16` | Before a date |
| `during:month` | `during:january` | During a time period |

---

## Reading Channel History

### Get Incident Channel Context

```python
# Get recent messages from an incident channel
slack_get_channel_history(channel_id="C123ABC", limit=100)

# Get messages since a specific time (Unix timestamp)
slack_get_channel_history(
    channel_id="C123ABC",
    limit=50,
    oldest="1705320000"  # Timestamp when incident started
)
```

### Follow a Thread

```python
# Get all replies in a discussion thread
slack_get_thread_replies(
    channel_id="C123ABC",
    thread_ts="1705320123.456789"  # Thread parent timestamp
)
```

**Finding thread_ts**: Look for the `thread_ts` field in channel history results, or click "Copy link" on a Slack message and extract the timestamp.

---

## Posting Updates

### Status Update to Incident Channel

```python
# Post an update to the incident channel
slack_post_message(
    channel_id="C123ABC",
    text=":mag: *Investigation Update*\n\nIdentified the issue: Database connection pool exhaustion caused by connection leak in commit abc123.\n\nNext step: Rolling back to previous version."
)

# Reply to an existing thread
slack_post_message(
    channel_id="C123ABC",
    text="Rollback completed. Monitoring for recovery.",
    thread_ts="1705320123.456789"
)
```

### Status Update Templates

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

## Common Workflows

### 1. Gather Context for New Incident

```python
# Step 1: Search for similar issues
similar = slack_search_messages(query="api timeout in:#incidents", count=20)

# Step 2: Check the incident channel for recent activity
history = slack_get_channel_history(channel_id="C_INCIDENTS", limit=50)

# Step 3: Look for the original alert/report thread
thread = slack_get_thread_replies(channel_id="C_INCIDENTS", thread_ts="...")
```

### 2. Find What's Been Tried

```python
# Search for actions taken during this incident
slack_search_messages(
    query="in:#incident-123 (restart OR rollback OR revert OR tried)",
    count=30
)
```

### 3. Check Customer Impact

```python
# Search support/customer channels
slack_search_messages(query="in:#support error OR issue", count=20)
slack_search_messages(query="in:#customer-feedback outage OR slow", count=20)
```

### 4. Post Investigation Summary

```python
# Post summary to incident channel
slack_post_message(
    channel_id="C_INCIDENTS",
    text="""
:clipboard: *Investigation Summary*

*Timeline:*
• 14:00 - Alerts started firing
• 14:05 - Investigation began
• 14:15 - Root cause identified (connection leak)
• 14:20 - Fix deployed

*Root Cause:*
Connection pool exhaustion due to unclosed connections in new payment flow (commit abc123).

*Resolution:*
Rolled back to v2.3.4, deployed fix in v2.3.5.

*Action Items:*
1. Add connection pool monitoring
2. Code review for connection handling
""",
    thread_ts="1705320123.456789"
)
```

---

## Output Format

```markdown
## Slack Context Summary

### Related Discussions Found
- **[#channel]** [timestamp]: [Summary of message]
- **[#channel]** [timestamp]: [Summary of message]

### Active Incident Threads
- **Thread**: [link/timestamp]
- **Started by**: [user]
- **Replies**: [count]
- **Last activity**: [timestamp]

### Key Information Gathered
- [What responders have already tried]
- [Customer reports or impact mentions]
- [Relevant past incidents referenced]

### Recommendations
- [Post update to thread X]
- [Check with user Y who mentioned similar issue]
- [Review past incident Z for resolution steps]
```

---

## Best Practices

### Searching
- **Be specific**: Use channel filters (`in:#channel`) to reduce noise
- **Use operators**: Combine `from:`, `after:`, `has:` for precision
- **Check multiple channels**: Incidents might be discussed in #support, #engineering, or service-specific channels

### Posting Updates
- **Use threads**: Keep updates in the incident thread, not the main channel
- **Be concise**: Busy responders scan updates quickly
- **Use formatting**: Bold key info, use lists, add emojis for status
- **Include next steps**: Always say what's happening next

### Finding Channel IDs
- Channel IDs look like `C123ABC456`
- Get them from channel settings or by right-clicking → "Copy link"
- The link format is: `slack.com/archives/CHANNEL_ID/...`

---

## Anti-Patterns

1. **Posting before reading** - Check what's already been discussed
2. **Top-posting in threads** - Reply in the thread, not the channel
3. **Vague updates** - "Working on it" tells responders nothing
4. **Missing timestamps** - Include when things happened
5. **Forgetting customer channels** - Support and customer feedback often have valuable context

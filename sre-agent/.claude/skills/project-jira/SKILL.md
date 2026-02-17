---
name: jira-integration
description: Jira issue tracking and incident management. Use when creating, searching, or updating Jira issues. Supports JQL queries for incident ticket analysis and alert fatigue tracking.
allowed-tools: Bash(python *)
---

# Jira Integration

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Do NOT check for `JIRA_API_TOKEN` or `JIRA_EMAIL` in environment variables - they won't be visible to you. Just run the scripts directly; authentication is handled transparently.

Configuration environment variables you CAN check (non-secret):
- `JIRA_URL` - Jira instance URL (e.g., `https://your-company.atlassian.net`)

---

## Available Scripts

All scripts are in `.claude/skills/project-jira/scripts/`

### search_issues.py - Search with JQL
Powerful search using Jira Query Language. Best for finding incident tickets, patterns, action items.
```bash
python .claude/skills/project-jira/scripts/search_issues.py --jql "JQL_QUERY" [--max-results N]

# Examples:
python .claude/skills/project-jira/scripts/search_issues.py --jql "type = Bug AND status != Done AND created >= -7d"
python .claude/skills/project-jira/scripts/search_issues.py --jql "labels = incident AND created >= -30d" --max-results 50
```

### get_issue.py - Get Issue Details
```bash
python .claude/skills/project-jira/scripts/get_issue.py --issue-key PROJ-123
```

### create_issue.py - Create New Issue
```bash
python .claude/skills/project-jira/scripts/create_issue.py --project PROJ --summary "Title" --description "Details" [--type Bug] [--priority High] [--labels "incident,p1"]
```

### update_issue.py - Update Existing Issue
```bash
python .claude/skills/project-jira/scripts/update_issue.py --issue-key PROJ-123 [--summary "New title"] [--status "In Progress"] [--priority High]
```

### add_comment.py - Add Comment
```bash
python .claude/skills/project-jira/scripts/add_comment.py --issue-key PROJ-123 --comment "Investigation findings..."
```

### list_issues.py - List Project Issues
```bash
python .claude/skills/project-jira/scripts/list_issues.py --project PROJ [--max-results 20]
```

---

## JQL Quick Reference

### Common Patterns
```
# Recent bugs
type = Bug AND created >= -7d ORDER BY created DESC

# Open incidents
type = Incident AND status != Done

# By label
labels IN ("incident", "p1", "alert-tuning")

# Text search
summary ~ "high CPU" OR description ~ "timeout"

# Stale issues
updated <= -90d AND status != Done
```

### Operators
| Operator | Meaning | Example |
|----------|---------|---------|
| = | Equals | `status = Done` |
| != | Not equals | `status != Done` |
| ~ | Contains text | `summary ~ "error"` |
| IN | In list | `status IN ("Open", "In Progress")` |
| >= | Greater/equal | `created >= -7d` |
| ORDER BY | Sort | `ORDER BY created DESC` |

---

## Investigation Workflow

### Incident Ticket Analysis
```
1. Search for related incidents:
   search_issues.py --jql "type = Incident AND created >= -30d"

2. Get details of specific incident:
   get_issue.py --issue-key INC-456

3. Add investigation findings:
   add_comment.py --issue-key INC-456 --comment "Root cause: ..."

4. Update status:
   update_issue.py --issue-key INC-456 --status "Resolved"
```

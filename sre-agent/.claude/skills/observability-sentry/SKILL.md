---
name: sentry-monitoring
description: Sentry error tracking and performance monitoring. Use when investigating application errors, checking error frequency, managing issue status, or reviewing releases.
allowed-tools: Bash(python *)
---

# Sentry Error Tracking

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Do NOT check for `SENTRY_AUTH_TOKEN` in environment variables - it won't be visible to you. Just run the scripts directly; authentication is handled transparently.

Configuration environment variables you CAN check (non-secret):
- `SENTRY_ORGANIZATION` - Sentry organization slug
- `SENTRY_PROJECT` - Default Sentry project slug

---

## MANDATORY: Error-First Investigation

**Start with listing issues, then drill into details.**

```
LIST ISSUES -> GET DETAILS -> CHECK STATS -> REVIEW RELEASES
```

## Available Scripts

All scripts are in `.claude/skills/observability-sentry/scripts/`

### list_issues.py - ALWAYS START HERE
```bash
python .claude/skills/observability-sentry/scripts/list_issues.py --project PROJECT_SLUG [--query "is:unresolved"]

# Examples:
python .claude/skills/observability-sentry/scripts/list_issues.py --project api-backend
python .claude/skills/observability-sentry/scripts/list_issues.py --project api-backend --query "is:unresolved level:error"
```

### get_issue.py - Get Issue Details
```bash
python .claude/skills/observability-sentry/scripts/get_issue.py --issue-id 12345678
```

### update_issue_status.py - Update Issue Status
```bash
python .claude/skills/observability-sentry/scripts/update_issue_status.py --issue-id 12345678 --status resolved
# Status options: resolved, unresolved, ignored, resolvedInNextRelease
```

### list_projects.py - List Organization Projects
```bash
python .claude/skills/observability-sentry/scripts/list_projects.py
```

### get_project_stats.py - Project Statistics
```bash
python .claude/skills/observability-sentry/scripts/get_project_stats.py --project PROJECT_SLUG [--stat received] [--resolution 1h]
```

### list_releases.py - List Releases
```bash
python .claude/skills/observability-sentry/scripts/list_releases.py --project PROJECT_SLUG [--limit 10]
```

---

## Sentry Search Query Syntax
```
is:unresolved                    # Status
level:error                      # Level
first-release:1.2.0              # Release
firstSeen:-24h                   # Time
assigned:user@company.com        # Assignment
is:unresolved level:error firstSeen:-24h   # Combined
```

---

## Investigation Workflow

### Error Spike Investigation
```
1. list_issues.py --project api --query "is:unresolved"
2. get_issue.py --issue-id <id>
3. list_releases.py --project api
4. get_project_stats.py --project api --stat received --resolution 1h
```

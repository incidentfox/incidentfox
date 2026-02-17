---
name: linear-integration
description: Linear issue tracking and project management. Use for creating issues, searching issues, and managing projects. Supports GraphQL queries with team and state filtering.
allowed-tools: Bash(python *)
---

# Linear Integration

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Just run the scripts directly.

## Priority Levels

| Value | Level |
|-------|-------|
| 0 | No priority |
| 1 | Urgent |
| 2 | High |
| 3 | Medium |
| 4 | Low |

## Available Scripts

All scripts are in `.claude/skills/project-linear/scripts/`

### create_issue.py
```bash
python .claude/skills/project-linear/scripts/create_issue.py --title "Fix auth bug" [--description "Details..."] [--team-id ID] [--priority 2] [--assignee-id ID] [--labels "label1,label2"]
```

### create_project.py
```bash
python .claude/skills/project-linear/scripts/create_project.py --name "Q1 Reliability" [--description "..."] [--team-id ID]
```

### get_issue.py
```bash
python .claude/skills/project-linear/scripts/get_issue.py --issue-id TEAM-123
```

### list_issues.py
```bash
python .claude/skills/project-linear/scripts/list_issues.py [--team-id ID] [--state "In Progress"] [--max-results 50]
```

---
name: project-clickup
description: ClickUp project management integration for incident tracking and task management
category: project-management
required_integrations:
  - clickup
allowed-tools:
  - Bash(python *)
---

# ClickUp Project Management

Query and manage tasks in ClickUp for incident tracking and project management.

## Authentication

This skill uses credentials managed by the credential-proxy service. In production, credentials are injected automatically via JWT authentication.

For local development, set:
- `CLICKUP_API_TOKEN` - Your ClickUp API token (Personal Access Token)
- `CLICKUP_TEAM_ID` - Your workspace/team ID (optional, auto-detected if not set)

## Available Scripts

### list_spaces.py - Discover Workspace Structure

List all spaces, folders, and lists in the workspace:

```bash
# List spaces
python list_spaces.py

# Include lists and folders
python list_spaces.py --include-lists

# JSON output
python list_spaces.py --json
```

### search_tasks.py - Search for Tasks

Search across all tasks in the workspace:

```bash
# Search by query
python search_tasks.py --query "payment error"

# Filter by status
python search_tasks.py --query "incident" --status "investigating"

# Recently updated
python search_tasks.py --updated-since 24h

# Combined filters
python search_tasks.py --query "api" --status "open" --updated-since 7d --json
```

Options:
- `--query, -q` - Search text (matches name and description)
- `--status, -s` - Filter by status (can repeat for multiple)
- `--assignee, -a` - Filter by assignee ID
- `--list-id` - Filter by list ID
- `--space-id` - Filter by space ID
- `--updated-since` - Tasks updated since (e.g., "1h", "24h", "7d")
- `--created-since` - Tasks created since
- `--include-closed` - Include closed tasks
- `--limit` - Maximum results (default: 50)
- `--json` - Output as JSON

### get_task.py - Get Task Details

Retrieve full details for a specific task:

```bash
# Basic details
python get_task.py abc123

# Include comments
python get_task.py abc123 --include-comments

# Include subtasks
python get_task.py abc123 --include-subtasks

# Full details as JSON
python get_task.py abc123 --include-comments --include-subtasks --json
```

Options:
- `--include-comments, -c` - Include task comments
- `--include-subtasks, -s` - Include subtasks
- `--json` - Output as JSON

### add_comment.py - Add Task Comment

Add investigation findings to a task:

```bash
# Simple comment
python add_comment.py abc123 --message "Found root cause in logs"

# Markdown comment
python add_comment.py abc123 -m "## Investigation Summary\n- Error in payment service\n- Caused by config change"
```

Options:
- `--message, -m` - Comment text (supports markdown)
- `--json` - Output as JSON

## ClickUp Hierarchy

Understanding ClickUp's structure helps with navigation:

```
Workspace (Team)
└── Space
    ├── Folder (optional)
    │   └── List
    │       └── Task
    │           └── Subtask
    └── List (folderless)
        └── Task
```

## Investigation Workflow

### 1. Discover Structure

First, find where incidents are tracked:

```bash
python list_spaces.py --include-lists
```

Look for spaces/lists like "Incidents", "SRE", "On-Call", etc.

### 2. Search for Related Incidents

Search for incidents related to your investigation:

```bash
python search_tasks.py --query "payment" --status "investigating"
```

### 3. Get Incident Details

Review the full incident context:

```bash
python get_task.py abc123 --include-comments
```

### 4. Document Findings

Add your investigation findings:

```bash
python add_comment.py abc123 --message "Root cause: Database connection pool exhausted"
```

## Task Properties

### Status
Tasks have configurable statuses. Common incident statuses:
- `to do` / `open` - New incident
- `investigating` - Active investigation
- `in progress` - Remediation underway
- `resolved` / `complete` - Incident resolved
- `closed` - Post-mortem complete

### Priority
- 1 = Urgent
- 2 = High
- 3 = Normal
- 4 = Low

### Custom Fields
Teams often use custom fields for:
- Severity (P0, P1, P2, etc.)
- Affected services
- Impact scope
- Customer impact
- Root cause category

## Integration with Other Skills

ClickUp integrates with the investigation workflow:

1. **Start**: Check ClickUp for existing incident tickets
2. **Investigate**: Use observability skills to find root cause
3. **Document**: Add findings to ClickUp task as comments
4. **Correlate**: Link with deployment-correlation skill for change analysis

## Tips

- **Use task IDs** - Copy task IDs from ClickUp URLs (format: `abc123`)
- **Search broadly first** - Start with general queries, then filter
- **Check comments** - Previous investigation notes may have clues
- **Document as you go** - Add comments with findings for team visibility

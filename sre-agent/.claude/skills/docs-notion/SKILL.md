---
name: notion-integration
description: Notion page and database management. Use for searching, creating, and writing to Notion pages. Supports creating pages in databases or under parent pages.
allowed-tools: Bash(python *)
---

# Notion Integration

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Just run the scripts directly.

## Available Scripts

All scripts are in `.claude/skills/docs-notion/scripts/`

### search.py - Search Pages
```bash
python .claude/skills/docs-notion/scripts/search.py --query "incident runbook" [--max-results 10]
```

### create_page.py - Create Page
```bash
python .claude/skills/docs-notion/scripts/create_page.py --title "Incident Report" --parent-page-id PAGE_ID [--content "Report content..."]
python .claude/skills/docs-notion/scripts/create_page.py --title "New Entry" --parent-database-id DB_ID
```

### write_content.py - Write to Page
```bash
python .claude/skills/docs-notion/scripts/write_content.py --page-id PAGE_ID --content "New content..." [--replace]
```

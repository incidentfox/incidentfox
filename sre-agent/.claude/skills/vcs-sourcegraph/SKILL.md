---
name: sourcegraph-integration
description: Sourcegraph code search across repositories. Use for searching code patterns, finding implementations, and exploring codebases. Supports repo and file filters.
allowed-tools: Bash(python *)
---

# Sourcegraph Code Search

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Just run the scripts directly.

## Available Scripts

All scripts are in `.claude/skills/vcs-sourcegraph/scripts/`

### search.py - Code Search
```bash
python .claude/skills/vcs-sourcegraph/scripts/search.py --query "func handleError" [--repo-filter "github.com/org/*"] [--file-filter "*.go"] [--limit 20]
```

## Search Syntax

| Filter | Example | Description |
|--------|---------|-------------|
| `repo:` | `repo:github.com/org/*` | Filter by repository |
| `file:` | `file:*.py` | Filter by file path |
| `lang:` | `lang:python` | Filter by language |
| `type:` | `type:symbol` | Search type (symbol, file, diff, commit) |

Regex patterns are supported in queries.

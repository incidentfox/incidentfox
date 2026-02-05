---
name: knowledge-base
description: Search runbooks, documentation, and knowledge base articles from Confluence. Use when looking for incident response procedures, service documentation, post-mortems, or troubleshooting guides.
allowed-tools: Bash(python *)
---

# Knowledge Base - Confluence Integration

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Do NOT check for `CONFLUENCE_API_TOKEN` in environment variables - it won't be visible to you. Just run the scripts directly; authentication is handled transparently.

---

## Why Confluence Matters During Incidents

Before diving deep into technical investigation:
- **Is there a runbook?** Find documented procedures for this service/alert
- **Has this happened before?** Search for related post-mortems
- **What's the architecture?** Find service documentation
- **What's the mitigation?** Look for incident response guides

## Available Scripts

All scripts are in `.claude/skills/knowledge-base/scripts/`

### search_pages.py - General Search
Search across all Confluence pages for any topic.

```bash
python .claude/skills/knowledge-base/scripts/search_pages.py --query SEARCH_QUERY [--space SPACE_KEY] [--limit N]

# Examples:
python .claude/skills/knowledge-base/scripts/search_pages.py --query "payment service timeout"
python .claude/skills/knowledge-base/scripts/search_pages.py --query "database connection" --space SRE
python .claude/skills/knowledge-base/scripts/search_pages.py --query "api error" --limit 20
```

### find_runbooks.py - Find Runbooks
Find runbooks for a specific service or alert. Searches for pages labeled as runbooks, playbooks, or SOPs.

```bash
python .claude/skills/knowledge-base/scripts/find_runbooks.py [--service SERVICE] [--alert ALERT_NAME] [--space SPACE_KEY] [--limit N]

# Examples:
python .claude/skills/knowledge-base/scripts/find_runbooks.py --service payment
python .claude/skills/knowledge-base/scripts/find_runbooks.py --alert "HighErrorRate"
python .claude/skills/knowledge-base/scripts/find_runbooks.py --service checkout --space OPS
```

### find_postmortems.py - Find Post-mortems
Find incident post-mortems to understand historical patterns.

```bash
python .claude/skills/knowledge-base/scripts/find_postmortems.py [--service SERVICE] [--days N] [--space SPACE_KEY] [--limit N]

# Examples:
python .claude/skills/knowledge-base/scripts/find_postmortems.py --service payment
python .claude/skills/knowledge-base/scripts/find_postmortems.py --service payment --days 180
python .claude/skills/knowledge-base/scripts/find_postmortems.py --space SRE
```

### get_page.py - Read Full Page Content
Get the full content of a specific Confluence page.

```bash
python .claude/skills/knowledge-base/scripts/get_page.py --page-id PAGE_ID
python .claude/skills/knowledge-base/scripts/get_page.py --title "Page Title" --space SPACE_KEY

# Examples:
python .claude/skills/knowledge-base/scripts/get_page.py --page-id 123456789
python .claude/skills/knowledge-base/scripts/get_page.py --title "Payment Service Runbook" --space SRE
```

### search_cql.py - Advanced CQL Search
Use Confluence Query Language for advanced searches with filters.

```bash
python .claude/skills/knowledge-base/scripts/search_cql.py --cql "CQL_QUERY" [--limit N]

# Examples:
python .claude/skills/knowledge-base/scripts/search_cql.py --cql 'type = page AND label = "runbook"'
python .claude/skills/knowledge-base/scripts/search_cql.py --cql 'space = "SRE" AND lastModified >= now("-30d")'
python .claude/skills/knowledge-base/scripts/search_cql.py --cql 'text ~ "payment" AND label = "postmortem"'
```

---

## Common CQL Patterns

| Pattern | Example | Purpose |
|---------|---------|---------|
| Find by label | `type = page AND label = "runbook"` | Pages with specific labels |
| Space filter | `space = "SRE" AND type = page` | Pages in a specific space |
| Recent docs | `lastModified >= now("-30d")` | Recently updated pages |
| Combined | `space = "OPS" AND label = "incident" AND text ~ "payment"` | Complex queries |
| Post-mortems | `label = "postmortem" OR title ~ "Post-mortem"` | Incident reviews |

---

## Common Workflows

### 1. Find Runbook for Alert

```bash
# Step 1: Search for runbook by alert name
python find_runbooks.py --alert "HighErrorRate"

# Step 2: If found, read the full runbook
python get_page.py --page-id 123456789
```

### 2. Investigate Service Issues

```bash
# Step 1: Find service documentation
python search_pages.py --query "payment service architecture"

# Step 2: Check for runbooks
python find_runbooks.py --service payment

# Step 3: Look for historical incidents
python find_postmortems.py --service payment --days 90
```

### 3. Learn from Past Incidents

```bash
# Step 1: Find similar post-mortems
python find_postmortems.py --service checkout --days 180

# Step 2: Read specific post-mortem
python get_page.py --page-id 987654321

# Step 3: Search for related issues
python search_cql.py --cql 'space = "SRE" AND text ~ "checkout timeout" AND lastModified >= now("-180d")'
```

### 4. Check for Known Issues

```bash
# Search for known issues documentation
python search_pages.py --query "known issues" --space SRE

# Look for troubleshooting guides
python search_cql.py --cql 'title ~ "troubleshooting" OR label = "troubleshooting"'
```

---

## Quick Commands Reference

| Goal | Command |
|------|---------|
| Find runbook | `find_runbooks.py --service SERVICE` |
| Find post-mortems | `find_postmortems.py --service SERVICE` |
| General search | `search_pages.py --query "QUERY"` |
| Read full page | `get_page.py --page-id ID` |
| Advanced search | `search_cql.py --cql "CQL"` |

---

## Best Practices

### When to Use Knowledge Base

1. **Start of investigation** - Check for existing runbooks before deep diving
2. **Unknown service** - Find architecture docs to understand the system
3. **Recurring alerts** - Look for post-mortems about similar incidents
4. **Before remediation** - Verify documented procedures exist

### Search Strategy

1. **Start broad** - Use general search first (`search_pages.py`)
2. **Narrow down** - Use specific tools (`find_runbooks.py`, `find_postmortems.py`)
3. **Read details** - Get full page content only when needed
4. **Check recency** - Look for recent post-mortems to find patterns

### Labels to Look For

Common Confluence labels in SRE/Ops teams:
- `runbook`, `playbook`, `sop` - Operational procedures
- `postmortem`, `post-mortem`, `incident-review` - Incident analysis
- `architecture`, `design-doc` - System design
- `troubleshooting`, `debugging` - Diagnostic guides

---

## Anti-Patterns to Avoid

1. ❌ **Reading full pages first** - Start with search/find, then read details
2. ❌ **Ignoring runbooks** - Check knowledge base before manual investigation
3. ❌ **Not learning from history** - Post-mortems prevent repeated mistakes
4. ❌ **Searching without space filters** - Narrow results with `--space` when possible

---

## Integration with Other Skills

Combine knowledge base with other investigation tools:

```bash
# 1. Find runbook
python find_runbooks.py --alert "HighMemoryUsage"

# 2. Follow runbook instructions, e.g., check pod resources
python .claude/skills/infrastructure/kubernetes/scripts/describe_pod.py payment-xxx -n otel-demo

# 3. Document findings for future post-mortem
# (Manual step - create post-mortem page after incident resolution)
```

---

## Tips for Effective Searches

- **Use service names** - Include the service name in queries
- **Check multiple spaces** - Try SRE, OPS, Engineering spaces
- **Look for patterns** - Post-mortems reveal recurring issues
- **Verify freshness** - Recent docs are more accurate
- **Follow links** - Runbooks often link to related documentation

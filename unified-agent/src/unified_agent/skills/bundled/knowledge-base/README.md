# Knowledge Base Skill - Confluence Integration

Search runbooks, documentation, and knowledge base articles from Confluence during incident investigations.

## Quick Start

```bash
# Find a runbook for a service
python scripts/find_runbooks.py --service payment

# Search for post-mortems about similar incidents
python scripts/find_postmortems.py --service checkout --days 90

# General search across documentation
python scripts/search_pages.py --query "api timeout troubleshooting"

# Read a full runbook
python scripts/get_page.py --page-id 123456789
```

## Authentication

Credentials are automatically injected by the credential proxy. Scripts work in both:
- **Production**: Credentials injected via `CONFLUENCE_BASE_URL` proxy
- **Local development**: Fallback to `CONFLUENCE_URL`, `CONFLUENCE_EMAIL`, `CONFLUENCE_API_TOKEN` environment variables

## Integration with Incident Investigation

1. **Check for runbooks first** - Before deep diving into logs/metrics
2. **Learn from history** - Search post-mortems for similar incidents
3. **Find architecture docs** - Understand the system before debugging
4. **Document findings** - Use knowledge base to inform post-mortem creation

## Scripts

- **search_pages.py** - General text search across Confluence
- **find_runbooks.py** - Find runbooks by service/alert with relevance scoring
- **find_postmortems.py** - Find incident post-mortems with time filtering
- **get_page.py** - Read full page content (HTML or plain text)
- **search_cql.py** - Advanced search with Confluence Query Language

See `SKILL.md` for detailed usage instructions and examples.

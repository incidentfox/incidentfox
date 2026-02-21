"""
Confluence Integration Scanner.

Scans a Confluence workspace for operational knowledge:
- Runbooks, incident response docs, postmortems, architecture pages

Calls the Confluence REST API directly using credentials fetched from config_service.
"""

import json
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional

from . import Document, register_scanner


def _log(event: str, **fields) -> None:
    payload = {
        "timestamp": datetime.utcnow().isoformat(),
        "service": "ai-learning-pipeline",
        "module": "scanners.confluence",
        "event": event,
        **fields,
    }
    print(json.dumps(payload, default=str))


# Search queries to find ops-relevant pages
OPS_SEARCH_QUERIES = [
    "runbook",
    "incident response",
    "on-call",
    "postmortem",
    "architecture",
    "deployment",
    "troubleshooting",
]

MAX_PAGES_PER_QUERY = 10
MAX_CONTENT_SIZE = 200_000  # 200KB


def _confluence_api(
    base_url: str,
    path: str,
    email: str,
    api_token: str,
    params: Optional[Dict[str, str]] = None,
) -> Optional[Dict[str, Any]]:
    """Make a Confluence Cloud REST API request."""
    url = f"{base_url.rstrip('/')}/wiki/rest/api{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"

    req = urllib.request.Request(url)
    # Confluence Cloud uses email:api_token basic auth
    import base64

    credentials = base64.b64encode(f"{email}:{api_token}".encode()).decode()
    req.add_header("Authorization", f"Basic {credentials}")
    req.add_header("Accept", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        _log("confluence_api_error", path=path, status=e.code)
        return None
    except Exception as e:
        _log("confluence_api_failed", path=path, error=str(e))
        return None


def _search_pages(
    base_url: str,
    email: str,
    api_token: str,
    query: str,
    limit: int = MAX_PAGES_PER_QUERY,
) -> List[Dict[str, Any]]:
    """Search for Confluence pages by CQL query."""
    data = _confluence_api(
        base_url,
        "/content/search",
        email,
        api_token,
        {
            "cql": f'type=page AND text~"{query}"',
            "limit": str(limit),
            "expand": "body.storage,version",
        },
    )
    if not data:
        return []
    return data.get("results", [])


def _html_to_text(html: str) -> str:
    """Strip HTML tags for plain-text extraction (simple approach)."""
    import re

    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text


@register_scanner("confluence")
async def scan(
    credentials: Dict[str, Any],
    config: Dict[str, Any],
    org_id: str,
) -> List[Document]:
    """
    Scan Confluence for operational documents.

    Args:
        credentials: Decrypted credentials (api_key/api_token, email/username)
        config: Integration config (base_url/url/domain)
        org_id: IncidentFox org ID
    """
    api_token = credentials.get("api_key") or credentials.get("api_token", "")
    email = credentials.get("email") or credentials.get("username", "")
    base_url = config.get("base_url") or config.get("url") or config.get("domain", "")

    if not api_token or not email:
        _log("no_confluence_credentials")
        return []

    if not base_url:
        _log("no_confluence_url")
        return []

    # Ensure base_url has scheme
    if not base_url.startswith("http"):
        base_url = f"https://{base_url}"

    _log("confluence_scan_started", base_url=base_url)

    seen_ids: set = set()
    documents: List[Document] = []

    for query in OPS_SEARCH_QUERIES:
        pages = _search_pages(base_url, email, api_token, query)

        for page in pages:
            page_id = page.get("id", "")
            if page_id in seen_ids:
                continue
            seen_ids.add(page_id)

            title = page.get("title", "Untitled")
            body_html = page.get("body", {}).get("storage", {}).get("value", "")
            if not body_html:
                continue

            content = _html_to_text(body_html)
            if len(content) < 50 or len(content) > MAX_CONTENT_SIZE:
                continue

            page_url = (
                f"{base_url.rstrip('/')}/wiki{page.get('_links', {}).get('webui', '')}"
            )

            documents.append(
                Document(
                    content=content,
                    source_url=page_url,
                    content_type="text",  # HTML already stripped to plain text
                    metadata={
                        "title": title,
                        "page_id": page_id,
                        "org_id": org_id,
                        "source": "integration_scan",
                        "search_query": query,
                    },
                )
            )

    _log(
        "confluence_scan_completed",
        pages_found=len(documents),
        queries_run=len(OPS_SEARCH_QUERIES),
    )
    return documents

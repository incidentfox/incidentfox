"""Confluence documentation tools."""

import os
from typing import Any

import json
import logging

from ..core.agent import function_tool
from . import register_tool


logger = logging.getLogger(__name__)


def _get_confluence_config() -> str:
    """Get Confluence configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    # Credentials from environment variables
    # 2. Try environment variables (dev/testing fallback)
    if os.getenv("CONFLUENCE_URL") and os.getenv("CONFLUENCE_API_TOKEN"):
        return {
            "url": os.getenv("CONFLUENCE_URL"),
            "username": os.getenv("CONFLUENCE_USERNAME"),
            "api_token": os.getenv("CONFLUENCE_API_TOKEN"),
        }

    # 3. Not configured - raise error
    return {"error": "confluence not configured"}


def _get_confluence_client():
    """Get Confluence client."""
    try:
        from atlassian import Confluence

        config = _get_confluence_config()

        return Confluence(
            url=config["url"],
            username=config.get("username"),
            password=config["api_token"],
            cloud=True,
        )

    except ImportError:
        return json.dumps({"ok": False, "error": "confluence"})


@function_tool
def search_confluence(
    query: str, space: str | None = None, limit: int = 10
) -> str:
    """
    Search Confluence pages.

    Args:
        query: Search query
        space: Optional space key to limit search
        limit: Max results

    Returns:
        List of matching pages
    """
    try:
        confluence = _get_confluence_client()

        cql = f'text ~ "{query}"'
        if space:
            cql += f' AND space = "{space}"'

        results = confluence.cql(cql, limit=limit)

        pages = []
        for result in results.get("results", []):
            pages.append(
                {
                    "title": result["content"]["title"],
                    "space": result["content"]["space"]["key"],
                    "url": result["url"],
                    "excerpt": result.get("excerpt", ""),
                    "last_modified": result["lastModified"],
                }
            )

        logger.info("confluence_search_completed", query=query, results=len(pages))
        return pages

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except Exception as e:
        logger.error("confluence_search_failed", error=str(e), query=query)
        return json.dumps({"ok": False, "error": "search_confluence"})


@function_tool
def get_confluence_page(
    page_id: str | None = None, title: str | None = None, space: str | None = None
) -> str:
    """
    Get a Confluence page by ID or title.

    Args:
        page_id: Page ID
        title: Page title (if page_id not provided)
        space: Space key (required if using title)

    Returns:
        Page content and metadata
    """
    try:
        confluence = _get_confluence_client()

        if page_id:
            page = confluence.get_page_by_id(
                page_id, expand="body.storage,version,space"
            )
        elif title and space:
            page = confluence.get_page_by_title(
                space=space, title=title, expand="body.storage,version"
            )
        else:
            raise ValueError("Must provide page_id or (title and space)")

        return {
            "id": page["id"],
            "title": page["title"],
            "space": page["space"]["key"],
            "content": page["body"]["storage"]["value"],
            "version": page["version"]["number"],
            "url": f"{confluence.url}/wiki{page['_links']['webui']}",
        }

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except Exception as e:
        logger.error("confluence_get_page_failed", error=str(e))
        return json.dumps({"ok": False, "error": "get_confluence_page"})


@function_tool
def list_space_pages(space: str, limit: int = 25) -> str:
    """
    List pages in a Confluence space.

    Args:
        space: Space key
        limit: Max pages to return

    Returns:
        List of pages
    """
    try:
        confluence = _get_confluence_client()
        pages = confluence.get_all_pages_from_space(space, limit=limit)

        page_list = []
        for page in pages:
            page_list.append(
                {
                    "id": page["id"],
                    "title": page["title"],
                    "url": page["_links"]["webui"],
                }
            )

        logger.info("confluence_pages_listed", space=space, count=len(page_list))
        return page_list

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except Exception as e:
        logger.error("confluence_list_failed", error=str(e), space=space)
        return json.dumps({"ok": False, "error": "list_space_pages"})


@function_tool
def confluence_create_page(
    space: str, title: str, content: str, parent_id: str | None = None
) -> str:
    """
    Create a new Confluence page.

    Args:
        space: Space key to create page in
        title: Page title
        content: Page content in Confluence storage format (HTML)
        parent_id: Optional parent page ID

    Returns:
        Created page details including ID and URL
    """
    try:
        confluence = _get_confluence_client()

        # Convert markdown-like content to Confluence HTML if needed
        # Simple conversion - for full markdown support, use a markdown library
        html_content = content.replace("\n", "<br/>")
        html_content = f"<p>{html_content}</p>"

        page = confluence.create_page(
            space=space, title=title, body=html_content, parent_id=parent_id
        )

        logger.info("confluence_page_created", page_id=page["id"], title=title)

        return {
            "id": page["id"],
            "title": page["title"],
            "space": space,
            "url": f"{confluence.url}/wiki{page['_links']['webui']}",
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except Exception as e:
        logger.error("confluence_create_page_failed", error=str(e), title=title)
        return json.dumps({"ok": False, "error": "confluence_create_page"})


@function_tool
def confluence_write_content(
    page_id: str, content: str, append: bool = False
) -> str:
    """
    Write or append content to an existing Confluence page.

    Args:
        page_id: Page ID to update
        content: Content to write
        append: If True, append to existing content; if False, replace

    Returns:
        Update result
    """
    try:
        confluence = _get_confluence_client()

        # Get current page
        page = confluence.get_page_by_id(page_id, expand="body.storage,version")

        # Convert content to HTML
        html_content = content.replace("\n", "<br/>")
        html_content = f"<p>{html_content}</p>"

        if append:
            # Append to existing content
            new_content = page["body"]["storage"]["value"] + html_content
        else:
            # Replace content
            new_content = html_content

        # Update page
        confluence.update_page(
            page_id=page_id,
            title=page["title"],
            body=new_content,
            version_number=page["version"]["number"] + 1,
        )

        logger.info("confluence_content_written", page_id=page_id, length=len(content))

        return {
            "page_id": page_id,
            "success": True,
            "characters_written": len(content),
        }

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except Exception as e:
        logger.error("confluence_write_failed", error=str(e), page_id=page_id)
        return json.dumps({"ok": False, "error": "confluence_write_content"})


@function_tool
def confluence_get_page(
    page_id: str | None = None, title: str | None = None, space: str | None = None
) -> str:
    """
    Get a Confluence page by ID or title.

    Args:
        page_id: Page ID
        title: Page title (if page_id not provided)
        space: Space key (required if using title)

    Returns:
        Page content and metadata
    """
    try:
        confluence = _get_confluence_client()

        if page_id:
            page = confluence.get_page_by_id(
                page_id, expand="body.storage,version,space"
            )
        elif title and space:
            page = confluence.get_page_by_title(
                space=space, title=title, expand="body.storage,version"
            )
        else:
            raise ValueError("Must provide page_id or (title and space)")

        return {
            "id": page["id"],
            "title": page["title"],
            "space": page["space"]["key"],
            "content": page["body"]["storage"]["value"],
            "version": page["version"]["number"],
            "url": f"{confluence.url}/wiki{page['_links']['webui']}",
        }

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except Exception as e:
        logger.error("confluence_get_page_failed", error=str(e))
        return json.dumps({"ok": False, "error": "confluence_get_page"})


@function_tool
def confluence_search_cql(
    cql: str,
    limit: int = 25,
    expand: str | None = None,
) -> str:
    """
    Search Confluence using CQL (Confluence Query Language).

    More powerful than text search - supports filtering by space, type,
    labels, dates, etc. Useful for finding runbooks, post-mortems, and
    incident documentation.

    Common CQL patterns:
    - Find runbooks: 'type = page AND label = "runbook"'
    - Find post-mortems: 'type = page AND (label = "postmortem" OR title ~ "Post-mortem")'
    - Find by space: 'space = "OPS" AND type = page'
    - Find recent: 'lastModified >= now("-30d") AND type = page'
    - Combined: 'space = "SRE" AND label = "incident" AND lastModified >= now("-90d")'

    Args:
        cql: CQL query string
        limit: Maximum results to return
        expand: Optional fields to expand (e.g., "body.storage")

    Returns:
        Dict with search results and metadata
    """
    try:
        confluence = _get_confluence_client()

        results = confluence.cql(cql, limit=limit, expand=expand)

        pages = []
        for result in results.get("results", []):
            content = result.get("content", result)  # Handle different response formats

            page_data = {
                "id": content.get("id"),
                "title": content.get("title"),
                "type": content.get("type"),
                "space": (
                    content.get("space", {}).get("key")
                    if content.get("space")
                    else None
                ),
                "url": result.get("url") or content.get("_links", {}).get("webui"),
                "excerpt": result.get("excerpt", ""),
                "last_modified": result.get("lastModified")
                or content.get("history", {}).get("lastUpdated", {}).get("when"),
            }

            # Include labels if available
            if "metadata" in content and "labels" in content["metadata"]:
                page_data["labels"] = [
                    label["name"]
                    for label in content["metadata"]["labels"].get("results", [])
                ]

            pages.append(page_data)

        logger.info(
            "confluence_cql_search_completed", cql=cql[:100], results=len(pages)
        )

        return {
            "success": True,
            "cql": cql,
            "total_results": results.get("totalSize", len(pages)),
            "returned_results": len(pages),
            "pages": pages,
        }

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except Exception as e:
        logger.error("confluence_cql_search_failed", error=str(e), cql=cql[:100])
        return json.dumps({"ok": False, "error": "confluence_search_cql"})


@function_tool
def confluence_find_runbooks(
    service: str | None = None,
    alert_name: str | None = None,
    space: str | None = None,
    limit: int = 10,
) -> str:
    """
    Find runbooks in Confluence for a service or alert.

    Searches for runbook documentation using common labeling and naming
    conventions. Useful for incident response and alert fatigue analysis
    to understand if alerts have proper runbooks.

    Args:
        service: Service name to search for
        alert_name: Alert name to search for
        space: Optional space to limit search
        limit: Maximum results

    Returns:
        Dict with matching runbooks
    """
    try:
        confluence = _get_confluence_client()

        # Build search query
        search_terms = []

        if service:
            search_terms.append(f'(title ~ "{service}" OR text ~ "{service}")')
        if alert_name:
            search_terms.append(f'(title ~ "{alert_name}" OR text ~ "{alert_name}")')

        # Look for runbook labels/titles
        runbook_filter = '(label = "runbook" OR label = "playbook" OR label = "sop" OR title ~ "runbook" OR title ~ "playbook")'

        cql_parts = [runbook_filter]
        if search_terms:
            cql_parts.append(f"({' OR '.join(search_terms)})")
        if space:
            cql_parts.append(f'space = "{space}"')

        cql = " AND ".join(cql_parts) + " AND type = page"

        results = confluence.cql(cql, limit=limit, expand="metadata.labels")

        runbooks = []
        for result in results.get("results", []):
            content = result.get("content", result)

            runbooks.append(
                {
                    "id": content.get("id"),
                    "title": content.get("title"),
                    "space": (
                        content.get("space", {}).get("key")
                        if content.get("space")
                        else None
                    ),
                    "url": result.get("url"),
                    "excerpt": result.get("excerpt", "")[:300],
                    "relevance": (
                        "high"
                        if service
                        and service.lower() in content.get("title", "").lower()
                        else "medium"
                    ),
                }
            )

        logger.info(
            "confluence_runbooks_found",
            service=service,
            alert=alert_name,
            count=len(runbooks),
        )

        return {
            "success": True,
            "search": {"service": service, "alert_name": alert_name, "space": space},
            "runbooks_found": len(runbooks),
            "runbooks": runbooks,
            "has_runbook": len(runbooks) > 0,
        }

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except Exception as e:
        logger.error(
            "confluence_find_runbooks_failed",
            error=str(e),
            service=service,
        )
        return json.dumps({"ok": False, "error": "confluence_find_runbooks"})


@function_tool
def confluence_find_postmortems(
    service: str | None = None,
    since_days: int = 90,
    space: str | None = None,
    limit: int = 20,
) -> str:
    """
    Find post-mortem documents in Confluence.

    Searches for incident post-mortems to understand historical incident
    patterns. Useful for alert fatigue analysis to identify recurring issues.

    Args:
        service: Service name to filter by
        since_days: Look back this many days (default 90)
        space: Optional space to limit search
        limit: Maximum results

    Returns:
        Dict with post-mortem documents
    """
    try:
        confluence = _get_confluence_client()

        # Build CQL query
        cql_parts = [
            f'lastModified >= now("-{since_days}d")',
            "type = page",
            '(label = "postmortem" OR label = "post-mortem" OR label = "incident-review" OR title ~ "Post-mortem" OR title ~ "Postmortem" OR title ~ "Incident Review")',
        ]

        if service:
            cql_parts.append(f'(title ~ "{service}" OR text ~ "{service}")')
        if space:
            cql_parts.append(f'space = "{space}"')

        cql = " AND ".join(cql_parts)

        results = confluence.cql(cql, limit=limit)

        postmortems = []
        for result in results.get("results", []):
            content = result.get("content", result)

            postmortems.append(
                {
                    "id": content.get("id"),
                    "title": content.get("title"),
                    "space": (
                        content.get("space", {}).get("key")
                        if content.get("space")
                        else None
                    ),
                    "url": result.get("url"),
                    "last_modified": result.get("lastModified"),
                    "excerpt": result.get("excerpt", "")[:300],
                }
            )

        logger.info(
            "confluence_postmortems_found",
            service=service,
            count=len(postmortems),
        )

        return {
            "success": True,
            "search": {"service": service, "since_days": since_days, "space": space},
            "postmortems_found": len(postmortems),
            "postmortems": postmortems,
        }

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except Exception as e:
        logger.error(
            "confluence_find_postmortems_failed",
            error=str(e),
            service=service,
        )
        return json.dumps({"ok": False, "error": "confluence_find_postmortems"})


# List of all Confluence tools for registration
CONFLUENCE_TOOLS = [
    search_confluence,
    confluence_get_page,
    list_space_pages,
    confluence_create_page,
    confluence_write_content,
    confluence_search_cql,
    confluence_find_runbooks,
    confluence_find_postmortems,
]


# Register tools
register_tool("search_confluence", search_confluence)
register_tool("get_confluence_page", get_confluence_page)
register_tool("list_space_pages", list_space_pages)
register_tool("confluence_create_page", confluence_create_page)
register_tool("confluence_write_content", confluence_write_content)
register_tool("confluence_get_page", confluence_get_page)
register_tool("confluence_search_cql", confluence_search_cql)
register_tool("confluence_find_runbooks", confluence_find_runbooks)
register_tool("confluence_find_postmortems", confluence_find_postmortems)

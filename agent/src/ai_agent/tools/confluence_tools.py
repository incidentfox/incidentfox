"""Confluence documentation tools."""

import os
from typing import Any

from ..core.config_required import handle_integration_not_configured
from ..core.errors import ToolExecutionError
from ..core.execution_context import get_execution_context
from ..core.integration_errors import IntegrationNotConfiguredError
from ..core.logging import get_logger

logger = get_logger(__name__)


def _get_confluence_config() -> dict:
    """Get Confluence configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("confluence")
        if config and config.get("url") and config.get("api_token"):
            return config

    # 2. Try environment variables (dev/testing fallback)
    if os.getenv("CONFLUENCE_URL") and os.getenv("CONFLUENCE_API_TOKEN"):
        return {
            "url": os.getenv("CONFLUENCE_URL"),
            "username": os.getenv("CONFLUENCE_USERNAME"),
            "api_token": os.getenv("CONFLUENCE_API_TOKEN"),
        }

    # 3. Not configured - raise error
    raise IntegrationNotConfiguredError(
        integration_id="confluence",
        tool_id="confluence_tools",
        missing_fields=["url", "username", "api_token"],
    )


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
        raise ToolExecutionError("confluence", "atlassian-python-api not installed")


def search_confluence(
    query: str, space: str | None = None, limit: int = 10
) -> list[dict[str, Any]]:
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
        return handle_integration_not_configured(e, "search_confluence", "confluence")
    except Exception as e:
        logger.error("confluence_search_failed", error=str(e), query=query)
        raise ToolExecutionError("search_confluence", str(e), e)


def get_confluence_page(
    page_id: str | None = None, title: str | None = None, space: str | None = None
) -> dict[str, Any]:
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
        return handle_integration_not_configured(e, "get_confluence_page", "confluence")
    except Exception as e:
        logger.error("confluence_get_page_failed", error=str(e))
        raise ToolExecutionError("get_confluence_page", str(e), e)


def list_space_pages(space: str, limit: int = 25) -> list[dict[str, Any]]:
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
        return handle_integration_not_configured(e, "list_space_pages", "confluence")
    except Exception as e:
        logger.error("confluence_list_failed", error=str(e), space=space)
        raise ToolExecutionError("list_space_pages", str(e), e)


def confluence_create_page(
    space: str, title: str, content: str, parent_id: str | None = None
) -> dict[str, Any]:
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
        return handle_integration_not_configured(
            e, "confluence_create_page", "confluence"
        )
    except Exception as e:
        logger.error("confluence_create_page_failed", error=str(e), title=title)
        raise ToolExecutionError("confluence_create_page", str(e), e)


def confluence_write_content(
    page_id: str, content: str, append: bool = False
) -> dict[str, Any]:
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
        return handle_integration_not_configured(
            e, "confluence_write_content", "confluence"
        )
    except Exception as e:
        logger.error("confluence_write_failed", error=str(e), page_id=page_id)
        raise ToolExecutionError("confluence_write_content", str(e), e)


def confluence_get_page(
    page_id: str | None = None, title: str | None = None, space: str | None = None
) -> dict[str, Any]:
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
        return handle_integration_not_configured(e, "confluence_get_page", "confluence")
    except Exception as e:
        logger.error("confluence_get_page_failed", error=str(e))
        raise ToolExecutionError("confluence_get_page", str(e), e)


# List of all Confluence tools for registration
CONFLUENCE_TOOLS = [
    search_confluence,
    confluence_get_page,
    list_space_pages,
    confluence_create_page,
    confluence_write_content,
]

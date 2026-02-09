"""Notion integration tools for documentation."""

import os
from typing import Any

import json
import logging

from ..core.agent import function_tool
from . import register_tool


logger = logging.getLogger(__name__)


def _get_notion_config() -> str:
    """Get Notion configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    # Credentials from environment variables
    # 2. Try environment variables (dev/testing fallback)
    if os.getenv("NOTION_API_KEY"):
        return {"api_key": os.getenv("NOTION_API_KEY")}

    # 3. Not configured - raise error
    return {"error": "notion not configured"}


def _get_notion_client():
    """Get Notion client."""
    try:
        from notion_client import Client

        config = _get_notion_config()
        return Client(auth=config["api_key"])

    except ImportError:
        return json.dumps({"ok": False, "error": "Tool execution error"})
            "notion",
            "notion-client package not installed. Install with: poetry add notion-client",
        )


@function_tool
def notion_create_page(
    parent_page_id: str | None = None,
    parent_database_id: str | None = None,
    title: str = "Untitled",
    content: str = "",
) -> str:
    """
    Create a new Notion page.

    Args:
        parent_page_id: Parent page ID (use this OR parent_database_id)
        parent_database_id: Parent database ID
        title: Page title
        content: Page content (markdown-like text)

    Returns:
        Created page details including ID and URL
    """
    try:
        notion = _get_notion_client()

        # Set parent
        if parent_database_id:
            parent = {"database_id": parent_database_id}
        elif parent_page_id:
            parent = {"page_id": parent_page_id}
        else:
            raise ValueError("Must provide parent_page_id or parent_database_id")

        # Build page properties
        properties = {"title": {"title": [{"text": {"content": title}}]}}

        # Build content blocks
        children = []
        if content:
            # Split into paragraphs
            paragraphs = content.split("\n\n")
            for para in paragraphs:
                if para.strip():
                    children.append(
                        {
                            "object": "block",
                            "type": "paragraph",
                            "paragraph": {
                                "rich_text": [
                                    {"type": "text", "text": {"content": para.strip()}}
                                ]
                            },
                        }
                    )

        page = notion.pages.create(
            parent=parent,
            properties=properties,
            children=children if children else None,
        )

        logger.info("notion_page_created", page_id=page["id"], title=title)

        return {
            "id": page["id"],
            "url": page["url"],
            "title": title,
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except Exception as e:
        logger.error("notion_create_page_failed", error=str(e), title=title)
        return json.dumps({"ok": False, "error": "notion_create_page"})


@function_tool
def notion_write_content(
    page_id: str, content: str, append: bool = True
) -> str:
    """
    Write or append content to a Notion page.

    Args:
        page_id: Notion page ID
        content: Content to write
        append: If True, append to page; if False, replace content

    Returns:
        Write operation result
    """
    try:
        notion = _get_notion_client()

        # Build content blocks
        children = []
        paragraphs = content.split("\n\n")
        for para in paragraphs:
            if para.strip():
                children.append(
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [
                                {"type": "text", "text": {"content": para.strip()}}
                            ]
                        },
                    }
                )

        if not append:
            # Get existing blocks and delete them
            blocks = notion.blocks.children.list(block_id=page_id)
            for block in blocks.get("results", []):
                notion.blocks.delete(block_id=block["id"])

        # Append new blocks
        notion.blocks.children.append(block_id=page_id, children=children)

        logger.info("notion_content_written", page_id=page_id, blocks=len(children))

        return {
            "page_id": page_id,
            "success": True,
            "blocks_added": len(children),
        }

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except Exception as e:
        logger.error("notion_write_failed", error=str(e), page_id=page_id)
        return json.dumps({"ok": False, "error": "notion_write_content"})


@function_tool
def notion_search(query: str, max_results: int = 10) -> str:
    """
    Search Notion pages.

    Args:
        query: Search query
        max_results: Maximum results to return

    Returns:
        List of matching pages
    """
    try:
        notion = _get_notion_client()

        response = notion.search(query=query, page_size=max_results)

        results = []
        for item in response.get("results", []):
            if item["object"] == "page":
                title = ""
                if "properties" in item and "title" in item["properties"]:
                    title_prop = item["properties"]["title"]
                    if "title" in title_prop and title_prop["title"]:
                        title = title_prop["title"][0]["text"]["content"]

                results.append(
                    {
                        "id": item["id"],
                        "title": title,
                        "url": item.get("url"),
                        "last_edited": item.get("last_edited_time"),
                    }
                )

        logger.info("notion_search_completed", query=query, results=len(results))
        return results

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except Exception as e:
        logger.error("notion_search_failed", error=str(e), query=query)
        return json.dumps({"ok": False, "error": "notion_search"})


# List of all Notion tools for registration
NOTION_TOOLS = [
    notion_create_page,
    notion_write_content,
    notion_search,
]


# Register tools
register_tool("notion_create_page", notion_create_page)
register_tool("notion_write_content", notion_write_content)
register_tool("notion_search", notion_search)

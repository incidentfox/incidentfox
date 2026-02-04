"""Shared Confluence API client with credential proxy support.

This client is designed to work with the IncidentFox credential proxy.
Credentials are injected automatically by the proxy - scripts never see API tokens.

Two modes:
1. Proxy mode (production): Routes requests through CONFLUENCE_BASE_URL proxy
   which injects Basic auth headers automatically
2. Direct mode (local dev): Uses CONFLUENCE_* environment variables directly
"""

import json
import os
from pathlib import Path
from typing import Any

import httpx


def get_config() -> dict[str, Any]:
    """Load configuration from standard locations."""
    config = {}

    # Check for config file
    config_paths = [
        Path.home() / ".incidentfox" / "config.json",
        Path("/etc/incidentfox/config.json"),
    ]

    for path in config_paths:
        if path.exists():
            with open(path) as f:
                config = json.load(f)
                break

    # Environment overrides
    if os.getenv("INCIDENTFOX_TENANT_ID"):
        config["tenant_id"] = os.getenv("INCIDENTFOX_TENANT_ID")
    if os.getenv("INCIDENTFOX_TEAM_ID"):
        config["team_id"] = os.getenv("INCIDENTFOX_TEAM_ID")

    return config


def get_api_url(path: str) -> str:
    """Build the Confluence API URL.

    Supports two modes:
    1. Proxy mode (production): Uses credential-resolver's reverse proxy
       The path /wiki/... is sent to http://credential-resolver:8002/confluence/wiki/...
    2. Direct mode (local dev): Uses CONFLUENCE_URL with local credentials

    Args:
        path: API path (e.g., "/wiki/rest/api/content/search")

    Returns:
        Full API URL
    """
    # Proxy mode (production) - requests go through credential-resolver's proxy
    # The credential-resolver has a /confluence/* endpoint that proxies to the
    # actual Confluence instance with auth injected
    proxy_url = os.getenv("CONFLUENCE_BASE_URL")
    if proxy_url:
        # CONFLUENCE_BASE_URL points to credential-resolver
        # e.g., http://credential-resolver:8002/confluence
        return f"{proxy_url.rstrip('/')}{path}"

    # Direct mode (local dev) - requires CONFLUENCE_URL and credentials
    url = os.getenv("CONFLUENCE_URL")
    if url:
        # Remove trailing /wiki if present (we add it in the path)
        url = url.rstrip("/")
        if url.endswith("/wiki"):
            url = url[:-5]
        return f"{url}{path}"

    raise RuntimeError(
        "No Confluence URL configured. Either:\n"
        "  - Set CONFLUENCE_BASE_URL for proxy mode (production), or\n"
        "  - Set CONFLUENCE_URL for direct mode (local development)"
    )


def get_headers() -> dict[str, str]:
    """Get request headers for Confluence API.

    In proxy mode: includes tenant context for credential lookup.
    In direct mode: includes Basic auth directly.
    """
    config = get_config()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # Check if we're in direct mode (have credentials locally)
    email = os.getenv("CONFLUENCE_EMAIL")
    api_token = os.getenv("CONFLUENCE_API_TOKEN")

    if email and api_token and not os.getenv("CONFLUENCE_BASE_URL"):
        # Direct mode - add Basic auth
        import base64

        auth_string = f"{email}:{api_token}"
        encoded = base64.b64encode(auth_string.encode()).decode()
        headers["Authorization"] = f"Basic {encoded}"
    else:
        # Proxy mode - add JWT for authentication with credential-resolver
        # The JWT contains tenant/team context and is validated by credential-resolver
        sandbox_jwt = os.getenv("SANDBOX_JWT")
        if sandbox_jwt:
            headers["X-Sandbox-JWT"] = sandbox_jwt
        else:
            # Fallback to tenant headers (for local dev without JWT)
            headers["X-Tenant-Id"] = config.get("tenant_id") or "local"
            headers["X-Team-Id"] = config.get("team_id") or "local"

    return headers


def search_content(
    cql: str,
    limit: int = 25,
    expand: str | None = None,
) -> dict[str, Any]:
    """Search Confluence using CQL (Confluence Query Language).

    Args:
        cql: CQL query string
        limit: Maximum results to return
        expand: Optional fields to expand (comma-separated)

    Returns:
        Search results with 'results' array
    """
    params = {
        "cql": cql,
        "limit": limit,
    }
    if expand:
        params["expand"] = expand

    url = get_api_url("/wiki/rest/api/content/search")

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, headers=get_headers(), params=params)
        response.raise_for_status()
        return response.json()


def cql_search(
    cql: str,
    limit: int = 25,
    expand: str | None = None,
) -> dict[str, Any]:
    """Search using the CQL endpoint (alternative to content/search).

    Args:
        cql: CQL query string
        limit: Maximum results to return
        expand: Optional fields to expand

    Returns:
        Search results
    """
    params = {
        "cql": cql,
        "limit": limit,
    }
    if expand:
        params["expand"] = expand

    url = get_api_url("/wiki/rest/api/search")

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, headers=get_headers(), params=params)
        response.raise_for_status()
        return response.json()


def get_page_by_id(
    page_id: str,
    expand: str = "body.storage,version,space",
) -> dict[str, Any]:
    """Get a Confluence page by ID.

    Args:
        page_id: Page ID
        expand: Fields to expand (comma-separated)

    Returns:
        Page data
    """
    url = get_api_url(f"/wiki/rest/api/content/{page_id}")
    params = {"expand": expand}

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, headers=get_headers(), params=params)
        response.raise_for_status()
        return response.json()


def get_page_by_title(
    space: str,
    title: str,
    expand: str = "body.storage,version,space",
) -> dict[str, Any] | None:
    """Get a Confluence page by title.

    Args:
        space: Space key
        title: Page title
        expand: Fields to expand

    Returns:
        Page data or None if not found
    """
    url = get_api_url("/wiki/rest/api/content")
    params = {
        "spaceKey": space,
        "title": title,
        "expand": expand,
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, headers=get_headers(), params=params)
        response.raise_for_status()
        data = response.json()

        results = data.get("results", [])
        if results:
            return results[0]
        return None


def format_page_result(result: dict[str, Any]) -> dict[str, Any]:
    """Format a CQL search result for consistent output.

    Args:
        result: Raw result from CQL search

    Returns:
        Formatted page data
    """
    # Handle different response formats (search vs content endpoints)
    content = result.get("content", result)

    return {
        "id": content.get("id"),
        "title": content.get("title"),
        "type": content.get("type"),
        "space": content.get("space", {}).get("key") if content.get("space") else None,
        "url": result.get("url") or content.get("_links", {}).get("webui"),
        "excerpt": result.get("excerpt", ""),
        "created": content.get("history", {}).get("createdDate"),
        "updated": result.get("lastModified") or content.get("version", {}).get("when"),
    }


# Legacy compatibility - keep get_confluence_client for scripts that use it
def get_confluence_client():
    """Get Confluence client instance.

    DEPRECATED: This function exists for backward compatibility.
    New code should use the module-level functions directly:
    - search_content()
    - get_page_by_id()
    - get_page_by_title()

    Returns:
        Self (this module acts as the client)
    """
    import sys

    # Return this module as a pseudo-client
    # Functions can be called as confluence_client.search_content(), etc.
    return sys.modules[__name__]

#!/usr/bin/env python3
"""Shared Jira API client with proxy support.

Uses Jira Cloud REST API v3 (Atlassian Document Format for descriptions).
Credentials are injected transparently by the proxy layer.
"""

import base64
import json
import os
import sys
from typing import Any

import httpx


def get_config() -> dict[str, str | None]:
    """Get Jira configuration from environment."""
    return {
        "tenant_id": os.getenv("INCIDENTFOX_TENANT_ID", "local"),
        "team_id": os.getenv("INCIDENTFOX_TEAM_ID", "local"),
        "jira_url": os.getenv("JIRA_URL", ""),
    }


def get_base_url() -> str:
    """Get Jira REST API base URL.

    Supports two modes:
    1. Proxy mode (production): Uses JIRA_BASE_URL
    2. Direct mode (testing): Uses JIRA_URL + /rest/api/3
    """
    proxy_url = os.getenv("JIRA_BASE_URL")
    if proxy_url:
        return proxy_url.rstrip("/")

    jira_url = os.getenv("JIRA_URL")
    if jira_url:
        return f"{jira_url.rstrip('/')}/rest/api/3"

    raise RuntimeError(
        "Either JIRA_BASE_URL (proxy mode) or JIRA_URL (direct mode) must be set."
    )


def get_headers() -> dict[str, str]:
    """Get Jira API headers.

    In proxy mode: includes tenant context for credential lookup.
    In direct mode: includes Basic auth with email + API token.
    """
    config = get_config()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    email = os.getenv("JIRA_EMAIL")
    api_token = os.getenv("JIRA_API_TOKEN")
    if email and api_token:
        credentials = base64.b64encode(f"{email}:{api_token}".encode()).decode()
        headers["Authorization"] = f"Basic {credentials}"
    else:
        sandbox_jwt = os.getenv("SANDBOX_JWT")
        if sandbox_jwt:
            headers["X-Sandbox-JWT"] = sandbox_jwt
        else:
            headers["X-Tenant-Id"] = config.get("tenant_id") or "local"
            headers["X-Team-Id"] = config.get("team_id") or "local"

    return headers


def get_browse_url() -> str | None:
    """Get the Jira browse URL for constructing issue links."""
    if os.getenv("JIRA_BASE_URL"):
        return None
    jira_url = os.getenv("JIRA_URL", "")
    return jira_url.rstrip("/") if jira_url else None


def jira_request(
    method: str,
    path: str,
    params: dict | None = None,
    json_body: dict | None = None,
) -> dict | list | None:
    """Make a request to Jira REST API."""
    base_url = get_base_url()
    url = f"{base_url}/{path.lstrip('/')}"

    with httpx.Client(timeout=30.0) as client:
        response = client.request(
            method,
            url,
            headers=get_headers(),
            params=params,
            json=json_body,
        )
        response.raise_for_status()
        if response.status_code == 204:
            return None
        return response.json()


def make_adf_text(text: str) -> dict:
    """Create Atlassian Document Format (ADF) for a text block."""
    return {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


def extract_adf_text(adf: Any) -> str:
    """Extract plain text from Atlassian Document Format."""
    if isinstance(adf, str):
        return adf
    if not isinstance(adf, dict):
        return ""
    parts = []
    for block in adf.get("content", []):
        for inline in block.get("content", []):
            if inline.get("type") == "text":
                parts.append(inline.get("text", ""))
        parts.append("\n")
    return "\n".join(parts).strip()

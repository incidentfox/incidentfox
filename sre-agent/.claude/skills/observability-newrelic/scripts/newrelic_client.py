#!/usr/bin/env python3
"""Shared New Relic API client with proxy support.

Credentials are injected transparently by the proxy layer.
"""

import json
import os
from typing import Any

import httpx


def get_config() -> dict[str, str | None]:
    """Get New Relic configuration from environment."""
    return {
        "tenant_id": os.getenv("INCIDENTFOX_TENANT_ID", "local"),
        "team_id": os.getenv("INCIDENTFOX_TEAM_ID", "local"),
        "account_id": os.getenv("NEWRELIC_ACCOUNT_ID", ""),
    }


def get_base_url() -> str:
    """Get New Relic API base URL.

    Supports two modes:
    1. Proxy mode (production): Uses NEWRELIC_BASE_URL
    2. Direct mode (testing): Uses https://api.newrelic.com
    """
    proxy_url = os.getenv("NEWRELIC_BASE_URL")
    if proxy_url:
        return proxy_url.rstrip("/")

    if os.getenv("NEWRELIC_API_KEY"):
        return "https://api.newrelic.com"

    raise RuntimeError(
        "Either NEWRELIC_BASE_URL (proxy mode) or NEWRELIC_API_KEY (direct mode) must be set."
    )


def get_headers() -> dict[str, str]:
    """Get New Relic API headers."""
    config = get_config()
    headers = {"Content-Type": "application/json"}

    api_key = os.getenv("NEWRELIC_API_KEY")
    if api_key:
        headers["Api-Key"] = api_key
    else:
        sandbox_jwt = os.getenv("SANDBOX_JWT")
        if sandbox_jwt:
            headers["X-Sandbox-JWT"] = sandbox_jwt
        else:
            headers["X-Tenant-Id"] = config.get("tenant_id") or "local"
            headers["X-Team-Id"] = config.get("team_id") or "local"

    return headers


def newrelic_graphql(query: str, variables: dict | None = None) -> Any:
    """Execute a GraphQL query against New Relic."""
    base_url = get_base_url()
    url = f"{base_url}/graphql"

    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    with httpx.Client(timeout=30.0) as client:
        response = client.post(url, headers=get_headers(), json=payload)
        response.raise_for_status()
        return response.json()


def format_output(data: dict) -> str:
    """Format output as JSON string."""
    return json.dumps(data, indent=2, default=str)

#!/usr/bin/env python3
"""Shared Grafana API client with proxy support.

Credentials are injected transparently by the proxy layer.
"""

import os
from typing import Any

import httpx


def get_config() -> dict[str, str | None]:
    """Get Grafana configuration from environment."""
    return {
        "tenant_id": os.getenv("INCIDENTFOX_TENANT_ID", "local"),
        "team_id": os.getenv("INCIDENTFOX_TEAM_ID", "local"),
    }


def get_base_url() -> str:
    """Get Grafana API base URL.

    Supports two modes:
    1. Proxy mode (production): Uses GRAFANA_BASE_URL
    2. Direct mode (testing): Uses GRAFANA_URL
    """
    proxy_url = os.getenv("GRAFANA_BASE_URL")
    if proxy_url:
        return proxy_url.rstrip("/")

    url = os.getenv("GRAFANA_URL")
    if url:
        return url.rstrip("/")

    raise RuntimeError(
        "Either GRAFANA_BASE_URL (proxy mode) or GRAFANA_URL (direct mode) must be set."
    )


def get_headers() -> dict[str, str]:
    """Get Grafana API headers."""
    config = get_config()
    headers = {"Content-Type": "application/json", "Accept": "application/json"}

    api_key = os.getenv("GRAFANA_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    else:
        sandbox_jwt = os.getenv("SANDBOX_JWT")
        if sandbox_jwt:
            headers["X-Sandbox-JWT"] = sandbox_jwt
        else:
            headers["X-Tenant-Id"] = config.get("tenant_id") or "local"
            headers["X-Team-Id"] = config.get("team_id") or "local"

    return headers


def grafana_request(
    method: str,
    path: str,
    params: dict | None = None,
    json_body: dict | None = None,
) -> Any:
    """Make a request to Grafana API."""
    base_url = get_base_url()
    url = f"{base_url}/{path.lstrip('/')}"

    with httpx.Client(timeout=30.0) as client:
        response = client.request(
            method, url, headers=get_headers(), params=params, json=json_body
        )
        response.raise_for_status()
        return response.json()

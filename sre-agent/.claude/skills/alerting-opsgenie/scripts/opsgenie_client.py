#!/usr/bin/env python3
"""Shared Opsgenie API client with proxy support.

Credentials are injected transparently by the proxy layer.
"""

import os

import httpx


def get_base_url() -> str:
    """Get Opsgenie API base URL."""
    proxy_url = os.getenv("OPSGENIE_BASE_URL")
    if proxy_url:
        return proxy_url.rstrip("/")
    return os.getenv("OPSGENIE_API_URL", "https://api.opsgenie.com").rstrip("/")


def get_headers() -> dict[str, str]:
    """Get API headers."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    api_key = os.getenv("OPSGENIE_API_KEY")
    if api_key:
        headers["Authorization"] = f"GenieKey {api_key}"
    else:
        sandbox_jwt = os.getenv("SANDBOX_JWT")
        if sandbox_jwt:
            headers["X-Sandbox-JWT"] = sandbox_jwt
        else:
            headers["X-Tenant-Id"] = os.getenv("INCIDENTFOX_TENANT_ID", "local")
            headers["X-Team-Id"] = os.getenv("INCIDENTFOX_TEAM_ID", "local")

    return headers


def opsgenie_request(
    method: str,
    path: str,
    params: dict | None = None,
    json_body: dict | None = None,
) -> dict | list | None:
    """Make a request to Opsgenie API."""
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

#!/usr/bin/env python3
"""Shared Sentry API client with proxy support.

Credentials are injected transparently by the proxy layer.
"""

import os
from typing import Any

import httpx


def get_config() -> dict[str, str | None]:
    """Get Sentry configuration from environment."""
    return {
        "tenant_id": os.getenv("INCIDENTFOX_TENANT_ID", "local"),
        "team_id": os.getenv("INCIDENTFOX_TEAM_ID", "local"),
        "organization": os.getenv("SENTRY_ORGANIZATION", ""),
        "project": os.getenv("SENTRY_PROJECT"),
    }


def get_base_url() -> str:
    """Get Sentry API base URL.

    Supports two modes:
    1. Proxy mode (production): Uses SENTRY_BASE_URL
    2. Direct mode (testing): Uses https://sentry.io/api/0
    """
    proxy_url = os.getenv("SENTRY_BASE_URL")
    if proxy_url:
        return proxy_url.rstrip("/")

    if os.getenv("SENTRY_AUTH_TOKEN"):
        return "https://sentry.io/api/0"

    raise RuntimeError(
        "Either SENTRY_BASE_URL (proxy mode) or SENTRY_AUTH_TOKEN (direct mode) must be set."
    )


def get_headers() -> dict[str, str]:
    """Get Sentry API headers."""
    config = get_config()
    headers = {"Content-Type": "application/json"}

    auth_token = os.getenv("SENTRY_AUTH_TOKEN")
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    else:
        sandbox_jwt = os.getenv("SANDBOX_JWT")
        if sandbox_jwt:
            headers["X-Sandbox-JWT"] = sandbox_jwt
        else:
            headers["X-Tenant-Id"] = config.get("tenant_id") or "local"
            headers["X-Team-Id"] = config.get("team_id") or "local"

    return headers


def sentry_request(
    method: str,
    path: str,
    params: dict | None = None,
    json_body: dict | None = None,
) -> Any:
    """Make a request to Sentry API."""
    base_url = get_base_url()
    url = f"{base_url}/{path.lstrip('/')}"

    with httpx.Client(timeout=30.0) as client:
        response = client.request(
            method, url, headers=get_headers(), params=params, json=json_body
        )
        response.raise_for_status()
        return response.json()


def get_organization() -> str:
    """Get the Sentry organization slug."""
    org = os.getenv("SENTRY_ORGANIZATION", "")
    if not org:
        raise RuntimeError("SENTRY_ORGANIZATION must be set")
    return org

#!/usr/bin/env python3
"""Shared GitLab API client with proxy support.

Uses REST API v4 directly via httpx (no python-gitlab dependency).
Credentials are injected transparently by the proxy layer.
"""

import os
import urllib.parse
from typing import Any

import httpx


def get_config() -> dict[str, str | None]:
    """Get GitLab configuration from environment."""
    return {
        "tenant_id": os.getenv("INCIDENTFOX_TENANT_ID", "local"),
        "team_id": os.getenv("INCIDENTFOX_TEAM_ID", "local"),
        "gitlab_url": os.getenv("GITLAB_URL", "https://gitlab.com"),
    }


def get_base_url() -> str:
    """Get GitLab API base URL.

    Supports two modes:
    1. Proxy mode (production): Uses GITLAB_BASE_URL
    2. Direct mode (testing): Uses GITLAB_URL + /api/v4
    """
    proxy_url = os.getenv("GITLAB_BASE_URL")
    if proxy_url:
        return proxy_url.rstrip("/")

    gitlab_url = os.getenv("GITLAB_URL", "https://gitlab.com")
    return f"{gitlab_url.rstrip('/')}/api/v4"


def get_headers() -> dict[str, str]:
    """Get GitLab API headers."""
    config = get_config()
    headers = {"Content-Type": "application/json", "Accept": "application/json"}

    token = os.getenv("GITLAB_TOKEN")
    if token:
        headers["PRIVATE-TOKEN"] = token
    else:
        sandbox_jwt = os.getenv("SANDBOX_JWT")
        if sandbox_jwt:
            headers["X-Sandbox-JWT"] = sandbox_jwt
        else:
            headers["X-Tenant-Id"] = config.get("tenant_id") or "local"
            headers["X-Team-Id"] = config.get("team_id") or "local"

    return headers


def encode_project(project: str) -> str:
    """URL-encode project path for GitLab API."""
    if project.isdigit():
        return project
    return urllib.parse.quote(project, safe="")


def gitlab_request(
    method: str,
    path: str,
    params: dict | None = None,
    json_body: dict | None = None,
) -> Any:
    """Make a request to GitLab REST API v4."""
    base_url = get_base_url()
    url = f"{base_url}/{path.lstrip('/')}"

    with httpx.Client(timeout=30.0) as client:
        response = client.request(
            method, url, headers=get_headers(), params=params, json=json_body
        )
        response.raise_for_status()
        if response.status_code == 204:
            return None
        return response.json()

#!/usr/bin/env python3
"""Shared Blameless API client with proxy support."""

import os

import httpx


def get_base_url() -> str:
    proxy_url = os.getenv("BLAMELESS_BASE_URL")
    if proxy_url:
        return proxy_url.rstrip("/")
    instance = os.getenv("BLAMELESS_INSTANCE_URL", "https://api.blameless.io").rstrip(
        "/"
    )
    return f"{instance}/api/v1"


def get_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    api_key = os.getenv("BLAMELESS_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    else:
        sandbox_jwt = os.getenv("SANDBOX_JWT")
        if sandbox_jwt:
            headers["X-Sandbox-JWT"] = sandbox_jwt
        else:
            headers["X-Tenant-Id"] = os.getenv("INCIDENTFOX_TENANT_ID", "local")
            headers["X-Team-Id"] = os.getenv("INCIDENTFOX_TEAM_ID", "local")
    return headers


def blameless_request(method, path, params=None, json_body=None):
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

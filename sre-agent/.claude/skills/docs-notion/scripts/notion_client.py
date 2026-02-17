#!/usr/bin/env python3
"""Shared Notion API client with proxy support. Uses httpx (not notion-client package)."""

import os

import httpx

NOTION_VERSION = "2022-06-28"


def get_base_url() -> str:
    proxy_url = os.getenv("NOTION_BASE_URL")
    if proxy_url:
        return proxy_url.rstrip("/")
    return "https://api.notion.com/v1"


def get_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json", "Notion-Version": NOTION_VERSION}
    api_key = os.getenv("NOTION_API_KEY")
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


def notion_request(method, path, params=None, json_body=None):
    url = f"{get_base_url()}/{path.lstrip('/')}"
    with httpx.Client(timeout=30.0) as client:
        response = client.request(
            method, url, headers=get_headers(), params=params, json=json_body
        )
        response.raise_for_status()
        return None if response.status_code == 204 else response.json()

#!/usr/bin/env python3
"""Shared FireHydrant API client with proxy support."""

import os

import httpx


def get_base_url() -> str:
    proxy_url = os.getenv("FIREHYDRANT_BASE_URL")
    if proxy_url:
        return proxy_url.rstrip("/")
    return "https://api.firehydrant.io/v1"


def get_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    api_key = os.getenv("FIREHYDRANT_API_KEY")
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


def firehydrant_request(method, path, params=None, json_body=None):
    url = f"{get_base_url()}/{path.lstrip('/')}"
    with httpx.Client(timeout=30.0) as client:
        response = client.request(
            method, url, headers=get_headers(), params=params, json=json_body
        )
        response.raise_for_status()
        return None if response.status_code == 204 else response.json()

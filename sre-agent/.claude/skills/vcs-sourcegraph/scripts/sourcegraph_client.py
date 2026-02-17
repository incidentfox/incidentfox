#!/usr/bin/env python3
"""Shared Sourcegraph GraphQL client with proxy support."""

import os

import httpx


def get_graphql_url() -> str:
    proxy_url = os.getenv("SOURCEGRAPH_BASE_URL")
    if proxy_url:
        return proxy_url.rstrip("/")
    url = os.getenv("SOURCEGRAPH_URL", "https://sourcegraph.com").rstrip("/")
    return f"{url}/.api/graphql"


def get_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = os.getenv("SOURCEGRAPH_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"
    else:
        sandbox_jwt = os.getenv("SANDBOX_JWT")
        if sandbox_jwt:
            headers["X-Sandbox-JWT"] = sandbox_jwt
        else:
            headers["X-Tenant-Id"] = os.getenv("INCIDENTFOX_TENANT_ID", "local")
            headers["X-Team-Id"] = os.getenv("INCIDENTFOX_TEAM_ID", "local")
    return headers


def graphql_request(query, variables=None):
    body = {"query": query}
    if variables:
        body["variables"] = variables
    with httpx.Client(timeout=30.0) as client:
        response = client.post(get_graphql_url(), headers=get_headers(), json=body)
        response.raise_for_status()
        data = response.json()
        if "errors" in data:
            raise Exception(f"GraphQL errors: {data['errors']}")
        return data.get("data", {})

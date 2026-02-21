#!/usr/bin/env python3
"""Shared Amplitude API client with proxy support.

This module provides the Amplitude API client that works through the credential proxy.
Credentials are injected transparently by the proxy layer.

Amplitude Regions:
- US: amplitude.com/api/2/ (default)
- EU: analytics.eu.amplitude.com/api/2/
"""

import base64
import os
import sys
from typing import Any

import httpx

# Region to base URL mapping
REGION_URLS = {
    "US": "https://amplitude.com/api/2",
    "EU": "https://analytics.eu.amplitude.com/api/2",
}


def get_config() -> dict[str, str | None]:
    """Get Amplitude configuration from environment.

    Environment variables:
        INCIDENTFOX_TENANT_ID - Tenant ID for credential lookup
        INCIDENTFOX_TEAM_ID - Team ID for credential lookup
        AMPLITUDE_REGION - Region: US (default) or EU
    """
    return {
        "tenant_id": os.getenv("INCIDENTFOX_TENANT_ID", "local"),
        "team_id": os.getenv("INCIDENTFOX_TEAM_ID", "local"),
        "region": os.getenv("AMPLITUDE_REGION", "US"),
    }


def get_api_url(endpoint: str) -> str:
    """Build the Amplitude API URL.

    Supports two modes:
    1. Proxy mode (production): Uses AMPLITUDE_BASE_URL
    2. Direct mode (testing): Uses AMPLITUDE_REGION to build URL

    Args:
        endpoint: API path (e.g., "/events/segmentation")

    Returns:
        Full API URL
    """
    # Proxy mode (production)
    base_url = os.getenv("AMPLITUDE_BASE_URL")
    if base_url:
        return f"{base_url.rstrip('/')}{endpoint}"

    # Direct mode (testing) - requires AMPLITUDE_API_KEY
    if os.getenv("AMPLITUDE_API_KEY"):
        region = os.getenv("AMPLITUDE_REGION", "US").upper()
        base = REGION_URLS.get(region, REGION_URLS["US"])
        return f"{base}{endpoint}"

    raise RuntimeError(
        "Either AMPLITUDE_BASE_URL (proxy mode) or AMPLITUDE_API_KEY (direct mode) must be set."
    )


def get_headers() -> dict[str, str]:
    """Get Amplitude API headers.

    In proxy mode: includes tenant context for credential lookup.
    In direct mode: includes HTTP Basic auth (api_key:secret_key).
    """
    config = get_config()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # Direct mode - add Basic auth
    api_key = os.getenv("AMPLITUDE_API_KEY")
    secret_key = os.getenv("AMPLITUDE_SECRET_KEY")
    if api_key and secret_key:
        encoded = base64.b64encode(f"{api_key}:{secret_key}".encode()).decode()
        headers["Authorization"] = f"Basic {encoded}"
    else:
        # Proxy mode - use JWT for credential-resolver auth
        sandbox_jwt = os.getenv("SANDBOX_JWT")
        if not sandbox_jwt:
            jwt_path = "/tmp/sandbox-jwt"
            if os.path.exists(jwt_path):
                with open(jwt_path) as f:
                    sandbox_jwt = f.read().strip()
        if sandbox_jwt:
            headers["X-Sandbox-JWT"] = sandbox_jwt
        else:
            # Fallback for local dev
            headers["X-Tenant-Id"] = config.get("tenant_id") or "local"
            headers["X-Team-Id"] = config.get("team_id") or "local"

    return headers


def amplitude_request(
    method: str,
    endpoint: str,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Make an Amplitude API request.

    Args:
        method: HTTP method (GET, POST)
        endpoint: API path (e.g., "/events/segmentation")
        params: Query parameters
        json_body: JSON body for POST requests

    Returns:
        Parsed JSON response

    Raises:
        httpx.HTTPStatusError: On API errors
    """
    url = get_api_url(endpoint)
    headers = get_headers()

    with httpx.Client(timeout=60.0) as client:
        response = client.request(
            method, url, headers=headers, params=params, json=json_body
        )

        if response.status_code != 200:
            print(
                f"ERROR: Amplitude API returned {response.status_code}", file=sys.stderr
            )
            response.raise_for_status()

        return response.json()


def format_event_data(data: dict[str, Any]) -> str:
    """Format event segmentation data for display."""
    series = data.get("data", {}).get("series", [])
    labels = data.get("data", {}).get("seriesLabels", [])
    x_values = data.get("data", {}).get("xValues", [])

    if not series:
        return "No data returned."

    lines = []
    for i, label in enumerate(labels):
        label_str = (
            str(label)
            if not isinstance(label, list)
            else " > ".join(str(l) for l in label)
        )
        if i < len(series) and series[i]:
            total = sum(v for v in series[i] if v is not None)
            lines.append(f"  {label_str}: {total:,.0f} total")

    if x_values:
        lines.insert(0, f"Time range: {x_values[0]} to {x_values[-1]}")

    return "\n".join(lines)

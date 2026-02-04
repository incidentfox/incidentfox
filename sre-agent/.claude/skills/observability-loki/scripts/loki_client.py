#!/usr/bin/env python3
"""Shared Loki client with proxy support.

This module provides the Loki client that works through the credential proxy.
Credentials are injected transparently by the proxy layer.

Supports Loki 2.x and 3.x via HTTP API.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx


def get_config() -> dict[str, str | None]:
    """Get Loki configuration from environment.

    Credentials are injected by the credential-proxy based on tenant context.

    Environment variables:
        INCIDENTFOX_TENANT_ID - Tenant ID for credential lookup
        INCIDENTFOX_TEAM_ID - Team ID for credential lookup
    """
    return {
        "tenant_id": os.getenv("INCIDENTFOX_TENANT_ID", "local"),
        "team_id": os.getenv("INCIDENTFOX_TEAM_ID", "local"),
    }


def get_api_url(endpoint: str) -> str:
    """Build the Loki API URL.

    Supports two modes:
    1. Proxy mode (production): Uses LOKI_BASE_URL
    2. Direct mode (testing): Uses LOKI_URL

    Args:
        endpoint: API path (e.g., "/loki/api/v1/query")

    Returns:
        Full API URL
    """
    # Proxy mode (production)
    base_url = os.getenv("LOKI_BASE_URL")
    if base_url:
        return f"{base_url.rstrip('/')}{endpoint}"

    # Direct mode (testing)
    direct_url = os.getenv("LOKI_URL")
    if direct_url:
        return f"{direct_url.rstrip('/')}{endpoint}"

    raise RuntimeError(
        "Either LOKI_BASE_URL (proxy mode) or LOKI_URL (direct mode) must be set."
    )


def get_headers() -> dict[str, str]:
    """Get Loki API headers.

    Supports multiple auth methods:
    1. Bearer token - LOKI_TOKEN
    2. Basic auth - LOKI_USER + LOKI_PASSWORD
    3. Multi-tenant org ID - LOKI_ORG_ID (X-Scope-OrgID header)
    4. Proxy mode - tenant context headers

    Environment variables:
        LOKI_TOKEN: Bearer token (Grafana Cloud, enterprise)
        LOKI_USER + LOKI_PASSWORD: Basic auth
        LOKI_ORG_ID: Multi-tenant organization ID
    """
    config = get_config()
    import base64

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # Always add org ID if provided (multi-tenant Loki)
    org_id = os.getenv("LOKI_ORG_ID")
    if org_id:
        headers["X-Scope-OrgID"] = org_id

    # Priority 1: Bearer token (Grafana Cloud / enterprise)
    token = os.getenv("LOKI_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
        return headers

    # Priority 2: Basic auth
    user = os.getenv("LOKI_USER")
    password = os.getenv("LOKI_PASSWORD")
    if user and password:
        encoded = base64.b64encode(f"{user}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {encoded}"
        return headers

    # Priority 3: Proxy mode - add tenant context
    if os.getenv("LOKI_BASE_URL"):
        headers["X-Tenant-Id"] = config.get("tenant_id") or "local"
        headers["X-Team-Id"] = config.get("team_id") or "local"

    # No auth (local Loki without security)
    return headers


def query(
    query: str,
    limit: int = 100,
    start: datetime | None = None,
    end: datetime | None = None,
    direction: str = "backward",
) -> dict[str, Any]:
    """Execute a LogQL query (log stream query).

    Args:
        query: LogQL query string
        limit: Maximum number of entries to return
        start: Start time (default: 1 hour ago)
        end: End time (default: now)
        direction: "forward" or "backward" (default)

    Returns:
        Query response with streams or matrix data
    """
    now = datetime.now(timezone.utc)
    if end is None:
        end = now
    if start is None:
        start = now - timedelta(hours=1)

    # Convert to nanoseconds
    start_ns = int(start.timestamp() * 1e9)
    end_ns = int(end.timestamp() * 1e9)

    params = {
        "query": query,
        "limit": limit,
        "start": start_ns,
        "end": end_ns,
        "direction": direction,
    }

    url = get_api_url(f"/loki/api/v1/query_range?{urlencode(params)}")

    with httpx.Client(timeout=60.0) as client:
        response = client.get(url, headers=get_headers())
        response.raise_for_status()
        return response.json()


def query_instant(query: str, time: datetime | None = None) -> dict[str, Any]:
    """Execute an instant LogQL query (for metric queries at a single point).

    Args:
        query: LogQL metric query
        time: Evaluation time (default: now)

    Returns:
        Query response with vector data
    """
    if time is None:
        time = datetime.now(timezone.utc)

    time_ns = int(time.timestamp() * 1e9)

    params = {
        "query": query,
        "time": time_ns,
    }

    url = get_api_url(f"/loki/api/v1/query?{urlencode(params)}")

    with httpx.Client(timeout=60.0) as client:
        response = client.get(url, headers=get_headers())
        response.raise_for_status()
        return response.json()


def get_labels(start: datetime | None = None, end: datetime | None = None) -> list[str]:
    """Get all label names.

    Args:
        start: Start time (default: 6 hours ago)
        end: End time (default: now)

    Returns:
        List of label names
    """
    now = datetime.now(timezone.utc)
    if end is None:
        end = now
    if start is None:
        start = now - timedelta(hours=6)

    start_ns = int(start.timestamp() * 1e9)
    end_ns = int(end.timestamp() * 1e9)

    params = {"start": start_ns, "end": end_ns}
    url = get_api_url(f"/loki/api/v1/labels?{urlencode(params)}")

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, headers=get_headers())
        response.raise_for_status()
        data = response.json()
        return data.get("data", [])


def get_label_values(
    label: str, start: datetime | None = None, end: datetime | None = None
) -> list[str]:
    """Get values for a specific label.

    Args:
        label: Label name
        start: Start time (default: 6 hours ago)
        end: End time (default: now)

    Returns:
        List of label values
    """
    now = datetime.now(timezone.utc)
    if end is None:
        end = now
    if start is None:
        start = now - timedelta(hours=6)

    start_ns = int(start.timestamp() * 1e9)
    end_ns = int(end.timestamp() * 1e9)

    params = {"start": start_ns, "end": end_ns}
    url = get_api_url(f"/loki/api/v1/label/{label}/values?{urlencode(params)}")

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, headers=get_headers())
        response.raise_for_status()
        data = response.json()
        return data.get("data", [])


def get_series(
    match: list[str], start: datetime | None = None, end: datetime | None = None
) -> list[dict]:
    """Get series (label combinations) matching selectors.

    Args:
        match: List of stream selectors (e.g., ['{app="api"}'])
        start: Start time (default: 1 hour ago)
        end: End time (default: now)

    Returns:
        List of label sets
    """
    now = datetime.now(timezone.utc)
    if end is None:
        end = now
    if start is None:
        start = now - timedelta(hours=1)

    start_ns = int(start.timestamp() * 1e9)
    end_ns = int(end.timestamp() * 1e9)

    params = [("start", start_ns), ("end", end_ns)]
    for m in match:
        params.append(("match[]", m))

    url = get_api_url(f"/loki/api/v1/series?{urlencode(params)}")

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, headers=get_headers())
        response.raise_for_status()
        data = response.json()
        return data.get("data", [])


def format_log_entry(stream: dict, entry: list, max_length: int = 300) -> str:
    """Format a log entry for display.

    Args:
        stream: Stream labels dict
        entry: [timestamp_ns, line] tuple
        max_length: Maximum line length

    Returns:
        Formatted string
    """
    ts_ns, line = entry
    # Convert nanoseconds to datetime
    ts = datetime.fromtimestamp(int(ts_ns) / 1e9, tz=timezone.utc)
    ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")

    # Get key labels
    app = (
        stream.get("app")
        or stream.get("application")
        or stream.get("container")
        or "unknown"
    )
    pod = stream.get("pod") or stream.get("instance") or ""
    namespace = stream.get("namespace") or ""

    # Build context
    context_parts = [app]
    if namespace:
        context_parts.insert(0, namespace)
    if pod:
        context_parts.append(pod)

    context = "/".join(context_parts)

    # Truncate line
    if len(line) > max_length:
        line = line[: max_length - 3] + "..."

    return f"[{ts_str}] {context}\n  {line}"

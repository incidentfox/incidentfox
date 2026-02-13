#!/usr/bin/env python3
"""Shared VictoriaMetrics client with proxy support.

This module provides the VictoriaMetrics client that works through the credential proxy.
Credentials are injected transparently by the proxy layer.

VictoriaMetrics is Prometheus-compatible and supports MetricsQL extensions.
"""

import base64
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx


def get_config() -> dict[str, str | None]:
    """Get VictoriaMetrics configuration from environment.

    Credentials are injected by the credential-proxy based on tenant context.
    """
    return {
        "tenant_id": os.getenv("INCIDENTFOX_TENANT_ID", "local"),
        "team_id": os.getenv("INCIDENTFOX_TEAM_ID", "local"),
    }


def get_api_url(endpoint: str) -> str:
    """Build the VictoriaMetrics API URL.

    Supports two modes:
    1. Proxy mode (production): Uses VICTORIAMETRICS_BASE_URL
    2. Direct mode (testing): Uses VICTORIAMETRICS_URL
    """
    # Proxy mode (production)
    base_url = os.getenv("VICTORIAMETRICS_BASE_URL")
    if base_url:
        return f"{base_url.rstrip('/')}{endpoint}"

    # Direct mode (testing)
    direct_url = os.getenv("VICTORIAMETRICS_URL")
    if direct_url:
        return f"{direct_url.rstrip('/')}{endpoint}"

    raise RuntimeError(
        "Either VICTORIAMETRICS_BASE_URL (proxy mode) or VICTORIAMETRICS_URL (direct mode) must be set."
    )


def get_headers() -> dict[str, str]:
    """Get VictoriaMetrics API headers.

    Supports multiple auth methods:
    1. Bearer token - VICTORIAMETRICS_TOKEN
    2. Basic auth - VICTORIAMETRICS_USER + VICTORIAMETRICS_PASSWORD
    3. Proxy mode - JWT for credential-resolver auth
    """
    config = get_config()

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # Priority 1: Bearer token
    token = os.getenv("VICTORIAMETRICS_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
        return headers

    # Priority 2: Basic auth
    user = os.getenv("VICTORIAMETRICS_USER")
    password = os.getenv("VICTORIAMETRICS_PASSWORD")
    if user and password:
        encoded = base64.b64encode(f"{user}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {encoded}"
        return headers

    # Priority 3: Proxy mode - use JWT for credential-resolver auth
    if os.getenv("VICTORIAMETRICS_BASE_URL"):
        sandbox_jwt = os.getenv("SANDBOX_JWT")
        if sandbox_jwt:
            headers["X-Sandbox-JWT"] = sandbox_jwt
        else:
            # Fallback for local dev
            headers["X-Tenant-Id"] = config.get("tenant_id") or "local"
            headers["X-Team-Id"] = config.get("team_id") or "local"

    return headers


def query_instant(query: str, time: datetime | None = None) -> dict:
    """Execute an instant MetricsQL query.

    Args:
        query: MetricsQL/PromQL query string
        time: Evaluation time (default: now)

    Returns:
        Query response with vector data
    """
    params = {"query": query}

    if time is not None:
        params["time"] = str(int(time.timestamp()))

    url = get_api_url(f"/api/v1/query?{urlencode(params)}")

    with httpx.Client(timeout=60.0) as client:
        response = client.get(url, headers=get_headers())
        response.raise_for_status()
        return response.json()


def query_range(
    query: str,
    start: datetime | None = None,
    end: datetime | None = None,
    step: str = "5m",
) -> dict:
    """Execute a range MetricsQL query.

    Args:
        query: MetricsQL/PromQL query string
        start: Start time (default: 1 hour ago)
        end: End time (default: now)
        step: Query resolution step (default: 5m)

    Returns:
        Query response with matrix data
    """
    now = datetime.now(timezone.utc)
    if end is None:
        end = now
    if start is None:
        start = now - timedelta(hours=1)

    params = {
        "query": query,
        "start": str(int(start.timestamp())),
        "end": str(int(end.timestamp())),
        "step": step,
    }

    url = get_api_url(f"/api/v1/query_range?{urlencode(params)}")

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

    params = {
        "start": str(int(start.timestamp())),
        "end": str(int(end.timestamp())),
    }

    url = get_api_url(f"/api/v1/labels?{urlencode(params)}")

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, headers=get_headers())
        response.raise_for_status()
        data = response.json()
        return data.get("data", [])


def get_label_values(
    label: str,
    start: datetime | None = None,
    end: datetime | None = None,
    match: str | None = None,
) -> list[str]:
    """Get values for a specific label.

    Args:
        label: Label name
        start: Start time (default: 6 hours ago)
        end: End time (default: now)
        match: Optional series selector to scope results

    Returns:
        List of label values
    """
    now = datetime.now(timezone.utc)
    if end is None:
        end = now
    if start is None:
        start = now - timedelta(hours=6)

    params = {
        "start": str(int(start.timestamp())),
        "end": str(int(end.timestamp())),
    }
    if match:
        params["match[]"] = match

    url = get_api_url(f"/api/v1/label/{label}/values?{urlencode(params)}")

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, headers=get_headers())
        response.raise_for_status()
        data = response.json()
        return data.get("data", [])


def get_series(
    match: list[str],
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 100,
) -> list[dict]:
    """Get series matching selectors.

    Args:
        match: List of series selectors (e.g., ['{job="api"}'])
        start: Start time (default: 1 hour ago)
        end: End time (default: now)
        limit: Max series to return

    Returns:
        List of label sets
    """
    now = datetime.now(timezone.utc)
    if end is None:
        end = now
    if start is None:
        start = now - timedelta(hours=1)

    params = [
        ("start", str(int(start.timestamp()))),
        ("end", str(int(end.timestamp()))),
        ("limit", str(limit)),
    ]
    for m in match:
        params.append(("match[]", m))

    url = get_api_url(f"/api/v1/series?{urlencode(params)}")

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, headers=get_headers())
        response.raise_for_status()
        data = response.json()
        return data.get("data", [])


def format_metric_result(result: dict, max_series: int = 20) -> str:
    """Format a query result for human-readable display.

    Caps output to max_series to avoid flooding the context window.

    Args:
        result: API response dict
        max_series: Maximum number of series to display

    Returns:
        Formatted string
    """
    data = result.get("data", {})
    result_type = data.get("resultType", "vector")
    results = data.get("result", [])

    if not results:
        return "No results found."

    lines = []
    total = len(results)

    for item in results[:max_series]:
        metric = item.get("metric", {})
        name = metric.get("__name__", "")
        labels = {k: v for k, v in metric.items() if k != "__name__"}
        label_str = ", ".join(f'{k}="{v}"' for k, v in labels.items())

        if result_type == "vector":
            # Instant query: [timestamp, value]
            value = item.get("value", [None, "N/A"])
            lines.append(f"  {name}{{{label_str}}}: {value[1]}")
        elif result_type == "matrix":
            # Range query: show only latest value to keep output compact
            values = item.get("values", [])
            if values:
                latest = values[-1]
                lines.append(
                    f"  {name}{{{label_str}}}: {latest[1]} (latest, {len(values)} points)"
                )
            else:
                lines.append(f"  {name}{{{label_str}}}: (no data)")

    if total > max_series:
        lines.append(f"\n  ... showing {max_series} of {total} series")

    return "\n".join(lines)

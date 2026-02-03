#!/usr/bin/env python3
"""Shared Datadog API client with proxy support.

This module provides the Datadog API client that works through the credential proxy.
Credentials are injected transparently by the proxy layer.

Datadog Sites:
- US1: api.datadoghq.com (default)
- US3: api.us3.datadoghq.com
- US5: api.us5.datadoghq.com
- EU1: api.datadoghq.eu
- AP1: api.ap1.datadoghq.com
- GOV: api.ddog-gov.com
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx


def get_config() -> dict[str, str | None]:
    """Get Datadog configuration from environment.

    Credentials are injected by the credential-proxy based on tenant context.

    Environment variables:
        INCIDENTFOX_TENANT_ID - Tenant ID for credential lookup
        INCIDENTFOX_TEAM_ID - Team ID for credential lookup
        DATADOG_SITE - Datadog site (e.g., us5.datadoghq.com)
    """
    return {
        "tenant_id": os.getenv("INCIDENTFOX_TENANT_ID", "local"),
        "team_id": os.getenv("INCIDENTFOX_TEAM_ID", "local"),
        "site": os.getenv("DATADOG_SITE", "datadoghq.com"),
    }


def get_api_url(endpoint: str) -> str:
    """Build the Datadog API URL for proxy mode.

    Uses DATADOG_BASE_URL which routes through the credential proxy.
    The proxy handles credential injection and forwards to the real Datadog API.

    Args:
        endpoint: API path (e.g., "/api/v2/logs/events/search")

    Returns:
        Full API URL
    """
    base_url = os.getenv("DATADOG_BASE_URL")
    if not base_url:
        raise RuntimeError(
            "DATADOG_BASE_URL not set. Agent must run through credential proxy."
        )
    return f"{base_url.rstrip('/')}{endpoint}"


def get_headers() -> dict[str, str]:
    """Get Datadog API headers.

    Includes tenant context headers for credential-proxy to look up credentials.
    API-KEY and APP-KEY headers will be injected by the proxy.
    """
    config = get_config()
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Tenant-Id": config.get("tenant_id") or "local",
        "X-Team-Id": config.get("team_id") or "local",
    }


def search_logs(
    query: str,
    time_range_minutes: int = 60,
    limit: int = 100,
    sort: str = "timestamp",
    sort_order: str = "desc",
) -> list[dict[str, Any]]:
    """Search Datadog logs.

    Args:
        query: Datadog log query (e.g., "service:api status:error")
        time_range_minutes: Time range to query (default: 60 minutes)
        limit: Maximum results to return (default: 100)
        sort: Field to sort by (default: timestamp)
        sort_order: Sort order - asc or desc (default: desc)

    Returns:
        List of log entries

    Raises:
        httpx.HTTPStatusError: On API errors
    """
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(minutes=time_range_minutes)

    url = get_api_url("/api/v2/logs/events/search")

    payload = {
        "filter": {
            "query": query,
            "from": start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "to": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "sort": sort_order,
        "page": {"limit": min(limit, 1000)},  # Datadog max is 1000
    }

    with httpx.Client(timeout=60.0) as client:
        response = client.post(url, headers=get_headers(), json=payload)
        response.raise_for_status()

        data = response.json()
        logs = []

        for log in data.get("data", []):
            attrs = log.get("attributes", {})
            logs.append(
                {
                    "id": log.get("id"),
                    "timestamp": attrs.get("timestamp"),
                    "status": attrs.get("status"),
                    "service": attrs.get("service"),
                    "host": attrs.get("host"),
                    "message": attrs.get("message"),
                    "attributes": attrs.get("attributes", {}),
                    "tags": attrs.get("tags", []),
                }
            )

        return logs


def aggregate_logs(
    query: str,
    group_by: list[str] | None = None,
    time_range_minutes: int = 60,
    compute: str = "count",
) -> dict[str, Any]:
    """Aggregate Datadog logs.

    Args:
        query: Datadog log query
        group_by: Fields to group by (e.g., ["service", "status"])
        time_range_minutes: Time range to query
        compute: Aggregation type - count, cardinality, sum, avg, min, max

    Returns:
        Aggregation results

    Raises:
        httpx.HTTPStatusError: On API errors
    """
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(minutes=time_range_minutes)

    url = get_api_url("/api/v2/logs/analytics/aggregate")

    payload = {
        "filter": {
            "query": query,
            "from": start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "to": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "compute": [{"aggregation": compute}],
    }

    if group_by:
        payload["group_by"] = [{"facet": f, "limit": 50} for f in group_by]

    with httpx.Client(timeout=60.0) as client:
        response = client.post(url, headers=get_headers(), json=payload)
        response.raise_for_status()
        return response.json()


def query_metrics(
    query: str,
    time_range_minutes: int = 60,
) -> dict[str, Any]:
    """Query Datadog metrics.

    Args:
        query: Datadog metric query (e.g., "avg:system.cpu.user{*}")
        time_range_minutes: Time range to query

    Returns:
        Metric data with series

    Raises:
        httpx.HTTPStatusError: On API errors
    """
    now = int(datetime.now(timezone.utc).timestamp())
    start = now - (time_range_minutes * 60)

    url = get_api_url(f"/api/v1/query?from={start}&to={now}&query={query}")

    with httpx.Client(timeout=60.0) as client:
        response = client.get(url, headers=get_headers())
        response.raise_for_status()
        return response.json()


def format_log_entry(log: dict[str, Any], max_message_length: int = 300) -> str:
    """Format a log entry for display.

    Args:
        log: Log entry dictionary
        max_message_length: Maximum length for message (truncated if longer)

    Returns:
        Formatted string
    """
    status = log.get("status", "info").upper()
    timestamp = log.get("timestamp", "")
    service = log.get("service", "unknown")
    message = log.get("message", "")

    # Format timestamp
    if "T" in str(timestamp):
        ts = str(timestamp).split(".")[0].replace("T", " ")
    else:
        ts = str(timestamp)

    # Truncate message
    if len(message) > max_message_length:
        message = message[:max_message_length] + "..."

    lines = [f"[{status}] {ts} | {service}"]
    if message:
        lines.append(f"  {message}")

    # Add host context
    host = log.get("host")
    if host:
        lines.append(f"  Host: {host}")

    return "\n".join(lines)

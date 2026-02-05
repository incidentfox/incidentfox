#!/usr/bin/env python3
"""Shared Elasticsearch client with proxy support.

This module provides the Elasticsearch client that works through the credential proxy.
Credentials are injected transparently by the proxy layer.

Works with Elasticsearch 7.x, 8.x, and 9.x via REST API.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx


def get_config() -> dict[str, str | None]:
    """Get Elasticsearch configuration from environment.

    Credentials are injected by the credential-proxy based on tenant context.

    Environment variables:
        INCIDENTFOX_TENANT_ID - Tenant ID for credential lookup
        INCIDENTFOX_TEAM_ID - Team ID for credential lookup
        ELASTICSEARCH_INDEX - Default index pattern (e.g., logs-*)
    """
    return {
        "tenant_id": os.getenv("INCIDENTFOX_TENANT_ID", "local"),
        "team_id": os.getenv("INCIDENTFOX_TEAM_ID", "local"),
        "index_pattern": os.getenv("ELASTICSEARCH_INDEX", "logs-*"),
    }


def get_api_url(endpoint: str) -> str:
    """Build the Elasticsearch API URL.

    Supports two modes:
    1. Proxy mode (production): Uses ELASTICSEARCH_BASE_URL
    2. Direct mode (testing): Uses ELASTICSEARCH_URL

    Args:
        endpoint: API path (e.g., "/logs-*/_search")

    Returns:
        Full API URL
    """
    # Proxy mode (production)
    base_url = os.getenv("ELASTICSEARCH_BASE_URL")
    if base_url:
        return f"{base_url.rstrip('/')}{endpoint}"

    # Direct mode (testing)
    direct_url = os.getenv("ELASTICSEARCH_URL")
    if direct_url:
        return f"{direct_url.rstrip('/')}{endpoint}"

    raise RuntimeError(
        "Either ELASTICSEARCH_BASE_URL (proxy mode) or ELASTICSEARCH_URL (direct mode) must be set."
    )


def get_headers() -> dict[str, str]:
    """Get Elasticsearch API headers.

    Supports multiple auth methods (checked in order):
    1. API Key (Elastic Cloud / Enterprise) - ES_API_KEY or ELASTICSEARCH_API_KEY
    2. Basic auth - ES_USER + ES_PASSWORD
    3. Bearer token - ES_TOKEN or ELASTICSEARCH_TOKEN
    4. Proxy mode - tenant context headers

    Environment variables:
        ES_API_KEY / ELASTICSEARCH_API_KEY: API key (id:secret or encoded)
        ES_USER / ELASTICSEARCH_USER: Username for basic auth
        ES_PASSWORD / ELASTICSEARCH_PASSWORD: Password for basic auth
        ES_TOKEN / ELASTICSEARCH_TOKEN: Bearer token
    """
    config = get_config()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    import base64

    # Priority 1: API Key (Elastic Cloud / Enterprise pattern)
    api_key = os.getenv("ES_API_KEY") or os.getenv("ELASTICSEARCH_API_KEY")
    if api_key:
        # API key can be provided as "id:secret" or already base64 encoded
        if ":" in api_key:
            encoded = base64.b64encode(api_key.encode()).decode()
        else:
            encoded = api_key  # Assume already encoded
        headers["Authorization"] = f"ApiKey {encoded}"
        return headers

    # Priority 2: Basic auth (user:password)
    user = os.getenv("ES_USER") or os.getenv("ELASTICSEARCH_USER")
    password = os.getenv("ES_PASSWORD") or os.getenv("ELASTICSEARCH_PASSWORD")
    if user and password:
        auth = base64.b64encode(f"{user}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {auth}"
        return headers

    # Priority 3: Bearer token
    token = os.getenv("ES_TOKEN") or os.getenv("ELASTICSEARCH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
        return headers

    # Priority 4: Proxy mode - use JWT for credential-resolver auth
    if os.getenv("ELASTICSEARCH_BASE_URL"):
        sandbox_jwt = os.getenv("SANDBOX_JWT")
        if sandbox_jwt:
            headers["X-Sandbox-JWT"] = sandbox_jwt
        else:
            # Fallback for local dev
            headers["X-Tenant-Id"] = config.get("tenant_id") or "local"
            headers["X-Team-Id"] = config.get("team_id") or "local"

    # No auth (local ES without security)
    return headers


def search(
    query: dict[str, Any],
    index: str | None = None,
    size: int = 100,
    sort: list[dict] | None = None,
) -> dict[str, Any]:
    """Execute an Elasticsearch search query.

    Args:
        query: Elasticsearch query DSL (the "query" part)
        index: Index pattern (default: from config)
        size: Maximum results to return (default: 100)
        sort: Sort specification (default: @timestamp desc)

    Returns:
        Search response with hits

    Raises:
        httpx.HTTPStatusError: On API errors
    """
    config = get_config()
    index = index or config.get("index_pattern", "logs-*")

    url = get_api_url(f"/{index}/_search")

    body = {
        "query": query,
        "size": size,
        "sort": sort or [{"@timestamp": {"order": "desc"}}],
    }

    with httpx.Client(
        timeout=60.0, verify=False
    ) as client:  # verify=False for self-signed certs
        response = client.post(url, headers=get_headers(), json=body)
        response.raise_for_status()
        return response.json()


def aggregate(
    query: dict[str, Any],
    aggs: dict[str, Any],
    index: str | None = None,
    size: int = 0,
) -> dict[str, Any]:
    """Execute an Elasticsearch aggregation query.

    Args:
        query: Elasticsearch query DSL
        aggs: Aggregation specification
        index: Index pattern
        size: Number of hits to return (default: 0 for aggs only)

    Returns:
        Search response with aggregations

    Raises:
        httpx.HTTPStatusError: On API errors
    """
    config = get_config()
    index = index or config.get("index_pattern", "logs-*")

    url = get_api_url(f"/{index}/_search")

    body = {
        "query": query,
        "aggs": aggs,
        "size": size,
    }

    with httpx.Client(timeout=60.0, verify=False) as client:
        response = client.post(url, headers=get_headers(), json=body)
        response.raise_for_status()
        return response.json()


def build_time_range_query(
    time_range_minutes: int = 60,
    filters: list[dict] | None = None,
) -> dict[str, Any]:
    """Build a time-range filtered query.

    Args:
        time_range_minutes: Time range to query
        filters: Additional filter clauses

    Returns:
        Elasticsearch bool query
    """
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(minutes=time_range_minutes)

    must_clauses = [
        {
            "range": {
                "@timestamp": {
                    "gte": start_time.isoformat(),
                    "lte": now.isoformat(),
                }
            }
        }
    ]

    if filters:
        must_clauses.extend(filters)

    return {"bool": {"must": must_clauses}}


def format_log_entry(hit: dict[str, Any], max_message_length: int = 300) -> str:
    """Format an Elasticsearch hit for display.

    Args:
        hit: Elasticsearch hit document
        max_message_length: Maximum length for message

    Returns:
        Formatted string
    """
    source = hit.get("_source", {})

    # Common field names for log level
    level = (
        source.get("level")
        or source.get("log.level")
        or source.get("severity")
        or source.get("log_level")
        or "INFO"
    )

    # Common field names for timestamp
    timestamp = source.get("@timestamp") or source.get("timestamp") or ""

    # Common field names for service/application
    service = (
        source.get("service.name")
        or source.get("service")
        or source.get("application")
        or source.get("kubernetes.container.name")
        or "unknown"
    )

    # Common field names for message
    message = source.get("message") or source.get("log") or source.get("msg") or ""

    # Format timestamp
    if "T" in str(timestamp):
        ts = str(timestamp).split(".")[0].replace("T", " ")
    else:
        ts = str(timestamp)

    # Truncate message
    if len(message) > max_message_length:
        message = message[:max_message_length] + "..."

    lines = [f"[{str(level).upper()}] {ts} | {service}"]
    if message:
        lines.append(f"  {message}")

    # Add Kubernetes context if available
    k8s = source.get("kubernetes", {})
    if isinstance(k8s, dict):
        pod = k8s.get("pod", {}).get("name") or k8s.get("pod_name")
        namespace = k8s.get("namespace")
        if pod or namespace:
            ctx = []
            if namespace:
                ctx.append(f"ns={namespace}")
            if pod:
                ctx.append(f"pod={pod}")
            lines.append(f"  K8s: {', '.join(ctx)}")

    return "\n".join(lines)

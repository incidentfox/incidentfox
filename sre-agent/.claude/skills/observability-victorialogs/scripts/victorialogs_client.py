#!/usr/bin/env python3
"""Shared VictoriaLogs client with proxy support.

This module provides the VictoriaLogs client that works through the credential proxy.
Credentials are injected transparently by the proxy layer.

VictoriaLogs uses LogsQL query language and returns JSON lines (one JSON object per line).
"""

import base64
import json
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx


def get_config() -> dict[str, str | None]:
    """Get VictoriaLogs configuration from environment.

    Credentials are injected by the credential-proxy based on tenant context.
    """
    return {
        "tenant_id": os.getenv("INCIDENTFOX_TENANT_ID", "local"),
        "team_id": os.getenv("INCIDENTFOX_TEAM_ID", "local"),
    }


def get_api_url(endpoint: str) -> str:
    """Build the VictoriaLogs API URL.

    Supports two modes:
    1. Proxy mode (production): Uses VICTORIALOGS_BASE_URL
    2. Direct mode (testing): Uses VICTORIALOGS_URL
    """
    # Proxy mode (production)
    base_url = os.getenv("VICTORIALOGS_BASE_URL")
    if base_url:
        return f"{base_url.rstrip('/')}{endpoint}"

    # Direct mode (testing)
    direct_url = os.getenv("VICTORIALOGS_URL")
    if direct_url:
        return f"{direct_url.rstrip('/')}{endpoint}"

    raise RuntimeError(
        "Either VICTORIALOGS_BASE_URL (proxy mode) or VICTORIALOGS_URL (direct mode) must be set."
    )


def get_headers() -> dict[str, str]:
    """Get VictoriaLogs API headers.

    Supports multiple auth methods:
    1. Bearer token - VICTORIALOGS_TOKEN
    2. Basic auth - VICTORIALOGS_USER + VICTORIALOGS_PASSWORD
    3. Proxy mode - JWT for credential-resolver auth
    """
    config = get_config()

    headers = {
        "Accept": "application/json",
    }

    # Priority 1: Bearer token
    token = os.getenv("VICTORIALOGS_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
        return headers

    # Priority 2: Basic auth
    user = os.getenv("VICTORIALOGS_USER")
    password = os.getenv("VICTORIALOGS_PASSWORD")
    if user and password:
        encoded = base64.b64encode(f"{user}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {encoded}"
        return headers

    # Priority 3: Proxy mode - use JWT for credential-resolver auth
    if os.getenv("VICTORIALOGS_BASE_URL"):
        sandbox_jwt = os.getenv("SANDBOX_JWT")
        if sandbox_jwt:
            headers["X-Sandbox-JWT"] = sandbox_jwt
        else:
            # Fallback for local dev
            headers["X-Tenant-Id"] = config.get("tenant_id") or "local"
            headers["X-Team-Id"] = config.get("team_id") or "local"

    return headers


def _has_pipe(query: str, pipe_name: str) -> bool:
    """Check if a LogsQL query already contains a specific pipe.

    Handles edge cases where pipe keywords might appear inside quoted strings.
    """
    # Simple heuristic: check if pipe appears after a | character
    parts = query.split("|")
    for part in parts[1:]:  # Skip the filter part (before first |)
        stripped = part.strip().lower()
        if stripped.startswith(pipe_name):
            return True
    return False


def _ensure_limit(query: str, limit: int) -> str:
    """Ensure a LogsQL query has a limit to prevent unbounded results.

    Auto-appends '| limit N' if the query doesn't already contain
    '| limit' or '| stats' pipes.
    """
    if _has_pipe(query, "limit") or _has_pipe(query, "stats"):
        return query
    return f"{query} | limit {limit}"


def _parse_jsonlines(text: str) -> list[dict]:
    """Parse JSON lines response from VictoriaLogs.

    VictoriaLogs returns one JSON object per line, not a JSON array.
    """
    entries = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def query_logs(
    query: str,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 100,
) -> list[dict]:
    """Execute a LogsQL query and return log entries.

    Auto-appends '| limit' if the query doesn't contain '| limit' or '| stats'.

    Args:
        query: LogsQL query string
        start: Start time (default: 1 hour ago)
        end: End time (default: now)
        limit: Maximum entries to return (safety limit)

    Returns:
        List of log entry dicts
    """
    now = datetime.now(timezone.utc)
    if end is None:
        end = now
    if start is None:
        start = now - timedelta(hours=1)

    safe_query = _ensure_limit(query, limit)

    params = {
        "query": safe_query,
        "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    url = get_api_url(f"/select/logsql/query?{urlencode(params)}")

    with httpx.Client(timeout=60.0) as client:
        response = client.get(url, headers=get_headers())
        response.raise_for_status()
        return _parse_jsonlines(response.text)


def query_hits(
    query: str,
    start: datetime | None = None,
    end: datetime | None = None,
    step: str = "5m",
) -> dict:
    """Get log hit counts over time buckets.

    Returns compact counts per time bucket, not raw logs.

    Args:
        query: LogsQL query string
        start: Start time (default: 1 hour ago)
        end: End time (default: now)
        step: Time bucket size (default: 5m)

    Returns:
        Hits response with time buckets and counts
    """
    now = datetime.now(timezone.utc)
    if end is None:
        end = now
    if start is None:
        start = now - timedelta(hours=1)

    params = {
        "query": query,
        "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "step": step,
    }

    url = get_api_url(f"/select/logsql/hits?{urlencode(params)}")

    with httpx.Client(timeout=60.0) as client:
        response = client.get(url, headers=get_headers())
        response.raise_for_status()
        return response.json()


def query_stats(
    query: str,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict:
    """Execute an instant stats query.

    Args:
        query: LogsQL query with | stats pipe
        start: Start time (default: 1 hour ago)
        end: End time (default: now)

    Returns:
        Stats response
    """
    now = datetime.now(timezone.utc)
    if end is None:
        end = now
    if start is None:
        start = now - timedelta(hours=1)

    params = {
        "query": query,
        "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    url = get_api_url(f"/select/logsql/stats_query?{urlencode(params)}")

    with httpx.Client(timeout=60.0) as client:
        response = client.get(url, headers=get_headers())
        response.raise_for_status()
        return response.json()


def get_field_names(
    query: str = "*",
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[dict]:
    """Get all field names in logs matching query.

    Args:
        query: LogsQL filter (default: * = all)
        start: Start time (default: 1 hour ago)
        end: End time (default: now)

    Returns:
        List of dicts with field name and hit count
    """
    now = datetime.now(timezone.utc)
    if end is None:
        end = now
    if start is None:
        start = now - timedelta(hours=1)

    params = {
        "query": query,
        "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    url = get_api_url(f"/select/logsql/stream_field_names?{urlencode(params)}")

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, headers=get_headers())
        response.raise_for_status()
        return _parse_jsonlines(response.text)


def get_field_values(
    query: str,
    field: str,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 50,
) -> list[dict]:
    """Get distinct values for a specific field.

    Args:
        query: LogsQL filter
        field: Field name to get values for
        start: Start time (default: 1 hour ago)
        end: End time (default: now)
        limit: Max values to return

    Returns:
        List of dicts with field value and hit count
    """
    now = datetime.now(timezone.utc)
    if end is None:
        end = now
    if start is None:
        start = now - timedelta(hours=1)

    params = {
        "query": query,
        "field": field,
        "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "limit": str(limit),
    }

    url = get_api_url(f"/select/logsql/stream_field_values?{urlencode(params)}")

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, headers=get_headers())
        response.raise_for_status()
        return _parse_jsonlines(response.text)


def get_stream_ids(
    query: str = "*",
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 20,
) -> list[dict]:
    """Get stream IDs matching query.

    Args:
        query: LogsQL filter (default: * = all)
        start: Start time (default: 1 hour ago)
        end: End time (default: now)
        limit: Max streams to return

    Returns:
        List of dicts with stream_id and hit count
    """
    now = datetime.now(timezone.utc)
    if end is None:
        end = now
    if start is None:
        start = now - timedelta(hours=1)

    params = {
        "query": query,
        "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "limit": str(limit),
    }

    url = get_api_url(f"/select/logsql/stream_ids?{urlencode(params)}")

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, headers=get_headers())
        response.raise_for_status()
        return _parse_jsonlines(response.text)


def format_log_entry(entry: dict, max_length: int = 200) -> str:
    """Format a log entry for human-readable display.

    Truncates message to max_length to avoid flooding the context window.

    Args:
        entry: Log entry dict from VictoriaLogs
        max_length: Maximum message length

    Returns:
        Formatted string
    """
    # Extract key fields
    timestamp = entry.get("_time", "")
    if timestamp:
        # Truncate nanoseconds for readability
        timestamp = timestamp[:19]

    stream = entry.get("_stream", "")
    msg = entry.get("_msg", "")
    level = entry.get("level", entry.get("severity", ""))

    # Truncate message
    if len(msg) > max_length:
        msg = msg[: max_length - 3] + "..."

    # Build context
    context_parts = []
    if level:
        context_parts.append(level.upper())
    if stream:
        context_parts.append(stream)

    context = " ".join(context_parts)

    if context:
        return f"[{timestamp}] {context}\n  {msg}"
    else:
        return f"[{timestamp}] {msg}"


def normalize_message(msg: str) -> str:
    """Normalize a log message for pattern grouping.

    Removes UUIDs, IPs, numbers, and timestamps to group similar messages.
    """
    # Remove UUIDs
    normalized = re.sub(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
        "<UUID>",
        msg,
    )
    # Remove IPs
    normalized = re.sub(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "<IP>", normalized)
    # Remove numbers (but keep common status codes context)
    normalized = re.sub(r"\b\d+\b", "<N>", normalized)
    # Truncate for grouping
    return normalized[:100]

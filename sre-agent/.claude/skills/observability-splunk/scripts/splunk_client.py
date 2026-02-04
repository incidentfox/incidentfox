#!/usr/bin/env python3
"""Shared Splunk client with proxy support.

This module provides the Splunk client that works through the credential proxy.
Credentials are injected transparently by the proxy layer.

Uses Splunk REST API for search operations.
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx


def get_config() -> dict[str, str | None]:
    """Get Splunk configuration from environment.

    Credentials are injected by the credential-proxy based on tenant context.

    Environment variables:
        INCIDENTFOX_TENANT_ID - Tenant ID for credential lookup
        INCIDENTFOX_TEAM_ID - Team ID for credential lookup
        SPLUNK_INDEX - Default index (e.g., main)
    """
    return {
        "tenant_id": os.getenv("INCIDENTFOX_TENANT_ID", "local"),
        "team_id": os.getenv("INCIDENTFOX_TEAM_ID", "local"),
        "index": os.getenv("SPLUNK_INDEX", "main"),
    }


def get_api_url(endpoint: str) -> str:
    """Build the Splunk API URL.

    Supports two modes:
    1. Proxy mode (production): Uses SPLUNK_BASE_URL
    2. Direct mode (testing): Uses SPLUNK_URL

    Args:
        endpoint: API path (e.g., "/services/search/jobs")

    Returns:
        Full API URL
    """
    # Proxy mode (production)
    base_url = os.getenv("SPLUNK_BASE_URL")
    if base_url:
        return f"{base_url.rstrip('/')}{endpoint}"

    # Direct mode (testing/enterprise)
    direct_url = os.getenv("SPLUNK_URL")
    if direct_url:
        return f"{direct_url.rstrip('/')}{endpoint}"

    raise RuntimeError(
        "Either SPLUNK_BASE_URL (proxy mode) or SPLUNK_URL (direct mode) must be set."
    )


def get_headers() -> dict[str, str]:
    """Get Splunk API headers.

    Supports multiple auth methods:
    1. Bearer token - SPLUNK_TOKEN (Splunk Cloud / HEC token)
    2. Basic auth - SPLUNK_USER + SPLUNK_PASSWORD
    3. Proxy mode - tenant context headers

    Environment variables:
        SPLUNK_TOKEN: Bearer token (Splunk Cloud, HEC)
        SPLUNK_USER + SPLUNK_PASSWORD: Basic auth
    """
    config = get_config()
    import base64

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }

    # Priority 1: Bearer token (Splunk Cloud / enterprise)
    token = os.getenv("SPLUNK_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
        return headers

    # Priority 2: Basic auth
    user = os.getenv("SPLUNK_USER")
    password = os.getenv("SPLUNK_PASSWORD")
    if user and password:
        encoded = base64.b64encode(f"{user}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {encoded}"
        return headers

    # Priority 3: Proxy mode - use JWT for credential-resolver auth
    if os.getenv("SPLUNK_BASE_URL"):
        sandbox_jwt = os.getenv("SANDBOX_JWT")
        if sandbox_jwt:
            headers["X-Sandbox-JWT"] = sandbox_jwt
        else:
            # Fallback for local dev
            headers["X-Tenant-Id"] = config.get("tenant_id") or "local"
            headers["X-Team-Id"] = config.get("team_id") or "local"

    return headers


def execute_search(
    search_query: str,
    time_range_minutes: int = 60,
    max_results: int = 100,
    exec_mode: str = "blocking",
) -> list[dict[str, Any]]:
    """Execute a Splunk search and return results.

    Args:
        search_query: SPL search query (without 'search' prefix)
        time_range_minutes: Time range to query (default: 60 minutes)
        max_results: Maximum results to return (default: 100)
        exec_mode: Execution mode - blocking, oneshot, or normal (default: blocking)

    Returns:
        List of result dictionaries

    Raises:
        httpx.HTTPStatusError: On API errors
    """
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(minutes=time_range_minutes)

    # Ensure query starts with 'search'
    if not search_query.strip().lower().startswith("search"):
        search_query = f"search {search_query}"

    # Create search job
    job_url = get_api_url("/services/search/jobs")

    job_params = {
        "search": search_query,
        "earliest_time": start_time.strftime("%Y-%m-%dT%H:%M:%S"),
        "latest_time": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "output_mode": "json",
        "exec_mode": exec_mode,
        "max_count": max_results,
    }

    with httpx.Client(timeout=120.0, verify=False) as client:
        # Create the job
        response = client.post(
            job_url,
            headers=get_headers(),
            data=urlencode(job_params),
        )
        response.raise_for_status()

        job_data = response.json()
        sid = job_data.get("sid")

        if not sid:
            raise RuntimeError("Failed to get search job SID")

        # For blocking mode, results are ready immediately
        # For normal mode, poll until done
        if exec_mode == "normal":
            status_url = get_api_url(f"/services/search/jobs/{sid}")
            for _ in range(60):  # Max 60 iterations
                status_response = client.get(
                    status_url,
                    headers=get_headers(),
                    params={"output_mode": "json"},
                )
                status_data = status_response.json()
                entry = status_data.get("entry", [{}])[0]
                content = entry.get("content", {})

                if content.get("isDone"):
                    break
                time.sleep(1)

        # Fetch results
        results_url = get_api_url(f"/services/search/jobs/{sid}/results")
        results_response = client.get(
            results_url,
            headers=get_headers(),
            params={"output_mode": "json", "count": max_results},
        )
        results_response.raise_for_status()

        results_data = results_response.json()
        return results_data.get("results", [])


def format_log_entry(result: dict[str, Any], max_message_length: int = 300) -> str:
    """Format a Splunk result for display.

    Args:
        result: Splunk result dictionary
        max_message_length: Maximum length for message

    Returns:
        Formatted string
    """
    # Common Splunk field names
    timestamp = result.get("_time", "")
    level = (
        result.get("log_level")
        or result.get("level")
        or result.get("severity")
        or "INFO"
    )
    source = result.get("source", "")
    sourcetype = result.get("sourcetype", "")
    host = result.get("host", "")
    message = result.get("_raw") or result.get("message") or ""

    # Format timestamp
    if "T" in str(timestamp):
        ts = str(timestamp).split(".")[0].replace("T", " ")
    else:
        ts = str(timestamp)

    # Truncate message
    if len(message) > max_message_length:
        message = message[:max_message_length] + "..."

    lines = [f"[{str(level).upper()}] {ts} | {sourcetype or source}"]
    if message:
        lines.append(f"  {message}")
    if host:
        lines.append(f"  Host: {host}")

    return "\n".join(lines)

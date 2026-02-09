#!/usr/bin/env python3
"""Shared Honeycomb API client with proxy support.

This module provides the Honeycomb API client that works through the credential proxy.
Credentials are injected transparently by the proxy layer.

Honeycomb Endpoints:
- US: api.honeycomb.io (default)
- EU: api.eu1.honeycomb.io
"""

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

DEFAULT_API_ENDPOINT = "https://api.honeycomb.io"


def get_config() -> dict[str, str | None]:
    """Get Honeycomb configuration from environment.

    Credentials are injected by the credential-proxy based on tenant context.

    Environment variables:
        INCIDENTFOX_TENANT_ID - Tenant ID for credential lookup
        INCIDENTFOX_TEAM_ID - Team ID for credential lookup
        HONEYCOMB_API_ENDPOINT - Honeycomb API endpoint (optional)
    """
    return {
        "tenant_id": os.getenv("INCIDENTFOX_TENANT_ID", "local"),
        "team_id": os.getenv("INCIDENTFOX_TEAM_ID", "local"),
        "api_endpoint": os.getenv("HONEYCOMB_API_ENDPOINT", DEFAULT_API_ENDPOINT),
    }


def get_api_url(endpoint: str) -> str:
    """Build the Honeycomb API URL.

    Supports two modes:
    1. Proxy mode (production): Uses HONEYCOMB_BASE_URL
    2. Direct mode (testing): Uses HONEYCOMB_API_KEY

    Args:
        endpoint: API path (e.g., "/1/datasets")

    Returns:
        Full API URL
    """
    # Proxy mode (production)
    base_url = os.getenv("HONEYCOMB_BASE_URL")
    if base_url:
        return f"{base_url.rstrip('/')}{endpoint}"

    # Direct mode (testing) - requires HONEYCOMB_API_KEY
    api_endpoint = os.getenv("HONEYCOMB_API_ENDPOINT", DEFAULT_API_ENDPOINT)
    if os.getenv("HONEYCOMB_API_KEY"):
        return f"{api_endpoint.rstrip('/')}{endpoint}"

    raise RuntimeError(
        "Either HONEYCOMB_BASE_URL (proxy mode) or HONEYCOMB_API_KEY (direct mode) must be set."
    )


def get_headers() -> dict[str, str]:
    """Get Honeycomb API headers.

    In proxy mode: includes tenant context for credential lookup.
    In direct mode: includes API key directly.
    """
    config = get_config()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # Direct mode - add API key directly
    api_key = os.getenv("HONEYCOMB_API_KEY")
    if api_key:
        headers["X-Honeycomb-Team"] = api_key
    else:
        # Proxy mode - use JWT for credential-resolver auth
        sandbox_jwt = os.getenv("SANDBOX_JWT")
        if sandbox_jwt:
            headers["X-Sandbox-JWT"] = sandbox_jwt
        else:
            # Fallback for local dev
            headers["X-Tenant-Id"] = config.get("tenant_id") or "local"
            headers["X-Team-Id"] = config.get("team_id") or "local"

    return headers


def list_datasets() -> list[dict[str, Any]]:
    """List all datasets in the Honeycomb environment.

    Returns:
        List of datasets with name, slug, description, and timestamps

    Raises:
        httpx.HTTPStatusError: On API errors
    """
    url = get_api_url("/1/datasets")

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, headers=get_headers())
        response.raise_for_status()

        datasets = response.json()
        return [
            {
                "name": ds.get("name"),
                "slug": ds.get("slug"),
                "description": ds.get("description"),
                "created_at": ds.get("created_at"),
                "last_written_at": ds.get("last_written_at"),
            }
            for ds in datasets
        ]


def get_columns(dataset_slug: str) -> list[dict[str, Any]]:
    """Get columns (fields) for a dataset.

    Args:
        dataset_slug: The dataset slug/identifier

    Returns:
        List of columns with name, type, and metadata

    Raises:
        httpx.HTTPStatusError: On API errors
    """
    url = get_api_url(f"/1/columns/{dataset_slug}")

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, headers=get_headers())
        response.raise_for_status()

        columns = response.json()
        return [
            {
                "key_name": col.get("key_name"),
                "type": col.get("type"),
                "description": col.get("description"),
                "hidden": col.get("hidden", False),
                "last_written": col.get("last_written"),
            }
            for col in columns
        ]


def run_query(
    dataset_slug: str,
    calculations: list[dict[str, Any]] | None = None,
    filters: list[dict[str, Any]] | None = None,
    breakdowns: list[str] | None = None,
    time_range: int = 3600,
    granularity: int | None = None,
    limit: int | None = None,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Run a query on a Honeycomb dataset.

    Args:
        dataset_slug: The dataset slug/identifier
        calculations: List of calculations, e.g., [{"op": "COUNT"}, {"op": "P99", "column": "duration_ms"}]
        filters: List of filters, e.g., [{"column": "status", "op": "=", "value": "error"}]
        breakdowns: List of columns to group by
        time_range: Time range in seconds (default: 3600 = 1 hour)
        granularity: Time bucket size in seconds (optional)
        limit: Maximum results per group (optional)
        timeout_seconds: Query timeout (default: 60)

    Returns:
        Query results with data and series

    Raises:
        httpx.HTTPStatusError: On API errors
        TimeoutError: If query doesn't complete in time
    """
    headers = get_headers()

    # Default to COUNT if no calculations specified
    if not calculations:
        calculations = [{"op": "COUNT"}]

    # Build query spec
    query_spec = {
        "calculations": calculations,
        "time_range": time_range,
    }

    if filters:
        query_spec["filters"] = filters
    if breakdowns:
        query_spec["breakdowns"] = breakdowns
    if granularity:
        query_spec["granularity"] = granularity
    if limit:
        query_spec["limit"] = limit

    with httpx.Client(timeout=float(timeout_seconds + 10)) as client:
        # Step 1: Create query spec
        create_url = get_api_url(f"/1/queries/{dataset_slug}")
        create_response = client.post(create_url, headers=headers, json=query_spec)
        create_response.raise_for_status()

        query_data = create_response.json()
        query_id = query_data.get("id")

        if not query_id:
            raise RuntimeError("Failed to create query - no query ID returned")

        # Step 2: Execute query
        execute_url = get_api_url(f"/1/query_results/{dataset_slug}")
        execute_response = client.post(
            execute_url, headers=headers, json={"query_id": query_id}
        )
        execute_response.raise_for_status()

        result_data = execute_response.json()
        query_result_id = result_data.get("id")

        if not query_result_id:
            raise RuntimeError("Failed to execute query - no result ID returned")

        # Step 3: Poll for results
        poll_url = get_api_url(f"/1/query_results/{dataset_slug}/{query_result_id}")
        max_attempts = timeout_seconds
        poll_interval = 1.0

        for _ in range(max_attempts):
            poll_response = client.get(poll_url, headers=headers)
            poll_response.raise_for_status()
            poll_data = poll_response.json()

            if poll_data.get("complete"):
                return {
                    "query_id": query_id,
                    "result_id": query_result_id,
                    "data": poll_data.get("data", {}).get("results", []),
                    "series": poll_data.get("data", {}).get("series", []),
                    "complete": True,
                }

            time.sleep(poll_interval)

        raise TimeoutError(f"Query timed out after {timeout_seconds} seconds")


def list_slos(dataset_slug: str) -> list[dict[str, Any]]:
    """List SLOs for a dataset.

    Args:
        dataset_slug: The dataset slug/identifier

    Returns:
        List of SLOs with name, target, and status

    Raises:
        httpx.HTTPStatusError: On API errors
    """
    url = get_api_url(f"/1/slos/{dataset_slug}")

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, headers=get_headers())
        response.raise_for_status()

        slos = response.json()
        return [
            {
                "id": slo.get("id"),
                "name": slo.get("name"),
                "description": slo.get("description"),
                "target_percentage": slo.get("target_percentage"),
                "time_period_days": slo.get("time_period_days"),
                "sli": slo.get("sli"),
            }
            for slo in slos
        ]


def list_triggers(dataset_slug: str) -> list[dict[str, Any]]:
    """List triggers (alerts) for a dataset.

    Args:
        dataset_slug: The dataset slug/identifier

    Returns:
        List of triggers with name, threshold, and status

    Raises:
        httpx.HTTPStatusError: On API errors
    """
    url = get_api_url(f"/1/triggers/{dataset_slug}")

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, headers=get_headers())
        response.raise_for_status()

        triggers = response.json()
        return [
            {
                "id": trigger.get("id"),
                "name": trigger.get("name"),
                "description": trigger.get("description"),
                "disabled": trigger.get("disabled", False),
                "triggered": trigger.get("triggered", False),
                "frequency": trigger.get("frequency"),
                "threshold": trigger.get("threshold"),
            }
            for trigger in triggers
        ]


def format_results(
    results: list[dict[str, Any]], breakdowns: list[str] | None = None
) -> str:
    """Format query results for display.

    Args:
        results: Query results from run_query
        breakdowns: Breakdown columns used in query

    Returns:
        Formatted string for display
    """
    if not results:
        return "No results found."

    lines = []
    for i, row in enumerate(results[:50]):  # Limit to 50 rows
        parts = []

        # Add breakdown values
        if breakdowns:
            for bd in breakdowns:
                val = row.get(bd, "N/A")
                parts.append(f"{bd}={val}")

        # Add aggregation values
        for key, value in row.items():
            if breakdowns and key in breakdowns:
                continue
            if isinstance(value, float):
                parts.append(f"{key}={value:.2f}")
            else:
                parts.append(f"{key}={value}")

        lines.append(" | ".join(parts))

    return "\n".join(lines)

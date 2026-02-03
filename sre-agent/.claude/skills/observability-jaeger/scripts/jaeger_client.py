#!/usr/bin/env python3
"""Shared Jaeger API client with proxy support."""

import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Any


def get_api_url() -> str:
    """Get Jaeger API URL from environment or use proxy default."""
    # Check for direct URL first
    if os.environ.get("JAEGER_URL"):
        return os.environ["JAEGER_URL"].rstrip("/")

    # Default to proxy endpoint
    return "http://localhost:8001/jaeger"


def get_headers() -> dict[str, str]:
    """Get headers for API requests (proxy handles auth)."""
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def api_request(endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Make a GET request to Jaeger API.

    Args:
        endpoint: API endpoint (e.g., '/api/services')
        params: Query parameters

    Returns:
        JSON response as dict
    """
    base_url = get_api_url()
    url = f"{base_url}{endpoint}"

    if params:
        # Filter out None values and convert to strings
        filtered_params = {k: str(v) for k, v in params.items() if v is not None}
        if filtered_params:
            url = f"{url}?{urllib.parse.urlencode(filtered_params)}"

    req = urllib.request.Request(url, headers=get_headers())

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else ""
        raise RuntimeError(f"Jaeger API error {e.code}: {error_body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Failed to connect to Jaeger: {e.reason}") from e


def get_services() -> list[str]:
    """Get list of all services."""
    response = api_request("/api/services")
    return response.get("data", [])


def get_operations(service: str) -> list[str]:
    """Get list of operations for a service."""
    response = api_request(f"/api/services/{urllib.parse.quote(service)}/operations")
    return response.get("data", [])


def search_traces(
    service: str,
    operation: str | None = None,
    tags: dict[str, str] | None = None,
    min_duration: int | None = None,
    max_duration: int | None = None,
    limit: int = 20,
    lookback_hours: float = 1,
) -> list[dict[str, Any]]:
    """Search for traces with filters.

    Args:
        service: Service name (required)
        operation: Operation name filter
        tags: Tag filters as key=value pairs
        min_duration: Minimum duration in milliseconds
        max_duration: Maximum duration in milliseconds
        limit: Maximum number of traces to return
        lookback_hours: How far back to search in hours

    Returns:
        List of trace objects
    """
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(hours=lookback_hours)

    params = {
        "service": service,
        "limit": limit,
        "start": int(start_time.timestamp() * 1_000_000),  # microseconds
        "end": int(now.timestamp() * 1_000_000),
    }

    if operation:
        params["operation"] = operation

    if min_duration:
        params["minDuration"] = f"{min_duration}ms"

    if max_duration:
        params["maxDuration"] = f"{max_duration}ms"

    if tags:
        # Jaeger expects tags as JSON string
        params["tags"] = json.dumps(tags)

    response = api_request("/api/traces", params)
    return response.get("data", [])


def get_trace(trace_id: str) -> dict[str, Any] | None:
    """Get a specific trace by ID.

    Args:
        trace_id: The trace ID

    Returns:
        Trace object or None if not found
    """
    response = api_request(f"/api/traces/{trace_id}")
    traces = response.get("data", [])
    return traces[0] if traces else None


def format_duration(microseconds: int) -> str:
    """Format duration in microseconds to human readable string."""
    if microseconds < 1000:
        return f"{microseconds}µs"
    elif microseconds < 1_000_000:
        return f"{microseconds / 1000:.1f}ms"
    else:
        return f"{microseconds / 1_000_000:.2f}s"


def extract_span_info(span: dict[str, Any], processes: dict[str, Any]) -> dict[str, Any]:
    """Extract relevant info from a span.

    Args:
        span: Span object from Jaeger
        processes: Process map from trace

    Returns:
        Simplified span info dict
    """
    process_id = span.get("processID", "")
    process = processes.get(process_id, {})
    service_name = process.get("serviceName", "unknown")

    # Extract tags
    tags = {}
    for tag in span.get("tags", []):
        tags[tag["key"]] = tag["value"]

    # Check for errors
    has_error = tags.get("error", False) or tags.get("otel.status_code") == "ERROR"

    return {
        "span_id": span.get("spanID", ""),
        "trace_id": span.get("traceID", ""),
        "operation": span.get("operationName", ""),
        "service": service_name,
        "duration_us": span.get("duration", 0),
        "duration": format_duration(span.get("duration", 0)),
        "start_time": span.get("startTime", 0),
        "tags": tags,
        "has_error": has_error,
        "logs": span.get("logs", []),
    }


def calculate_latency_stats(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate latency statistics from traces.

    Args:
        traces: List of trace objects

    Returns:
        Statistics dict with p50, p95, p99, etc.
    """
    if not traces:
        return {"count": 0, "p50": 0, "p95": 0, "p99": 0, "min": 0, "max": 0, "avg": 0}

    # Get root span durations
    durations = []
    for trace in traces:
        spans = trace.get("spans", [])
        if spans:
            # Find root span (no parent or min start time)
            root_span = min(spans, key=lambda s: s.get("startTime", float("inf")))
            durations.append(root_span.get("duration", 0))

    if not durations:
        return {"count": 0, "p50": 0, "p95": 0, "p99": 0, "min": 0, "max": 0, "avg": 0}

    durations.sort()
    n = len(durations)

    def percentile(p: float) -> int:
        idx = int(n * p / 100)
        return durations[min(idx, n - 1)]

    return {
        "count": n,
        "p50": percentile(50),
        "p95": percentile(95),
        "p99": percentile(99),
        "min": durations[0],
        "max": durations[-1],
        "avg": sum(durations) // n,
    }

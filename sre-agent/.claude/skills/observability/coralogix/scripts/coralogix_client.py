#!/usr/bin/env python3
"""Shared Coralogix API client with correct endpoint mapping.

This module provides the correct API URL construction for Coralogix DataPrime queries.

Region/Domain mapping (from Coralogix docs):
- US1: api.us1.coralogix.com (team hostname: *.app.coralogix.us)
- US2: api.us2.coralogix.com (team hostname: *.app.cx498.coralogix.com)
- EU1: api.eu1.coralogix.com (team hostname: *.coralogix.com)
- EU2: api.eu2.coralogix.com (team hostname: *.app.eu2.coralogix.com)
- AP1: api.ap1.coralogix.com (team hostname: *.app.coralogix.in)
- AP2: api.ap2.coralogix.com (team hostname: *.app.coralogixsg.com)
- AP3: api.ap3.coralogix.com (team hostname: *.app.ap3.coralogix.com)
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta
from typing import Any

import httpx

# Mapping from team hostname patterns to API domains
HOSTNAME_TO_DOMAIN = {
    r"\.app\.coralogix\.us$": "us1.coralogix.com",
    r"\.app\.cx498\.coralogix\.com$": "us2.coralogix.com",
    r"\.coralogix\.com$": "eu1.coralogix.com",  # Default EU1 (must be after cx498)
    r"\.app\.eu2\.coralogix\.com$": "eu2.coralogix.com",
    r"\.app\.coralogix\.in$": "ap1.coralogix.com",
    r"\.app\.coralogixsg\.com$": "ap2.coralogix.com",
    r"\.app\.ap3\.coralogix\.com$": "ap3.coralogix.com",
}

# Direct region code to domain mapping
REGION_TO_DOMAIN = {
    "us1": "us1.coralogix.com",
    "us2": "us2.coralogix.com",
    "cx498": "us2.coralogix.com",  # cx498 is US2
    "eu1": "eu1.coralogix.com",
    "eu2": "eu2.coralogix.com",
    "ap1": "ap1.coralogix.com",
    "ap2": "ap2.coralogix.com",
    "ap3": "ap3.coralogix.com",
}


def get_config() -> dict[str, str | None]:
    """Get Coralogix configuration from environment.

    Environment variables:
        CORALOGIX_API_KEY - Required API key
        CORALOGIX_DOMAIN - Team hostname (e.g., myteam.app.cx498.coralogix.com)
        CORALOGIX_REGION - Region code (e.g., us2, eu1)
    """
    api_key = os.getenv("CORALOGIX_API_KEY")
    if not api_key:
        print("Error: CORALOGIX_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)

    return {
        "api_key": api_key,
        "domain": os.getenv("CORALOGIX_DOMAIN"),
        "region": os.getenv("CORALOGIX_REGION"),
    }


def resolve_api_domain(config: dict[str, str | None]) -> str:
    """Resolve the correct API domain from configuration.

    Priority:
    1. Extract from CORALOGIX_DOMAIN (team hostname)
    2. Map from CORALOGIX_REGION
    3. Default to US2 (cx498)
    """
    domain = config.get("domain")

    if domain:
        # Try to match against known hostname patterns
        # Order matters: check more specific patterns first
        for pattern, api_domain in [
            (r"\.app\.cx498\.coralogix\.com", "us2.coralogix.com"),
            (r"\.app\.coralogix\.us", "us1.coralogix.com"),
            (r"\.app\.eu2\.coralogix\.com", "eu2.coralogix.com"),
            (r"\.app\.coralogix\.in", "ap1.coralogix.com"),
            (r"\.app\.coralogixsg\.com", "ap2.coralogix.com"),
            (r"\.app\.ap3\.coralogix\.com", "ap3.coralogix.com"),
            (r"\.coralogix\.com", "eu1.coralogix.com"),  # Generic .coralogix.com = EU1
        ]:
            if re.search(pattern, domain):
                return api_domain

        # If domain looks like an API domain already (api.X.coralogix.com)
        match = re.search(r"api\.([a-z0-9]+)\.coralogix\.com", domain)
        if match:
            return f"{match.group(1)}.coralogix.com"

    # Try region mapping
    region = config.get("region")
    if region:
        region_lower = region.lower()
        if region_lower in REGION_TO_DOMAIN:
            return REGION_TO_DOMAIN[region_lower]

    # Default to US2
    return "us2.coralogix.com"


def get_api_url(endpoint: str) -> str:
    """Build the correct Coralogix API URL.

    Args:
        endpoint: API path (e.g., "/api/v1/dataprime/query")

    Returns:
        Full API URL (e.g., "https://api.us2.coralogix.com/api/v1/dataprime/query")
    """
    config = get_config()
    api_domain = resolve_api_domain(config)
    return f"https://api.{api_domain}{endpoint}"


def get_headers() -> dict[str, str]:
    """Get Coralogix API headers with proper authentication."""
    config = get_config()
    api_key = config["api_key"]

    # Handle both raw keys and "Bearer xxx" format
    if api_key and api_key.lower().startswith("bearer "):
        auth_value = api_key
    else:
        auth_value = f"Bearer {api_key}"

    return {
        "Authorization": auth_value,
        "Content-Type": "application/json",
    }


def parse_result(result: dict[str, Any]) -> dict[str, Any]:
    """Parse a single result, handling userData JSON strings.

    Coralogix returns aggregation results in userData as a JSON string.
    This function parses that and merges it into a flat dict.
    """
    parsed = {}

    # Copy metadata and labels if present
    for item in result.get("metadata", []):
        if isinstance(item, dict) and "key" in item and "value" in item:
            parsed[item["key"]] = item["value"]

    for item in result.get("labels", []):
        if isinstance(item, dict) and "key" in item and "value" in item:
            parsed[item["key"]] = item["value"]

    # Parse userData - this is where aggregation results live
    user_data = result.get("userData")
    if user_data:
        if isinstance(user_data, str):
            try:
                user_data = json.loads(user_data)
            except json.JSONDecodeError:
                pass
        if isinstance(user_data, dict):
            parsed.update(user_data)

    # If we didn't find anything, return original
    return parsed if parsed else result


def execute_query(
    query: str,
    time_range_minutes: int = 60,
    limit: int = 100,
    tier: str = "TIER_FREQUENT_SEARCH",
) -> list[dict[str, Any]]:
    """Execute a DataPrime query and return results.

    Args:
        query: DataPrime query string
        time_range_minutes: Time range to query (default: 60 minutes)
        limit: Maximum results to return (default: 100)
        tier: Storage tier (TIER_FREQUENT_SEARCH or TIER_ARCHIVE)

    Returns:
        List of result dictionaries

    Raises:
        httpx.HTTPStatusError: On API errors
    """
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(minutes=time_range_minutes)

    url = get_api_url("/api/v1/dataprime/query")

    payload = {
        "query": query,
        "metadata": {
            "startDate": start_time.isoformat() + "Z",
            "endDate": end_time.isoformat() + "Z",
            "tier": tier,
        },
        "limit": limit,
    }

    with httpx.Client(timeout=60.0) as client:
        response = client.post(url, headers=get_headers(), json=payload)
        response.raise_for_status()

        # Parse NDJSON response (newline-delimited JSON)
        all_results = []
        for line in response.text.strip().split("\n"):
            if line.strip():
                try:
                    obj = json.loads(line)
                    if "result" in obj and "results" in obj["result"]:
                        # Parse each result to handle userData JSON strings
                        for raw_result in obj["result"]["results"]:
                            all_results.append(parse_result(raw_result))
                except json.JSONDecodeError:
                    continue

        return all_results


def format_log_entry(result: dict[str, Any], max_body_length: int = 300) -> str:
    """Format a log entry result for display with clear structure.

    Args:
        result: Log entry dictionary from query results
        max_body_length: Maximum length for log body (truncated if longer)

    Returns:
        Multi-line formatted string with severity, timestamp, service, message, and context
    """
    # Handle different response formats
    timestamp = result.get("timestamp", result.get("@timestamp", ""))

    # Severity can be in different locations
    severity_raw = (
        result.get("severity")
        or result.get("$m.severity")
        or result.get("severityText")
        or "3"
    )

    # Map numeric severity to human-readable names
    severity_map = {
        "1": "DEBUG",
        "2": "VERBOSE",
        "3": "INFO",
        "4": "WARNING",
        "5": "ERROR",
        "6": "CRITICAL",
    }
    severity = severity_map.get(str(severity_raw), str(severity_raw).upper())

    # Subsystem/service name
    subsystem = (
        result.get("subsystemname")
        or result.get("$l.subsystemname")
        or result.get("subsystemName")
        or "unknown"
    )

    # Log body/message - handle multiple formats
    body = ""
    # OTEL format: nested in logRecord.body
    log_record = result.get("logRecord", {})
    if isinstance(log_record, dict):
        body = log_record.get("body", "")
    # Direct body field
    if not body:
        body = (
            result.get("body")
            or result.get("$d")
            or result.get("message")
            or result.get("userData", "")
        )
    # Handle nested dict in body
    if isinstance(body, dict):
        body = body.get("logRecord", {}).get("body", str(body))
    # Structured logs without body - create pattern from key fields
    if not body:
        parts = []
        for key in [
            "limit_event_type",
            "limit_name",
            "error_type",
            "error_code",
            "exception",
            "error",
        ]:
            if key in result:
                parts.append(f"{key}={result[key]}")
        body = " ".join(parts) if parts else str(result)[:100]

    # Truncate message if needed
    body_str = str(body)
    if len(body_str) > max_body_length:
        body_str = body_str[:max_body_length] + "..."

    # Format timestamp to be more readable
    if "T" in str(timestamp):
        # ISO format: "2026-01-27T06:09:39.657474697" -> "2026-01-27 06:09:39"
        ts = str(timestamp).split(".")[0].replace("T", " ")
    else:
        ts = str(timestamp)

    # Build multi-line output
    lines = [f"[{severity}] {ts} | {subsystem}", f"  {body_str}"]

    # Add optional context from OTEL resource attributes
    resource = result.get("resource", {})
    if isinstance(resource, dict):
        attrs = resource.get("attributes", {})
        context_parts = []

        # K8s pod name
        pod = attrs.get("k8s.pod.name", "")
        if pod:
            context_parts.append(f"pod={pod}")

        # K8s node name (short form)
        node = attrs.get("k8s.node.name", "")
        if node:
            # Shorten AWS node names: "ip-10-0-40-187.us-west-2.compute.internal" -> "ip-10-0-40-187"
            node_short = node.split(".")[0] if "." in node else node
            context_parts.append(f"node={node_short}")

        # Namespace (if not already obvious)
        namespace = attrs.get("k8s.namespace.name", "")
        if namespace and namespace != subsystem:
            context_parts.append(f"ns={namespace}")

        if context_parts:
            lines.append(f"  Context: {', '.join(context_parts)}")

    return "\n".join(lines)

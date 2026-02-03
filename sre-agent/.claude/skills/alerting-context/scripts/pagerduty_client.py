"""Shared PagerDuty API client with credential proxy support.

This client is designed to work with the IncidentFox credential proxy.
Credentials are injected automatically - scripts should NOT check for
PAGERDUTY_API_KEY in environment variables.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx


def get_config() -> dict[str, Any]:
    """Load configuration from standard locations."""
    config = {}

    # Check for config file
    config_paths = [
        Path.home() / ".incidentfox" / "config.json",
        Path("/etc/incidentfox/config.json"),
    ]

    for path in config_paths:
        if path.exists():
            with open(path) as f:
                config = json.load(f)
                break

    # Environment overrides
    if os.getenv("TENANT_ID"):
        config["tenant_id"] = os.getenv("TENANT_ID")
    if os.getenv("TEAM_ID"):
        config["team_id"] = os.getenv("TEAM_ID")

    return config


def get_api_url(endpoint: str) -> str:
    """Get the PagerDuty API URL for an endpoint.

    In production, this routes through the credential proxy.
    """
    base_url = os.getenv("PAGERDUTY_BASE_URL")
    if not base_url:
        # Fall back to direct API (for local development only)
        base_url = "https://api.pagerduty.com"

    return f"{base_url.rstrip('/')}{endpoint}"


def get_headers() -> dict[str, str]:
    """Get headers for PagerDuty API requests.

    The credential proxy will inject Authorization header.
    """
    config = get_config()

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/vnd.pagerduty+json;version=2",
        "X-Tenant-Id": config.get("tenant_id") or "local",
        "X-Team-Id": config.get("team_id") or "local",
    }

    # For local development, allow direct token usage
    token = os.getenv("PAGERDUTY_API_KEY")
    if token and not os.getenv("PAGERDUTY_BASE_URL"):
        headers["Authorization"] = f"Token token={token}"

    return headers


def api_request(
    method: str,
    endpoint: str,
    params: dict[str, Any] | None = None,
    json_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Make a request to the PagerDuty API.

    Args:
        method: HTTP method
        endpoint: API endpoint
        params: Query parameters
        json_data: JSON body

    Returns:
        Parsed JSON response

    Raises:
        RuntimeError: If the request fails
    """
    url = get_api_url(endpoint)
    headers = get_headers()

    with httpx.Client(timeout=60.0) as client:
        response = client.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json=json_data,
        )

        if response.status_code >= 400:
            raise RuntimeError(
                f"PagerDuty API error {response.status_code}: {response.text}"
            )

        return response.json()


def get_incident(incident_id: str) -> dict[str, Any]:
    """Get details of a specific incident.

    Args:
        incident_id: PagerDuty incident ID

    Returns:
        Incident object
    """
    result = api_request("GET", f"/incidents/{incident_id}")
    return result.get("incident", {})


def list_incidents(
    status: str | None = None,
    service_ids: list[str] | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """List incidents with optional filters.

    Args:
        status: Filter by status (triggered, acknowledged, resolved)
        service_ids: Filter by service IDs
        since: Start date (ISO 8601)
        until: End date (ISO 8601)
        limit: Maximum results

    Returns:
        List of incident objects
    """
    params = {"limit": limit}
    if status:
        params["statuses[]"] = status
    if service_ids:
        params["service_ids[]"] = service_ids
    if since:
        params["since"] = since
    if until:
        params["until"] = until

    result = api_request("GET", "/incidents", params=params)
    return result.get("incidents", [])


def get_incident_log_entries(
    incident_id: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Get log entries (timeline) for an incident.

    Args:
        incident_id: PagerDuty incident ID
        limit: Maximum entries

    Returns:
        List of log entry objects
    """
    result = api_request(
        "GET",
        f"/incidents/{incident_id}/log_entries",
        params={"limit": limit},
    )
    return result.get("log_entries", [])


def get_escalation_policy(policy_id: str) -> dict[str, Any]:
    """Get an escalation policy.

    Args:
        policy_id: Escalation policy ID

    Returns:
        Escalation policy object
    """
    result = api_request("GET", f"/escalation_policies/{policy_id}")
    return result.get("escalation_policy", {})


def list_services(limit: int = 100) -> list[dict[str, Any]]:
    """List all services.

    Args:
        limit: Maximum results

    Returns:
        List of service objects
    """
    result = api_request("GET", "/services", params={"limit": limit})
    return result.get("services", [])


def get_on_calls(
    escalation_policy_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Get current on-call users.

    Args:
        escalation_policy_ids: Filter by escalation policies

    Returns:
        List of on-call objects
    """
    params = {}
    if escalation_policy_ids:
        params["escalation_policy_ids[]"] = escalation_policy_ids

    result = api_request("GET", "/oncalls", params=params)
    return result.get("oncalls", [])


def calculate_mttr(
    service_id: str | None = None,
    days: int = 30,
) -> dict[str, Any]:
    """Calculate Mean Time To Resolve for incidents.

    Args:
        service_id: Filter by service ID
        days: Number of days to analyze

    Returns:
        MTTR statistics
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat().replace("+00:00", "Z")
    until = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    params = {
        "since": since,
        "until": until,
        "statuses[]": "resolved",
        "limit": 100,
    }
    if service_id:
        params["service_ids[]"] = [service_id]

    result = api_request("GET", "/incidents", params=params)
    incidents = result.get("incidents", [])

    if not incidents:
        return {
            "sample_size": 0,
            "message": "No resolved incidents found in time range",
        }

    # Calculate resolution times
    resolution_times = []
    for inc in incidents:
        created = inc.get("created_at")
        resolved = inc.get("last_status_change_at")
        if created and resolved:
            try:
                created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                resolved_dt = datetime.fromisoformat(resolved.replace("Z", "+00:00"))
                duration = (resolved_dt - created_dt).total_seconds() / 60  # Minutes
                resolution_times.append(duration)
            except (ValueError, TypeError):
                pass

    if not resolution_times:
        return {
            "sample_size": 0,
            "message": "Could not calculate resolution times",
        }

    resolution_times.sort()
    n = len(resolution_times)

    return {
        "sample_size": n,
        "days_analyzed": days,
        "service_id": service_id,
        "mttr_minutes": {
            "mean": sum(resolution_times) / n,
            "median": resolution_times[n // 2],
            "p95": resolution_times[int(n * 0.95)] if n >= 20 else None,
            "min": min(resolution_times),
            "max": max(resolution_times),
        },
    }


def format_incident(incident: dict[str, Any]) -> str:
    """Format an incident for display.

    Args:
        incident: Incident object from API

    Returns:
        Formatted string
    """
    inc_id = incident.get("id", "")
    title = incident.get("title", "Untitled")
    status = incident.get("status", "unknown")
    urgency = incident.get("urgency", "unknown")
    created = incident.get("created_at", "")
    service = incident.get("service", {}).get("summary", "unknown")

    status_icon = {
        "triggered": "🔴",
        "acknowledged": "🟡",
        "resolved": "🟢",
    }.get(status, "❓")

    output = f"{status_icon} [{inc_id}] {title}\n"
    output += f"   Status: {status} | Urgency: {urgency}\n"
    output += f"   Service: {service}\n"
    output += f"   Created: {created}"

    return output

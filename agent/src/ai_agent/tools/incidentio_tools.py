"""Incident.io integration tools for incident management and analytics."""

import os
from typing import Any

from ..core.config_required import handle_integration_not_configured
from ..core.errors import ToolExecutionError
from ..core.execution_context import get_execution_context
from ..core.integration_errors import IntegrationNotConfiguredError
from ..core.logging import get_logger

logger = get_logger(__name__)


def _get_incidentio_config() -> dict:
    """Get Incident.io configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("incidentio")
        if config and config.get("api_key"):
            return config

    # 2. Try environment variables (dev/testing fallback)
    if os.getenv("INCIDENTIO_API_KEY"):
        return {"api_key": os.getenv("INCIDENTIO_API_KEY")}

    # 3. Not configured - raise error
    raise IntegrationNotConfiguredError(
        integration_id="incidentio",
        tool_id="incidentio_tools",
        missing_fields=["api_key"],
    )


def _get_incidentio_headers() -> dict:
    """Get headers for Incident.io API requests."""
    config = _get_incidentio_config()
    return {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }


def incidentio_list_incidents(
    status: str | None = None,
    severity_id: str | None = None,
    max_results: int = 100,
) -> dict[str, Any]:
    """
    List Incident.io incidents with optional filters.

    Args:
        status: Filter by status (triage, active, resolved, closed)
        severity_id: Filter by severity ID
        max_results: Maximum incidents to return

    Returns:
        Dict with incidents list and summary
    """
    try:
        import requests

        headers = _get_incidentio_headers()

        params = {"page_size": min(max_results, 100)}
        if status:
            params["status"] = status
        if severity_id:
            params["severity_id"] = severity_id

        all_incidents = []
        next_cursor = None

        while len(all_incidents) < max_results:
            if next_cursor:
                params["after"] = next_cursor

            response = requests.get(
                "https://api.incident.io/v2/incidents",
                headers=headers,
                params=params,
            )
            response.raise_for_status()

            data = response.json()
            incidents = data.get("incidents", [])

            if not incidents:
                break

            for incident in incidents:
                all_incidents.append(
                    {
                        "id": incident["id"],
                        "name": incident.get("name"),
                        "reference": incident.get("reference"),
                        "status": incident.get("status", {}).get("category"),
                        "severity": incident.get("severity", {}).get("name"),
                        "severity_id": incident.get("severity", {}).get("id"),
                        "created_at": incident.get("created_at"),
                        "updated_at": incident.get("updated_at"),
                        "summary": incident.get("summary"),
                        "incident_lead": incident.get("incident_lead", {}).get("name"),
                        "url": incident.get("permalink"),
                    }
                )

            # Check for pagination
            pagination = data.get("pagination_meta", {})
            if pagination.get("after"):
                next_cursor = pagination["after"]
            else:
                break

        logger.info("incidentio_incidents_listed", count=len(all_incidents))

        return {
            "success": True,
            "total_count": len(all_incidents),
            "incidents": all_incidents,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "incidentio_list_incidents", "incidentio"
        )
    except Exception as e:
        logger.error("incidentio_list_incidents_failed", error=str(e))
        raise ToolExecutionError("incidentio_list_incidents", str(e), e)


def incidentio_get_incident(incident_id: str) -> dict[str, Any]:
    """
    Get details of a specific Incident.io incident.

    Args:
        incident_id: Incident.io incident ID

    Returns:
        Incident details including status, severity, roles, and timeline
    """
    try:
        import requests

        headers = _get_incidentio_headers()

        response = requests.get(
            f"https://api.incident.io/v2/incidents/{incident_id}",
            headers=headers,
        )
        response.raise_for_status()

        incident = response.json().get("incident", {})

        # Parse roles
        roles = []
        for role in incident.get("incident_role_assignments", []):
            roles.append(
                {
                    "role": role.get("role", {}).get("name"),
                    "assignee": role.get("assignee", {}).get("name"),
                }
            )

        logger.info("incidentio_incident_fetched", incident_id=incident_id)

        return {
            "id": incident["id"],
            "name": incident.get("name"),
            "reference": incident.get("reference"),
            "status": incident.get("status", {}).get("category"),
            "severity": incident.get("severity", {}).get("name"),
            "created_at": incident.get("created_at"),
            "updated_at": incident.get("updated_at"),
            "resolved_at": incident.get("resolved_at"),
            "summary": incident.get("summary"),
            "postmortem_document_url": incident.get("postmortem_document_url"),
            "slack_channel_id": incident.get("slack_channel_id"),
            "slack_channel_name": incident.get("slack_channel_name"),
            "roles": roles,
            "custom_fields": [
                {
                    "name": cf.get("custom_field", {}).get("name"),
                    "value": cf.get("value_text")
                    or cf.get("value_option", {}).get("value"),
                }
                for cf in incident.get("custom_field_entries", [])
            ],
            "url": incident.get("permalink"),
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "incidentio_get_incident", "incidentio"
        )
    except Exception as e:
        logger.error(
            "incidentio_get_incident_failed", error=str(e), incident_id=incident_id
        )
        raise ToolExecutionError("incidentio_get_incident", str(e), e)


def incidentio_get_incident_updates(
    incident_id: str, max_results: int = 50
) -> list[dict[str, Any]]:
    """
    Get timeline updates for an Incident.io incident.

    Args:
        incident_id: Incident.io incident ID
        max_results: Maximum updates to return

    Returns:
        List of incident updates/timeline entries
    """
    try:
        import requests

        headers = _get_incidentio_headers()

        response = requests.get(
            f"https://api.incident.io/v2/incident_updates",
            headers=headers,
            params={"incident_id": incident_id, "page_size": max_results},
        )
        response.raise_for_status()

        updates = response.json().get("incident_updates", [])

        result = []
        for update in updates:
            result.append(
                {
                    "id": update["id"],
                    "created_at": update.get("created_at"),
                    "message": update.get("message"),
                    "updater": update.get("updater", {}).get("name"),
                    "new_status": update.get("new_incident_status", {}).get("category"),
                    "new_severity": update.get("new_severity", {}).get("name"),
                }
            )

        logger.info(
            "incidentio_updates_fetched", incident_id=incident_id, count=len(result)
        )

        return result

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "incidentio_get_incident_updates", "incidentio"
        )
    except Exception as e:
        logger.error(
            "incidentio_get_updates_failed", error=str(e), incident_id=incident_id
        )
        raise ToolExecutionError("incidentio_get_incident_updates", str(e), e)


def incidentio_list_incidents_by_date_range(
    since: str,
    until: str,
    status: str | None = None,
    max_results: int = 500,
) -> dict[str, Any]:
    """
    List Incident.io incidents within a date range.

    Essential for alert fatigue analysis - retrieves historical incident data
    for computing metrics like frequency, MTTA, MTTR.

    Args:
        since: Start date in ISO format (e.g., "2024-01-01T00:00:00Z")
        until: End date in ISO format (e.g., "2024-01-31T23:59:59Z")
        status: Optional status filter
        max_results: Maximum incidents to return

    Returns:
        Dict with incidents and computed metrics
    """
    try:
        from datetime import datetime

        import requests

        headers = _get_incidentio_headers()

        params = {
            "page_size": 100,
            "created_at[gte]": since,
            "created_at[lte]": until,
        }
        if status:
            params["status"] = status

        all_incidents = []
        next_cursor = None

        while len(all_incidents) < max_results:
            if next_cursor:
                params["after"] = next_cursor

            response = requests.get(
                "https://api.incident.io/v2/incidents",
                headers=headers,
                params=params,
            )
            response.raise_for_status()

            data = response.json()
            incidents = data.get("incidents", [])

            if not incidents:
                break

            for incident in incidents:
                created_at = datetime.fromisoformat(
                    incident["created_at"].replace("Z", "+00:00")
                )

                # Calculate MTTR if resolved
                mttr_minutes = None
                resolved_at = incident.get("resolved_at")
                if resolved_at:
                    resolved_dt = datetime.fromisoformat(
                        resolved_at.replace("Z", "+00:00")
                    )
                    mttr_minutes = (resolved_dt - created_at).total_seconds() / 60

                all_incidents.append(
                    {
                        "id": incident["id"],
                        "name": incident.get("name"),
                        "reference": incident.get("reference"),
                        "status": incident.get("status", {}).get("category"),
                        "severity": incident.get("severity", {}).get("name"),
                        "created_at": incident["created_at"],
                        "resolved_at": resolved_at,
                        "mttr_minutes": round(mttr_minutes, 2) if mttr_minutes else None,
                        "incident_lead": incident.get("incident_lead", {}).get("name"),
                        "url": incident.get("permalink"),
                    }
                )

            pagination = data.get("pagination_meta", {})
            if pagination.get("after"):
                next_cursor = pagination["after"]
            else:
                break

        # Compute summary statistics
        total = len(all_incidents)
        resolved_incidents = [i for i in all_incidents if i["mttr_minutes"]]
        mttr_values = [i["mttr_minutes"] for i in resolved_incidents]

        # Group by severity
        by_severity = {}
        for incident in all_incidents:
            sev = incident["severity"] or "Unknown"
            by_severity[sev] = by_severity.get(sev, 0) + 1

        # Group by incident lead
        by_lead = {}
        for incident in all_incidents:
            lead = incident["incident_lead"] or "Unassigned"
            by_lead[lead] = by_lead.get(lead, 0) + 1

        logger.info(
            "incidentio_incidents_by_date_range_fetched",
            count=total,
            since=since,
            until=until,
        )

        return {
            "success": True,
            "period": {"since": since, "until": until},
            "total_incidents": total,
            "summary": {
                "resolved_count": len(resolved_incidents),
                "avg_mttr_minutes": (
                    round(sum(mttr_values) / len(mttr_values), 2) if mttr_values else None
                ),
                "median_mttr_minutes": (
                    round(sorted(mttr_values)[len(mttr_values) // 2], 2)
                    if mttr_values
                    else None
                ),
            },
            "by_severity": by_severity,
            "by_incident_lead": dict(
                sorted(by_lead.items(), key=lambda x: x[1], reverse=True)[:10]
            ),
            "incidents": all_incidents,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "incidentio_list_incidents_by_date_range", "incidentio"
        )
    except Exception as e:
        logger.error(
            "incidentio_list_incidents_by_date_range_failed",
            error=str(e),
            since=since,
            until=until,
        )
        raise ToolExecutionError("incidentio_list_incidents_by_date_range", str(e), e)


def incidentio_list_severities() -> list[dict[str, Any]]:
    """
    List all configured severity levels.

    Returns:
        List of severity definitions with their IDs and names
    """
    try:
        import requests

        headers = _get_incidentio_headers()

        response = requests.get(
            "https://api.incident.io/v2/severities",
            headers=headers,
        )
        response.raise_for_status()

        severities = response.json().get("severities", [])

        result = []
        for sev in severities:
            result.append(
                {
                    "id": sev["id"],
                    "name": sev["name"],
                    "description": sev.get("description"),
                    "rank": sev.get("rank"),
                }
            )

        logger.info("incidentio_severities_listed", count=len(result))

        return result

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "incidentio_list_severities", "incidentio"
        )
    except Exception as e:
        logger.error("incidentio_list_severities_failed", error=str(e))
        raise ToolExecutionError("incidentio_list_severities", str(e), e)


def incidentio_list_incident_types() -> list[dict[str, Any]]:
    """
    List all configured incident types.

    Returns:
        List of incident type definitions
    """
    try:
        import requests

        headers = _get_incidentio_headers()

        response = requests.get(
            "https://api.incident.io/v2/incident_types",
            headers=headers,
        )
        response.raise_for_status()

        types = response.json().get("incident_types", [])

        result = []
        for t in types:
            result.append(
                {
                    "id": t["id"],
                    "name": t["name"],
                    "description": t.get("description"),
                    "is_default": t.get("is_default", False),
                }
            )

        logger.info("incidentio_incident_types_listed", count=len(result))

        return result

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "incidentio_list_incident_types", "incidentio"
        )
    except Exception as e:
        logger.error("incidentio_list_incident_types_failed", error=str(e))
        raise ToolExecutionError("incidentio_list_incident_types", str(e), e)


def incidentio_get_alert_analytics(
    since: str,
    until: str,
) -> dict[str, Any]:
    """
    Get alert analytics from Incident.io alerts.

    Analyzes alert patterns for fatigue reduction:
    - Fire frequency per alert route
    - Acknowledgment patterns
    - Time distribution

    Args:
        since: Start date in ISO format
        until: End date in ISO format

    Returns:
        Dict with alert analytics and recommendations
    """
    try:
        from collections import defaultdict
        from datetime import datetime

        import requests

        headers = _get_incidentio_headers()

        # Get alerts in date range
        params = {
            "page_size": 100,
            "created_at[gte]": since,
            "created_at[lte]": until,
        }

        all_alerts = []
        next_cursor = None

        while True:
            if next_cursor:
                params["after"] = next_cursor

            response = requests.get(
                "https://api.incident.io/v2/alerts",
                headers=headers,
                params=params,
            )
            response.raise_for_status()

            data = response.json()
            alerts = data.get("alerts", [])

            if not alerts:
                break

            all_alerts.extend(alerts)

            pagination = data.get("pagination_meta", {})
            if pagination.get("after"):
                next_cursor = pagination["after"]
            else:
                break

        # Analyze by alert route/source
        route_stats = defaultdict(
            lambda: {
                "fire_count": 0,
                "acknowledged_count": 0,
                "hours_distribution": defaultdict(int),
            }
        )

        for alert in all_alerts:
            route = alert.get("alert_route", {}).get("name", "Unknown")
            stats = route_stats[route]

            stats["fire_count"] += 1
            if alert.get("status") == "acknowledged":
                stats["acknowledged_count"] += 1

            created = datetime.fromisoformat(
                alert["created_at"].replace("Z", "+00:00")
            )
            stats["hours_distribution"][created.hour] += 1

        # Compute analytics per route
        route_analytics = []
        for route, stats in route_stats.items():
            fire_count = stats["fire_count"]
            ack_count = stats["acknowledged_count"]
            ack_rate = round(ack_count / fire_count * 100, 1) if fire_count > 0 else 0

            # Off-hours rate
            hours_dist = dict(stats["hours_distribution"])
            off_hours_count = sum(hours_dist.get(h, 0) for h in [0, 1, 2, 3, 4, 5, 22, 23])
            off_hours_rate = (
                round(off_hours_count / fire_count * 100, 1) if fire_count > 0 else 0
            )

            is_noisy = fire_count > 10 and ack_rate < 50

            route_analytics.append(
                {
                    "route": route,
                    "fire_count": fire_count,
                    "acknowledgment_rate": ack_rate,
                    "off_hours_rate": off_hours_rate,
                    "classification": {
                        "is_noisy": is_noisy,
                        "reason": "High frequency, low ack rate" if is_noisy else None,
                    },
                }
            )

        route_analytics.sort(key=lambda x: x["fire_count"], reverse=True)

        noisy_routes = sum(1 for r in route_analytics if r["classification"]["is_noisy"])

        logger.info(
            "incidentio_alert_analytics_computed",
            total_alerts=len(all_alerts),
            noisy_routes=noisy_routes,
        )

        return {
            "success": True,
            "period": {"since": since, "until": until},
            "summary": {
                "total_alerts": len(all_alerts),
                "unique_routes": len(route_analytics),
                "noisy_routes_count": noisy_routes,
            },
            "route_analytics": route_analytics[:30],
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "incidentio_get_alert_analytics", "incidentio"
        )
    except Exception as e:
        logger.error(
            "incidentio_get_alert_analytics_failed",
            error=str(e),
            since=since,
            until=until,
        )
        raise ToolExecutionError("incidentio_get_alert_analytics", str(e), e)


def incidentio_calculate_mttr(
    severity_id: str | None = None, days: int = 30
) -> dict[str, Any]:
    """
    Calculate Mean Time To Resolve (MTTR) for Incident.io incidents.

    Args:
        severity_id: Optional severity ID to filter
        days: Number of days to analyze (default 30)

    Returns:
        MTTR statistics including average, median, and percentiles
    """
    try:
        from datetime import datetime, timedelta, timezone

        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        until = datetime.now(timezone.utc).isoformat()

        # Use the date range function
        incidents_data = incidentio_list_incidents_by_date_range(
            since=since,
            until=until,
            status="closed",
            max_results=500,
        )

        if not incidents_data.get("success"):
            return incidents_data

        incidents = incidents_data.get("incidents", [])

        # Filter by severity if specified
        if severity_id:
            # We need to get severity name mapping first
            severities = incidentio_list_severities()
            sev_map = {s["id"]: s["name"] for s in severities}
            target_sev = sev_map.get(severity_id)
            if target_sev:
                incidents = [i for i in incidents if i["severity"] == target_sev]

        # Extract resolution times
        mttr_values = [i["mttr_minutes"] for i in incidents if i["mttr_minutes"]]

        if not mttr_values:
            return {
                "severity_id": severity_id,
                "period_days": days,
                "incident_count": 0,
                "mttr_minutes": 0,
                "message": "No resolved incidents in this period",
            }

        mttr_values.sort()
        count = len(mttr_values)
        avg_mttr = sum(mttr_values) / count
        median_mttr = mttr_values[count // 2]
        p95_mttr = mttr_values[int(count * 0.95)] if count > 0 else 0

        logger.info("incidentio_mttr_calculated", incidents=count, mttr=avg_mttr)

        return {
            "severity_id": severity_id,
            "period_days": days,
            "incident_count": count,
            "mttr_minutes": round(avg_mttr, 2),
            "mttr_hours": round(avg_mttr / 60, 2),
            "median_minutes": round(median_mttr, 2),
            "p95_minutes": round(p95_mttr, 2),
            "fastest_resolution_minutes": round(min(mttr_values), 2),
            "slowest_resolution_minutes": round(max(mttr_values), 2),
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "incidentio_calculate_mttr", "incidentio"
        )
    except Exception as e:
        logger.error(
            "incidentio_mttr_failed", error=str(e), severity_id=severity_id
        )
        raise ToolExecutionError("incidentio_calculate_mttr", str(e), e)


# List of all Incident.io tools for registration
INCIDENTIO_TOOLS = [
    incidentio_list_incidents,
    incidentio_get_incident,
    incidentio_get_incident_updates,
    incidentio_list_incidents_by_date_range,
    incidentio_list_severities,
    incidentio_list_incident_types,
    incidentio_get_alert_analytics,
    incidentio_calculate_mttr,
]

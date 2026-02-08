"""Blameless integration tools for incident management and retrospectives."""

import os
from typing import Any

from ..core.config_required import handle_integration_not_configured
from ..core.errors import ToolExecutionError
from ..core.execution_context import get_execution_context
from ..core.integration_errors import IntegrationNotConfiguredError
from ..core.logging import get_logger

logger = get_logger(__name__)


def _get_blameless_config() -> dict:
    """Get Blameless configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("blameless")
        if config and config.get("api_key"):
            return config

    # 2. Try environment variables (dev/testing fallback)
    if os.getenv("BLAMELESS_API_KEY"):
        return {
            "api_key": os.getenv("BLAMELESS_API_KEY"),
            "instance_url": os.getenv(
                "BLAMELESS_INSTANCE_URL", "https://api.blameless.io"
            ),
        }

    # 3. Not configured - raise error
    raise IntegrationNotConfiguredError(
        integration_id="blameless",
        tool_id="blameless_tools",
        missing_fields=["api_key"],
    )


def _get_blameless_headers() -> dict:
    """Get headers for Blameless API requests."""
    config = _get_blameless_config()
    return {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }


def _get_blameless_base_url() -> str:
    """Get Blameless API base URL."""
    config = _get_blameless_config()
    return config.get("instance_url", "https://api.blameless.io").rstrip("/")


def blameless_list_incidents(
    status: str | None = None,
    severity: str | None = None,
    incident_type: str | None = None,
    max_results: int = 100,
) -> dict[str, Any]:
    """
    List Blameless incidents with optional filters.

    Args:
        status: Filter by status (investigating, identified, monitoring, resolved)
        severity: Filter by severity (SEV0, SEV1, SEV2, SEV3, SEV4)
        incident_type: Filter by incident type
        max_results: Maximum incidents to return

    Returns:
        Dict with incidents list and summary
    """
    try:
        import requests

        headers = _get_blameless_headers()
        base_url = _get_blameless_base_url()

        params: dict[str, Any] = {"limit": min(max_results, 100)}
        if status:
            params["status"] = status
        if severity:
            params["severity"] = severity
        if incident_type:
            params["type"] = incident_type

        all_incidents = []
        page = 1

        while len(all_incidents) < max_results:
            params["page"] = page

            response = requests.get(
                f"{base_url}/api/v1/incidents",
                headers=headers,
                params=params,
            )
            response.raise_for_status()

            data = response.json()
            incidents = data.get("incidents", data.get("data", []))

            if not incidents:
                break

            for incident in incidents:
                all_incidents.append(
                    {
                        "id": incident.get("id"),
                        "title": incident.get("title") or incident.get("name"),
                        "description": incident.get("description"),
                        "status": incident.get("status"),
                        "severity": incident.get("severity"),
                        "incident_type": incident.get("type")
                        or incident.get("incident_type"),
                        "created_at": incident.get("created_at"),
                        "updated_at": incident.get("updated_at"),
                        "resolved_at": incident.get("resolved_at"),
                        "commander": (
                            incident.get("commander", {}).get("name")
                            if isinstance(incident.get("commander"), dict)
                            else incident.get("commander")
                        ),
                        "url": incident.get("url") or incident.get("permalink"),
                    }
                )

            page += 1
            if len(incidents) < params["limit"]:
                break

        # Compute summary
        by_status: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        for inc in all_incidents:
            s = inc["status"] or "unknown"
            by_status[s] = by_status.get(s, 0) + 1
            sev = inc["severity"] or "unknown"
            by_severity[sev] = by_severity.get(sev, 0) + 1

        logger.info("blameless_incidents_listed", count=len(all_incidents))

        return {
            "success": True,
            "total_count": len(all_incidents),
            "summary": {
                "by_status": by_status,
                "by_severity": by_severity,
            },
            "incidents": all_incidents,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "blameless_list_incidents", "blameless"
        )
    except Exception as e:
        logger.error("blameless_list_incidents_failed", error=str(e))
        raise ToolExecutionError("blameless_list_incidents", str(e), e)


def blameless_get_incident(incident_id: str) -> dict[str, Any]:
    """
    Get details of a specific Blameless incident.

    Args:
        incident_id: Blameless incident ID

    Returns:
        Incident details including status, severity, roles, and timeline
    """
    try:
        import requests

        headers = _get_blameless_headers()
        base_url = _get_blameless_base_url()

        response = requests.get(
            f"{base_url}/api/v1/incidents/{incident_id}",
            headers=headers,
        )
        response.raise_for_status()

        data = response.json()
        incident = data.get("incident", data)

        # Parse roles
        roles = []
        for role in incident.get("roles", []):
            roles.append(
                {
                    "role": role.get("role") or role.get("name"),
                    "assignee": (
                        role.get("user", {}).get("name")
                        if isinstance(role.get("user"), dict)
                        else role.get("assignee")
                    ),
                }
            )

        logger.info("blameless_incident_fetched", incident_id=incident_id)

        return {
            "id": incident.get("id"),
            "title": incident.get("title") or incident.get("name"),
            "description": incident.get("description"),
            "status": incident.get("status"),
            "severity": incident.get("severity"),
            "incident_type": incident.get("type") or incident.get("incident_type"),
            "created_at": incident.get("created_at"),
            "updated_at": incident.get("updated_at"),
            "resolved_at": incident.get("resolved_at"),
            "commander": (
                incident.get("commander", {}).get("name")
                if isinstance(incident.get("commander"), dict)
                else incident.get("commander")
            ),
            "communication_lead": (
                incident.get("communication_lead", {}).get("name")
                if isinstance(incident.get("communication_lead"), dict)
                else incident.get("communication_lead")
            ),
            "roles": roles,
            "slack_channel": incident.get("slack_channel")
            or incident.get("slack_channel_name"),
            "postmortem_url": incident.get("postmortem_url")
            or incident.get("retrospective_url"),
            "custom_fields": incident.get("custom_fields", []),
            "url": incident.get("url") or incident.get("permalink"),
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "blameless_get_incident", "blameless"
        )
    except Exception as e:
        logger.error(
            "blameless_get_incident_failed", error=str(e), incident_id=incident_id
        )
        raise ToolExecutionError("blameless_get_incident", str(e), e)


def blameless_get_incident_timeline(
    incident_id: str, max_results: int = 50
) -> list[dict[str, Any]]:
    """
    Get timeline entries for a Blameless incident.

    Args:
        incident_id: Blameless incident ID
        max_results: Maximum timeline entries to return

    Returns:
        List of timeline entries showing incident progression
    """
    try:
        import requests

        headers = _get_blameless_headers()
        base_url = _get_blameless_base_url()

        response = requests.get(
            f"{base_url}/api/v1/incidents/{incident_id}/events",
            headers=headers,
            params={"limit": max_results},
        )
        response.raise_for_status()

        data = response.json()
        events = data.get("events", data.get("data", []))

        result = []
        for event in events:
            result.append(
                {
                    "id": event.get("id"),
                    "type": event.get("type") or event.get("event_type"),
                    "description": event.get("description")
                    or event.get("message")
                    or event.get("summary"),
                    "created_at": event.get("created_at") or event.get("timestamp"),
                    "user": (
                        event.get("user", {}).get("name")
                        if isinstance(event.get("user"), dict)
                        else event.get("user")
                    ),
                }
            )

        logger.info(
            "blameless_timeline_fetched", incident_id=incident_id, count=len(result)
        )

        return result

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "blameless_get_incident_timeline", "blameless"
        )
    except Exception as e:
        logger.error(
            "blameless_get_timeline_failed", error=str(e), incident_id=incident_id
        )
        raise ToolExecutionError("blameless_get_incident_timeline", str(e), e)


def blameless_list_incidents_by_date_range(
    since: str,
    until: str,
    severity: str | None = None,
    max_results: int = 500,
) -> dict[str, Any]:
    """
    List Blameless incidents within a date range.

    Essential for alert fatigue analysis - retrieves historical incident data
    for computing metrics like frequency, MTTA, MTTR.

    Args:
        since: Start date in ISO format (e.g., "2024-01-01T00:00:00Z")
        until: End date in ISO format (e.g., "2024-01-31T23:59:59Z")
        severity: Optional severity filter (SEV0-SEV4)
        max_results: Maximum incidents to return

    Returns:
        Dict with incidents and computed metrics
    """
    try:
        from datetime import datetime

        import requests

        headers = _get_blameless_headers()
        base_url = _get_blameless_base_url()

        params: dict[str, Any] = {
            "limit": 100,
            "created_after": since,
            "created_before": until,
        }
        if severity:
            params["severity"] = severity

        all_incidents = []
        page = 1

        while len(all_incidents) < max_results:
            params["page"] = page

            response = requests.get(
                f"{base_url}/api/v1/incidents",
                headers=headers,
                params=params,
            )
            response.raise_for_status()

            data = response.json()
            incidents = data.get("incidents", data.get("data", []))

            if not incidents:
                break

            for incident in incidents:
                created_at_str = incident.get("created_at", "")
                resolved_at_str = incident.get("resolved_at")

                # Calculate MTTR if resolved
                mttr_minutes = None
                if created_at_str and resolved_at_str:
                    try:
                        created_dt = datetime.fromisoformat(
                            created_at_str.replace("Z", "+00:00")
                        )
                        resolved_dt = datetime.fromisoformat(
                            resolved_at_str.replace("Z", "+00:00")
                        )
                        mttr_minutes = (resolved_dt - created_dt).total_seconds() / 60
                    except (ValueError, TypeError):
                        pass

                all_incidents.append(
                    {
                        "id": incident.get("id"),
                        "title": incident.get("title") or incident.get("name"),
                        "status": incident.get("status"),
                        "severity": incident.get("severity"),
                        "created_at": created_at_str,
                        "resolved_at": resolved_at_str,
                        "mttr_minutes": (
                            round(mttr_minutes, 2) if mttr_minutes else None
                        ),
                        "commander": (
                            incident.get("commander", {}).get("name")
                            if isinstance(incident.get("commander"), dict)
                            else incident.get("commander")
                        ),
                        "url": incident.get("url") or incident.get("permalink"),
                    }
                )

            page += 1
            if len(incidents) < params["limit"]:
                break

        # Compute summary statistics
        total = len(all_incidents)
        resolved_incidents = [i for i in all_incidents if i["mttr_minutes"]]
        mttr_values = [i["mttr_minutes"] for i in resolved_incidents]

        # Group by severity
        by_severity: dict[str, int] = {}
        for incident in all_incidents:
            sev = incident["severity"] or "Unknown"
            by_severity[sev] = by_severity.get(sev, 0) + 1

        # Group by commander
        by_commander: dict[str, int] = {}
        for incident in all_incidents:
            commander = incident["commander"] or "Unassigned"
            by_commander[commander] = by_commander.get(commander, 0) + 1

        logger.info(
            "blameless_incidents_by_date_range_fetched",
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
                    round(sum(mttr_values) / len(mttr_values), 2)
                    if mttr_values
                    else None
                ),
                "median_mttr_minutes": (
                    round(sorted(mttr_values)[len(mttr_values) // 2], 2)
                    if mttr_values
                    else None
                ),
            },
            "by_severity": by_severity,
            "by_commander": dict(
                sorted(by_commander.items(), key=lambda x: x[1], reverse=True)[:10]
            ),
            "incidents": all_incidents,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "blameless_list_incidents_by_date_range", "blameless"
        )
    except Exception as e:
        logger.error(
            "blameless_list_incidents_by_date_range_failed",
            error=str(e),
            since=since,
            until=until,
        )
        raise ToolExecutionError("blameless_list_incidents_by_date_range", str(e), e)


def blameless_list_severities() -> list[dict[str, Any]]:
    """
    List all configured severity levels in Blameless.

    Returns:
        List of severity definitions with their IDs and names
    """
    try:
        import requests

        headers = _get_blameless_headers()
        base_url = _get_blameless_base_url()

        response = requests.get(
            f"{base_url}/api/v1/severities",
            headers=headers,
        )
        response.raise_for_status()

        data = response.json()
        severities = data.get("severities", data.get("data", []))

        result = []
        for sev in severities:
            result.append(
                {
                    "id": sev.get("id"),
                    "name": sev.get("name"),
                    "description": sev.get("description"),
                    "rank": sev.get("rank") or sev.get("order"),
                }
            )

        logger.info("blameless_severities_listed", count=len(result))

        return result

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "blameless_list_severities", "blameless"
        )
    except Exception as e:
        logger.error("blameless_list_severities_failed", error=str(e))
        raise ToolExecutionError("blameless_list_severities", str(e), e)


def blameless_get_retrospective(incident_id: str) -> dict[str, Any]:
    """
    Get the retrospective (post-incident review) for a Blameless incident.

    Blameless is known for structured retrospectives with contributing factors,
    action items, and lessons learned.

    Args:
        incident_id: Blameless incident ID

    Returns:
        Retrospective details including contributing factors, action items, and timeline
    """
    try:
        import requests

        headers = _get_blameless_headers()
        base_url = _get_blameless_base_url()

        response = requests.get(
            f"{base_url}/api/v1/incidents/{incident_id}/retrospective",
            headers=headers,
        )
        response.raise_for_status()

        data = response.json()
        retro = data.get("retrospective", data)

        # Parse contributing factors
        contributing_factors = []
        for factor in retro.get("contributing_factors", []):
            contributing_factors.append(
                {
                    "id": factor.get("id"),
                    "description": factor.get("description"),
                    "category": factor.get("category"),
                }
            )

        # Parse action items
        action_items = []
        for item in retro.get("action_items", []):
            action_items.append(
                {
                    "id": item.get("id"),
                    "title": item.get("title") or item.get("description"),
                    "status": item.get("status"),
                    "assignee": (
                        item.get("assignee", {}).get("name")
                        if isinstance(item.get("assignee"), dict)
                        else item.get("assignee")
                    ),
                    "due_date": item.get("due_date"),
                    "priority": item.get("priority"),
                }
            )

        logger.info("blameless_retrospective_fetched", incident_id=incident_id)

        return {
            "incident_id": incident_id,
            "summary": retro.get("summary") or retro.get("description"),
            "impact": retro.get("impact"),
            "root_cause": retro.get("root_cause"),
            "contributing_factors": contributing_factors,
            "action_items": action_items,
            "lessons_learned": retro.get("lessons_learned", []),
            "timeline": retro.get("timeline", []),
            "status": retro.get("status"),
            "url": retro.get("url") or retro.get("permalink"),
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "blameless_get_retrospective", "blameless"
        )
    except Exception as e:
        logger.error(
            "blameless_get_retrospective_failed",
            error=str(e),
            incident_id=incident_id,
        )
        raise ToolExecutionError("blameless_get_retrospective", str(e), e)


def blameless_get_alert_analytics(
    since: str,
    until: str,
    severity: str | None = None,
) -> dict[str, Any]:
    """
    Get alert analytics from Blameless incidents.

    Analyzes incident patterns for fatigue reduction:
    - Fire frequency per incident title
    - Resolution patterns
    - Time-of-day distribution
    - Noisy incident detection

    Args:
        since: Start date in ISO format
        until: End date in ISO format
        severity: Optional severity filter

    Returns:
        Dict with alert analytics and recommendations
    """
    try:
        from collections import defaultdict
        from datetime import datetime

        # Get all incidents in the range
        incidents_data = blameless_list_incidents_by_date_range(
            since=since,
            until=until,
            severity=severity,
            max_results=1000,
        )

        if not incidents_data.get("success"):
            return incidents_data

        incidents = incidents_data.get("incidents", [])

        # Analyze per incident title
        title_stats: dict[str, dict] = defaultdict(
            lambda: {
                "fire_count": 0,
                "resolved_count": 0,
                "mttr_values": [],
                "hours_distribution": defaultdict(int),
                "severities": defaultdict(int),
            }
        )

        for incident in incidents:
            title = (incident.get("title") or "Unknown")[:100]
            stats = title_stats[title]

            stats["fire_count"] += 1
            stats["severities"][incident.get("severity") or "Unknown"] += 1

            if incident.get("status") in ("resolved", "closed"):
                stats["resolved_count"] += 1

            if incident.get("mttr_minutes"):
                stats["mttr_values"].append(incident["mttr_minutes"])

            # Time distribution
            created_at = incident.get("created_at", "")
            if created_at:
                try:
                    created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    stats["hours_distribution"][created.hour] += 1
                except (ValueError, TypeError):
                    pass

        # Compute analytics per title
        alert_analytics = []
        for title, stats in title_stats.items():
            fire_count = stats["fire_count"]
            mttr_vals = stats["mttr_values"]
            avg_mttr = round(sum(mttr_vals) / len(mttr_vals), 2) if mttr_vals else None

            # Determine if noisy
            resolve_rate = (
                round(stats["resolved_count"] / fire_count * 100, 1)
                if fire_count > 0
                else 0
            )
            is_noisy = fire_count > 10
            is_flapping = fire_count > 20 and avg_mttr and avg_mttr < 10

            # Off-hours rate
            hours_dist = dict(stats["hours_distribution"])
            off_hours_count = sum(
                hours_dist.get(h, 0) for h in [0, 1, 2, 3, 4, 5, 22, 23]
            )
            off_hours_rate = (
                round(off_hours_count / fire_count * 100, 1) if fire_count > 0 else 0
            )

            peak_hour = max(hours_dist, key=hours_dist.get) if hours_dist else None

            alert_analytics.append(
                {
                    "incident_title": title,
                    "fire_count": fire_count,
                    "resolved_count": stats["resolved_count"],
                    "resolve_rate": resolve_rate,
                    "avg_mttr_minutes": avg_mttr,
                    "severity_distribution": dict(stats["severities"]),
                    "peak_hour": peak_hour,
                    "off_hours_rate": off_hours_rate,
                    "classification": {
                        "is_noisy": is_noisy,
                        "is_flapping": is_flapping,
                        "reason": (
                            "High frequency incident"
                            if is_noisy
                            else ("Quick auto-resolve pattern" if is_flapping else None)
                        ),
                    },
                }
            )

        # Sort by fire count
        alert_analytics.sort(key=lambda x: x["fire_count"], reverse=True)

        # Overall summary
        total_unique = len(alert_analytics)
        noisy_count = sum(1 for a in alert_analytics if a["classification"]["is_noisy"])
        flapping_count = sum(
            1 for a in alert_analytics if a["classification"]["is_flapping"]
        )

        logger.info(
            "blameless_alert_analytics_computed",
            total_alerts=total_unique,
            noisy_alerts=noisy_count,
        )

        return {
            "success": True,
            "period": {"since": since, "until": until},
            "severity": severity,
            "summary": {
                "total_unique_incidents": total_unique,
                "total_incident_count": len(incidents),
                "noisy_incidents_count": noisy_count,
                "flapping_incidents_count": flapping_count,
                "potential_noise_reduction": sum(
                    a["fire_count"]
                    for a in alert_analytics
                    if a["classification"]["is_noisy"]
                    or a["classification"]["is_flapping"]
                ),
            },
            "alert_analytics": alert_analytics[:50],
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "blameless_get_alert_analytics", "blameless"
        )
    except Exception as e:
        logger.error(
            "blameless_get_alert_analytics_failed",
            error=str(e),
            since=since,
            until=until,
        )
        raise ToolExecutionError("blameless_get_alert_analytics", str(e), e)


def blameless_calculate_mttr(
    severity: str | None = None, days: int = 30
) -> dict[str, Any]:
    """
    Calculate Mean Time To Resolve (MTTR) for Blameless incidents.

    Args:
        severity: Optional severity filter (SEV0-SEV4)
        days: Number of days to analyze (default 30)

    Returns:
        MTTR statistics including average, median, and percentiles
    """
    try:
        from datetime import datetime, timedelta, timezone

        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        until = datetime.now(timezone.utc).isoformat()

        # Use the date range function
        incidents_data = blameless_list_incidents_by_date_range(
            since=since,
            until=until,
            severity=severity,
            max_results=500,
        )

        if not incidents_data.get("success"):
            return incidents_data

        incidents = incidents_data.get("incidents", [])

        # Extract resolution times
        mttr_values = [i["mttr_minutes"] for i in incidents if i["mttr_minutes"]]

        if not mttr_values:
            return {
                "severity": severity,
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

        logger.info("blameless_mttr_calculated", incidents=count, mttr=avg_mttr)

        return {
            "severity": severity,
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
            e, "blameless_calculate_mttr", "blameless"
        )
    except Exception as e:
        logger.error("blameless_mttr_failed", error=str(e), severity=severity)
        raise ToolExecutionError("blameless_calculate_mttr", str(e), e)


# List of all Blameless tools for registration
BLAMELESS_TOOLS = [
    blameless_list_incidents,
    blameless_get_incident,
    blameless_get_incident_timeline,
    blameless_list_incidents_by_date_range,
    blameless_list_severities,
    blameless_get_retrospective,
    blameless_get_alert_analytics,
    blameless_calculate_mttr,
]

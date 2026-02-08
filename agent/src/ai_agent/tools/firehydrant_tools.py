"""FireHydrant integration tools for incident management."""

import os
from typing import Any

from ..core.config_required import handle_integration_not_configured
from ..core.errors import ToolExecutionError
from ..core.execution_context import get_execution_context
from ..core.integration_errors import IntegrationNotConfiguredError
from ..core.logging import get_logger

logger = get_logger(__name__)


def _get_firehydrant_config() -> dict:
    """Get FireHydrant configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("firehydrant")
        if config and config.get("api_key"):
            return config

    # 2. Try environment variables (dev/testing fallback)
    if os.getenv("FIREHYDRANT_API_KEY"):
        return {"api_key": os.getenv("FIREHYDRANT_API_KEY")}

    # 3. Not configured - raise error
    raise IntegrationNotConfiguredError(
        integration_id="firehydrant",
        tool_id="firehydrant_tools",
        missing_fields=["api_key"],
    )


def _get_firehydrant_headers() -> dict:
    """Get headers for FireHydrant API requests."""
    config = _get_firehydrant_config()
    return {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }


def firehydrant_list_incidents(
    status: str | None = None,
    severity: str | None = None,
    environment_id: str | None = None,
    max_results: int = 100,
) -> dict[str, Any]:
    """
    List FireHydrant incidents with optional filters.

    Args:
        status: Filter by status (open, in_progress, resolved, closed)
        severity: Filter by severity
        environment_id: Filter by environment ID
        max_results: Maximum incidents to return

    Returns:
        Dict with incidents list and summary
    """
    try:
        import requests

        headers = _get_firehydrant_headers()

        params: dict[str, Any] = {"per_page": min(max_results, 100)}
        if status:
            params["status"] = status
        if severity:
            params["severity"] = severity
        if environment_id:
            params["environment_id"] = environment_id

        all_incidents = []
        page = 1

        while len(all_incidents) < max_results:
            params["page"] = page

            response = requests.get(
                "https://api.firehydrant.io/v1/incidents",
                headers=headers,
                params=params,
            )
            response.raise_for_status()

            data = response.json()
            incidents = data.get("data", [])

            if not incidents:
                break

            for incident in incidents:
                # Extract milestone timestamps
                milestones = {}
                for ms in incident.get("milestones", []):
                    ms_type = ms.get("type") or ms.get("slug")
                    if ms_type:
                        milestones[ms_type] = ms.get("occurred_at") or ms.get(
                            "created_at"
                        )

                all_incidents.append(
                    {
                        "id": incident.get("id"),
                        "name": incident.get("name"),
                        "description": incident.get("description"),
                        "status": incident.get("current_milestone"),
                        "severity": incident.get("severity"),
                        "priority": incident.get("priority"),
                        "created_at": incident.get("created_at"),
                        "started_at": incident.get("started_at"),
                        "resolved_at": milestones.get("resolved"),
                        "environments": [
                            env.get("name") for env in incident.get("environments", [])
                        ],
                        "services": [
                            svc.get("name") for svc in incident.get("services", [])
                        ],
                        "functionalities": [
                            f.get("name") for f in incident.get("functionalities", [])
                        ],
                        "incident_url": incident.get("incident_url"),
                    }
                )

            page += 1
            if len(incidents) < params["per_page"]:
                break

        # Compute summary
        by_status: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        for inc in all_incidents:
            s = inc["status"] or "unknown"
            by_status[s] = by_status.get(s, 0) + 1
            sev = inc["severity"] or "unknown"
            by_severity[sev] = by_severity.get(sev, 0) + 1

        logger.info("firehydrant_incidents_listed", count=len(all_incidents))

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
            e, "firehydrant_list_incidents", "firehydrant"
        )
    except Exception as e:
        logger.error("firehydrant_list_incidents_failed", error=str(e))
        raise ToolExecutionError("firehydrant_list_incidents", str(e), e)


def firehydrant_get_incident(incident_id: str) -> dict[str, Any]:
    """
    Get details of a specific FireHydrant incident.

    Args:
        incident_id: FireHydrant incident ID

    Returns:
        Incident details including milestones, services, environments, and roles
    """
    try:
        import requests

        headers = _get_firehydrant_headers()

        response = requests.get(
            f"https://api.firehydrant.io/v1/incidents/{incident_id}",
            headers=headers,
        )
        response.raise_for_status()

        incident = response.json()

        # Parse milestones
        milestones = []
        for ms in incident.get("milestones", []):
            milestones.append(
                {
                    "type": ms.get("type") or ms.get("slug"),
                    "occurred_at": ms.get("occurred_at") or ms.get("created_at"),
                    "duration_ms": ms.get("duration"),
                }
            )

        # Parse role assignments
        role_assignments = []
        for assignment in incident.get("role_assignments", []):
            role_assignments.append(
                {
                    "role": assignment.get("incident_role", {}).get("name"),
                    "user": assignment.get("user", {}).get("name"),
                    "email": assignment.get("user", {}).get("email"),
                }
            )

        logger.info("firehydrant_incident_fetched", incident_id=incident_id)

        return {
            "id": incident.get("id"),
            "name": incident.get("name"),
            "description": incident.get("description"),
            "status": incident.get("current_milestone"),
            "severity": incident.get("severity"),
            "priority": incident.get("priority"),
            "created_at": incident.get("created_at"),
            "started_at": incident.get("started_at"),
            "customer_impact_summary": incident.get("customer_impact_summary"),
            "milestones": milestones,
            "role_assignments": role_assignments,
            "services": [
                {"id": svc.get("id"), "name": svc.get("name")}
                for svc in incident.get("services", [])
            ],
            "environments": [
                {"id": env.get("id"), "name": env.get("name")}
                for env in incident.get("environments", [])
            ],
            "functionalities": [
                {"id": f.get("id"), "name": f.get("name")}
                for f in incident.get("functionalities", [])
            ],
            "slack_channel_name": incident.get("slack_channel_name"),
            "incident_url": incident.get("incident_url"),
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "firehydrant_get_incident", "firehydrant"
        )
    except Exception as e:
        logger.error(
            "firehydrant_get_incident_failed", error=str(e), incident_id=incident_id
        )
        raise ToolExecutionError("firehydrant_get_incident", str(e), e)


def firehydrant_get_incident_timeline(
    incident_id: str, max_results: int = 50
) -> list[dict[str, Any]]:
    """
    Get timeline events for a FireHydrant incident.

    Args:
        incident_id: FireHydrant incident ID
        max_results: Maximum timeline entries to return

    Returns:
        List of timeline events showing incident progression
    """
    try:
        import requests

        headers = _get_firehydrant_headers()

        response = requests.get(
            f"https://api.firehydrant.io/v1/incidents/{incident_id}/events",
            headers=headers,
            params={"per_page": max_results},
        )
        response.raise_for_status()

        data = response.json()
        events = data.get("data", [])

        result = []
        for event in events:
            result.append(
                {
                    "id": event.get("id"),
                    "type": event.get("type"),
                    "occurred_at": event.get("occurred_at") or event.get("created_at"),
                    "description": event.get("description")
                    or event.get("body")
                    or event.get("summary"),
                    "author": (
                        event.get("author", {}).get("name")
                        if isinstance(event.get("author"), dict)
                        else event.get("author")
                    ),
                    "visibility": event.get("visibility"),
                }
            )

        logger.info(
            "firehydrant_timeline_fetched",
            incident_id=incident_id,
            count=len(result),
        )

        return result

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "firehydrant_get_incident_timeline", "firehydrant"
        )
    except Exception as e:
        logger.error(
            "firehydrant_get_timeline_failed", error=str(e), incident_id=incident_id
        )
        raise ToolExecutionError("firehydrant_get_incident_timeline", str(e), e)


def firehydrant_list_incidents_by_date_range(
    since: str,
    until: str,
    severity: str | None = None,
    max_results: int = 500,
) -> dict[str, Any]:
    """
    List FireHydrant incidents within a date range.

    Essential for alert fatigue analysis - retrieves historical incident data
    for computing metrics like frequency, MTTA, MTTR.

    Args:
        since: Start date in ISO format (e.g., "2024-01-01T00:00:00Z")
        until: End date in ISO format (e.g., "2024-01-31T23:59:59Z")
        severity: Optional severity filter
        max_results: Maximum incidents to return

    Returns:
        Dict with incidents and computed metrics
    """
    try:
        from datetime import datetime

        import requests

        headers = _get_firehydrant_headers()

        params: dict[str, Any] = {
            "per_page": 100,
            "start_date": since,
            "end_date": until,
        }
        if severity:
            params["severity"] = severity

        all_incidents = []
        page = 1

        while len(all_incidents) < max_results:
            params["page"] = page

            response = requests.get(
                "https://api.firehydrant.io/v1/incidents",
                headers=headers,
                params=params,
            )
            response.raise_for_status()

            data = response.json()
            incidents = data.get("data", [])

            if not incidents:
                break

            for incident in incidents:
                created_at_str = incident.get("created_at", "")
                started_at_str = incident.get("started_at")

                # Extract resolved milestone
                resolved_at_str = None
                for ms in incident.get("milestones", []):
                    if (ms.get("type") or ms.get("slug")) == "resolved":
                        resolved_at_str = ms.get("occurred_at") or ms.get("created_at")

                # Calculate MTTR if resolved
                mttr_minutes = None
                start_time = started_at_str or created_at_str
                if start_time and resolved_at_str:
                    try:
                        started_dt = datetime.fromisoformat(
                            start_time.replace("Z", "+00:00")
                        )
                        resolved_dt = datetime.fromisoformat(
                            resolved_at_str.replace("Z", "+00:00")
                        )
                        mttr_minutes = (resolved_dt - started_dt).total_seconds() / 60
                    except (ValueError, TypeError):
                        pass

                all_incidents.append(
                    {
                        "id": incident.get("id"),
                        "name": incident.get("name"),
                        "status": incident.get("current_milestone"),
                        "severity": incident.get("severity"),
                        "created_at": created_at_str,
                        "started_at": started_at_str,
                        "resolved_at": resolved_at_str,
                        "mttr_minutes": (
                            round(mttr_minutes, 2) if mttr_minutes else None
                        ),
                        "services": [
                            svc.get("name") for svc in incident.get("services", [])
                        ],
                        "environments": [
                            env.get("name") for env in incident.get("environments", [])
                        ],
                        "incident_url": incident.get("incident_url"),
                    }
                )

            page += 1
            if len(incidents) < params["per_page"]:
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

        # Group by service
        by_service: dict[str, int] = {}
        for incident in all_incidents:
            for svc in incident.get("services", []):
                if svc:
                    by_service[svc] = by_service.get(svc, 0) + 1

        logger.info(
            "firehydrant_incidents_by_date_range_fetched",
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
            "by_service": dict(
                sorted(by_service.items(), key=lambda x: x[1], reverse=True)[:10]
            ),
            "incidents": all_incidents,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "firehydrant_list_incidents_by_date_range", "firehydrant"
        )
    except Exception as e:
        logger.error(
            "firehydrant_list_incidents_by_date_range_failed",
            error=str(e),
            since=since,
            until=until,
        )
        raise ToolExecutionError("firehydrant_list_incidents_by_date_range", str(e), e)


def firehydrant_list_services() -> list[dict[str, Any]]:
    """
    List all FireHydrant services.

    Returns all services configured in FireHydrant, useful for understanding
    the service landscape and filtering incident queries.

    Returns:
        List of services with their IDs, names, and owners
    """
    try:
        import requests

        headers = _get_firehydrant_headers()

        all_services = []
        page = 1

        while True:
            response = requests.get(
                "https://api.firehydrant.io/v1/services",
                headers=headers,
                params={"per_page": 100, "page": page},
            )
            response.raise_for_status()

            data = response.json()
            services = data.get("data", [])

            if not services:
                break

            for svc in services:
                all_services.append(
                    {
                        "id": svc.get("id"),
                        "name": svc.get("name"),
                        "description": svc.get("description"),
                        "slug": svc.get("slug"),
                        "tier": svc.get("service_tier"),
                        "owner": (
                            svc.get("owner", {}).get("name")
                            if isinstance(svc.get("owner"), dict)
                            else None
                        ),
                        "labels": svc.get("labels", {}),
                        "active_incidents_count": (
                            svc.get("active_incidents", []).__len__()
                            if isinstance(svc.get("active_incidents"), list)
                            else 0
                        ),
                    }
                )

            page += 1
            if len(services) < 100:
                break

        logger.info("firehydrant_services_listed", count=len(all_services))

        return all_services

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "firehydrant_list_services", "firehydrant"
        )
    except Exception as e:
        logger.error("firehydrant_list_services_failed", error=str(e))
        raise ToolExecutionError("firehydrant_list_services", str(e), e)


def firehydrant_list_environments() -> list[dict[str, Any]]:
    """
    List all FireHydrant environments.

    Returns:
        List of environments with their IDs and names
    """
    try:
        import requests

        headers = _get_firehydrant_headers()

        response = requests.get(
            "https://api.firehydrant.io/v1/environments",
            headers=headers,
            params={"per_page": 100},
        )
        response.raise_for_status()

        data = response.json()
        environments = data.get("data", [])

        result = []
        for env in environments:
            result.append(
                {
                    "id": env.get("id"),
                    "name": env.get("name"),
                    "description": env.get("description"),
                    "slug": env.get("slug"),
                    "active_incidents_count": len(env.get("active_incidents", [])),
                }
            )

        logger.info("firehydrant_environments_listed", count=len(result))

        return result

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "firehydrant_list_environments", "firehydrant"
        )
    except Exception as e:
        logger.error("firehydrant_list_environments_failed", error=str(e))
        raise ToolExecutionError("firehydrant_list_environments", str(e), e)


def firehydrant_get_alert_analytics(
    since: str,
    until: str,
    service_id: str | None = None,
) -> dict[str, Any]:
    """
    Get alert analytics from FireHydrant incidents.

    Analyzes incident patterns for fatigue reduction:
    - Fire frequency per incident name
    - Resolution patterns
    - Time-of-day distribution
    - Service impact analysis

    Args:
        since: Start date in ISO format
        until: End date in ISO format
        service_id: Optional service ID to filter

    Returns:
        Dict with alert analytics and recommendations
    """
    try:
        from collections import defaultdict
        from datetime import datetime

        # Get all incidents in the range
        incidents_data = firehydrant_list_incidents_by_date_range(
            since=since,
            until=until,
            max_results=1000,
        )

        if not incidents_data.get("success"):
            return incidents_data

        incidents = incidents_data.get("incidents", [])

        # Filter by service if specified
        if service_id:
            # Need to get service name for matching
            try:
                services = firehydrant_list_services()
                svc_name = None
                for svc in services:
                    if svc.get("id") == service_id:
                        svc_name = svc.get("name")
                        break
                if svc_name:
                    incidents = [
                        i for i in incidents if svc_name in i.get("services", [])
                    ]
            except Exception:
                pass  # Continue without filtering

        # Analyze per incident name
        name_stats: dict[str, dict] = defaultdict(
            lambda: {
                "fire_count": 0,
                "resolved_count": 0,
                "mttr_values": [],
                "hours_distribution": defaultdict(int),
                "severities": defaultdict(int),
                "services": set(),
            }
        )

        for incident in incidents:
            name = (incident.get("name") or "Unknown")[:100]
            stats = name_stats[name]

            stats["fire_count"] += 1
            stats["severities"][incident.get("severity") or "Unknown"] += 1
            for svc in incident.get("services", []):
                if svc:
                    stats["services"].add(svc)

            if incident.get("status") in ("resolved", "closed", "post_incident"):
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

        # Compute analytics per name
        alert_analytics = []
        for name, stats in name_stats.items():
            fire_count = stats["fire_count"]
            mttr_vals = stats["mttr_values"]
            avg_mttr = round(sum(mttr_vals) / len(mttr_vals), 2) if mttr_vals else None

            # Determine if noisy
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
                    "incident_name": name,
                    "fire_count": fire_count,
                    "resolved_count": stats["resolved_count"],
                    "avg_mttr_minutes": avg_mttr,
                    "services": list(stats["services"]),
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
            "firehydrant_alert_analytics_computed",
            total_alerts=total_unique,
            noisy_alerts=noisy_count,
        )

        return {
            "success": True,
            "period": {"since": since, "until": until},
            "service_id": service_id,
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
            e, "firehydrant_get_alert_analytics", "firehydrant"
        )
    except Exception as e:
        logger.error(
            "firehydrant_get_alert_analytics_failed",
            error=str(e),
            since=since,
            until=until,
        )
        raise ToolExecutionError("firehydrant_get_alert_analytics", str(e), e)


def firehydrant_calculate_mttr(
    severity: str | None = None,
    service_id: str | None = None,
    days: int = 30,
) -> dict[str, Any]:
    """
    Calculate Mean Time To Resolve (MTTR) for FireHydrant incidents.

    Args:
        severity: Optional severity filter
        service_id: Optional service ID to filter
        days: Number of days to analyze (default 30)

    Returns:
        MTTR statistics including average, median, and percentiles
    """
    try:
        from datetime import datetime, timedelta, timezone

        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        until = datetime.now(timezone.utc).isoformat()

        # Use the date range function
        incidents_data = firehydrant_list_incidents_by_date_range(
            since=since,
            until=until,
            severity=severity,
            max_results=500,
        )

        if not incidents_data.get("success"):
            return incidents_data

        incidents = incidents_data.get("incidents", [])

        # Filter by service if specified
        if service_id:
            try:
                services = firehydrant_list_services()
                svc_name = None
                for svc in services:
                    if svc.get("id") == service_id:
                        svc_name = svc.get("name")
                        break
                if svc_name:
                    incidents = [
                        i for i in incidents if svc_name in i.get("services", [])
                    ]
            except Exception:
                pass

        # Extract resolution times
        mttr_values = [i["mttr_minutes"] for i in incidents if i["mttr_minutes"]]

        if not mttr_values:
            return {
                "severity": severity,
                "service_id": service_id,
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

        logger.info("firehydrant_mttr_calculated", incidents=count, mttr=avg_mttr)

        return {
            "severity": severity,
            "service_id": service_id,
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
            e, "firehydrant_calculate_mttr", "firehydrant"
        )
    except Exception as e:
        logger.error("firehydrant_mttr_failed", error=str(e), severity=severity)
        raise ToolExecutionError("firehydrant_calculate_mttr", str(e), e)


# List of all FireHydrant tools for registration
FIREHYDRANT_TOOLS = [
    firehydrant_list_incidents,
    firehydrant_get_incident,
    firehydrant_get_incident_timeline,
    firehydrant_list_incidents_by_date_range,
    firehydrant_list_services,
    firehydrant_list_environments,
    firehydrant_get_alert_analytics,
    firehydrant_calculate_mttr,
]

"""
FireHydrant integration tools for incident management.

Provides FireHydrant API access for incidents, timelines, services, environments, and MTTR analytics.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from ..core.agent import function_tool
from . import get_proxy_headers, register_tool

logger = logging.getLogger(__name__)


def _get_firehydrant_base_url():
    """Get FireHydrant API base URL (supports proxy mode)."""
    return os.getenv("FIREHYDRANT_BASE_URL", "https://api.firehydrant.io").rstrip("/")


def _get_firehydrant_headers():
    """Get FireHydrant API headers.

    Supports two modes:
    - Direct: FIREHYDRANT_API_KEY (sends Bearer auth directly)
    - Proxy: FIREHYDRANT_BASE_URL points to credential-resolver (handles auth)
    """
    if os.getenv("FIREHYDRANT_BASE_URL"):
        # Proxy mode: credential-resolver handles auth
        headers = {"Content-Type": "application/json"}
        headers.update(get_proxy_headers())
        return headers

    api_key = os.getenv("FIREHYDRANT_API_KEY")
    if not api_key:
        raise ValueError("FIREHYDRANT_API_KEY environment variable not set")

    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


@function_tool
def firehydrant_list_incidents(
    status: str = "",
    severity: str = "",
    environment_id: str = "",
    max_results: int = 25,
) -> str:
    """
    List FireHydrant incidents with optional filters.

    Args:
        status: Filter by status (open, in_progress, resolved, closed)
        severity: Filter by severity
        environment_id: Filter by environment ID
        max_results: Maximum incidents to return

    Returns:
        JSON with incidents list
    """
    logger.info(f"firehydrant_list_incidents: status={status}, severity={severity}")

    try:
        import requests

        headers = _get_firehydrant_headers()

        params = {"per_page": min(max_results, 100)}
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
                f"{_get_firehydrant_base_url()}/v1/incidents",
                headers=headers,
                params=params,
                timeout=30,
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
                        "status": incident.get("current_milestone"),
                        "severity": incident.get("severity"),
                        "priority": incident.get("priority"),
                        "created_at": incident.get("created_at"),
                        "started_at": incident.get("started_at"),
                        "resolved_at": milestones.get("resolved"),
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

        return json.dumps(
            {
                "ok": True,
                "incidents": all_incidents,
                "count": len(all_incidents),
            }
        )

    except ValueError as e:
        return json.dumps(
            {"ok": False, "error": str(e), "hint": "Set FIREHYDRANT_API_KEY"}
        )
    except Exception as e:
        logger.error(f"firehydrant_list_incidents error: {e}")
        return json.dumps({"ok": False, "error": str(e)})


@function_tool
def firehydrant_get_incident(incident_id: str) -> str:
    """
    Get details of a specific FireHydrant incident.

    Args:
        incident_id: FireHydrant incident ID

    Returns:
        JSON with incident details including milestones, services, and roles
    """
    if not incident_id:
        return json.dumps({"ok": False, "error": "incident_id is required"})

    logger.info(f"firehydrant_get_incident: incident_id={incident_id}")

    try:
        import requests

        headers = _get_firehydrant_headers()

        response = requests.get(
            f"{_get_firehydrant_base_url()}/v1/incidents/{incident_id}",
            headers=headers,
            timeout=30,
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

        return json.dumps(
            {
                "ok": True,
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
                "slack_channel_name": incident.get("slack_channel_name"),
                "incident_url": incident.get("incident_url"),
            }
        )

    except ValueError as e:
        return json.dumps(
            {"ok": False, "error": str(e), "hint": "Set FIREHYDRANT_API_KEY"}
        )
    except Exception as e:
        logger.error(f"firehydrant_get_incident error: {e}")
        return json.dumps({"ok": False, "error": str(e), "incident_id": incident_id})


@function_tool
def firehydrant_get_incident_timeline(
    incident_id: str,
    max_results: int = 50,
) -> str:
    """
    Get timeline events for a FireHydrant incident.

    Args:
        incident_id: FireHydrant incident ID
        max_results: Maximum timeline entries to return

    Returns:
        JSON with timeline events
    """
    if not incident_id:
        return json.dumps({"ok": False, "error": "incident_id is required"})

    logger.info(f"firehydrant_get_incident_timeline: incident_id={incident_id}")

    try:
        import requests

        headers = _get_firehydrant_headers()

        response = requests.get(
            f"{_get_firehydrant_base_url()}/v1/incidents/{incident_id}/events",
            headers=headers,
            params={"per_page": max_results},
            timeout=30,
        )
        response.raise_for_status()

        data = response.json()
        events = data.get("data", [])

        entries = []
        for event in events:
            entries.append(
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

        return json.dumps(
            {
                "ok": True,
                "entries": entries,
                "count": len(entries),
            }
        )

    except ValueError as e:
        return json.dumps(
            {"ok": False, "error": str(e), "hint": "Set FIREHYDRANT_API_KEY"}
        )
    except Exception as e:
        logger.error(f"firehydrant_get_incident_timeline error: {e}")
        return json.dumps({"ok": False, "error": str(e), "incident_id": incident_id})


@function_tool
def firehydrant_list_incidents_by_date_range(
    since: str,
    until: str,
    severity: str = "",
    max_results: int = 100,
) -> str:
    """
    List FireHydrant incidents within a date range with MTTR calculations.

    Args:
        since: Start date in ISO format (e.g., "2024-01-01T00:00:00Z")
        until: End date in ISO format (e.g., "2024-01-31T23:59:59Z")
        severity: Optional severity filter
        max_results: Maximum incidents to return

    Returns:
        JSON with incidents and computed MTTR metrics
    """
    logger.info(
        f"firehydrant_list_incidents_by_date_range: since={since}, until={until}"
    )

    try:
        import requests

        headers = _get_firehydrant_headers()

        params = {
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
                f"{_get_firehydrant_base_url()}/v1/incidents",
                headers=headers,
                params=params,
                timeout=30,
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

                # Calculate MTTR
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
                    }
                )

            page += 1
            if len(incidents) < params["per_page"]:
                break

        # Compute summary
        resolved = [i for i in all_incidents if i["mttr_minutes"]]
        mttr_values = [i["mttr_minutes"] for i in resolved]

        return json.dumps(
            {
                "ok": True,
                "period": {"since": since, "until": until},
                "incidents": all_incidents,
                "count": len(all_incidents),
                "resolved_count": len(resolved),
                "avg_mttr_minutes": (
                    round(sum(mttr_values) / len(mttr_values), 2)
                    if mttr_values
                    else None
                ),
            }
        )

    except ValueError as e:
        return json.dumps(
            {"ok": False, "error": str(e), "hint": "Set FIREHYDRANT_API_KEY"}
        )
    except Exception as e:
        logger.error(f"firehydrant_list_incidents_by_date_range error: {e}")
        return json.dumps({"ok": False, "error": str(e)})


@function_tool
def firehydrant_list_services() -> str:
    """
    List all FireHydrant services.

    Returns:
        JSON with services including IDs, names, and owners
    """
    logger.info("firehydrant_list_services")

    try:
        import requests

        headers = _get_firehydrant_headers()

        all_services = []
        page = 1

        while True:
            response = requests.get(
                f"{_get_firehydrant_base_url()}/v1/services",
                headers=headers,
                params={"per_page": 100, "page": page},
                timeout=30,
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
                    }
                )

            page += 1
            if len(services) < 100:
                break

        return json.dumps(
            {
                "ok": True,
                "services": all_services,
                "count": len(all_services),
            }
        )

    except ValueError as e:
        return json.dumps(
            {"ok": False, "error": str(e), "hint": "Set FIREHYDRANT_API_KEY"}
        )
    except Exception as e:
        logger.error(f"firehydrant_list_services error: {e}")
        return json.dumps({"ok": False, "error": str(e)})


@function_tool
def firehydrant_list_environments() -> str:
    """
    List all FireHydrant environments.

    Returns:
        JSON with environments including IDs and names
    """
    logger.info("firehydrant_list_environments")

    try:
        import requests

        headers = _get_firehydrant_headers()

        response = requests.get(
            f"{_get_firehydrant_base_url()}/v1/environments",
            headers=headers,
            params={"per_page": 100},
            timeout=30,
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
                }
            )

        return json.dumps(
            {
                "ok": True,
                "environments": result,
                "count": len(result),
            }
        )

    except ValueError as e:
        return json.dumps(
            {"ok": False, "error": str(e), "hint": "Set FIREHYDRANT_API_KEY"}
        )
    except Exception as e:
        logger.error(f"firehydrant_list_environments error: {e}")
        return json.dumps({"ok": False, "error": str(e)})


@function_tool
def firehydrant_get_alert_analytics(
    since: str,
    until: str,
    service_id: str = "",
) -> str:
    """
    Get alert analytics from FireHydrant incidents for fatigue analysis.

    Analyzes incident patterns including fire frequency, resolution patterns,
    time-of-day distribution, and noisy/flapping detection.

    Args:
        since: Start date in ISO format
        until: End date in ISO format
        service_id: Optional service ID to filter

    Returns:
        JSON with alert analytics and noise classification
    """
    logger.info(f"firehydrant_get_alert_analytics: since={since}, until={until}")

    try:
        from collections import defaultdict

        # Get incidents in range
        result = json.loads(
            firehydrant_list_incidents_by_date_range(
                since=since, until=until, max_results=500
            )
        )

        if not result.get("ok"):
            return json.dumps(result)

        incidents = result.get("incidents", [])

        # Filter by service if specified
        if service_id:
            try:
                svc_result = json.loads(firehydrant_list_services())
                if svc_result.get("ok"):
                    svc_name = None
                    for svc in svc_result.get("services", []):
                        if svc.get("id") == service_id:
                            svc_name = svc.get("name")
                            break
                    if svc_name:
                        incidents = [
                            i for i in incidents if svc_name in i.get("services", [])
                        ]
            except Exception:
                pass

        # Analyze per incident name
        name_stats: dict = defaultdict(
            lambda: {
                "fire_count": 0,
                "resolved_count": 0,
                "mttr_values": [],
                "hours_distribution": defaultdict(int),
                "services": set(),
            }
        )

        for incident in incidents:
            name = (incident.get("name") or "Unknown")[:100]
            stats = name_stats[name]
            stats["fire_count"] += 1

            if incident.get("status") in (
                "resolved",
                "closed",
                "post_incident",
            ):
                stats["resolved_count"] += 1
            if incident.get("mttr_minutes"):
                stats["mttr_values"].append(incident["mttr_minutes"])
            for svc in incident.get("services", []):
                if svc:
                    stats["services"].add(svc)

            created_at = incident.get("created_at", "")
            if created_at:
                try:
                    created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    stats["hours_distribution"][created.hour] += 1
                except (ValueError, TypeError):
                    pass

        analytics = []
        for name, stats in name_stats.items():
            fire_count = stats["fire_count"]
            mttr_vals = stats["mttr_values"]
            avg_mttr = round(sum(mttr_vals) / len(mttr_vals), 2) if mttr_vals else None

            is_noisy = fire_count > 10
            is_flapping = fire_count > 20 and avg_mttr is not None and avg_mttr < 10

            hours_dist = dict(stats["hours_distribution"])
            off_hours_count = sum(
                hours_dist.get(h, 0) for h in [0, 1, 2, 3, 4, 5, 22, 23]
            )
            off_hours_rate = (
                round(off_hours_count / fire_count * 100, 1) if fire_count > 0 else 0
            )

            analytics.append(
                {
                    "incident_name": name,
                    "fire_count": fire_count,
                    "resolved_count": stats["resolved_count"],
                    "avg_mttr_minutes": avg_mttr,
                    "services": list(stats["services"]),
                    "off_hours_rate": off_hours_rate,
                    "is_noisy": is_noisy,
                    "is_flapping": is_flapping,
                }
            )

        analytics.sort(key=lambda x: x["fire_count"], reverse=True)

        noisy_count = sum(1 for a in analytics if a["is_noisy"])
        flapping_count = sum(1 for a in analytics if a["is_flapping"])

        return json.dumps(
            {
                "ok": True,
                "period": {"since": since, "until": until},
                "service_id": service_id or None,
                "total_unique_incidents": len(analytics),
                "total_incident_count": len(incidents),
                "noisy_count": noisy_count,
                "flapping_count": flapping_count,
                "analytics": analytics[:50],
            }
        )

    except Exception as e:
        logger.error(f"firehydrant_get_alert_analytics error: {e}")
        return json.dumps({"ok": False, "error": str(e)})


@function_tool
def firehydrant_calculate_mttr(
    severity: str = "",
    service_id: str = "",
    days: int = 30,
) -> str:
    """
    Calculate Mean Time To Resolve (MTTR) for FireHydrant incidents.

    Args:
        severity: Optional severity filter
        service_id: Optional service ID to filter
        days: Number of days to analyze (default 30)

    Returns:
        JSON with MTTR statistics
    """
    logger.info(
        f"firehydrant_calculate_mttr: severity={severity}, service_id={service_id}, days={days}"
    )

    try:
        from datetime import timezone

        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        until = datetime.now(timezone.utc).isoformat()

        result = json.loads(
            firehydrant_list_incidents_by_date_range(
                since=since, until=until, severity=severity, max_results=500
            )
        )

        if not result.get("ok"):
            return json.dumps(result)

        incidents = result.get("incidents", [])

        # Filter by service if specified
        if service_id:
            try:
                svc_result = json.loads(firehydrant_list_services())
                if svc_result.get("ok"):
                    svc_name = None
                    for svc in svc_result.get("services", []):
                        if svc.get("id") == service_id:
                            svc_name = svc.get("name")
                            break
                    if svc_name:
                        incidents = [
                            i for i in incidents if svc_name in i.get("services", [])
                        ]
            except Exception:
                pass

        mttr_values = [i["mttr_minutes"] for i in incidents if i.get("mttr_minutes")]

        if not mttr_values:
            return json.dumps(
                {
                    "ok": True,
                    "severity": severity or None,
                    "service_id": service_id or None,
                    "period_days": days,
                    "incident_count": 0,
                    "mttr_minutes": 0,
                    "message": "No resolved incidents in this period",
                }
            )

        mttr_values.sort()
        count = len(mttr_values)
        avg_mttr = sum(mttr_values) / count
        median_mttr = mttr_values[count // 2]
        p95_mttr = mttr_values[int(count * 0.95)] if count > 0 else 0

        return json.dumps(
            {
                "ok": True,
                "severity": severity or None,
                "service_id": service_id or None,
                "period_days": days,
                "incident_count": count,
                "mttr_minutes": round(avg_mttr, 2),
                "mttr_hours": round(avg_mttr / 60, 2),
                "median_minutes": round(median_mttr, 2),
                "p95_minutes": round(p95_mttr, 2),
                "fastest_resolution_minutes": round(min(mttr_values), 2),
                "slowest_resolution_minutes": round(max(mttr_values), 2),
            }
        )

    except ValueError as e:
        return json.dumps(
            {"ok": False, "error": str(e), "hint": "Set FIREHYDRANT_API_KEY"}
        )
    except Exception as e:
        logger.error(f"firehydrant_calculate_mttr error: {e}")
        return json.dumps({"ok": False, "error": str(e)})


# Register tools
register_tool("firehydrant_list_incidents", firehydrant_list_incidents)
register_tool("firehydrant_get_incident", firehydrant_get_incident)
register_tool("firehydrant_get_incident_timeline", firehydrant_get_incident_timeline)
register_tool(
    "firehydrant_list_incidents_by_date_range", firehydrant_list_incidents_by_date_range
)
register_tool("firehydrant_list_services", firehydrant_list_services)
register_tool("firehydrant_list_environments", firehydrant_list_environments)
register_tool("firehydrant_get_alert_analytics", firehydrant_get_alert_analytics)
register_tool("firehydrant_calculate_mttr", firehydrant_calculate_mttr)

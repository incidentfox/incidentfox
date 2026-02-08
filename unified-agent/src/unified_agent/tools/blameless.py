"""
Blameless integration tools for incident management and retrospectives.

Provides Blameless API access for incidents, timelines, retrospectives, and MTTR analytics.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from ..core.agent import function_tool
from . import get_proxy_headers, register_tool

logger = logging.getLogger(__name__)


def _get_blameless_base_url():
    """Get Blameless API base URL (supports proxy mode)."""
    return os.getenv("BLAMELESS_BASE_URL", "https://api.blameless.io").rstrip("/")


def _get_blameless_headers():
    """Get Blameless API headers.

    Supports two modes:
    - Direct: BLAMELESS_API_KEY (sends Bearer auth directly)
    - Proxy: BLAMELESS_BASE_URL points to credential-resolver (handles auth)
    """
    if os.getenv("BLAMELESS_BASE_URL"):
        # Proxy mode: credential-resolver handles auth
        headers = {"Content-Type": "application/json"}
        headers.update(get_proxy_headers())
        return headers

    api_key = os.getenv("BLAMELESS_API_KEY")
    if not api_key:
        raise ValueError("BLAMELESS_API_KEY environment variable not set")

    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


@function_tool
def blameless_list_incidents(
    status: str = "",
    severity: str = "",
    max_results: int = 25,
) -> str:
    """
    List Blameless incidents with optional filters.

    Args:
        status: Filter by status (investigating, identified, monitoring, resolved)
        severity: Filter by severity (SEV0, SEV1, SEV2, SEV3, SEV4)
        max_results: Maximum incidents to return

    Returns:
        JSON with incidents list
    """
    logger.info(f"blameless_list_incidents: status={status}, severity={severity}")

    try:
        import requests

        headers = _get_blameless_headers()

        params = {"limit": min(max_results, 100)}
        if status:
            params["status"] = status
        if severity:
            params["severity"] = severity

        all_incidents = []
        page = 1

        while len(all_incidents) < max_results:
            params["page"] = page

            response = requests.get(
                f"{_get_blameless_base_url()}/api/v1/incidents",
                headers=headers,
                params=params,
                timeout=30,
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

        return json.dumps(
            {
                "ok": True,
                "incidents": all_incidents,
                "count": len(all_incidents),
            }
        )

    except ValueError as e:
        return json.dumps(
            {"ok": False, "error": str(e), "hint": "Set BLAMELESS_API_KEY"}
        )
    except Exception as e:
        logger.error(f"blameless_list_incidents error: {e}")
        return json.dumps({"ok": False, "error": str(e)})


@function_tool
def blameless_get_incident(incident_id: str) -> str:
    """
    Get details of a specific Blameless incident.

    Args:
        incident_id: Blameless incident ID

    Returns:
        JSON with incident details including roles and timeline info
    """
    if not incident_id:
        return json.dumps({"ok": False, "error": "incident_id is required"})

    logger.info(f"blameless_get_incident: incident_id={incident_id}")

    try:
        import requests

        headers = _get_blameless_headers()

        response = requests.get(
            f"{_get_blameless_base_url()}/api/v1/incidents/{incident_id}",
            headers=headers,
            timeout=30,
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

        return json.dumps(
            {
                "ok": True,
                "id": incident.get("id"),
                "title": incident.get("title") or incident.get("name"),
                "description": incident.get("description"),
                "status": incident.get("status"),
                "severity": incident.get("severity"),
                "incident_type": incident.get("type") or incident.get("incident_type"),
                "created_at": incident.get("created_at"),
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
                "url": incident.get("url") or incident.get("permalink"),
            }
        )

    except ValueError as e:
        return json.dumps(
            {"ok": False, "error": str(e), "hint": "Set BLAMELESS_API_KEY"}
        )
    except Exception as e:
        logger.error(f"blameless_get_incident error: {e}")
        return json.dumps({"ok": False, "error": str(e), "incident_id": incident_id})


@function_tool
def blameless_get_incident_timeline(
    incident_id: str,
    max_results: int = 50,
) -> str:
    """
    Get timeline entries for a Blameless incident.

    Args:
        incident_id: Blameless incident ID
        max_results: Maximum timeline entries to return

    Returns:
        JSON with timeline events showing incident progression
    """
    if not incident_id:
        return json.dumps({"ok": False, "error": "incident_id is required"})

    logger.info(f"blameless_get_incident_timeline: incident_id={incident_id}")

    try:
        import requests

        headers = _get_blameless_headers()

        response = requests.get(
            f"{_get_blameless_base_url()}/api/v1/incidents/{incident_id}/events",
            headers=headers,
            params={"limit": max_results},
            timeout=30,
        )
        response.raise_for_status()

        data = response.json()
        events = data.get("events", data.get("data", []))

        entries = []
        for event in events:
            entries.append(
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

        return json.dumps(
            {
                "ok": True,
                "entries": entries,
                "count": len(entries),
            }
        )

    except ValueError as e:
        return json.dumps(
            {"ok": False, "error": str(e), "hint": "Set BLAMELESS_API_KEY"}
        )
    except Exception as e:
        logger.error(f"blameless_get_incident_timeline error: {e}")
        return json.dumps({"ok": False, "error": str(e), "incident_id": incident_id})


@function_tool
def blameless_list_incidents_by_date_range(
    since: str,
    until: str,
    severity: str = "",
    max_results: int = 100,
) -> str:
    """
    List Blameless incidents within a date range with MTTR calculations.

    Args:
        since: Start date in ISO format (e.g., "2024-01-01T00:00:00Z")
        until: End date in ISO format (e.g., "2024-01-31T23:59:59Z")
        severity: Optional severity filter (SEV0-SEV4)
        max_results: Maximum incidents to return

    Returns:
        JSON with incidents and computed MTTR metrics
    """
    logger.info(f"blameless_list_incidents_by_date_range: since={since}, until={until}")

    try:
        import requests

        headers = _get_blameless_headers()

        params = {
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
                f"{_get_blameless_base_url()}/api/v1/incidents",
                headers=headers,
                params=params,
                timeout=30,
            )
            response.raise_for_status()

            data = response.json()
            incidents = data.get("incidents", data.get("data", []))

            if not incidents:
                break

            for incident in incidents:
                created_at_str = incident.get("created_at", "")
                resolved_at_str = incident.get("resolved_at")

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
                    }
                )

            page += 1
            if len(incidents) < params["limit"]:
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
            {"ok": False, "error": str(e), "hint": "Set BLAMELESS_API_KEY"}
        )
    except Exception as e:
        logger.error(f"blameless_list_incidents_by_date_range error: {e}")
        return json.dumps({"ok": False, "error": str(e)})


@function_tool
def blameless_list_severities() -> str:
    """
    List all configured severity levels in Blameless.

    Returns:
        JSON with severity definitions
    """
    logger.info("blameless_list_severities")

    try:
        import requests

        headers = _get_blameless_headers()

        response = requests.get(
            f"{_get_blameless_base_url()}/api/v1/severities",
            headers=headers,
            timeout=30,
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

        return json.dumps(
            {
                "ok": True,
                "severities": result,
                "count": len(result),
            }
        )

    except ValueError as e:
        return json.dumps(
            {"ok": False, "error": str(e), "hint": "Set BLAMELESS_API_KEY"}
        )
    except Exception as e:
        logger.error(f"blameless_list_severities error: {e}")
        return json.dumps({"ok": False, "error": str(e)})


@function_tool
def blameless_get_retrospective(incident_id: str) -> str:
    """
    Get the retrospective (post-incident review) for a Blameless incident.

    Blameless retrospectives include contributing factors, action items,
    and lessons learned.

    Args:
        incident_id: Blameless incident ID

    Returns:
        JSON with retrospective details
    """
    if not incident_id:
        return json.dumps({"ok": False, "error": "incident_id is required"})

    logger.info(f"blameless_get_retrospective: incident_id={incident_id}")

    try:
        import requests

        headers = _get_blameless_headers()

        response = requests.get(
            f"{_get_blameless_base_url()}/api/v1/incidents/{incident_id}/retrospective",
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()

        data = response.json()
        retro = data.get("retrospective", data)

        contributing_factors = []
        for factor in retro.get("contributing_factors", []):
            contributing_factors.append(
                {
                    "id": factor.get("id"),
                    "description": factor.get("description"),
                    "category": factor.get("category"),
                }
            )

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

        return json.dumps(
            {
                "ok": True,
                "incident_id": incident_id,
                "summary": retro.get("summary") or retro.get("description"),
                "impact": retro.get("impact"),
                "root_cause": retro.get("root_cause"),
                "contributing_factors": contributing_factors,
                "action_items": action_items,
                "lessons_learned": retro.get("lessons_learned", []),
                "status": retro.get("status"),
                "url": retro.get("url") or retro.get("permalink"),
            }
        )

    except ValueError as e:
        return json.dumps(
            {"ok": False, "error": str(e), "hint": "Set BLAMELESS_API_KEY"}
        )
    except Exception as e:
        logger.error(f"blameless_get_retrospective error: {e}")
        return json.dumps({"ok": False, "error": str(e), "incident_id": incident_id})


@function_tool
def blameless_get_alert_analytics(
    since: str,
    until: str,
    severity: str = "",
) -> str:
    """
    Get alert analytics from Blameless incidents for fatigue analysis.

    Analyzes incident patterns including fire frequency, resolution patterns,
    time-of-day distribution, and noisy/flapping incident detection.

    Args:
        since: Start date in ISO format
        until: End date in ISO format
        severity: Optional severity filter

    Returns:
        JSON with alert analytics and noise classification
    """
    logger.info(f"blameless_get_alert_analytics: since={since}, until={until}")

    try:
        from collections import defaultdict

        # Get incidents in range
        result = json.loads(
            blameless_list_incidents_by_date_range(
                since=since, until=until, severity=severity, max_results=500
            )
        )

        if not result.get("ok"):
            return json.dumps(result)

        incidents = result.get("incidents", [])

        # Analyze per title
        title_stats: dict = defaultdict(
            lambda: {
                "fire_count": 0,
                "resolved_count": 0,
                "mttr_values": [],
                "hours_distribution": defaultdict(int),
            }
        )

        for incident in incidents:
            title = (incident.get("title") or "Unknown")[:100]
            stats = title_stats[title]
            stats["fire_count"] += 1

            if incident.get("status") in ("resolved", "closed"):
                stats["resolved_count"] += 1
            if incident.get("mttr_minutes"):
                stats["mttr_values"].append(incident["mttr_minutes"])

            created_at = incident.get("created_at", "")
            if created_at:
                try:
                    created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    stats["hours_distribution"][created.hour] += 1
                except (ValueError, TypeError):
                    pass

        analytics = []
        for title, stats in title_stats.items():
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
                    "incident_title": title,
                    "fire_count": fire_count,
                    "resolved_count": stats["resolved_count"],
                    "avg_mttr_minutes": avg_mttr,
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
                "total_unique_incidents": len(analytics),
                "total_incident_count": len(incidents),
                "noisy_count": noisy_count,
                "flapping_count": flapping_count,
                "analytics": analytics[:50],
            }
        )

    except Exception as e:
        logger.error(f"blameless_get_alert_analytics error: {e}")
        return json.dumps({"ok": False, "error": str(e)})


@function_tool
def blameless_calculate_mttr(severity: str = "", days: int = 30) -> str:
    """
    Calculate Mean Time To Resolve (MTTR) for Blameless incidents.

    Args:
        severity: Optional severity filter (SEV0-SEV4)
        days: Number of days to analyze (default 30)

    Returns:
        JSON with MTTR statistics
    """
    logger.info(f"blameless_calculate_mttr: severity={severity}, days={days}")

    try:
        from datetime import timezone

        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        until = datetime.now(timezone.utc).isoformat()

        result = json.loads(
            blameless_list_incidents_by_date_range(
                since=since, until=until, severity=severity, max_results=500
            )
        )

        if not result.get("ok"):
            return json.dumps(result)

        incidents = result.get("incidents", [])
        mttr_values = [i["mttr_minutes"] for i in incidents if i.get("mttr_minutes")]

        if not mttr_values:
            return json.dumps(
                {
                    "ok": True,
                    "severity": severity,
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
        )

    except ValueError as e:
        return json.dumps(
            {"ok": False, "error": str(e), "hint": "Set BLAMELESS_API_KEY"}
        )
    except Exception as e:
        logger.error(f"blameless_calculate_mttr error: {e}")
        return json.dumps({"ok": False, "error": str(e)})


# Register tools
register_tool("blameless_list_incidents", blameless_list_incidents)
register_tool("blameless_get_incident", blameless_get_incident)
register_tool("blameless_get_incident_timeline", blameless_get_incident_timeline)
register_tool(
    "blameless_list_incidents_by_date_range", blameless_list_incidents_by_date_range
)
register_tool("blameless_list_severities", blameless_list_severities)
register_tool("blameless_get_retrospective", blameless_get_retrospective)
register_tool("blameless_get_alert_analytics", blameless_get_alert_analytics)
register_tool("blameless_calculate_mttr", blameless_calculate_mttr)

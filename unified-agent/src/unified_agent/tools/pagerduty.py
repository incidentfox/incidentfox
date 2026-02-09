"""
PagerDuty integration tools for incident management.

Provides PagerDuty API access for incidents, escalation policies, and on-call info.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from ..core.agent import function_tool
from . import get_proxy_headers, register_tool

logger = logging.getLogger(__name__)


def _get_pagerduty_base_url():
    """Get PagerDuty API base URL (supports proxy mode)."""
    return os.getenv("PAGERDUTY_BASE_URL", "https://api.pagerduty.com").rstrip("/")


def _get_pagerduty_headers():
    """Get PagerDuty API headers.

    Supports two modes:
    - Direct: PAGERDUTY_API_KEY (sends Token auth directly)
    - Proxy: PAGERDUTY_BASE_URL points to credential-resolver (handles auth)
    """
    if os.getenv("PAGERDUTY_BASE_URL"):
        # Proxy mode: credential-resolver handles auth
        headers = {
            "Accept": "application/vnd.pagerduty+json;version=2",
            "Content-Type": "application/json",
        }
        headers.update(get_proxy_headers())
        return headers

    api_key = os.getenv("PAGERDUTY_API_KEY")
    if not api_key:
        raise ValueError("PAGERDUTY_API_KEY environment variable not set")

    return {
        "Authorization": f"Token token={api_key}",
        "Accept": "application/vnd.pagerduty+json;version=2",
        "Content-Type": "application/json",
    }


@function_tool
def pagerduty_get_incident(incident_id: str) -> str:
    """
    Get details of a specific PagerDuty incident.

    Args:
        incident_id: PagerDuty incident ID

    Returns:
        JSON with incident details
    """
    if not incident_id:
        return json.dumps({"ok": False, "error": "incident_id is required"})

    logger.info(f"pagerduty_get_incident: incident_id={incident_id}")

    try:
        import requests

        headers = _get_pagerduty_headers()

        response = requests.get(
            f"{_get_pagerduty_base_url()}/incidents/{incident_id}",
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()

        incident = response.json()["incident"]

        return json.dumps(
            {
                "ok": True,
                "id": incident["id"],
                "incident_number": incident.get("incident_number"),
                "title": incident["title"],
                "description": incident.get("description"),
                "status": incident["status"],
                "urgency": incident["urgency"],
                "created_at": incident["created_at"],
                "updated_at": incident.get("updated_at"),
                "service": {
                    "id": incident["service"]["id"],
                    "name": incident["service"]["summary"],
                },
                "assignments": [
                    {"assignee": a["assignee"]["summary"], "at": a["at"]}
                    for a in incident.get("assignments", [])
                ],
                "acknowledgements": [
                    {"acknowledger": a["acknowledger"]["summary"], "at": a["at"]}
                    for a in incident.get("acknowledgements", [])
                ],
                "url": incident["html_url"],
            }
        )

    except ValueError as e:
        return json.dumps(
            {"ok": False, "error": str(e), "hint": "Set PAGERDUTY_API_KEY"}
        )
    except Exception as e:
        logger.error(f"pagerduty_get_incident error: {e}")
        return json.dumps({"ok": False, "error": str(e), "incident_id": incident_id})


@function_tool
def pagerduty_get_incident_log_entries(
    incident_id: str,
    max_results: int = 100,
) -> str:
    """
    Get log entries (timeline) for a PagerDuty incident.

    Args:
        incident_id: PagerDuty incident ID
        max_results: Maximum log entries to return

    Returns:
        JSON with log entries
    """
    if not incident_id:
        return json.dumps({"ok": False, "error": "incident_id is required"})

    logger.info(f"pagerduty_get_incident_log_entries: incident_id={incident_id}")

    try:
        import requests

        headers = _get_pagerduty_headers()

        response = requests.get(
            f"{_get_pagerduty_base_url()}/incidents/{incident_id}/log_entries",
            headers=headers,
            params={"limit": max_results},
            timeout=30,
        )
        response.raise_for_status()

        log_entries = response.json()["log_entries"]

        entries = []
        for entry in log_entries:
            entries.append(
                {
                    "id": entry["id"],
                    "type": entry["type"],
                    "created_at": entry["created_at"],
                    "agent": entry.get("agent", {}).get("summary"),
                    "channel": entry.get("channel", {}).get("type"),
                    "summary": entry.get("summary"),
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
            {"ok": False, "error": str(e), "hint": "Set PAGERDUTY_API_KEY"}
        )
    except Exception as e:
        logger.error(f"pagerduty_get_incident_log_entries error: {e}")
        return json.dumps({"ok": False, "error": str(e), "incident_id": incident_id})


@function_tool
def pagerduty_list_incidents(
    status: str = "",
    urgency: str = "",
    service_ids: str = "",
    max_results: int = 25,
) -> str:
    """
    List PagerDuty incidents with optional filters.

    Args:
        status: Filter by status (triggered, acknowledged, resolved)
        urgency: Filter by urgency (high, low)
        service_ids: Comma-separated service IDs
        max_results: Maximum incidents to return

    Returns:
        JSON with incidents list
    """
    logger.info(f"pagerduty_list_incidents: status={status}, urgency={urgency}")

    try:
        import requests

        headers = _get_pagerduty_headers()

        params = {"limit": max_results}
        if status:
            params["statuses[]"] = status
        if urgency:
            params["urgencies[]"] = urgency
        if service_ids:
            params["service_ids[]"] = [s.strip() for s in service_ids.split(",")]

        response = requests.get(
            f"{_get_pagerduty_base_url()}/incidents",
            headers=headers,
            params=params,
            timeout=30,
        )
        response.raise_for_status()

        incidents = response.json()["incidents"]

        incident_list = []
        for incident in incidents:
            incident_list.append(
                {
                    "id": incident["id"],
                    "incident_number": incident.get("incident_number"),
                    "title": incident["title"],
                    "status": incident["status"],
                    "urgency": incident["urgency"],
                    "created_at": incident["created_at"],
                    "service": incident["service"]["summary"],
                    "url": incident["html_url"],
                }
            )

        return json.dumps(
            {
                "ok": True,
                "incidents": incident_list,
                "count": len(incident_list),
            }
        )

    except ValueError as e:
        return json.dumps(
            {"ok": False, "error": str(e), "hint": "Set PAGERDUTY_API_KEY"}
        )
    except Exception as e:
        logger.error(f"pagerduty_list_incidents error: {e}")
        return json.dumps({"ok": False, "error": str(e)})


@function_tool
def pagerduty_get_escalation_policy(policy_id: str) -> str:
    """
    Get details of a PagerDuty escalation policy.

    Args:
        policy_id: Escalation policy ID

    Returns:
        JSON with escalation policy details
    """
    if not policy_id:
        return json.dumps({"ok": False, "error": "policy_id is required"})

    logger.info(f"pagerduty_get_escalation_policy: policy_id={policy_id}")

    try:
        import requests

        headers = _get_pagerduty_headers()

        response = requests.get(
            f"{_get_pagerduty_base_url()}/escalation_policies/{policy_id}",
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()

        policy = response.json()["escalation_policy"]

        return json.dumps(
            {
                "ok": True,
                "id": policy["id"],
                "name": policy["name"],
                "description": policy.get("description"),
                "num_loops": policy.get("num_loops"),
                "escalation_rules": [
                    {
                        "escalation_delay_in_minutes": rule[
                            "escalation_delay_in_minutes"
                        ],
                        "targets": [
                            {
                                "type": target["type"],
                                "id": target["id"],
                                "summary": target["summary"],
                            }
                            for target in rule.get("targets", [])
                        ],
                    }
                    for rule in policy.get("escalation_rules", [])
                ],
                "services": [
                    {"id": svc["id"], "summary": svc["summary"]}
                    for svc in policy.get("services", [])
                ],
            }
        )

    except ValueError as e:
        return json.dumps(
            {"ok": False, "error": str(e), "hint": "Set PAGERDUTY_API_KEY"}
        )
    except Exception as e:
        logger.error(f"pagerduty_get_escalation_policy error: {e}")
        return json.dumps({"ok": False, "error": str(e), "policy_id": policy_id})


@function_tool
def pagerduty_calculate_mttr(service_id: str = "", days: int = 30) -> str:
    """
    Calculate Mean Time To Resolve (MTTR) for PagerDuty incidents.

    Args:
        service_id: Optional service ID to filter by
        days: Number of days to analyze (default 30)

    Returns:
        JSON with MTTR statistics
    """
    logger.info(f"pagerduty_calculate_mttr: service_id={service_id}, days={days}")

    try:
        import requests

        headers = _get_pagerduty_headers()

        since = (datetime.utcnow() - timedelta(days=days)).isoformat()
        until = datetime.utcnow().isoformat()

        params = {
            "since": since,
            "until": until,
            "statuses[]": "resolved",
            "limit": 100,
        }

        if service_id:
            params["service_ids[]"] = service_id

        response = requests.get(
            f"{_get_pagerduty_base_url()}/incidents",
            headers=headers,
            params=params,
            timeout=30,
        )
        response.raise_for_status()

        incidents = response.json()["incidents"]

        # Calculate resolution times
        resolution_times = []
        for incident in incidents:
            created = datetime.fromisoformat(
                incident["created_at"].replace("Z", "+00:00")
            )
            resolved = datetime.fromisoformat(
                incident["last_status_change_at"].replace("Z", "+00:00")
            )
            resolution_minutes = (resolved - created).total_seconds() / 60
            resolution_times.append(resolution_minutes)

        if not resolution_times:
            return json.dumps(
                {
                    "ok": True,
                    "service_id": service_id,
                    "period_days": days,
                    "incident_count": 0,
                    "mttr_minutes": 0,
                    "message": "No resolved incidents in this period",
                }
            )

        # Calculate statistics
        resolution_times.sort()
        count = len(resolution_times)
        avg_mttr = sum(resolution_times) / count
        median_mttr = resolution_times[count // 2]
        p95_mttr = resolution_times[int(count * 0.95)] if count > 0 else 0

        return json.dumps(
            {
                "ok": True,
                "service_id": service_id,
                "period_days": days,
                "incident_count": count,
                "mttr_minutes": round(avg_mttr, 2),
                "mttr_hours": round(avg_mttr / 60, 2),
                "median_minutes": round(median_mttr, 2),
                "p95_minutes": round(p95_mttr, 2),
                "fastest_resolution_minutes": round(min(resolution_times), 2),
                "slowest_resolution_minutes": round(max(resolution_times), 2),
            }
        )

    except ValueError as e:
        return json.dumps(
            {"ok": False, "error": str(e), "hint": "Set PAGERDUTY_API_KEY"}
        )
    except Exception as e:
        logger.error(f"pagerduty_calculate_mttr error: {e}")
        return json.dumps({"ok": False, "error": str(e)})


@function_tool
def pagerduty_create_incident(
    service_id: str,
    title: str,
    urgency: str = "high",
    description: str = "",
    escalation_policy_id: str = "",
) -> str:
    """
    Create a PagerDuty incident to page the on-call responder.

    Use this to page a code owner or on-call engineer for urgent issues.

    Args:
        service_id: PagerDuty service ID to create the incident on
        title: Incident title (e.g. "[Enterprise] Acme Corp: bulk CSV export")
        urgency: Incident urgency - "high" (phone call) or "low" (email/push)
        description: Incident body with details
        escalation_policy_id: Optional escalation policy ID override

    Returns:
        JSON with the created incident details
    """
    if not service_id:
        return json.dumps({"ok": False, "error": "service_id is required"})
    if not title:
        return json.dumps({"ok": False, "error": "title is required"})

    logger.info(
        f"pagerduty_create_incident: service_id={service_id}, title={title}, urgency={urgency}"
    )

    try:
        import requests

        headers = _get_pagerduty_headers()

        payload = {
            "incident": {
                "type": "incident",
                "title": title,
                "urgency": urgency,
                "service": {
                    "id": service_id,
                    "type": "service_reference",
                },
            }
        }

        if description:
            payload["incident"]["body"] = {
                "type": "incident_body",
                "details": description,
            }

        if escalation_policy_id:
            payload["incident"]["escalation_policy"] = {
                "id": escalation_policy_id,
                "type": "escalation_policy_reference",
            }

        response = requests.post(
            f"{_get_pagerduty_base_url()}/incidents",
            headers=headers,
            json=payload,
            timeout=30,
        )
        response.raise_for_status()

        incident = response.json()["incident"]

        return json.dumps(
            {
                "ok": True,
                "id": incident["id"],
                "incident_number": incident.get("incident_number"),
                "title": incident["title"],
                "status": incident["status"],
                "urgency": incident["urgency"],
                "service": incident["service"]["summary"],
                "assignments": [
                    a.get("assignee", {}).get("summary")
                    for a in incident.get("assignments", [])
                ],
                "url": incident["html_url"],
            }
        )

    except ValueError as e:
        return json.dumps(
            {"ok": False, "error": str(e), "hint": "Set PAGERDUTY_API_KEY"}
        )
    except Exception as e:
        logger.error(f"pagerduty_create_incident error: {e}")
        return json.dumps({"ok": False, "error": str(e)})


# Register tools
register_tool("pagerduty_get_incident", pagerduty_get_incident)
register_tool("pagerduty_get_incident_log_entries", pagerduty_get_incident_log_entries)
register_tool("pagerduty_list_incidents", pagerduty_list_incidents)
register_tool("pagerduty_get_escalation_policy", pagerduty_get_escalation_policy)
register_tool("pagerduty_calculate_mttr", pagerduty_calculate_mttr)
register_tool("pagerduty_create_incident", pagerduty_create_incident)

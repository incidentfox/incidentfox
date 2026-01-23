"""PagerDuty integration tools for incident management."""

import os
from typing import Any

from ..core.config_required import handle_integration_not_configured
from ..core.errors import ToolExecutionError
from ..core.execution_context import get_execution_context
from ..core.integration_errors import IntegrationNotConfiguredError
from ..core.logging import get_logger

logger = get_logger(__name__)


def _get_pagerduty_config() -> dict:
    """Get PagerDuty configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("pagerduty")
        if config and config.get("api_key"):
            return config

    # 2. Try environment variables (dev/testing fallback)
    if os.getenv("PAGERDUTY_API_KEY"):
        return {"api_key": os.getenv("PAGERDUTY_API_KEY")}

    # 3. Not configured - raise error
    raise IntegrationNotConfiguredError(
        integration_id="pagerduty",
        tool_id="pagerduty_tools",
        missing_fields=["api_key"],
    )


def _get_pagerduty_client():
    """Get PagerDuty API client."""
    try:
        import requests

        config = _get_pagerduty_config()
        return config["api_key"]
    except ImportError:
        raise ToolExecutionError("pagerduty", "requests package not installed")


def pagerduty_get_incident(incident_id: str) -> dict[str, Any]:
    """
    Get details of a specific PagerDuty incident.

    Args:
        incident_id: PagerDuty incident ID

    Returns:
        Incident details including status, service, timestamps, and description
    """
    try:
        import requests

        api_key = _get_pagerduty_client()

        headers = {
            "Authorization": f"Token token={api_key}",
            "Accept": "application/vnd.pagerduty+json;version=2",
            "Content-Type": "application/json",
        }

        response = requests.get(
            f"https://api.pagerduty.com/incidents/{incident_id}", headers=headers
        )
        response.raise_for_status()

        incident = response.json()["incident"]

        logger.info("pagerduty_incident_fetched", incident_id=incident_id)

        return {
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
                {"assignee": assignment["assignee"]["summary"], "at": assignment["at"]}
                for assignment in incident.get("assignments", [])
            ],
            "acknowledgements": [
                {"acknowledger": ack["acknowledger"]["summary"], "at": ack["at"]}
                for ack in incident.get("acknowledgements", [])
            ],
            "url": incident["html_url"],
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "pagerduty_get_incident", "pagerduty"
        )
    except Exception as e:
        logger.error(
            "pagerduty_get_incident_failed", error=str(e), incident_id=incident_id
        )
        raise ToolExecutionError("pagerduty_get_incident", str(e), e)


def pagerduty_get_incident_log_entries(
    incident_id: str, max_results: int = 100
) -> list[dict[str, Any]]:
    """
    Get log entries (timeline) for a PagerDuty incident.

    Args:
        incident_id: PagerDuty incident ID
        max_results: Maximum log entries to return

    Returns:
        List of log entries showing incident timeline
    """
    try:
        import requests

        api_key = _get_pagerduty_client()

        headers = {
            "Authorization": f"Token token={api_key}",
            "Accept": "application/vnd.pagerduty+json;version=2",
            "Content-Type": "application/json",
        }

        response = requests.get(
            f"https://api.pagerduty.com/incidents/{incident_id}/log_entries",
            headers=headers,
            params={"limit": max_results},
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

        logger.info(
            "pagerduty_log_entries_fetched", incident_id=incident_id, count=len(entries)
        )
        return entries

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "pagerduty_get_incident_log_entries", "pagerduty"
        )
    except Exception as e:
        logger.error(
            "pagerduty_log_entries_failed", error=str(e), incident_id=incident_id
        )
        raise ToolExecutionError("pagerduty_get_incident_log_entries", str(e), e)


def pagerduty_list_incidents(
    status: str | None = None,
    urgency: str | None = None,
    service_ids: list[str] | None = None,
    max_results: int = 25,
) -> list[dict[str, Any]]:
    """
    List PagerDuty incidents with optional filters.

    Args:
        status: Filter by status (triggered, acknowledged, resolved)
        urgency: Filter by urgency (high, low)
        service_ids: Filter by service IDs
        max_results: Maximum incidents to return

    Returns:
        List of incidents
    """
    try:
        import requests

        api_key = _get_pagerduty_client()

        headers = {
            "Authorization": f"Token token={api_key}",
            "Accept": "application/vnd.pagerduty+json;version=2",
            "Content-Type": "application/json",
        }

        params = {"limit": max_results}
        if status:
            params["statuses[]"] = status
        if urgency:
            params["urgencies[]"] = urgency
        if service_ids:
            params["service_ids[]"] = service_ids

        response = requests.get(
            "https://api.pagerduty.com/incidents", headers=headers, params=params
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

        logger.info("pagerduty_incidents_listed", count=len(incident_list))
        return incident_list

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "pagerduty_list_incidents", "pagerduty"
        )
    except Exception as e:
        logger.error("pagerduty_list_incidents_failed", error=str(e))
        raise ToolExecutionError("pagerduty_list_incidents", str(e), e)


def pagerduty_get_escalation_policy(policy_id: str) -> dict[str, Any]:
    """
    Get details of a PagerDuty escalation policy.

    Args:
        policy_id: Escalation policy ID

    Returns:
        Escalation policy details including escalation rules and on-call schedules
    """
    try:
        import requests

        api_key = _get_pagerduty_client()

        headers = {
            "Authorization": f"Token token={api_key}",
            "Accept": "application/vnd.pagerduty+json;version=2",
            "Content-Type": "application/json",
        }

        response = requests.get(
            f"https://api.pagerduty.com/escalation_policies/{policy_id}",
            headers=headers,
        )
        response.raise_for_status()

        policy = response.json()["escalation_policy"]

        logger.info("pagerduty_escalation_policy_fetched", policy_id=policy_id)

        return {
            "id": policy["id"],
            "name": policy["name"],
            "description": policy.get("description"),
            "num_loops": policy.get("num_loops"),
            "escalation_rules": [
                {
                    "escalation_delay_in_minutes": rule["escalation_delay_in_minutes"],
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

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "pagerduty_get_escalation_policy", "pagerduty"
        )
    except Exception as e:
        logger.error(
            "pagerduty_escalation_policy_failed", error=str(e), policy_id=policy_id
        )
        raise ToolExecutionError("pagerduty_get_escalation_policy", str(e), e)


def pagerduty_calculate_mttr(
    service_id: str | None = None, days: int = 30
) -> dict[str, Any]:
    """
    Calculate Mean Time To Resolve (MTTR) for PagerDuty incidents.

    Args:
        service_id: Optional service ID to filter by
        days: Number of days to analyze (default 30)

    Returns:
        MTTR statistics including average, median, and percentiles
    """
    try:
        from datetime import datetime, timedelta

        import requests

        api_key = _get_pagerduty_client()

        headers = {
            "Authorization": f"Token token={api_key}",
            "Accept": "application/vnd.pagerduty+json;version=2",
            "Content-Type": "application/json",
        }

        # Get incidents from last N days
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
            "https://api.pagerduty.com/incidents", headers=headers, params=params
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
            return {
                "service_id": service_id,
                "period_days": days,
                "incident_count": 0,
                "mttr_minutes": 0,
                "message": "No resolved incidents in this period",
            }

        # Calculate statistics
        resolution_times.sort()
        count = len(resolution_times)
        avg_mttr = sum(resolution_times) / count
        median_mttr = resolution_times[count // 2]
        p95_mttr = resolution_times[int(count * 0.95)] if count > 0 else 0

        logger.info("pagerduty_mttr_calculated", incidents=count, mttr=avg_mttr)

        return {
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

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "pagerduty_calculate_mttr", "pagerduty"
        )
    except Exception as e:
        logger.error("pagerduty_mttr_failed", error=str(e), service_id=service_id)
        raise ToolExecutionError("pagerduty_calculate_mttr", str(e), e)


# List of all PagerDuty tools for registration
PAGERDUTY_TOOLS = [
    pagerduty_get_incident,
    pagerduty_get_incident_log_entries,
    pagerduty_list_incidents,
    pagerduty_get_escalation_policy,
    pagerduty_calculate_mttr,
]

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


def pagerduty_list_incidents_by_date_range(
    since: str,
    until: str,
    service_ids: list[str] | None = None,
    statuses: list[str] | None = None,
    max_results: int = 500,
) -> dict[str, Any]:
    """
    List PagerDuty incidents within a date range with pagination.

    Essential for alert fatigue analysis - retrieves historical incident data
    for computing metrics like fire frequency, ack rate, MTTA, MTTR.

    Args:
        since: Start date in ISO format (e.g., "2024-01-01T00:00:00Z")
        until: End date in ISO format (e.g., "2024-01-31T23:59:59Z")
        service_ids: Optional list of service IDs to filter
        statuses: Optional list of statuses (triggered, acknowledged, resolved)
        max_results: Maximum incidents to return (default 500, supports pagination)

    Returns:
        Dict with incidents list and summary statistics
    """
    try:
        from datetime import datetime

        import requests

        api_key = _get_pagerduty_client()

        headers = {
            "Authorization": f"Token token={api_key}",
            "Accept": "application/vnd.pagerduty+json;version=2",
            "Content-Type": "application/json",
        }

        all_incidents = []
        offset = 0
        limit = min(100, max_results)  # PagerDuty max per request

        while len(all_incidents) < max_results:
            params = {
                "since": since,
                "until": until,
                "limit": limit,
                "offset": offset,
                "total": "true",
            }

            if service_ids:
                params["service_ids[]"] = service_ids
            if statuses:
                params["statuses[]"] = statuses

            response = requests.get(
                "https://api.pagerduty.com/incidents", headers=headers, params=params
            )
            response.raise_for_status()

            data = response.json()
            incidents = data.get("incidents", [])

            if not incidents:
                break

            for incident in incidents:
                # Calculate time to acknowledge
                created_at = datetime.fromisoformat(
                    incident["created_at"].replace("Z", "+00:00")
                )

                ack_at = None
                mtta_minutes = None
                for ack in incident.get("acknowledgements", []):
                    ack_at = datetime.fromisoformat(ack["at"].replace("Z", "+00:00"))
                    mtta_minutes = (ack_at - created_at).total_seconds() / 60
                    break  # First acknowledgment

                # Calculate time to resolve
                mttr_minutes = None
                if incident["status"] == "resolved":
                    resolved_at = datetime.fromisoformat(
                        incident["last_status_change_at"].replace("Z", "+00:00")
                    )
                    mttr_minutes = (resolved_at - created_at).total_seconds() / 60

                all_incidents.append(
                    {
                        "id": incident["id"],
                        "incident_number": incident.get("incident_number"),
                        "title": incident["title"],
                        "status": incident["status"],
                        "urgency": incident["urgency"],
                        "created_at": incident["created_at"],
                        "service_id": incident["service"]["id"],
                        "service_name": incident["service"]["summary"],
                        "escalation_policy_id": incident.get(
                            "escalation_policy", {}
                        ).get("id"),
                        "acknowledged": len(incident.get("acknowledgements", [])) > 0,
                        "mtta_minutes": (
                            round(mtta_minutes, 2) if mtta_minutes else None
                        ),
                        "mttr_minutes": (
                            round(mttr_minutes, 2) if mttr_minutes else None
                        ),
                        "was_escalated": incident.get("last_status_change_by", {}).get(
                            "type"
                        )
                        == "escalation_policy_reference",
                        "url": incident["html_url"],
                    }
                )

            offset += limit
            if len(incidents) < limit:
                break

        # Compute summary statistics
        total_incidents = len(all_incidents)
        acknowledged_count = sum(1 for i in all_incidents if i["acknowledged"])
        escalated_count = sum(1 for i in all_incidents if i["was_escalated"])

        mtta_values = [i["mtta_minutes"] for i in all_incidents if i["mtta_minutes"]]
        mttr_values = [i["mttr_minutes"] for i in all_incidents if i["mttr_minutes"]]

        # Group by service
        by_service = {}
        for incident in all_incidents:
            svc = incident["service_name"]
            if svc not in by_service:
                by_service[svc] = {"count": 0, "service_id": incident["service_id"]}
            by_service[svc]["count"] += 1

        # Group by alert title (to find noisy alerts)
        by_title = {}
        for incident in all_incidents:
            title = incident["title"]
            if title not in by_title:
                by_title[title] = 0
            by_title[title] += 1

        # Sort by frequency
        top_alerts = sorted(by_title.items(), key=lambda x: x[1], reverse=True)[:20]

        logger.info(
            "pagerduty_incidents_by_date_range_fetched",
            count=total_incidents,
            since=since,
            until=until,
        )

        return {
            "success": True,
            "period": {"since": since, "until": until},
            "total_incidents": total_incidents,
            "summary": {
                "acknowledged_count": acknowledged_count,
                "acknowledged_rate": (
                    round(acknowledged_count / total_incidents * 100, 1)
                    if total_incidents > 0
                    else 0
                ),
                "escalated_count": escalated_count,
                "escalated_rate": (
                    round(escalated_count / total_incidents * 100, 1)
                    if total_incidents > 0
                    else 0
                ),
                "avg_mtta_minutes": (
                    round(sum(mtta_values) / len(mtta_values), 2)
                    if mtta_values
                    else None
                ),
                "avg_mttr_minutes": (
                    round(sum(mttr_values) / len(mttr_values), 2)
                    if mttr_values
                    else None
                ),
            },
            "by_service": dict(
                sorted(by_service.items(), key=lambda x: x[1]["count"], reverse=True)
            ),
            "top_alerts": top_alerts,
            "incidents": all_incidents,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "pagerduty_list_incidents_by_date_range", "pagerduty"
        )
    except Exception as e:
        logger.error(
            "pagerduty_list_incidents_by_date_range_failed",
            error=str(e),
            since=since,
            until=until,
        )
        raise ToolExecutionError("pagerduty_list_incidents_by_date_range", str(e), e)


def pagerduty_list_services() -> list[dict[str, Any]]:
    """
    List all PagerDuty services.

    Returns all services configured in PagerDuty, useful for understanding
    the service landscape and filtering incident queries.

    Returns:
        List of services with their IDs, names, and escalation policies
    """
    try:
        import requests

        api_key = _get_pagerduty_client()

        headers = {
            "Authorization": f"Token token={api_key}",
            "Accept": "application/vnd.pagerduty+json;version=2",
            "Content-Type": "application/json",
        }

        all_services = []
        offset = 0
        limit = 100

        while True:
            params = {"limit": limit, "offset": offset}

            response = requests.get(
                "https://api.pagerduty.com/services", headers=headers, params=params
            )
            response.raise_for_status()

            data = response.json()
            services = data.get("services", [])

            if not services:
                break

            for service in services:
                all_services.append(
                    {
                        "id": service["id"],
                        "name": service["name"],
                        "description": service.get("description"),
                        "status": service.get("status"),
                        "escalation_policy": {
                            "id": service.get("escalation_policy", {}).get("id"),
                            "name": service.get("escalation_policy", {}).get("summary"),
                        },
                        "created_at": service.get("created_at"),
                        "teams": [
                            {"id": t["id"], "name": t["summary"]}
                            for t in service.get("teams", [])
                        ],
                        "url": service.get("html_url"),
                    }
                )

            offset += limit
            if len(services) < limit:
                break

        logger.info("pagerduty_services_listed", count=len(all_services))

        return all_services

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "pagerduty_list_services", "pagerduty"
        )
    except Exception as e:
        logger.error("pagerduty_list_services_failed", error=str(e))
        raise ToolExecutionError("pagerduty_list_services", str(e), e)


def pagerduty_get_on_call(
    escalation_policy_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Get current on-call users.

    Returns who is currently on-call, optionally filtered by escalation policy.

    Args:
        escalation_policy_ids: Optional list of escalation policy IDs to filter

    Returns:
        List of on-call entries with user, schedule, and escalation level
    """
    try:
        import requests

        api_key = _get_pagerduty_client()

        headers = {
            "Authorization": f"Token token={api_key}",
            "Accept": "application/vnd.pagerduty+json;version=2",
            "Content-Type": "application/json",
        }

        params = {"limit": 100}

        if escalation_policy_ids:
            params["escalation_policy_ids[]"] = escalation_policy_ids

        response = requests.get(
            "https://api.pagerduty.com/oncalls", headers=headers, params=params
        )
        response.raise_for_status()

        oncalls = response.json().get("oncalls", [])

        result = []
        for oncall in oncalls:
            result.append(
                {
                    "user": {
                        "id": oncall.get("user", {}).get("id"),
                        "name": oncall.get("user", {}).get("summary"),
                        "email": oncall.get("user", {}).get("email"),
                    },
                    "schedule": {
                        "id": oncall.get("schedule", {}).get("id"),
                        "name": oncall.get("schedule", {}).get("summary"),
                    },
                    "escalation_policy": {
                        "id": oncall.get("escalation_policy", {}).get("id"),
                        "name": oncall.get("escalation_policy", {}).get("summary"),
                    },
                    "escalation_level": oncall.get("escalation_level"),
                    "start": oncall.get("start"),
                    "end": oncall.get("end"),
                }
            )

        logger.info("pagerduty_oncall_fetched", count=len(result))

        return result

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "pagerduty_get_on_call", "pagerduty"
        )
    except Exception as e:
        logger.error("pagerduty_get_on_call_failed", error=str(e))
        raise ToolExecutionError("pagerduty_get_on_call", str(e), e)


def pagerduty_get_alert_analytics(
    since: str,
    until: str,
    service_id: str | None = None,
) -> dict[str, Any]:
    """
    Get detailed analytics for alerts over a time period.

    Computes comprehensive metrics for alert fatigue analysis:
    - Fire frequency per alert
    - Acknowledgment rates
    - MTTA/MTTR statistics
    - Time-of-day distribution
    - Repeat/flapping detection

    Args:
        since: Start date in ISO format
        until: End date in ISO format
        service_id: Optional service ID to filter

    Returns:
        Dict with detailed analytics per alert and overall summary
    """
    try:
        from collections import defaultdict
        from datetime import datetime

        # First, get all incidents in the range
        incidents_data = pagerduty_list_incidents_by_date_range(
            since=since,
            until=until,
            service_ids=[service_id] if service_id else None,
            max_results=1000,
        )

        if not incidents_data.get("success"):
            return incidents_data

        incidents = incidents_data.get("incidents", [])

        # Analyze per alert (by title)
        alert_stats = defaultdict(
            lambda: {
                "fire_count": 0,
                "acknowledged_count": 0,
                "resolved_count": 0,
                "escalated_count": 0,
                "mtta_values": [],
                "mttr_values": [],
                "hours_distribution": defaultdict(int),
                "days_distribution": defaultdict(int),
                "services": set(),
                "incidents": [],
            }
        )

        for incident in incidents:
            title = incident["title"]
            stats = alert_stats[title]

            stats["fire_count"] += 1
            stats["services"].add(incident["service_name"])
            stats["incidents"].append(incident["id"])

            if incident["acknowledged"]:
                stats["acknowledged_count"] += 1
            if incident["status"] == "resolved":
                stats["resolved_count"] += 1
            if incident.get("was_escalated"):
                stats["escalated_count"] += 1

            if incident["mtta_minutes"]:
                stats["mtta_values"].append(incident["mtta_minutes"])
            if incident["mttr_minutes"]:
                stats["mttr_values"].append(incident["mttr_minutes"])

            # Time distribution
            created = datetime.fromisoformat(
                incident["created_at"].replace("Z", "+00:00")
            )
            stats["hours_distribution"][created.hour] += 1
            stats["days_distribution"][created.strftime("%A")] += 1

        # Compute final metrics per alert
        alert_analytics = []
        for title, stats in alert_stats.items():
            fire_count = stats["fire_count"]
            ack_count = stats["acknowledged_count"]
            mtta_vals = stats["mtta_values"]
            mttr_vals = stats["mttr_values"]

            # Calculate metrics
            ack_rate = round(ack_count / fire_count * 100, 1) if fire_count > 0 else 0
            avg_mtta = round(sum(mtta_vals) / len(mtta_vals), 2) if mtta_vals else None
            avg_mttr = round(sum(mttr_vals) / len(mttr_vals), 2) if mttr_vals else None

            # Determine if this is likely noise
            is_noisy = fire_count > 10 and ack_rate < 50
            is_flapping = (
                fire_count > 20 and avg_mttr and avg_mttr < 10
            )  # Quick auto-resolve

            # Find peak hours
            hours_dist = dict(stats["hours_distribution"])
            peak_hour = max(hours_dist, key=hours_dist.get) if hours_dist else None
            off_hours_count = sum(
                hours_dist.get(h, 0) for h in [0, 1, 2, 3, 4, 5, 22, 23]
            )
            off_hours_rate = (
                round(off_hours_count / fire_count * 100, 1) if fire_count > 0 else 0
            )

            alert_analytics.append(
                {
                    "alert_title": title,
                    "fire_count": fire_count,
                    "acknowledged_count": ack_count,
                    "acknowledgment_rate": ack_rate,
                    "escalated_count": stats["escalated_count"],
                    "escalation_rate": (
                        round(stats["escalated_count"] / fire_count * 100, 1)
                        if fire_count > 0
                        else 0
                    ),
                    "avg_mtta_minutes": avg_mtta,
                    "avg_mttr_minutes": avg_mttr,
                    "services": list(stats["services"]),
                    "peak_hour": peak_hour,
                    "off_hours_rate": off_hours_rate,
                    "classification": {
                        "is_noisy": is_noisy,
                        "is_flapping": is_flapping,
                        "reason": (
                            "High frequency, low ack rate"
                            if is_noisy
                            else ("Quick auto-resolve pattern" if is_flapping else None)
                        ),
                    },
                }
            )

        # Sort by fire count (noisiest first)
        alert_analytics.sort(key=lambda x: x["fire_count"], reverse=True)

        # Overall summary
        total_alerts = len(alert_analytics)
        noisy_alerts = sum(
            1 for a in alert_analytics if a["classification"]["is_noisy"]
        )
        flapping_alerts = sum(
            1 for a in alert_analytics if a["classification"]["is_flapping"]
        )

        logger.info(
            "pagerduty_alert_analytics_computed",
            total_alerts=total_alerts,
            noisy_alerts=noisy_alerts,
        )

        return {
            "success": True,
            "period": {"since": since, "until": until},
            "service_id": service_id,
            "summary": {
                "total_unique_alerts": total_alerts,
                "total_incidents": len(incidents),
                "noisy_alerts_count": noisy_alerts,
                "flapping_alerts_count": flapping_alerts,
                "potential_noise_reduction": sum(
                    a["fire_count"]
                    for a in alert_analytics
                    if a["classification"]["is_noisy"]
                    or a["classification"]["is_flapping"]
                ),
            },
            "alert_analytics": alert_analytics[:50],  # Top 50
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "pagerduty_get_alert_analytics", "pagerduty"
        )
    except Exception as e:
        logger.error(
            "pagerduty_get_alert_analytics_failed",
            error=str(e),
            since=since,
            until=until,
        )
        raise ToolExecutionError("pagerduty_get_alert_analytics", str(e), e)


# List of all PagerDuty tools for registration
PAGERDUTY_TOOLS = [
    pagerduty_get_incident,
    pagerduty_get_incident_log_entries,
    pagerduty_list_incidents,
    pagerduty_get_escalation_policy,
    pagerduty_calculate_mttr,
    pagerduty_list_incidents_by_date_range,
    pagerduty_list_services,
    pagerduty_get_on_call,
    pagerduty_get_alert_analytics,
]

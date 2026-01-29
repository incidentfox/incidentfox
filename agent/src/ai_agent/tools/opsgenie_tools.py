"""Opsgenie integration tools for alert and incident management."""

import os
from typing import Any

from ..core.config_required import handle_integration_not_configured
from ..core.errors import ToolExecutionError
from ..core.execution_context import get_execution_context
from ..core.integration_errors import IntegrationNotConfiguredError
from ..core.logging import get_logger

logger = get_logger(__name__)


def _get_opsgenie_config() -> dict:
    """Get Opsgenie configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("opsgenie")
        if config and config.get("api_key"):
            return config

    # 2. Try environment variables (dev/testing fallback)
    if os.getenv("OPSGENIE_API_KEY"):
        return {
            "api_key": os.getenv("OPSGENIE_API_KEY"),
            "api_url": os.getenv("OPSGENIE_API_URL", "https://api.opsgenie.com"),
        }

    # 3. Not configured - raise error
    raise IntegrationNotConfiguredError(
        integration_id="opsgenie",
        tool_id="opsgenie_tools",
        missing_fields=["api_key"],
    )


def _get_opsgenie_headers() -> dict:
    """Get headers for Opsgenie API requests."""
    config = _get_opsgenie_config()
    return {
        "Authorization": f"GenieKey {config['api_key']}",
        "Content-Type": "application/json",
    }


def _get_opsgenie_base_url() -> str:
    """Get Opsgenie API base URL."""
    config = _get_opsgenie_config()
    return config.get("api_url", "https://api.opsgenie.com")


def opsgenie_list_alerts(
    status: str | None = None,
    priority: str | None = None,
    query: str | None = None,
    max_results: int = 100,
) -> dict[str, Any]:
    """
    List Opsgenie alerts with optional filters.

    Args:
        status: Filter by status (open, acked, closed)
        priority: Filter by priority (P1, P2, P3, P4, P5)
        query: Opsgenie search query
        max_results: Maximum alerts to return

    Returns:
        Dict with alerts list and summary
    """
    try:
        import requests

        headers = _get_opsgenie_headers()
        base_url = _get_opsgenie_base_url()

        # Build query string
        query_parts = []
        if status:
            query_parts.append(f"status={status}")
        if priority:
            query_parts.append(f"priority={priority}")
        if query:
            query_parts.append(query)

        params = {"limit": min(max_results, 100)}
        if query_parts:
            params["query"] = " AND ".join(query_parts)

        all_alerts = []
        offset = 0

        while len(all_alerts) < max_results:
            params["offset"] = offset

            response = requests.get(
                f"{base_url}/v2/alerts",
                headers=headers,
                params=params,
            )
            response.raise_for_status()

            data = response.json()
            alerts = data.get("data", [])

            if not alerts:
                break

            for alert in alerts:
                all_alerts.append(
                    {
                        "id": alert["id"],
                        "tiny_id": alert.get("tinyId"),
                        "alias": alert.get("alias"),
                        "message": alert.get("message"),
                        "status": alert.get("status"),
                        "acknowledged": alert.get("acknowledged", False),
                        "is_seen": alert.get("isSeen", False),
                        "priority": alert.get("priority"),
                        "source": alert.get("source"),
                        "created_at": alert.get("createdAt"),
                        "updated_at": alert.get("updatedAt"),
                        "count": alert.get("count", 1),
                        "tags": alert.get("tags", []),
                        "teams": [t.get("name") for t in alert.get("teams", [])],
                        "owner": alert.get("owner"),
                    }
                )

            offset += len(alerts)
            if len(alerts) < params["limit"]:
                break

        # Compute summary
        by_status = {}
        by_priority = {}
        for alert in all_alerts:
            status = alert["status"]
            by_status[status] = by_status.get(status, 0) + 1
            priority = alert["priority"]
            by_priority[priority] = by_priority.get(priority, 0) + 1

        logger.info("opsgenie_alerts_listed", count=len(all_alerts))

        return {
            "success": True,
            "total_count": len(all_alerts),
            "summary": {
                "by_status": by_status,
                "by_priority": by_priority,
            },
            "alerts": all_alerts,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "opsgenie_list_alerts", "opsgenie")
    except Exception as e:
        logger.error("opsgenie_list_alerts_failed", error=str(e))
        raise ToolExecutionError("opsgenie_list_alerts", str(e), e)


def opsgenie_get_alert(alert_id: str) -> dict[str, Any]:
    """
    Get details of a specific Opsgenie alert.

    Args:
        alert_id: Opsgenie alert ID or alias

    Returns:
        Alert details including status, responders, and notes
    """
    try:
        import requests

        headers = _get_opsgenie_headers()
        base_url = _get_opsgenie_base_url()

        response = requests.get(
            f"{base_url}/v2/alerts/{alert_id}",
            headers=headers,
            params={"identifierType": "id"},
        )
        response.raise_for_status()

        alert = response.json().get("data", {})

        logger.info("opsgenie_alert_fetched", alert_id=alert_id)

        return {
            "id": alert["id"],
            "tiny_id": alert.get("tinyId"),
            "alias": alert.get("alias"),
            "message": alert.get("message"),
            "description": alert.get("description"),
            "status": alert.get("status"),
            "acknowledged": alert.get("acknowledged", False),
            "priority": alert.get("priority"),
            "source": alert.get("source"),
            "created_at": alert.get("createdAt"),
            "updated_at": alert.get("updatedAt"),
            "acknowledged_at": alert.get("report", {}).get("ackTime"),
            "closed_at": alert.get("report", {}).get("closeTime"),
            "tags": alert.get("tags", []),
            "teams": [t.get("name") for t in alert.get("teams", [])],
            "responders": [
                {"type": r.get("type"), "name": r.get("name") or r.get("id")}
                for r in alert.get("responders", [])
            ],
            "owner": alert.get("owner"),
            "count": alert.get("count", 1),
            "details": alert.get("details", {}),
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "opsgenie_get_alert", "opsgenie")
    except Exception as e:
        logger.error("opsgenie_get_alert_failed", error=str(e), alert_id=alert_id)
        raise ToolExecutionError("opsgenie_get_alert", str(e), e)


def opsgenie_get_alert_logs(
    alert_id: str, max_results: int = 50
) -> list[dict[str, Any]]:
    """
    Get log entries for an Opsgenie alert.

    Args:
        alert_id: Opsgenie alert ID
        max_results: Maximum log entries to return

    Returns:
        List of log entries showing alert timeline
    """
    try:
        import requests

        headers = _get_opsgenie_headers()
        base_url = _get_opsgenie_base_url()

        response = requests.get(
            f"{base_url}/v2/alerts/{alert_id}/logs",
            headers=headers,
            params={"limit": max_results},
        )
        response.raise_for_status()

        logs = response.json().get("data", [])

        result = []
        for log in logs:
            result.append(
                {
                    "log": log.get("log"),
                    "type": log.get("type"),
                    "owner": log.get("owner"),
                    "created_at": log.get("createdAt"),
                    "offset": log.get("offset"),
                }
            )

        logger.info("opsgenie_alert_logs_fetched", alert_id=alert_id, count=len(result))

        return result

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "opsgenie_get_alert_logs", "opsgenie"
        )
    except Exception as e:
        logger.error("opsgenie_get_alert_logs_failed", error=str(e), alert_id=alert_id)
        raise ToolExecutionError("opsgenie_get_alert_logs", str(e), e)


def opsgenie_list_alerts_by_date_range(
    since: str,
    until: str,
    query: str | None = None,
    max_results: int = 500,
) -> dict[str, Any]:
    """
    List Opsgenie alerts within a date range.

    Essential for alert fatigue analysis - retrieves historical alert data
    for computing metrics like fire frequency, ack rate, MTTA.

    Args:
        since: Start date in ISO format (e.g., "2024-01-01T00:00:00Z")
        until: End date in ISO format (e.g., "2024-01-31T23:59:59Z")
        query: Optional Opsgenie search query
        max_results: Maximum alerts to return

    Returns:
        Dict with alerts and computed metrics
    """
    try:
        from datetime import datetime

        import requests

        headers = _get_opsgenie_headers()
        base_url = _get_opsgenie_base_url()

        # Build date query
        date_query = f"createdAt >= {since} AND createdAt <= {until}"
        if query:
            date_query = f"({date_query}) AND ({query})"

        params = {
            "query": date_query,
            "limit": 100,
            "sort": "createdAt",
            "order": "desc",
        }

        all_alerts = []
        offset = 0

        while len(all_alerts) < max_results:
            params["offset"] = offset

            response = requests.get(
                f"{base_url}/v2/alerts",
                headers=headers,
                params=params,
            )
            response.raise_for_status()

            data = response.json()
            alerts = data.get("data", [])

            if not alerts:
                break

            for alert in alerts:
                created_at = datetime.fromisoformat(
                    alert["createdAt"].replace("Z", "+00:00")
                )

                # Calculate MTTA (time to ack)
                mtta_minutes = None
                ack_time = alert.get("report", {}).get("ackTime")
                if ack_time:
                    mtta_minutes = ack_time / 1000 / 60  # Convert ms to minutes

                # Calculate MTTR (time to close)
                mttr_minutes = None
                close_time = alert.get("report", {}).get("closeTime")
                if close_time:
                    mttr_minutes = close_time / 1000 / 60

                all_alerts.append(
                    {
                        "id": alert["id"],
                        "tiny_id": alert.get("tinyId"),
                        "message": alert.get("message"),
                        "status": alert.get("status"),
                        "acknowledged": alert.get("acknowledged", False),
                        "priority": alert.get("priority"),
                        "source": alert.get("source"),
                        "created_at": alert["createdAt"],
                        "mtta_minutes": (
                            round(mtta_minutes, 2) if mtta_minutes else None
                        ),
                        "mttr_minutes": (
                            round(mttr_minutes, 2) if mttr_minutes else None
                        ),
                        "count": alert.get("count", 1),
                        "tags": alert.get("tags", []),
                        "teams": [t.get("name") for t in alert.get("teams", [])],
                    }
                )

            offset += len(alerts)
            if len(alerts) < params["limit"]:
                break

        # Compute summary statistics
        total = len(all_alerts)
        acknowledged_count = sum(1 for a in all_alerts if a["acknowledged"])
        mtta_values = [a["mtta_minutes"] for a in all_alerts if a["mtta_minutes"]]
        mttr_values = [a["mttr_minutes"] for a in all_alerts if a["mttr_minutes"]]

        # Group by message (to find noisy alerts)
        by_message = {}
        for alert in all_alerts:
            msg = alert["message"][:100]  # Truncate long messages
            by_message[msg] = by_message.get(msg, 0) + 1

        # Sort by frequency
        top_alerts = sorted(by_message.items(), key=lambda x: x[1], reverse=True)[:20]

        # Group by priority
        by_priority = {}
        for alert in all_alerts:
            priority = alert["priority"]
            by_priority[priority] = by_priority.get(priority, 0) + 1

        # Group by source
        by_source = {}
        for alert in all_alerts:
            source = alert["source"] or "Unknown"
            by_source[source] = by_source.get(source, 0) + 1

        logger.info(
            "opsgenie_alerts_by_date_range_fetched",
            count=total,
            since=since,
            until=until,
        )

        return {
            "success": True,
            "period": {"since": since, "until": until},
            "total_alerts": total,
            "summary": {
                "acknowledged_count": acknowledged_count,
                "acknowledged_rate": (
                    round(acknowledged_count / total * 100, 1) if total > 0 else 0
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
            "by_priority": by_priority,
            "by_source": dict(
                sorted(by_source.items(), key=lambda x: x[1], reverse=True)[:10]
            ),
            "top_alerts": top_alerts,
            "alerts": all_alerts,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "opsgenie_list_alerts_by_date_range", "opsgenie"
        )
    except Exception as e:
        logger.error(
            "opsgenie_list_alerts_by_date_range_failed",
            error=str(e),
            since=since,
            until=until,
        )
        raise ToolExecutionError("opsgenie_list_alerts_by_date_range", str(e), e)


def opsgenie_list_services() -> list[dict[str, Any]]:
    """
    List all Opsgenie services.

    Returns:
        List of services with their IDs, names, and team associations
    """
    try:
        import requests

        headers = _get_opsgenie_headers()
        base_url = _get_opsgenie_base_url()

        all_services = []
        offset = 0
        limit = 100

        while True:
            response = requests.get(
                f"{base_url}/v1/services",
                headers=headers,
                params={"limit": limit, "offset": offset},
            )
            response.raise_for_status()

            data = response.json()
            services = data.get("data", [])

            if not services:
                break

            for svc in services:
                all_services.append(
                    {
                        "id": svc["id"],
                        "name": svc["name"],
                        "description": svc.get("description"),
                        "team_id": svc.get("teamId"),
                        "is_external_link": svc.get("isExternalLink", False),
                    }
                )

            offset += limit
            if len(services) < limit:
                break

        logger.info("opsgenie_services_listed", count=len(all_services))

        return all_services

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "opsgenie_list_services", "opsgenie"
        )
    except Exception as e:
        logger.error("opsgenie_list_services_failed", error=str(e))
        raise ToolExecutionError("opsgenie_list_services", str(e), e)


def opsgenie_list_teams() -> list[dict[str, Any]]:
    """
    List all Opsgenie teams.

    Returns:
        List of teams with their IDs and names
    """
    try:
        import requests

        headers = _get_opsgenie_headers()
        base_url = _get_opsgenie_base_url()

        response = requests.get(
            f"{base_url}/v2/teams",
            headers=headers,
        )
        response.raise_for_status()

        teams = response.json().get("data", [])

        result = []
        for team in teams:
            result.append(
                {
                    "id": team["id"],
                    "name": team["name"],
                    "description": team.get("description"),
                }
            )

        logger.info("opsgenie_teams_listed", count=len(result))

        return result

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "opsgenie_list_teams", "opsgenie")
    except Exception as e:
        logger.error("opsgenie_list_teams_failed", error=str(e))
        raise ToolExecutionError("opsgenie_list_teams", str(e), e)


def opsgenie_get_on_call(
    schedule_id: str | None = None,
    team_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Get current on-call users.

    Args:
        schedule_id: Optional schedule ID to filter
        team_id: Optional team ID to filter

    Returns:
        List of on-call entries
    """
    try:
        import requests

        headers = _get_opsgenie_headers()
        base_url = _get_opsgenie_base_url()

        # Get on-calls - different endpoints for schedule vs team
        if schedule_id:
            response = requests.get(
                f"{base_url}/v2/schedules/{schedule_id}/on-calls",
                headers=headers,
            )
        elif team_id:
            response = requests.get(
                f"{base_url}/v2/teams/{team_id}/on-calls",
                headers=headers,
            )
        else:
            # Get all schedules and their on-calls
            response = requests.get(
                f"{base_url}/v2/schedules",
                headers=headers,
            )
            response.raise_for_status()
            schedules = response.json().get("data", [])

            result = []
            for schedule in schedules:
                oncall_response = requests.get(
                    f"{base_url}/v2/schedules/{schedule['id']}/on-calls",
                    headers=headers,
                )
                if oncall_response.status_code == 200:
                    oncall_data = oncall_response.json().get("data", {})
                    participants = oncall_data.get("onCallParticipants", [])
                    for participant in participants:
                        result.append(
                            {
                                "schedule_id": schedule["id"],
                                "schedule_name": schedule["name"],
                                "user": participant.get("name"),
                                "type": participant.get("type"),
                            }
                        )

            logger.info("opsgenie_oncall_fetched", count=len(result))
            return result

        response.raise_for_status()
        oncall_data = response.json().get("data", {})

        result = []
        participants = oncall_data.get("onCallParticipants", [])
        for participant in participants:
            result.append(
                {
                    "user": participant.get("name"),
                    "type": participant.get("type"),
                    "escalation_time": participant.get("escalationTime"),
                    "notify_type": participant.get("notifyType"),
                }
            )

        logger.info("opsgenie_oncall_fetched", count=len(result))

        return result

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "opsgenie_get_on_call", "opsgenie")
    except Exception as e:
        logger.error("opsgenie_get_on_call_failed", error=str(e))
        raise ToolExecutionError("opsgenie_get_on_call", str(e), e)


def opsgenie_get_alert_analytics(
    since: str,
    until: str,
    team_id: str | None = None,
) -> dict[str, Any]:
    """
    Get detailed analytics for alerts over a time period.

    Computes comprehensive metrics for alert fatigue analysis:
    - Fire frequency per alert type
    - Acknowledgment rates
    - MTTA/MTTR statistics
    - Time-of-day distribution
    - Noisy alert detection

    Args:
        since: Start date in ISO format
        until: End date in ISO format
        team_id: Optional team ID to filter

    Returns:
        Dict with detailed analytics per alert and overall summary
    """
    try:
        from collections import defaultdict
        from datetime import datetime

        # Build query for team if specified
        query = f"responders:{team_id}" if team_id else None

        # Get all alerts in the range
        alerts_data = opsgenie_list_alerts_by_date_range(
            since=since,
            until=until,
            query=query,
            max_results=1000,
        )

        if not alerts_data.get("success"):
            return alerts_data

        alerts = alerts_data.get("alerts", [])

        # Analyze per alert message
        alert_stats = defaultdict(
            lambda: {
                "fire_count": 0,
                "acknowledged_count": 0,
                "mtta_values": [],
                "mttr_values": [],
                "hours_distribution": defaultdict(int),
                "priorities": defaultdict(int),
                "sources": set(),
            }
        )

        for alert in alerts:
            msg = alert["message"][:100]  # Truncate for grouping
            stats = alert_stats[msg]

            stats["fire_count"] += alert.get("count", 1)
            stats["sources"].add(alert.get("source") or "Unknown")
            stats["priorities"][alert["priority"]] += 1

            if alert["acknowledged"]:
                stats["acknowledged_count"] += 1

            if alert["mtta_minutes"]:
                stats["mtta_values"].append(alert["mtta_minutes"])
            if alert["mttr_minutes"]:
                stats["mttr_values"].append(alert["mttr_minutes"])

            # Time distribution
            created = datetime.fromisoformat(alert["created_at"].replace("Z", "+00:00"))
            stats["hours_distribution"][created.hour] += 1

        # Compute final metrics per alert
        alert_analytics = []
        for msg, stats in alert_stats.items():
            fire_count = stats["fire_count"]
            ack_count = stats["acknowledged_count"]
            mtta_vals = stats["mtta_values"]
            mttr_vals = stats["mttr_values"]

            ack_rate = round(ack_count / fire_count * 100, 1) if fire_count > 0 else 0
            avg_mtta = round(sum(mtta_vals) / len(mtta_vals), 2) if mtta_vals else None
            avg_mttr = round(sum(mttr_vals) / len(mttr_vals), 2) if mttr_vals else None

            # Determine if noisy
            is_noisy = fire_count > 10 and ack_rate < 50
            is_flapping = fire_count > 20 and avg_mttr and avg_mttr < 10

            # Off-hours rate
            hours_dist = dict(stats["hours_distribution"])
            off_hours_count = sum(
                hours_dist.get(h, 0) for h in [0, 1, 2, 3, 4, 5, 22, 23]
            )
            off_hours_rate = (
                round(off_hours_count / fire_count * 100, 1) if fire_count > 0 else 0
            )

            # Peak hour
            peak_hour = max(hours_dist, key=hours_dist.get) if hours_dist else None

            alert_analytics.append(
                {
                    "alert_message": msg,
                    "fire_count": fire_count,
                    "acknowledged_count": ack_count,
                    "acknowledgment_rate": ack_rate,
                    "avg_mtta_minutes": avg_mtta,
                    "avg_mttr_minutes": avg_mttr,
                    "sources": list(stats["sources"]),
                    "priority_distribution": dict(stats["priorities"]),
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

        # Sort by fire count
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
            "opsgenie_alert_analytics_computed",
            total_alerts=total_alerts,
            noisy_alerts=noisy_alerts,
        )

        return {
            "success": True,
            "period": {"since": since, "until": until},
            "team_id": team_id,
            "summary": {
                "total_unique_alerts": total_alerts,
                "total_alert_fires": len(alerts),
                "noisy_alerts_count": noisy_alerts,
                "flapping_alerts_count": flapping_alerts,
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
            e, "opsgenie_get_alert_analytics", "opsgenie"
        )
    except Exception as e:
        logger.error(
            "opsgenie_get_alert_analytics_failed",
            error=str(e),
            since=since,
            until=until,
        )
        raise ToolExecutionError("opsgenie_get_alert_analytics", str(e), e)


def opsgenie_calculate_mttr(
    team_id: str | None = None,
    priority: str | None = None,
    days: int = 30,
) -> dict[str, Any]:
    """
    Calculate Mean Time To Resolve (MTTR) for Opsgenie alerts.

    Args:
        team_id: Optional team ID to filter
        priority: Optional priority filter (P1-P5)
        days: Number of days to analyze (default 30)

    Returns:
        MTTR statistics including average, median, and percentiles
    """
    try:
        from datetime import datetime, timedelta, timezone

        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        until = datetime.now(timezone.utc).isoformat()

        # Build query
        query_parts = ["status=closed"]
        if team_id:
            query_parts.append(f"responders:{team_id}")
        if priority:
            query_parts.append(f"priority={priority}")

        alerts_data = opsgenie_list_alerts_by_date_range(
            since=since,
            until=until,
            query=" AND ".join(query_parts),
            max_results=500,
        )

        if not alerts_data.get("success"):
            return alerts_data

        alerts = alerts_data.get("alerts", [])
        mttr_values = [a["mttr_minutes"] for a in alerts if a["mttr_minutes"]]

        if not mttr_values:
            return {
                "team_id": team_id,
                "priority": priority,
                "period_days": days,
                "alert_count": 0,
                "mttr_minutes": 0,
                "message": "No closed alerts in this period",
            }

        mttr_values.sort()
        count = len(mttr_values)
        avg_mttr = sum(mttr_values) / count
        median_mttr = mttr_values[count // 2]
        p95_mttr = mttr_values[int(count * 0.95)] if count > 0 else 0

        logger.info("opsgenie_mttr_calculated", alerts=count, mttr=avg_mttr)

        return {
            "team_id": team_id,
            "priority": priority,
            "period_days": days,
            "alert_count": count,
            "mttr_minutes": round(avg_mttr, 2),
            "mttr_hours": round(avg_mttr / 60, 2),
            "median_minutes": round(median_mttr, 2),
            "p95_minutes": round(p95_mttr, 2),
            "fastest_resolution_minutes": round(min(mttr_values), 2),
            "slowest_resolution_minutes": round(max(mttr_values), 2),
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "opsgenie_calculate_mttr", "opsgenie"
        )
    except Exception as e:
        logger.error("opsgenie_mttr_failed", error=str(e), team_id=team_id)
        raise ToolExecutionError("opsgenie_calculate_mttr", str(e), e)


# List of all Opsgenie tools for registration
OPSGENIE_TOOLS = [
    opsgenie_list_alerts,
    opsgenie_get_alert,
    opsgenie_get_alert_logs,
    opsgenie_list_alerts_by_date_range,
    opsgenie_list_services,
    opsgenie_list_teams,
    opsgenie_get_on_call,
    opsgenie_get_alert_analytics,
    opsgenie_calculate_mttr,
]

"""PagerDuty integration tools for incident management.

Provides tools for:
- Getting incident details and timeline
- Listing incidents with filters
- Understanding escalation policies
- Calculating incident metrics (MTTR)

Essential for incident lifecycle management.
"""

import json
from datetime import datetime, timedelta

from mcp.server.fastmcp import FastMCP

from ..utils.config import get_env


class PagerDutyConfigError(Exception):
    """Raised when PagerDuty is not configured."""

    def __init__(self, message: str):
        super().__init__(message)


def _get_pagerduty_config():
    """Get PagerDuty configuration from environment or config file."""
    api_key = get_env("PAGERDUTY_API_KEY")

    if not api_key:
        raise PagerDutyConfigError(
            "PagerDuty not configured. Missing: PAGERDUTY_API_KEY. "
            "Use save_credential tool to set it, or export as environment variable."
        )

    return {"api_key": api_key}


def _get_pagerduty_headers():
    """Get PagerDuty API headers."""
    config = _get_pagerduty_config()
    return {
        "Authorization": f"Token token={config['api_key']}",
        "Accept": "application/vnd.pagerduty+json;version=2",
        "Content-Type": "application/json",
    }


def register_tools(mcp: FastMCP):
    """Register PagerDuty tools with the MCP server."""

    @mcp.tool()
    def pagerduty_get_incident(incident_id: str) -> str:
        """Get details of a specific PagerDuty incident.

        Args:
            incident_id: PagerDuty incident ID

        Returns:
            JSON with incident details including status, service, and assignments
        """
        try:
            import requests

            headers = _get_pagerduty_headers()

            response = requests.get(
                f"https://api.pagerduty.com/incidents/{incident_id}",
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()

            incident = response.json()["incident"]

            return json.dumps(
                {
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
                        {
                            "assignee": assignment["assignee"]["summary"],
                            "at": assignment["at"],
                        }
                        for assignment in incident.get("assignments", [])
                    ],
                    "acknowledgements": [
                        {
                            "acknowledger": ack["acknowledger"]["summary"],
                            "at": ack["at"],
                        }
                        for ack in incident.get("acknowledgements", [])
                    ],
                    "url": incident["html_url"],
                },
                indent=2,
            )

        except PagerDutyConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "incident_id": incident_id})

    @mcp.tool()
    def pagerduty_get_incident_log_entries(
        incident_id: str, max_results: int = 100
    ) -> str:
        """Get log entries (timeline) for a PagerDuty incident.

        Shows the full incident timeline including notifications,
        acknowledgements, and escalations.

        Args:
            incident_id: PagerDuty incident ID
            max_results: Maximum log entries to return (default: 100)

        Returns:
            JSON with list of log entries showing incident timeline
        """
        try:
            import requests

            headers = _get_pagerduty_headers()

            response = requests.get(
                f"https://api.pagerduty.com/incidents/{incident_id}/log_entries",
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
                    "incident_id": incident_id,
                    "entry_count": len(entries),
                    "log_entries": entries,
                },
                indent=2,
            )

        except PagerDutyConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "incident_id": incident_id})

    @mcp.tool()
    def pagerduty_list_incidents(
        status: str | None = None,
        urgency: str | None = None,
        service_ids: str | None = None,
        max_results: int = 25,
    ) -> str:
        """List PagerDuty incidents with optional filters.

        Args:
            status: Filter by status (triggered, acknowledged, resolved)
            urgency: Filter by urgency (high, low)
            service_ids: Comma-separated service IDs to filter by
            max_results: Maximum incidents to return (default: 25)

        Returns:
            JSON with list of incidents
        """
        try:
            import requests

            headers = _get_pagerduty_headers()

            params = {"limit": max_results}
            if status:
                params["statuses[]"] = status
            if urgency:
                params["urgencies[]"] = urgency
            if service_ids:
                params["service_ids[]"] = service_ids.split(",")

            response = requests.get(
                "https://api.pagerduty.com/incidents",
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
                {"incident_count": len(incident_list), "incidents": incident_list},
                indent=2,
            )

        except PagerDutyConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def pagerduty_get_escalation_policy(policy_id: str) -> str:
        """Get details of a PagerDuty escalation policy.

        Shows who gets notified and in what order.

        Args:
            policy_id: Escalation policy ID

        Returns:
            JSON with escalation policy details including rules and targets
        """
        try:
            import requests

            headers = _get_pagerduty_headers()

            response = requests.get(
                f"https://api.pagerduty.com/escalation_policies/{policy_id}",
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()

            policy = response.json()["escalation_policy"]

            return json.dumps(
                {
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
                },
                indent=2,
            )

        except PagerDutyConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "policy_id": policy_id})

    @mcp.tool()
    def pagerduty_calculate_mttr(service_id: str | None = None, days: int = 30) -> str:
        """Calculate Mean Time To Resolve (MTTR) for PagerDuty incidents.

        Provides incident resolution metrics over a time period.

        Args:
            service_id: Optional service ID to filter by
            days: Number of days to analyze (default: 30)

        Returns:
            JSON with MTTR statistics including average, median, and percentiles
        """
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
                "https://api.pagerduty.com/incidents",
                headers=headers,
                params=params,
                timeout=30,
            )
            response.raise_for_status()

            incidents = response.json()["incidents"]

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
                        "service_id": service_id,
                        "period_days": days,
                        "incident_count": 0,
                        "mttr_minutes": 0,
                        "message": "No resolved incidents in this period",
                    },
                    indent=2,
                )

            resolution_times.sort()
            count = len(resolution_times)
            avg_mttr = sum(resolution_times) / count
            median_mttr = resolution_times[count // 2]
            p95_mttr = resolution_times[int(count * 0.95)] if count > 0 else 0

            return json.dumps(
                {
                    "service_id": service_id,
                    "period_days": days,
                    "incident_count": count,
                    "mttr_minutes": round(avg_mttr, 2),
                    "mttr_hours": round(avg_mttr / 60, 2),
                    "median_minutes": round(median_mttr, 2),
                    "p95_minutes": round(p95_mttr, 2),
                    "fastest_resolution_minutes": round(min(resolution_times), 2),
                    "slowest_resolution_minutes": round(max(resolution_times), 2),
                },
                indent=2,
            )

        except PagerDutyConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "service_id": service_id})

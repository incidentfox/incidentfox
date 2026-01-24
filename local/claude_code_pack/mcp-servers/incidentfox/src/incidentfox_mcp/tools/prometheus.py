"""Prometheus and Alertmanager tools.

Tools for querying Prometheus metrics and Alertmanager alerts.
Many open-source users run Prometheus instead of commercial solutions.
"""

import json
from datetime import datetime, timedelta

import httpx
from mcp.server.fastmcp import FastMCP

from ..utils.config import get_env


def _get_prometheus_url() -> str | None:
    """Get Prometheus URL from environment or config file."""
    return get_env("PROMETHEUS_URL") or get_env("PROM_URL")


def _get_alertmanager_url() -> str | None:
    """Get Alertmanager URL from environment or config file."""
    return get_env("ALERTMANAGER_URL") or get_env("AM_URL")


def register_tools(mcp: FastMCP):
    """Register Prometheus and Alertmanager tools."""

    @mcp.tool()
    def query_prometheus(
        query: str,
        hours_ago: int = 1,
        step: str = "1m",
    ) -> str:
        """Execute a PromQL query against Prometheus.

        Args:
            query: PromQL query (e.g., "rate(http_requests_total[5m])")
            hours_ago: How far back to query (default: 1 hour)
            step: Query resolution (default: "1m")

        Returns:
            JSON with metric values over time.

        Example queries:
            - CPU usage: "100 - (avg by(instance) (rate(node_cpu_seconds_total{mode='idle'}[5m])) * 100)"
            - Memory: "node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes * 100"
            - HTTP rate: "sum(rate(http_requests_total[5m])) by (service)"
            - Error rate: "sum(rate(http_requests_total{status=~'5..'}[5m])) / sum(rate(http_requests_total[5m]))"
        """
        prom_url = _get_prometheus_url()
        if not prom_url:
            return json.dumps(
                {
                    "error": "Prometheus not configured",
                    "hint": "Set PROMETHEUS_URL environment variable",
                }
            )

        try:
            now = datetime.utcnow()
            start = now - timedelta(hours=hours_ago)

            params = {
                "query": query,
                "start": start.isoformat() + "Z",
                "end": now.isoformat() + "Z",
                "step": step,
            }

            with httpx.Client(timeout=30.0) as client:
                response = client.get(
                    f"{prom_url}/api/v1/query_range",
                    params=params,
                )
                response.raise_for_status()
                data = response.json()

            if data.get("status") != "success":
                return json.dumps(
                    {
                        "error": data.get("error", "Query failed"),
                        "errorType": data.get("errorType"),
                    }
                )

            result_type = data.get("data", {}).get("resultType")
            results = data.get("data", {}).get("result", [])

            # Format results
            formatted = []
            for series in results:
                metric = series.get("metric", {})
                values = series.get("values", [])

                # Get latest value for summary
                latest = values[-1] if values else None

                formatted.append(
                    {
                        "metric": metric,
                        "latest_value": float(latest[1]) if latest else None,
                        "latest_time": (
                            datetime.fromtimestamp(float(latest[0])).isoformat()
                            if latest
                            else None
                        ),
                        "sample_count": len(values),
                        "values": (
                            values[-10:] if len(values) > 10 else values
                        ),  # Last 10 for context
                    }
                )

            return json.dumps(
                {
                    "query": query,
                    "result_type": result_type,
                    "series_count": len(formatted),
                    "time_range": f"last {hours_ago} hour(s)",
                    "results": formatted,
                },
                indent=2,
            )

        except httpx.HTTPError as e:
            return json.dumps({"error": f"HTTP error: {e}"})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def prometheus_instant_query(query: str) -> str:
        """Execute an instant PromQL query (current value only).

        Args:
            query: PromQL query

        Returns:
            JSON with current metric values.
        """
        prom_url = _get_prometheus_url()
        if not prom_url:
            return json.dumps(
                {
                    "error": "Prometheus not configured",
                    "hint": "Set PROMETHEUS_URL environment variable",
                }
            )

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(
                    f"{prom_url}/api/v1/query",
                    params={"query": query},
                )
                response.raise_for_status()
                data = response.json()

            if data.get("status") != "success":
                return json.dumps(
                    {
                        "error": data.get("error", "Query failed"),
                    }
                )

            results = data.get("data", {}).get("result", [])

            formatted = []
            for item in results:
                metric = item.get("metric", {})
                value = item.get("value", [])

                formatted.append(
                    {
                        "metric": metric,
                        "value": float(value[1]) if len(value) > 1 else None,
                        "timestamp": (
                            datetime.fromtimestamp(float(value[0])).isoformat()
                            if value
                            else None
                        ),
                    }
                )

            return json.dumps(
                {
                    "query": query,
                    "result_count": len(formatted),
                    "results": formatted,
                },
                indent=2,
            )

        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def get_prometheus_alerts() -> str:
        """Get currently firing alerts from Prometheus.

        Returns:
            JSON with all active (firing/pending) alerts.
        """
        prom_url = _get_prometheus_url()
        if not prom_url:
            return json.dumps(
                {
                    "error": "Prometheus not configured",
                    "hint": "Set PROMETHEUS_URL environment variable",
                }
            )

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(f"{prom_url}/api/v1/alerts")
                response.raise_for_status()
                data = response.json()

            if data.get("status") != "success":
                return json.dumps({"error": "Failed to get alerts"})

            alerts = data.get("data", {}).get("alerts", [])

            # Categorize alerts
            firing = [a for a in alerts if a.get("state") == "firing"]
            pending = [a for a in alerts if a.get("state") == "pending"]

            formatted_alerts = []
            for alert in alerts:
                formatted_alerts.append(
                    {
                        "name": alert.get("labels", {}).get("alertname"),
                        "state": alert.get("state"),
                        "severity": alert.get("labels", {}).get("severity"),
                        "labels": alert.get("labels"),
                        "annotations": alert.get("annotations"),
                        "active_at": alert.get("activeAt"),
                    }
                )

            return json.dumps(
                {
                    "firing_count": len(firing),
                    "pending_count": len(pending),
                    "total_alerts": len(alerts),
                    "alerts": formatted_alerts,
                },
                indent=2,
            )

        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def get_alertmanager_alerts() -> str:
        """Get alerts from Alertmanager.

        Returns current alerts including silenced and inhibited alerts.
        """
        am_url = _get_alertmanager_url()
        if not am_url:
            return json.dumps(
                {
                    "error": "Alertmanager not configured",
                    "hint": "Set ALERTMANAGER_URL environment variable",
                }
            )

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(f"{am_url}/api/v2/alerts")
                response.raise_for_status()
                alerts = response.json()

            # Categorize
            active = [a for a in alerts if a.get("status", {}).get("state") == "active"]
            suppressed = [
                a for a in alerts if a.get("status", {}).get("state") == "suppressed"
            ]

            formatted = []
            for alert in alerts:
                formatted.append(
                    {
                        "name": alert.get("labels", {}).get("alertname"),
                        "state": alert.get("status", {}).get("state"),
                        "severity": alert.get("labels", {}).get("severity"),
                        "labels": alert.get("labels"),
                        "annotations": alert.get("annotations"),
                        "starts_at": alert.get("startsAt"),
                        "ends_at": alert.get("endsAt"),
                        "silenced_by": alert.get("status", {}).get("silencedBy"),
                        "inhibited_by": alert.get("status", {}).get("inhibitedBy"),
                    }
                )

            return json.dumps(
                {
                    "active_count": len(active),
                    "suppressed_count": len(suppressed),
                    "total_alerts": len(alerts),
                    "alerts": formatted,
                },
                indent=2,
            )

        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def get_active_alerts(service: str | None = None) -> str:
        """Get all currently firing alerts across configured sources.

        Aggregates alerts from:
        - Prometheus (if configured)
        - Alertmanager (if configured)
        - Datadog monitors (if configured)

        Args:
            service: Optional service name to filter alerts

        Returns:
            JSON with all active alerts across sources.
        """
        results = []

        # Try Prometheus
        prom_url = _get_prometheus_url()
        if prom_url:
            try:
                with httpx.Client(timeout=30.0) as client:
                    response = client.get(f"{prom_url}/api/v1/alerts")
                    if response.status_code == 200:
                        data = response.json()
                        alerts = data.get("data", {}).get("alerts", [])
                        firing = [a for a in alerts if a.get("state") == "firing"]

                        for alert in firing:
                            labels = alert.get("labels", {})
                            if service and labels.get("service") != service:
                                continue
                            results.append(
                                {
                                    "source": "prometheus",
                                    "name": labels.get("alertname"),
                                    "severity": labels.get("severity"),
                                    "service": labels.get("service"),
                                    "description": alert.get("annotations", {}).get(
                                        "description"
                                    ),
                                    "active_at": alert.get("activeAt"),
                                }
                            )
            except Exception:
                pass

        # Try Alertmanager
        am_url = _get_alertmanager_url()
        if am_url:
            try:
                with httpx.Client(timeout=30.0) as client:
                    response = client.get(f"{am_url}/api/v2/alerts")
                    if response.status_code == 200:
                        alerts = response.json()
                        active = [
                            a
                            for a in alerts
                            if a.get("status", {}).get("state") == "active"
                        ]

                        for alert in active:
                            labels = alert.get("labels", {})
                            if service and labels.get("service") != service:
                                continue
                            results.append(
                                {
                                    "source": "alertmanager",
                                    "name": labels.get("alertname"),
                                    "severity": labels.get("severity"),
                                    "service": labels.get("service"),
                                    "description": alert.get("annotations", {}).get(
                                        "description"
                                    ),
                                    "starts_at": alert.get("startsAt"),
                                }
                            )
            except Exception:
                pass

        # Try Datadog
        dd_api_key = get_env("DATADOG_API_KEY")
        dd_app_key = get_env("DATADOG_APP_KEY")
        if dd_api_key and dd_app_key:
            try:
                from datadog_api_client import ApiClient, Configuration
                from datadog_api_client.v1.api.monitors_api import MonitorsApi

                config = Configuration()
                config.api_key["apiKeyAuth"] = dd_api_key
                config.api_key["appKeyAuth"] = dd_app_key

                with ApiClient(config) as api_client:
                    api = MonitorsApi(api_client)
                    monitors = api.list_monitors()

                    for monitor in monitors:
                        if monitor.overall_state in ("Alert", "Warn"):
                            name = monitor.name or ""
                            if service and service.lower() not in name.lower():
                                continue
                            results.append(
                                {
                                    "source": "datadog",
                                    "name": name,
                                    "severity": (
                                        "critical"
                                        if monitor.overall_state == "Alert"
                                        else "warning"
                                    ),
                                    "state": monitor.overall_state,
                                    "type": monitor.type,
                                }
                            )
            except Exception:
                pass

        # Sort by severity
        severity_order = {"critical": 0, "error": 1, "warning": 2, "info": 3}
        results.sort(key=lambda x: severity_order.get(x.get("severity", "info"), 4))

        return json.dumps(
            {
                "service_filter": service,
                "total_alerts": len(results),
                "alerts": results,
                "sources_checked": {
                    "prometheus": bool(prom_url),
                    "alertmanager": bool(am_url),
                    "datadog": bool(dd_api_key and dd_app_key),
                },
            },
            indent=2,
        )

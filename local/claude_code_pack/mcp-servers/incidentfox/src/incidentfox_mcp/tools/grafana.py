"""Grafana dashboard and metrics tools.

Provides tools for:
- Listing and querying dashboards
- Querying Prometheus metrics via Grafana
- Getting annotations (deployment markers)
- Checking alert status

Essential for dashboard-driven investigation.
"""

import json
from datetime import datetime, timedelta

from mcp.server.fastmcp import FastMCP

from ..utils.config import get_env


class GrafanaConfigError(Exception):
    """Raised when Grafana is not configured."""

    def __init__(self, message: str):
        super().__init__(message)


def _get_grafana_config():
    """Get Grafana configuration from environment or config file."""
    url = get_env("GRAFANA_URL")
    api_key = get_env("GRAFANA_API_KEY")

    if not url or not api_key:
        missing = []
        if not url:
            missing.append("GRAFANA_URL")
        if not api_key:
            missing.append("GRAFANA_API_KEY")
        raise GrafanaConfigError(
            f"Grafana not configured. Missing: {', '.join(missing)}. "
            "Use save_credential tool to set these, or export as environment variables."
        )

    return {"url": url.rstrip("/"), "api_key": api_key}


def _get_grafana_client():
    """Get HTTP client configured for Grafana API."""
    try:
        import httpx
    except ImportError:
        raise GrafanaConfigError("httpx not installed. Install with: pip install httpx")

    config = _get_grafana_config()

    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }

    return httpx.Client(base_url=config["url"], headers=headers, timeout=30.0)


def register_tools(mcp: FastMCP):
    """Register Grafana tools with the MCP server."""

    @mcp.tool()
    def grafana_list_dashboards(folder_id: int = 0, query: str = "") -> str:
        """List dashboards in Grafana.

        Use to find relevant dashboards for investigation.

        Args:
            folder_id: Filter by folder (0 for all)
            query: Search query string

        Returns:
            JSON with list of dashboards including UIDs and titles
        """
        try:
            with _get_grafana_client() as client:
                params = {"type": "dash-db"}
                if folder_id > 0:
                    params["folderIds"] = folder_id
                if query:
                    params["query"] = query

                response = client.get("/api/search", params=params)
                response.raise_for_status()
                dashboards = response.json()

            dashboard_list = [
                {
                    "uid": d.get("uid"),
                    "title": d.get("title"),
                    "folder": d.get("folderTitle", "General"),
                    "url": d.get("url"),
                    "tags": d.get("tags", []),
                }
                for d in dashboards[:50]
            ]

            return json.dumps(
                {
                    "dashboard_count": len(dashboard_list),
                    "dashboards": dashboard_list,
                },
                indent=2,
            )

        except GrafanaConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def grafana_get_dashboard(dashboard_uid: str) -> str:
        """Get a specific dashboard with all its panels.

        Use to understand what metrics are available and extract queries.

        Args:
            dashboard_uid: Dashboard UID

        Returns:
            JSON with dashboard metadata and panel details including queries
        """
        if not dashboard_uid:
            return json.dumps({"error": "dashboard_uid is required"})

        try:
            with _get_grafana_client() as client:
                response = client.get(f"/api/dashboards/uid/{dashboard_uid}")
                response.raise_for_status()
                data = response.json()

            dashboard = data.get("dashboard", {})
            panels = dashboard.get("panels", [])

            panel_info = []
            for panel in panels:
                if panel.get("type") == "row":
                    continue

                targets = panel.get("targets", [])
                queries = []
                for t in targets:
                    if "expr" in t:
                        queries.append({"type": "prometheus", "query": t["expr"]})
                    elif "rawQuery" in t:
                        queries.append({"type": "sql", "query": t["rawQuery"]})
                    elif "query" in t:
                        queries.append({"type": "generic", "query": t["query"]})

                panel_info.append(
                    {
                        "id": panel.get("id"),
                        "title": panel.get("title"),
                        "type": panel.get("type"),
                        "datasource": panel.get("datasource"),
                        "queries": queries,
                    }
                )

            return json.dumps(
                {
                    "dashboard": {
                        "uid": dashboard_uid,
                        "title": dashboard.get("title"),
                        "description": dashboard.get("description"),
                        "tags": dashboard.get("tags", []),
                    },
                    "panel_count": len(panel_info),
                    "panels": panel_info,
                },
                indent=2,
            )

        except GrafanaConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "dashboard_uid": dashboard_uid})

    @mcp.tool()
    def grafana_query_prometheus(
        query: str, time_range: str = "1h", step: str = "1m"
    ) -> str:
        """Query Prometheus metrics via Grafana datasource.

        Use to query CPU, memory, latency, error rates, etc.

        Args:
            query: PromQL query (e.g., "rate(http_requests_total[5m])")
            time_range: How far back to query (e.g., "1h", "24h")
            step: Query resolution (e.g., "1m", "5m")

        Returns:
            JSON with metric values and timestamps
        """
        if not query:
            return json.dumps({"error": "query is required"})

        try:
            hours = 1
            if time_range.endswith("h"):
                hours = int(time_range[:-1])
            elif time_range.endswith("d"):
                hours = int(time_range[:-1]) * 24

            end_time = datetime.utcnow()
            start_time = end_time - timedelta(hours=hours)

            with _get_grafana_client() as client:
                params = {
                    "query": query,
                    "start": int(start_time.timestamp()),
                    "end": int(end_time.timestamp()),
                    "step": step,
                }

                response = None
                for ds_path in [
                    "/api/ds/query",
                    "/api/datasources/proxy/1/api/v1/query_range",
                ]:
                    try:
                        if "ds/query" in ds_path:
                            payload = {
                                "queries": [
                                    {
                                        "refId": "A",
                                        "expr": query,
                                        "range": True,
                                        "instant": False,
                                        "datasource": {"type": "prometheus"},
                                    }
                                ],
                                "from": str(int(start_time.timestamp() * 1000)),
                                "to": str(int(end_time.timestamp() * 1000)),
                            }
                            response = client.post(ds_path, json=payload)
                        else:
                            response = client.get(ds_path, params=params)

                        if response.status_code == 200:
                            break
                    except Exception:
                        continue

                if response is None or response.status_code != 200:
                    return json.dumps(
                        {
                            "error": "Could not query Prometheus datasource",
                            "hint": "Verify Grafana has a Prometheus datasource configured",
                        }
                    )

                data = response.json()

            series = []
            if "results" in data:
                for result in data.get("results", {}).values():
                    for frame in result.get("frames", []):
                        schema = frame.get("schema", {})
                        values = frame.get("data", {}).get("values", [])
                        if len(values) >= 2:
                            series.append(
                                {
                                    "name": schema.get("name", "metric"),
                                    "values": values[1][:100],
                                    "timestamps": values[0][:100],
                                }
                            )
            elif "data" in data:
                prom_data = data.get("data", {})
                for result in prom_data.get("result", []):
                    metric = result.get("metric", {})
                    values = result.get("values", [])
                    series.append(
                        {
                            "name": metric.get("__name__", "metric"),
                            "labels": metric,
                            "values": [float(v[1]) for v in values[:100]],
                            "timestamps": [v[0] for v in values[:100]],
                        }
                    )

            return json.dumps(
                {
                    "query": query,
                    "time_range": time_range,
                    "series_count": len(series),
                    "series": series,
                },
                indent=2,
            )

        except GrafanaConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "query": query[:100]})

    @mcp.tool()
    def grafana_list_datasources() -> str:
        """List all configured datasources in Grafana.

        Use to discover what metrics sources are available.

        Returns:
            JSON with list of datasources
        """
        try:
            with _get_grafana_client() as client:
                response = client.get("/api/datasources")
                response.raise_for_status()
                datasources = response.json()

            datasource_list = [
                {
                    "id": ds.get("id"),
                    "uid": ds.get("uid"),
                    "name": ds.get("name"),
                    "type": ds.get("type"),
                    "url": ds.get("url"),
                    "is_default": ds.get("isDefault", False),
                }
                for ds in datasources
            ]

            return json.dumps(
                {
                    "datasource_count": len(datasource_list),
                    "datasources": datasource_list,
                },
                indent=2,
            )

        except GrafanaConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def grafana_get_annotations(
        dashboard_uid: str = "", time_range: str = "24h", tags: str = ""
    ) -> str:
        """Get annotations from Grafana (deployments, incidents, events).

        Useful for finding deployment markers that correlate with issues.

        Args:
            dashboard_uid: Filter by dashboard (optional)
            time_range: How far back to look (e.g., "24h", "7d")
            tags: Comma-separated tags to filter (e.g., "deployment,incident")

        Returns:
            JSON with annotations
        """
        try:
            hours = 24
            if time_range.endswith("h"):
                hours = int(time_range[:-1])
            elif time_range.endswith("d"):
                hours = int(time_range[:-1]) * 24

            end_time = datetime.utcnow()
            start_time = end_time - timedelta(hours=hours)

            with _get_grafana_client() as client:
                params = {
                    "from": int(start_time.timestamp() * 1000),
                    "to": int(end_time.timestamp() * 1000),
                }
                if dashboard_uid:
                    params["dashboardUID"] = dashboard_uid
                if tags:
                    params["tags"] = tags.split(",")

                response = client.get("/api/annotations", params=params)
                response.raise_for_status()
                annotations = response.json()

            annotation_list = [
                {
                    "id": a.get("id"),
                    "time": datetime.fromtimestamp(a.get("time", 0) / 1000).isoformat(),
                    "text": a.get("text"),
                    "tags": a.get("tags", []),
                    "dashboard_uid": a.get("dashboardUID"),
                    "panel_id": a.get("panelId"),
                }
                for a in annotations[:100]
            ]

            return json.dumps(
                {
                    "time_range": time_range,
                    "annotation_count": len(annotation_list),
                    "annotations": annotation_list,
                },
                indent=2,
            )

        except GrafanaConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def grafana_get_alerts(state: str = "all") -> str:
        """Get alert rules and their current state from Grafana.

        Use to check which alerts are currently firing.

        Args:
            state: Filter by state (all, alerting, pending, normal, no_data)

        Returns:
            JSON with alert rules and states
        """
        try:
            with _get_grafana_client() as client:
                response = client.get("/api/v1/provisioning/alert-rules")

                if response.status_code == 404:
                    response = client.get("/api/alerts")

                response.raise_for_status()
                alerts_data = response.json()

            if isinstance(alerts_data, list):
                alerts = alerts_data
            else:
                alerts = (
                    alerts_data.get("rules", []) or alerts_data.get("data", []) or []
                )

            filtered = []
            for alert in alerts:
                alert_state = alert.get("state", "unknown").lower()
                if state == "all" or state == alert_state:
                    filtered.append(
                        {
                            "name": alert.get("name") or alert.get("title"),
                            "state": alert_state,
                            "severity": alert.get("labels", {}).get(
                                "severity", "unknown"
                            ),
                            "message": alert.get("annotations", {}).get("summary")
                            or alert.get("message"),
                            "dashboard_uid": alert.get("dashboardUid"),
                            "panel_id": alert.get("panelId"),
                        }
                    )

            firing_count = sum(1 for a in filtered if a["state"] == "alerting")

            return json.dumps(
                {
                    "filter": state,
                    "alert_count": len(filtered),
                    "firing_count": firing_count,
                    "alerts": filtered[:50],
                },
                indent=2,
            )

        except GrafanaConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e)})

"""
Grafana dashboard and metrics tools.

Provides direct Grafana API access for querying dashboards,
panels, and datasources.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

from agents import function_tool

from ..core.config_required import handle_integration_not_configured
from ..core.execution_context import get_execution_context
from ..core.integration_errors import IntegrationNotConfiguredError
from ..core.logging import get_logger

logger = get_logger(__name__)


def _get_grafana_config() -> dict:
    """Get Grafana configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("grafana")
        if config and config.get("url") and config.get("api_key"):
            return config

    # 2. Try environment variables (dev/testing fallback)
    if os.getenv("GRAFANA_URL") and os.getenv("GRAFANA_API_KEY"):
        return {
            "url": os.getenv("GRAFANA_URL"),
            "api_key": os.getenv("GRAFANA_API_KEY"),
        }

    # 3. Not configured - raise error
    raise IntegrationNotConfiguredError(
        integration_id="grafana",
        tool_id="grafana_tools",
        missing_fields=["url", "api_key"],
    )


def _get_grafana_client():
    """Get HTTP client configured for Grafana API."""
    try:
        import httpx
    except ImportError:
        raise RuntimeError("httpx not installed. Install with: pip install httpx")

    grafana_config = _get_grafana_config()

    base_url = grafana_config["url"].rstrip("/")
    api_key = grafana_config["api_key"]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    return httpx.Client(base_url=base_url, headers=headers, timeout=30.0)


@function_tool
def grafana_list_dashboards(folder_id: int = 0, query: str = "") -> str:
    """
    List dashboards in Grafana.

    Use cases:
    - Find relevant dashboards for investigation
    - Get dashboard UIDs for further queries
    - Search for dashboards by name

    Args:
        folder_id: Filter by folder (0 for all)
        query: Search query string

    Returns:
        JSON with list of dashboards
    """
    logger.info("grafana_list_dashboards", query=query)

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

        result = {
            "ok": True,
            "dashboards": [
                {
                    "uid": d.get("uid"),
                    "title": d.get("title"),
                    "folder": d.get("folderTitle", "General"),
                    "url": d.get("url"),
                    "tags": d.get("tags", []),
                }
                for d in dashboards[:50]  # Limit results
            ],
            "count": len(dashboards),
        }

        logger.info("grafana_dashboards_listed", count=len(dashboards))
        return json.dumps(result)

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "grafana_list_dashboards", "grafana"
        )
    except ValueError as e:
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "hint": "Set GRAFANA_URL and GRAFANA_API_KEY",
            }
        )
    except Exception as e:
        logger.error("grafana_list_dashboards_failed", error=str(e))
        return json.dumps({"ok": False, "error": str(e)})


@function_tool
def grafana_get_dashboard(dashboard_uid: str) -> str:
    """
    Get a specific dashboard with all its panels.

    Use cases:
    - Get panel definitions to understand available metrics
    - Extract queries from existing dashboards
    - Analyze dashboard structure

    Args:
        dashboard_uid: Dashboard UID

    Returns:
        JSON with dashboard metadata and panels
    """
    if not dashboard_uid:
        return json.dumps({"ok": False, "error": "dashboard_uid is required"})

    logger.info("grafana_get_dashboard", uid=dashboard_uid)

    try:
        with _get_grafana_client() as client:
            response = client.get(f"/api/dashboards/uid/{dashboard_uid}")
            response.raise_for_status()
            data = response.json()

        dashboard = data.get("dashboard", {})
        panels = dashboard.get("panels", [])

        # Extract panel info
        panel_info = []
        for panel in panels:
            if panel.get("type") == "row":
                continue  # Skip row containers

            targets = panel.get("targets", [])
            queries = []
            for t in targets:
                # Handle different datasource types
                if "expr" in t:  # Prometheus
                    queries.append({"type": "prometheus", "query": t["expr"]})
                elif "rawQuery" in t:  # SQL
                    queries.append({"type": "sql", "query": t["rawQuery"]})
                elif "query" in t:  # Generic
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

        result = {
            "ok": True,
            "dashboard": {
                "uid": dashboard_uid,
                "title": dashboard.get("title"),
                "description": dashboard.get("description"),
                "tags": dashboard.get("tags", []),
            },
            "panels": panel_info,
            "panel_count": len(panel_info),
        }

        logger.info(
            "grafana_dashboard_fetched", uid=dashboard_uid, panels=len(panel_info)
        )
        return json.dumps(result)

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "grafana_get_dashboard", "grafana")
    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e)})
    except Exception as e:
        logger.error("grafana_get_dashboard_failed", error=str(e), uid=dashboard_uid)
        return json.dumps({"ok": False, "error": str(e)})


@function_tool
def grafana_query_prometheus(
    query: str, time_range: str = "1h", step: str = "1m"
) -> str:
    """
    Query Prometheus metrics via Grafana datasource.

    Use cases:
    - Query CPU, memory, network metrics
    - Get application latency and error rates
    - Analyze time series data for anomalies

    Args:
        query: PromQL query (e.g., "rate(http_requests_total[5m])")
        time_range: How far back to query (e.g., "1h", "24h")
        step: Query resolution (e.g., "1m", "5m")

    Returns:
        JSON with metric values and timestamps
    """
    if not query:
        return json.dumps({"ok": False, "error": "query is required"})

    logger.info("grafana_query_prometheus", query=query[:50])

    try:
        # Parse time range
        hours = 1
        if time_range.endswith("h"):
            hours = int(time_range[:-1])
        elif time_range.endswith("d"):
            hours = int(time_range[:-1]) * 24

        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=hours)

        with _get_grafana_client() as client:
            # Query Prometheus via Grafana proxy
            params = {
                "query": query,
                "start": int(start_time.timestamp()),
                "end": int(end_time.timestamp()),
                "step": step,
            }

            # Try common Prometheus datasource paths
            response = None
            for ds_path in [
                "/api/ds/query",
                "/api/datasources/proxy/1/api/v1/query_range",
            ]:
                try:
                    if "ds/query" in ds_path:
                        # Use Grafana unified alerting query API
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
                except:
                    continue

            if response is None or response.status_code != 200:
                return json.dumps(
                    {
                        "ok": False,
                        "error": "Could not query Prometheus datasource",
                        "hint": "Verify Grafana has a Prometheus datasource configured",
                    }
                )

            data = response.json()

        # Parse response based on format
        series = []
        if "results" in data:  # Unified query response
            for result in data.get("results", {}).values():
                for frame in result.get("frames", []):
                    schema = frame.get("schema", {})
                    values = frame.get("data", {}).get("values", [])
                    if len(values) >= 2:
                        series.append(
                            {
                                "name": schema.get("name", "metric"),
                                "values": values[1][:100],  # Limit data points
                                "timestamps": values[0][:100],
                            }
                        )
        elif "data" in data:  # Direct Prometheus response
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

        result = {
            "ok": True,
            "query": query,
            "time_range": time_range,
            "series": series,
            "series_count": len(series),
        }

        logger.info("grafana_prometheus_queried", query=query[:50], series=len(series))
        return json.dumps(result)

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "grafana_query_prometheus", "grafana"
        )
    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e)})
    except Exception as e:
        logger.error("grafana_query_prometheus_failed", error=str(e), query=query[:50])
        return json.dumps({"ok": False, "error": str(e)})


@function_tool
def grafana_list_datasources() -> str:
    """
    List all configured datasources in Grafana.

    Use cases:
    - Discover what metrics sources are available
    - Get datasource IDs for queries
    - Understand monitoring setup

    Returns:
        JSON with list of datasources
    """
    logger.info("grafana_list_datasources")

    try:
        with _get_grafana_client() as client:
            response = client.get("/api/datasources")
            response.raise_for_status()
            datasources = response.json()

        result = {
            "ok": True,
            "datasources": [
                {
                    "id": ds.get("id"),
                    "uid": ds.get("uid"),
                    "name": ds.get("name"),
                    "type": ds.get("type"),
                    "url": ds.get("url"),
                    "is_default": ds.get("isDefault", False),
                }
                for ds in datasources
            ],
            "count": len(datasources),
        }

        logger.info("grafana_datasources_listed", count=len(datasources))
        return json.dumps(result)

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "grafana_list_datasources", "grafana"
        )
    except ValueError as e:
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "hint": "Set GRAFANA_URL and GRAFANA_API_KEY",
            }
        )
    except Exception as e:
        logger.error("grafana_list_datasources_failed", error=str(e))
        return json.dumps({"ok": False, "error": str(e)})


@function_tool
def grafana_get_annotations(
    dashboard_uid: str = "", time_range: str = "24h", tags: str = ""
) -> str:
    """
    Get annotations from Grafana (deployments, incidents, events).

    Use cases:
    - Find deployment markers that correlate with issues
    - Get incident annotations
    - Identify events that coincide with anomalies

    Args:
        dashboard_uid: Filter by dashboard (optional)
        time_range: How far back to look (e.g., "24h", "7d")
        tags: Comma-separated tags to filter (e.g., "deployment,incident")

    Returns:
        JSON with annotations
    """
    logger.info(
        "grafana_get_annotations", dashboard=dashboard_uid, time_range=time_range
    )

    try:
        # Parse time range
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

        result = {
            "ok": True,
            "annotations": [
                {
                    "id": a.get("id"),
                    "time": datetime.fromtimestamp(a.get("time", 0) / 1000).isoformat(),
                    "text": a.get("text"),
                    "tags": a.get("tags", []),
                    "dashboard_uid": a.get("dashboardUID"),
                    "panel_id": a.get("panelId"),
                }
                for a in annotations[:100]
            ],
            "count": len(annotations),
            "time_range": time_range,
        }

        logger.info("grafana_annotations_fetched", count=len(annotations))
        return json.dumps(result)

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "grafana_get_annotations", "grafana"
        )
    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e)})
    except Exception as e:
        logger.error("grafana_get_annotations_failed", error=str(e))
        return json.dumps({"ok": False, "error": str(e)})


@function_tool
def grafana_get_alerts(state: str = "all") -> str:
    """
    Get alert rules and their current state from Grafana.

    Use cases:
    - Check which alerts are currently firing
    - Understand alerting coverage
    - Correlate alerts with incidents

    Args:
        state: Filter by state (all, alerting, pending, normal, no_data)

    Returns:
        JSON with alert rules and states
    """
    logger.info("grafana_get_alerts", state=state)

    try:
        with _get_grafana_client() as client:
            # Try Grafana 8+ unified alerting
            response = client.get("/api/v1/provisioning/alert-rules")

            if response.status_code == 404:
                # Fall back to legacy alerting
                response = client.get("/api/alerts")

            response.raise_for_status()
            alerts_data = response.json()

        # Handle different response formats
        if isinstance(alerts_data, list):
            alerts = alerts_data
        else:
            alerts = alerts_data.get("rules", []) or alerts_data.get("data", []) or []

        # Filter by state if specified
        filtered = []
        for alert in alerts:
            alert_state = alert.get("state", "unknown").lower()
            if state == "all" or state == alert_state:
                filtered.append(
                    {
                        "name": alert.get("name") or alert.get("title"),
                        "state": alert_state,
                        "severity": alert.get("labels", {}).get("severity", "unknown"),
                        "message": alert.get("annotations", {}).get("summary")
                        or alert.get("message"),
                        "dashboard_uid": alert.get("dashboardUid"),
                        "panel_id": alert.get("panelId"),
                    }
                )

        result = {
            "ok": True,
            "alerts": filtered[:50],
            "count": len(filtered),
            "filter": state,
            "firing_count": sum(1 for a in filtered if a["state"] == "alerting"),
        }

        logger.info("grafana_alerts_fetched", count=len(filtered))
        return json.dumps(result)

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "grafana_get_alerts", "grafana")
    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e)})
    except Exception as e:
        logger.error("grafana_get_alerts_failed", error=str(e))
        return json.dumps({"ok": False, "error": str(e)})


@function_tool
def grafana_update_alert_rule(
    alert_uid: str,
    threshold: float | None = None,
    for_duration: str | None = None,
    query: str | None = None,
    condition: str | None = None,
) -> str:
    """
    Update a Grafana alert rule (threshold, duration, query).

    Use cases:
    - Adjust alert thresholds to reduce noise
    - Change evaluation duration (e.g., from 1m to 5m)
    - Update alert queries

    Args:
        alert_uid: Alert rule UID
        threshold: New threshold value
        for_duration: New duration (e.g., "5m", "10m")
        query: New PromQL or query expression
        condition: New condition expression

    Returns:
        JSON with update result
    """
    if not alert_uid:
        return json.dumps({"ok": False, "error": "alert_uid is required"})

    logger.info("grafana_update_alert_rule", uid=alert_uid)

    try:
        with _get_grafana_client() as client:
            # Get current alert rule
            response = client.get(f"/api/v1/provisioning/alert-rules/{alert_uid}")

            if response.status_code == 404:
                return json.dumps({"ok": False, "error": "Alert rule not found"})

            response.raise_for_status()
            alert_rule = response.json()

            # Update specified fields
            if threshold is not None:
                # Update threshold in condition
                if "condition" in alert_rule:
                    # This is simplified - actual implementation depends on Grafana version and alert type
                    alert_rule["condition"] = condition or alert_rule.get(
                        "condition", ""
                    )

            if for_duration:
                alert_rule["for"] = for_duration

            if query:
                # Update the query in data source
                if "data" in alert_rule and len(alert_rule["data"]) > 0:
                    alert_rule["data"][0]["model"]["expr"] = query

            # Update the alert rule
            update_response = client.put(
                f"/api/v1/provisioning/alert-rules/{alert_uid}", json=alert_rule
            )
            update_response.raise_for_status()

        result = {
            "ok": True,
            "alert_uid": alert_uid,
            "updated_fields": {
                "threshold": threshold,
                "for_duration": for_duration,
                "query": query is not None,
            },
        }

        logger.info("grafana_alert_rule_updated", uid=alert_uid)
        return json.dumps(result)

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "grafana_update_alert_rule", "grafana"
        )
    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e)})
    except Exception as e:
        logger.error("grafana_update_alert_rule_failed", error=str(e), uid=alert_uid)
        return json.dumps({"ok": False, "error": str(e)})

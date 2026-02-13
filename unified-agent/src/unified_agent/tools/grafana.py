"""
Grafana dashboard and metrics tools.

Provides Grafana API access for dashboards, panels, and Prometheus queries.
"""

import json
import logging
import os
from typing import Optional

from ..core.agent import function_tool
from . import get_proxy_headers, register_tool

logger = logging.getLogger(__name__)


def _get_grafana_client():
    """Get HTTP client configured for Grafana API.

    Supports two modes:
    - Direct: GRAFANA_URL + GRAFANA_API_KEY (sends auth directly)
    - Proxy: GRAFANA_BASE_URL points to credential-resolver proxy (handles auth)
    """
    try:
        import httpx
    except ImportError:
        raise RuntimeError("httpx not installed: pip install httpx")

    url = os.getenv("GRAFANA_URL") or os.getenv("GRAFANA_BASE_URL")
    api_key = os.getenv("GRAFANA_API_KEY")

    if not url:
        raise ValueError("GRAFANA_URL or GRAFANA_BASE_URL must be set")

    base_url = url.rstrip("/")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    else:
        # Proxy mode: add JWT/tenant headers for credential-resolver
        headers.update(get_proxy_headers())

    return httpx.Client(base_url=base_url, headers=headers, timeout=30.0)


@function_tool
def grafana_list_dashboards(query: str = "") -> str:
    """
    List dashboards in Grafana.

    Args:
        query: Search query string

    Returns:
        JSON with list of dashboards
    """
    logger.info(f"grafana_list_dashboards: query={query}")

    try:
        with _get_grafana_client() as client:
            params = {"type": "dash-db"}
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
                for d in dashboards[:50]
            ],
            "count": len(dashboards),
        }
        return json.dumps(result)

    except ValueError as e:
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "hint": "Set GRAFANA_URL and GRAFANA_API_KEY",
            }
        )
    except Exception as e:
        logger.error(f"grafana_list_dashboards error: {e}")
        return json.dumps({"ok": False, "error": str(e)})


@function_tool
def grafana_get_dashboard(dashboard_uid: str) -> str:
    """
    Get a specific dashboard with all its panels.

    Args:
        dashboard_uid: Dashboard UID

    Returns:
        JSON with dashboard metadata and panels
    """
    if not dashboard_uid:
        return json.dumps({"ok": False, "error": "dashboard_uid is required"})

    logger.info(f"grafana_get_dashboard: uid={dashboard_uid}")

    try:
        with _get_grafana_client() as client:
            response = client.get(f"/api/dashboards/uid/{dashboard_uid}")
            response.raise_for_status()
            data = response.json()

        dashboard = data.get("dashboard", {})
        panels = []
        for panel in dashboard.get("panels", []):
            panels.append(
                {
                    "id": panel.get("id"),
                    "title": panel.get("title"),
                    "type": panel.get("type"),
                    "datasource": panel.get("datasource"),
                }
            )

        result = {
            "ok": True,
            "uid": dashboard.get("uid"),
            "title": dashboard.get("title"),
            "tags": dashboard.get("tags", []),
            "panel_count": len(panels),
            "panels": panels,
        }
        return json.dumps(result)

    except Exception as e:
        logger.error(f"grafana_get_dashboard error: {e}")
        return json.dumps(
            {"ok": False, "error": str(e), "dashboard_uid": dashboard_uid}
        )


@function_tool
def grafana_query_prometheus(
    query: str,
    time_range_minutes: int = 60,
    step: str = "1m",
) -> str:
    """
    Query Prometheus via Grafana.

    Args:
        query: PromQL query
        time_range_minutes: Time range in minutes (default 60)
        step: Query step (default 1m)

    Returns:
        JSON with query results
    """
    if not query:
        return json.dumps({"ok": False, "error": "query is required"})

    logger.info(f"grafana_query_prometheus: query={query}")

    try:
        from datetime import datetime, timedelta

        with _get_grafana_client() as client:
            end = datetime.utcnow()
            start = end - timedelta(minutes=time_range_minutes)

            params = {
                "query": query,
                "start": int(start.timestamp()),
                "end": int(end.timestamp()),
                "step": step,
            }

            response = client.get(
                "/api/datasources/proxy/1/api/v1/query_range", params=params
            )
            response.raise_for_status()
            data = response.json()

        if data.get("status") != "success":
            return json.dumps({"ok": False, "error": data.get("error", "Query failed")})

        results = data.get("data", {}).get("result", [])
        formatted = []
        for r in results[:20]:  # Limit results
            formatted.append(
                {
                    "metric": r.get("metric", {}),
                    "values": r.get("values", [])[-100:],  # Last 100 datapoints
                }
            )

        return json.dumps(
            {
                "ok": True,
                "query": query,
                "result_count": len(results),
                "results": formatted,
            }
        )

    except Exception as e:
        logger.error(f"grafana_query_prometheus error: {e}")
        return json.dumps({"ok": False, "error": str(e), "query": query})


@function_tool
def grafana_list_datasources() -> str:
    """
    List all configured datasources.

    Returns:
        JSON with datasources list
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
                    "name": ds.get("name"),
                    "type": ds.get("type"),
                    "url": ds.get("url"),
                    "is_default": ds.get("isDefault"),
                }
                for ds in datasources
            ],
        }
        return json.dumps(result)

    except Exception as e:
        logger.error(f"grafana_list_datasources error: {e}")
        return json.dumps({"ok": False, "error": str(e)})


@function_tool
def grafana_get_alerts() -> str:
    """
    Get all active alerts from Grafana.

    Returns:
        JSON with active alerts
    """
    logger.info("grafana_get_alerts")

    try:
        with _get_grafana_client() as client:
            response = client.get("/api/alerts")
            response.raise_for_status()
            alerts = response.json()

        result = {
            "ok": True,
            "alert_count": len(alerts),
            "alerts": [
                {
                    "id": a.get("id"),
                    "name": a.get("name"),
                    "state": a.get("state"),
                    "dashboard_uid": a.get("dashboardUid"),
                    "panel_id": a.get("panelId"),
                }
                for a in alerts[:50]
            ],
        }
        return json.dumps(result)

    except Exception as e:
        logger.error(f"grafana_get_alerts error: {e}")
        return json.dumps({"ok": False, "error": str(e)})


# Register tools
register_tool("grafana_list_dashboards", grafana_list_dashboards)
register_tool("grafana_get_dashboard", grafana_get_dashboard)
register_tool("grafana_query_prometheus", grafana_query_prometheus)
register_tool("grafana_list_datasources", grafana_list_datasources)
register_tool("grafana_get_alerts", grafana_get_alerts)

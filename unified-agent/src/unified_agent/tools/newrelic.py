"""New Relic APM and monitoring tools."""

import os
from typing import Any

import httpx

import json
import logging

from ..core.agent import function_tool
from . import register_tool


logger = logging.getLogger(__name__)


def _get_newrelic_config() -> str:
    """Get New Relic configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    # Credentials from environment variables
    # 2. Try environment variables (dev/testing fallback)
    if os.getenv("NEWRELIC_API_KEY"):
        return {"api_key": os.getenv("NEWRELIC_API_KEY")}

    # 3. Not configured - raise error
    return {"error": "newrelic not configured"}


def _get_newrelic_headers() -> str:
    """Get New Relic API headers."""
    config = _get_newrelic_config()

    return {"Api-Key": config["api_key"], "Content-Type": "application/json"}


@function_tool
def query_newrelic_nrql(
    account_id: str, nrql_query: str, timeout: int = 30
) -> str:
    """
    Run an NRQL query in New Relic.

    Args:
        account_id: New Relic account ID
        nrql_query: NRQL query string
        timeout: Query timeout in seconds

    Returns:
        Query results

    Example query:
        "SELECT average(duration) FROM Transaction WHERE appName = 'MyApp' SINCE 1 hour ago"
    """
    try:
        url = "https://api.newrelic.com/graphql"

        graphql_query = """
        query($accountId: Int!, $nrql: Nrql!) {
            actor {
                account(id: $accountId) {
                    nrql(query: $nrql) {
                        results
                    }
                }
            }
        }
        """

        with httpx.Client() as client:
            response = client.post(
                url,
                headers=_get_newrelic_headers(),
                json={
                    "query": graphql_query,
                    "variables": {"accountId": int(account_id), "nrql": nrql_query},
                },
                timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()

        results = (
            data.get("data", {})
            .get("actor", {})
            .get("account", {})
            .get("nrql", {})
            .get("results", [])
        )

        logger.info("newrelic_nrql_completed", account=account_id, results=len(results))
        return results

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except Exception as e:
        logger.error("newrelic_nrql_failed", error=str(e), query=nrql_query)
        return json.dumps({"ok": False, "error": "query_newrelic_nrql"})


@function_tool
def get_apm_summary(
    app_name: str, account_id: str, time_range: str = "30m"
) -> str:
    """
    Get APM summary for an application.

    Args:
        app_name: Application name in New Relic
        account_id: New Relic account ID
        time_range: Time range (e.g., '30m', '1h')

    Returns:
        APM summary with key metrics
    """
    try:
        # Query key APM metrics
        queries = {
            "response_time": f"SELECT average(duration) FROM Transaction WHERE appName = '{app_name}' SINCE {time_range} ago",
            "throughput": f"SELECT count(*) FROM Transaction WHERE appName = '{app_name}' SINCE {time_range} ago",
            "error_rate": f"SELECT percentage(count(*), WHERE error = true) FROM Transaction WHERE appName = '{app_name}' SINCE {time_range} ago",
            "apdex": f"SELECT apdex(duration, t: 0.5) FROM Transaction WHERE appName = '{app_name}' SINCE {time_range} ago",
        }

        summary = {}
        for metric_name, query in queries.items():
            try:
                result = query_newrelic_nrql(account_id, query)
                summary[metric_name] = result[0] if result else None
            except:
                summary[metric_name] = None

        logger.info("newrelic_apm_summary", app=app_name)
        return {"app": app_name, "summary": summary}

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except Exception as e:
        logger.error("newrelic_apm_failed", error=str(e), app=app_name)
        return json.dumps({"ok": False, "error": "get_apm_summary"})


# Register tools
register_tool("query_newrelic_nrql", query_newrelic_nrql)
register_tool("get_apm_summary", get_apm_summary)

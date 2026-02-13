"""
New Relic APM and monitoring tools.

Provides New Relic API access for NRQL queries and APM metrics.
"""

import json
import logging
import os

from ..core.agent import function_tool
from . import get_proxy_headers, register_tool

logger = logging.getLogger(__name__)


def _get_newrelic_base_url():
    """Get New Relic API base URL (supports proxy mode).

    Supports two modes:
    - Direct: Uses https://api.newrelic.com with NEWRELIC_API_KEY
    - Proxy: NEWRELIC_BASE_URL points to credential-resolver
    """
    proxy_url = os.getenv("NEWRELIC_BASE_URL")
    if proxy_url:
        return proxy_url.rstrip("/")

    if os.getenv("NEWRELIC_API_KEY"):
        return "https://api.newrelic.com"

    raise ValueError(
        "NEWRELIC_API_KEY or NEWRELIC_BASE_URL environment variable not set"
    )


def _get_newrelic_headers():
    """Get New Relic API headers.

    Supports two modes:
    - Direct: NEWRELIC_API_KEY (User API key or Ingest key)
    - Proxy: NEWRELIC_BASE_URL → credential-resolver handles auth
    """
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    if os.getenv("NEWRELIC_BASE_URL"):
        headers.update(get_proxy_headers())
        return headers

    api_key = os.getenv("NEWRELIC_API_KEY")
    if api_key:
        headers["Api-Key"] = api_key
        return headers

    raise ValueError("NEWRELIC_API_KEY or NEWRELIC_BASE_URL must be set")


def _newrelic_request(json_body):
    """Make a GraphQL request to New Relic NerdGraph API."""
    import requests

    base_url = _get_newrelic_base_url()
    headers = _get_newrelic_headers()
    url = f"{base_url}/graphql"

    response = requests.post(url, headers=headers, json=json_body, timeout=30)
    response.raise_for_status()
    return response.json()


@function_tool
def query_newrelic_nrql(
    account_id: str,
    nrql_query: str,
    timeout: int = 30,
) -> str:
    """
    Run an NRQL query against New Relic.

    Args:
        account_id: New Relic account ID
        nrql_query: NRQL query string
        timeout: Query timeout in seconds

    Returns:
        JSON with query results

    Example queries:
        "SELECT average(duration) FROM Transaction WHERE appName = 'MyApp' SINCE 1 hour ago"
        "SELECT count(*) FROM Transaction FACET appName SINCE 30 minutes ago"
        "SELECT percentile(duration, 95) FROM Transaction WHERE appName = 'MyApp' TIMESERIES 5 minutes SINCE 1 hour ago"
        "SELECT count(*) FROM Log WHERE level = 'ERROR' FACET service SINCE 1 hour ago"
    """
    if not account_id or not nrql_query:
        return json.dumps(
            {"ok": False, "error": "account_id and nrql_query are required"}
        )

    logger.info(f"query_newrelic_nrql: account={account_id}, query={nrql_query[:80]}")

    try:
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

        data = _newrelic_request(
            {
                "query": graphql_query,
                "variables": {"accountId": int(account_id), "nrql": nrql_query},
            }
        )

        # Check for GraphQL errors
        if "errors" in data:
            return json.dumps(
                {
                    "ok": False,
                    "error": data["errors"][0].get("message", "GraphQL query failed"),
                    "account_id": account_id,
                }
            )

        results = (
            data.get("data", {})
            .get("actor", {})
            .get("account", {})
            .get("nrql", {})
            .get("results", [])
        )

        return json.dumps(
            {
                "ok": True,
                "account_id": account_id,
                "query": nrql_query,
                "result_count": len(results),
                "results": results,
            }
        )

    except ValueError as e:
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "hint": "Set NEWRELIC_API_KEY or NEWRELIC_BASE_URL",
            }
        )
    except Exception as e:
        logger.error(f"query_newrelic_nrql error: {e}")
        return json.dumps({"ok": False, "error": str(e), "account_id": account_id})


@function_tool
def get_newrelic_apm_summary(
    app_name: str,
    account_id: str,
    time_range: str = "30 minutes",
) -> str:
    """
    Get APM summary for an application from New Relic.

    Queries key APM metrics: response time, throughput, error rate, and apdex.

    Args:
        app_name: Application name in New Relic
        account_id: New Relic account ID
        time_range: NRQL time range (e.g., '30 minutes', '1 hour', '6 hours')

    Returns:
        JSON with APM summary metrics
    """
    if not app_name or not account_id:
        return json.dumps(
            {"ok": False, "error": "app_name and account_id are required"}
        )

    logger.info(f"get_newrelic_apm_summary: app={app_name}, account={account_id}")

    try:
        queries = {
            "response_time": f"SELECT average(duration) FROM Transaction WHERE appName = '{app_name}' SINCE {time_range} ago",
            "throughput": f"SELECT count(*) FROM Transaction WHERE appName = '{app_name}' SINCE {time_range} ago",
            "error_rate": f"SELECT percentage(count(*), WHERE error = true) FROM Transaction WHERE appName = '{app_name}' SINCE {time_range} ago",
            "apdex": f"SELECT apdex(duration, t: 0.5) FROM Transaction WHERE appName = '{app_name}' SINCE {time_range} ago",
        }

        summary = {}
        for metric_name, nrql in queries.items():
            result = json.loads(query_newrelic_nrql(account_id, nrql))
            if result.get("ok") and result.get("results"):
                summary[metric_name] = result["results"][0]
            else:
                summary[metric_name] = None

        return json.dumps(
            {
                "ok": True,
                "app_name": app_name,
                "account_id": account_id,
                "time_range": time_range,
                "summary": summary,
            }
        )

    except ValueError as e:
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "hint": "Set NEWRELIC_API_KEY or NEWRELIC_BASE_URL",
            }
        )
    except Exception as e:
        logger.error(f"get_newrelic_apm_summary error: {e}")
        return json.dumps({"ok": False, "error": str(e), "app_name": app_name})


# Register tools
register_tool("query_newrelic_nrql", query_newrelic_nrql)
register_tool("get_newrelic_apm_summary", get_newrelic_apm_summary)

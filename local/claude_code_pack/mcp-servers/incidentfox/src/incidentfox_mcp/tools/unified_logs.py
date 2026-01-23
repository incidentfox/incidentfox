"""Unified Log Search.

A single interface for searching logs across multiple backends:
- Datadog
- CloudWatch
- Elasticsearch
- Prometheus/Loki
- Local files

Automatically detects which backends are configured and queries them.
"""

import json
from datetime import datetime, timedelta

from mcp.server.fastmcp import FastMCP

from ..utils.config import get_env


def _detect_backends() -> list[str]:
    """Detect which log backends are configured."""
    backends = []

    if get_env("DATADOG_API_KEY") and get_env("DATADOG_APP_KEY"):
        backends.append("datadog")

    if _has_aws_credentials():
        backends.append("cloudwatch")

    if get_env("ELASTICSEARCH_URL") or get_env("ES_URL"):
        backends.append("elasticsearch")

    if get_env("LOKI_URL"):
        backends.append("loki")

    if get_env("LOG_PATH") or get_env("LOG_FILE"):
        backends.append("local")

    return backends


def _has_aws_credentials() -> bool:
    """Check if AWS credentials are available."""
    if get_env("AWS_ACCESS_KEY_ID") and get_env("AWS_SECRET_ACCESS_KEY"):
        return True
    # Check for default credentials file
    from pathlib import Path

    if (Path.home() / ".aws" / "credentials").exists():
        return True
    return False


def _search_datadog(
    query: str, service: str | None, hours_ago: int, limit: int
) -> dict:
    """Search Datadog logs."""
    try:
        from datadog_api_client import ApiClient, Configuration
        from datadog_api_client.v2.api.logs_api import LogsApi
        from datadog_api_client.v2.model.logs_list_request import LogsListRequest
        from datadog_api_client.v2.model.logs_list_request_page import (
            LogsListRequestPage,
        )
        from datadog_api_client.v2.model.logs_query_filter import LogsQueryFilter
        from datadog_api_client.v2.model.logs_sort import LogsSort

        config = Configuration()
        config.api_key["apiKeyAuth"] = get_env("DATADOG_API_KEY")
        config.api_key["appKeyAuth"] = get_env("DATADOG_APP_KEY")

        # Build query
        full_query = query
        if service:
            full_query = f"service:{service} {query}"

        now = datetime.utcnow()
        from_time = now - timedelta(hours=hours_ago)

        with ApiClient(config) as api_client:
            api = LogsApi(api_client)
            response = api.list_logs(
                body=LogsListRequest(
                    filter=LogsQueryFilter(
                        query=full_query,
                        _from=from_time.isoformat() + "Z",
                        to=now.isoformat() + "Z",
                    ),
                    sort=LogsSort.TIMESTAMP_DESCENDING,
                    page=LogsListRequestPage(limit=limit),
                )
            )

        logs = []
        for log in response.data or []:
            attrs = log.attributes
            logs.append(
                {
                    "timestamp": str(attrs.timestamp) if attrs.timestamp else None,
                    "service": attrs.service,
                    "status": attrs.status,
                    "message": attrs.message,
                }
            )

        return {
            "backend": "datadog",
            "query": full_query,
            "count": len(logs),
            "logs": logs,
        }

    except Exception as e:
        return {"backend": "datadog", "error": str(e)}


def _search_cloudwatch(
    query: str, service: str | None, hours_ago: int, limit: int
) -> dict:
    """Search CloudWatch logs using Logs Insights."""
    try:
        import time

        import boto3

        session = boto3.Session(
            region_name=get_env("AWS_REGION")
            or get_env("AWS_DEFAULT_REGION")
            or "us-east-1"
        )
        logs_client = session.client("logs")

        # Determine log group
        log_group = get_env("CLOUDWATCH_LOG_GROUP")
        if service and not log_group:
            # Try common patterns
            log_group = f"/aws/eks/{service}"

        if not log_group:
            return {
                "backend": "cloudwatch",
                "error": "No log group specified. Set CLOUDWATCH_LOG_GROUP or provide service name.",
            }

        # Build Insights query
        insights_query = f"""
            fields @timestamp, @message, @logStream
            | filter @message like /{query}/
            | sort @timestamp desc
            | limit {limit}
        """

        now = datetime.utcnow()
        start_time = int((now - timedelta(hours=hours_ago)).timestamp())
        end_time = int(now.timestamp())

        # Start query
        response = logs_client.start_query(
            logGroupName=log_group,
            startTime=start_time,
            endTime=end_time,
            queryString=insights_query,
        )
        query_id = response["queryId"]

        # Poll for results
        for _ in range(30):
            result = logs_client.get_query_results(queryId=query_id)
            if result["status"] == "Complete":
                logs = []
                for record in result["results"]:
                    log_entry = {}
                    for field in record:
                        log_entry[field["field"]] = field["value"]
                    logs.append(log_entry)

                return {
                    "backend": "cloudwatch",
                    "log_group": log_group,
                    "query": query,
                    "count": len(logs),
                    "logs": logs,
                }
            elif result["status"] in ("Failed", "Cancelled"):
                return {
                    "backend": "cloudwatch",
                    "error": f"Query {result['status'].lower()}",
                }
            time.sleep(1)

        return {"backend": "cloudwatch", "error": "Query timeout"}

    except Exception as e:
        return {"backend": "cloudwatch", "error": str(e)}


def _search_elasticsearch(
    query: str, service: str | None, hours_ago: int, limit: int
) -> dict:
    """Search Elasticsearch logs."""
    try:
        import httpx

        es_url = get_env("ELASTICSEARCH_URL") or get_env("ES_URL")
        es_index = get_env("ES_INDEX") or "logs-*"
        es_user = get_env("ES_USER")
        es_password = get_env("ES_PASSWORD")

        auth = None
        if es_user and es_password:
            auth = (es_user, es_password)

        # Build query
        must = [{"query_string": {"query": query}}]
        if service:
            must.append({"match": {"service": service}})

        body = {
            "query": {
                "bool": {
                    "must": must,
                    "filter": [
                        {
                            "range": {
                                "@timestamp": {
                                    "gte": f"now-{hours_ago}h",
                                    "lte": "now",
                                }
                            }
                        }
                    ],
                }
            },
            "sort": [{"@timestamp": "desc"}],
            "size": limit,
        }

        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                f"{es_url}/{es_index}/_search",
                json=body,
                auth=auth,
            )
            response.raise_for_status()
            data = response.json()

        logs = []
        for hit in data.get("hits", {}).get("hits", []):
            source = hit.get("_source", {})
            logs.append(
                {
                    "timestamp": source.get("@timestamp"),
                    "message": source.get("message"),
                    "service": source.get("service"),
                    "level": source.get("level"),
                }
            )

        return {
            "backend": "elasticsearch",
            "index": es_index,
            "query": query,
            "count": len(logs),
            "logs": logs,
        }

    except Exception as e:
        return {"backend": "elasticsearch", "error": str(e)}


def _search_loki(query: str, service: str | None, hours_ago: int, limit: int) -> dict:
    """Search Grafana Loki logs."""
    try:
        import httpx

        loki_url = get_env("LOKI_URL")

        # Build LogQL query
        if service:
            logql = f'{{service="{service}"}} |= `{query}`'
        else:
            logql = f'{{job=~".+"}} |= `{query}`'

        now = datetime.utcnow()
        start_ns = int((now - timedelta(hours=hours_ago)).timestamp() * 1e9)
        end_ns = int(now.timestamp() * 1e9)

        params = {
            "query": logql,
            "start": start_ns,
            "end": end_ns,
            "limit": limit,
        }

        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                f"{loki_url}/loki/api/v1/query_range",
                params=params,
            )
            response.raise_for_status()
            data = response.json()

        logs = []
        for stream in data.get("data", {}).get("result", []):
            labels = stream.get("stream", {})
            for value in stream.get("values", []):
                logs.append(
                    {
                        "timestamp": value[0],
                        "message": value[1],
                        "labels": labels,
                    }
                )

        return {
            "backend": "loki",
            "query": logql,
            "count": len(logs),
            "logs": logs,
        }

    except Exception as e:
        return {"backend": "loki", "error": str(e)}


def _search_local(query: str, service: str | None, hours_ago: int, limit: int) -> dict:
    """Search local log files."""
    try:
        import re
        from pathlib import Path

        log_path = get_env("LOG_PATH") or get_env("LOG_FILE")
        if not log_path:
            return {"backend": "local", "error": "LOG_PATH not set"}

        path = Path(log_path)
        if not path.exists():
            return {"backend": "local", "error": f"Log path not found: {log_path}"}

        # Get files to search
        if path.is_dir():
            files = list(path.glob("**/*.log")) + list(path.glob("**/*.txt"))
        else:
            files = [path]

        logs = []
        pattern = re.compile(query, re.IGNORECASE)

        for file in files:
            try:
                with open(file) as f:
                    for line in f:
                        if pattern.search(line):
                            logs.append(
                                {
                                    "file": str(file),
                                    "message": line.strip(),
                                }
                            )
                            if len(logs) >= limit:
                                break
            except Exception:
                continue

            if len(logs) >= limit:
                break

        return {
            "backend": "local",
            "path": log_path,
            "query": query,
            "count": len(logs),
            "logs": logs[-limit:],  # Most recent
        }

    except Exception as e:
        return {"backend": "local", "error": str(e)}


def register_tools(mcp: FastMCP):
    """Register unified log search tools."""

    @mcp.tool()
    def search_logs(
        query: str,
        service: str | None = None,
        hours_ago: int = 1,
        limit: int = 50,
        backends: str | None = None,
    ) -> str:
        """Search logs across all configured backends.

        This is the primary log search tool. It automatically detects and queries
        all available log backends (Datadog, CloudWatch, Elasticsearch, Loki, local files).

        Args:
            query: Search query (text to find in logs)
            service: Optional service name to filter logs
            hours_ago: How far back to search (default: 1 hour)
            limit: Maximum logs per backend (default: 50)
            backends: Comma-separated list of backends to query (default: all configured)

        Returns:
            JSON with results from each backend that returned data.
        """
        detected = _detect_backends()

        if not detected:
            return json.dumps(
                {
                    "error": "No log backends configured",
                    "hint": "Set environment variables for at least one backend:",
                    "backends": {
                        "datadog": "DATADOG_API_KEY, DATADOG_APP_KEY",
                        "cloudwatch": "AWS credentials + CLOUDWATCH_LOG_GROUP",
                        "elasticsearch": "ELASTICSEARCH_URL or ES_URL",
                        "loki": "LOKI_URL",
                        "local": "LOG_PATH or LOG_FILE",
                    },
                }
            )

        # Filter backends if specified
        if backends:
            requested = [b.strip().lower() for b in backends.split(",")]
            detected = [b for b in detected if b in requested]

        results = []

        # Query each backend
        if "datadog" in detected:
            results.append(_search_datadog(query, service, hours_ago, limit))

        if "cloudwatch" in detected:
            results.append(_search_cloudwatch(query, service, hours_ago, limit))

        if "elasticsearch" in detected:
            results.append(_search_elasticsearch(query, service, hours_ago, limit))

        if "loki" in detected:
            results.append(_search_loki(query, service, hours_ago, limit))

        if "local" in detected:
            results.append(_search_local(query, service, hours_ago, limit))

        # Aggregate results
        total_logs = sum(r.get("count", 0) for r in results if "error" not in r)
        errors = [r for r in results if "error" in r]
        successful = [r for r in results if "error" not in r]

        return json.dumps(
            {
                "query": query,
                "service": service,
                "time_range": f"last {hours_ago} hour(s)",
                "backends_queried": detected,
                "total_logs_found": total_logs,
                "results": successful,
                "errors": errors if errors else None,
            },
            indent=2,
        )

    @mcp.tool()
    def get_log_backends() -> str:
        """List configured log backends and their status.

        Returns which log backends are available based on environment configuration.
        """
        detected = _detect_backends()

        all_backends = {
            "datadog": {
                "configured": "datadog" in detected,
                "requires": ["DATADOG_API_KEY", "DATADOG_APP_KEY"],
            },
            "cloudwatch": {
                "configured": "cloudwatch" in detected,
                "requires": ["AWS credentials", "CLOUDWATCH_LOG_GROUP (optional)"],
            },
            "elasticsearch": {
                "configured": "elasticsearch" in detected,
                "requires": ["ELASTICSEARCH_URL or ES_URL"],
            },
            "loki": {
                "configured": "loki" in detected,
                "requires": ["LOKI_URL"],
            },
            "local": {
                "configured": "local" in detected,
                "requires": ["LOG_PATH or LOG_FILE"],
            },
        }

        return json.dumps(
            {
                "configured_backends": detected,
                "all_backends": all_backends,
            },
            indent=2,
        )

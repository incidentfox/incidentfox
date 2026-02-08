"""
Elasticsearch integration tools for log search and metric analysis.

Provides Elasticsearch API access for searching logs, querying metrics
(metricbeat/APM), running aggregations, and inspecting cluster health.
"""

import base64
import json
import logging
import os
from datetime import datetime, timedelta

from ..core.agent import function_tool
from . import get_proxy_headers, register_tool

logger = logging.getLogger(__name__)


def _get_elasticsearch_base_url():
    """Get Elasticsearch base URL (supports proxy mode).

    Supports two modes:
    - Direct: ELASTICSEARCH_URL (e.g., https://elasticsearch.example.com:9200)
    - Proxy: ELASTICSEARCH_BASE_URL points to credential-resolver
    """
    proxy_url = os.getenv("ELASTICSEARCH_BASE_URL")
    if proxy_url:
        return proxy_url.rstrip("/")

    es_url = os.getenv("ELASTICSEARCH_URL")
    if es_url:
        return es_url.rstrip("/")

    raise ValueError(
        "ELASTICSEARCH_URL or ELASTICSEARCH_BASE_URL environment variable not set"
    )


def _get_elasticsearch_headers():
    """Get Elasticsearch API headers.

    Supports multiple auth modes:
    - Proxy: ELASTICSEARCH_BASE_URL → credential-resolver handles auth
    - API Key: ELASTICSEARCH_API_KEY (id:secret or pre-encoded base64)
    - Basic: ELASTICSEARCH_USERNAME + ELASTICSEARCH_PASSWORD
    """
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    if os.getenv("ELASTICSEARCH_BASE_URL"):
        # Proxy mode: credential-resolver handles auth
        headers.update(get_proxy_headers())
        return headers

    # Direct mode: check for credentials
    api_key = os.getenv("ELASTICSEARCH_API_KEY")
    if api_key:
        if ":" in api_key:
            # id:secret format — encode to base64
            encoded = base64.b64encode(api_key.encode()).decode()
            headers["Authorization"] = f"ApiKey {encoded}"
        else:
            # Already base64 encoded
            headers["Authorization"] = f"ApiKey {api_key}"
        return headers

    username = os.getenv("ELASTICSEARCH_USERNAME")
    password = os.getenv("ELASTICSEARCH_PASSWORD")
    if username and password:
        credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {credentials}"
        return headers

    # No auth — Elasticsearch may allow anonymous access
    return headers


def _es_request(method, path, params=None, json_body=None):
    """Make a request to Elasticsearch API."""
    import requests as req

    base_url = _get_elasticsearch_base_url()
    headers = _get_elasticsearch_headers()
    url = f"{base_url}/{path.lstrip('/')}"

    response = req.request(
        method,
        url,
        headers=headers,
        params=params,
        json=json_body,
        timeout=30,
        verify=not os.getenv("ELASTICSEARCH_SKIP_TLS_VERIFY"),
    )
    response.raise_for_status()
    return response.json()


def _parse_time_range(time_range: str) -> datetime:
    """Parse time range string (e.g., '15m', '1h', '24h', '7d') to start datetime."""
    now = datetime.utcnow()
    value = int(time_range[:-1])
    unit = time_range[-1]
    if unit == "m":
        return now - timedelta(minutes=value)
    elif unit == "h":
        return now - timedelta(hours=value)
    elif unit == "d":
        return now - timedelta(days=value)
    raise ValueError(
        f"Invalid time range: {time_range}. Use format like '15m', '1h', '7d'"
    )


@function_tool
def elasticsearch_search_logs(
    query: str,
    index: str = "logs-*",
    time_range: str = "15m",
    size: int = 100,
) -> str:
    """
    Search Elasticsearch logs using Lucene query string syntax.

    Args:
        query: Search query (Lucene syntax, e.g., 'level:ERROR AND service:api')
        index: Index pattern (default: logs-*)
        time_range: Time range like '15m', '1h', '24h', '7d'
        size: Maximum results to return

    Returns:
        JSON with matching log entries
    """
    if not query:
        return json.dumps({"error": "query is required"})

    logger.info(f"elasticsearch_search_logs: query={query[:80]}, index={index}")

    try:
        start_time = _parse_time_range(time_range)

        body = {
            "query": {
                "bool": {
                    "must": [
                        {"query_string": {"query": query}},
                    ],
                    "filter": [
                        {
                            "range": {
                                "@timestamp": {
                                    "gte": start_time.isoformat() + "Z",
                                    "lte": "now",
                                }
                            }
                        }
                    ],
                }
            },
            "sort": [{"@timestamp": {"order": "desc"}}],
            "size": size,
        }

        data = _es_request("POST", f"/{index}/_search", json_body=body)

        hits = data.get("hits", {})
        total = hits.get("total", {})
        total_count = total.get("value", 0) if isinstance(total, dict) else total

        logs = []
        for hit in hits.get("hits", []):
            source = hit.get("_source", {})
            logs.append(
                {
                    "timestamp": source.get("@timestamp"),
                    "message": source.get("message", ""),
                    "level": source.get("level") or source.get("log", {}).get("level"),
                    "service": (
                        source.get("service", {}).get("name")
                        if isinstance(source.get("service"), dict)
                        else source.get("service")
                    ),
                    "host": (
                        source.get("host", {}).get("name")
                        if isinstance(source.get("host"), dict)
                        else source.get("host")
                    ),
                    "index": hit.get("_index"),
                }
            )

        return json.dumps(
            {
                "ok": True,
                "total_hits": total_count,
                "count": len(logs),
                "logs": logs,
            }
        )

    except ValueError as e:
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "hint": "Set ELASTICSEARCH_URL or ELASTICSEARCH_BASE_URL",
            }
        )
    except Exception as e:
        logger.error(f"elasticsearch_search_logs error: {e}")
        return json.dumps({"ok": False, "error": str(e), "query": query[:80]})


@function_tool
def elasticsearch_search(
    index: str,
    query_body: str,
    time_range: str = "1h",
    size: int = 100,
) -> str:
    """
    Search Elasticsearch using full Query DSL (advanced).

    Supports complex queries with aggregations, filters, and highlights.

    Args:
        index: Index pattern (e.g., 'logs-*', 'metricbeat-*', 'app-logs-2024-*')
        query_body: Full Elasticsearch Query DSL as JSON string
        time_range: Time range for @timestamp filter ('15m', '1h', '24h', '7d')
        size: Maximum results (default: 100)

    Returns:
        JSON with hits, aggregations, and metadata

    Example query_body:
        '{"query": {"bool": {"must": [{"match": {"message": "error"}}]}}}'
        '{"aggs": {"status_codes": {"terms": {"field": "http.response.status_code"}}}}'
    """
    if not index:
        return json.dumps({"error": "index is required"})

    logger.info(f"elasticsearch_search: index={index}")

    try:
        body = json.loads(query_body) if query_body else {}

        start_time = _parse_time_range(time_range)
        time_filter = {
            "range": {
                "@timestamp": {
                    "gte": start_time.isoformat() + "Z",
                    "lte": "now",
                }
            }
        }

        # Inject time filter into query
        if "query" in body:
            existing_query = body["query"]
            if "bool" in existing_query:
                existing_query["bool"].setdefault("filter", [])
                if isinstance(existing_query["bool"]["filter"], list):
                    existing_query["bool"]["filter"].append(time_filter)
                else:
                    existing_query["bool"]["filter"] = [
                        existing_query["bool"]["filter"],
                        time_filter,
                    ]
            else:
                body["query"] = {
                    "bool": {"must": [existing_query], "filter": [time_filter]}
                }
        else:
            body["query"] = {"bool": {"filter": [time_filter]}}

        body.setdefault("size", size)
        body.setdefault("sort", [{"@timestamp": {"order": "desc"}}])

        data = _es_request("POST", f"/{index}/_search", json_body=body)

        hits = data.get("hits", {})
        total = hits.get("total", {})
        total_count = total.get("value", 0) if isinstance(total, dict) else total

        result = {
            "ok": True,
            "total_hits": total_count,
            "took_ms": data.get("took"),
            "count": len(hits.get("hits", [])),
            "hits": [
                {
                    "index": h.get("_index"),
                    "id": h.get("_id"),
                    "score": h.get("_score"),
                    "source": h.get("_source", {}),
                }
                for h in hits.get("hits", [])
            ],
        }

        if "aggregations" in data:
            result["aggregations"] = data["aggregations"]

        return json.dumps(result)

    except json.JSONDecodeError as e:
        return json.dumps({"ok": False, "error": f"Invalid JSON in query_body: {e}"})
    except ValueError as e:
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "hint": "Set ELASTICSEARCH_URL or ELASTICSEARCH_BASE_URL",
            }
        )
    except Exception as e:
        logger.error(f"elasticsearch_search error: {e}")
        return json.dumps({"ok": False, "error": str(e), "index": index})


@function_tool
def elasticsearch_query_metrics(
    metric_field: str,
    index: str = "metricbeat-*",
    time_range: str = "1h",
    interval: str = "5m",
    stat: str = "avg",
    filters: str = "",
) -> str:
    """
    Query time-series metrics from Elasticsearch (Metricbeat, APM, or custom metrics).

    Runs a date_histogram aggregation to return metric values over time.

    Args:
        metric_field: Metric field to query (e.g., 'system.cpu.total.pct',
            'system.memory.used.pct', 'http.server.duration', 'system.load.1')
        index: Index pattern (default: metricbeat-*)
        time_range: Time range like '15m', '1h', '24h', '7d'
        interval: Aggregation interval (e.g., '1m', '5m', '1h')
        stat: Statistic to compute: avg, sum, max, min, value_count
        filters: Optional Lucene filter query (e.g., 'host.name:web-01 AND service.name:api')

    Returns:
        JSON with time-series metric datapoints

    Common metric fields (Metricbeat):
        system.cpu.total.pct - CPU usage (0-1)
        system.memory.used.pct - Memory usage (0-1)
        system.memory.used.bytes - Memory used in bytes
        system.load.1 - 1-minute load average
        system.load.5 - 5-minute load average
        system.diskio.read.bytes - Disk read bytes
        system.diskio.write.bytes - Disk write bytes
        system.network.in.bytes - Network bytes in
        system.network.out.bytes - Network bytes out
        system.filesystem.used.pct - Filesystem usage (0-1)
    """
    if not metric_field:
        return json.dumps({"error": "metric_field is required"})

    logger.info(
        f"elasticsearch_query_metrics: field={metric_field}, index={index}, stat={stat}"
    )

    try:
        start_time = _parse_time_range(time_range)

        # Build query with time filter
        must = []
        if filters:
            must.append({"query_string": {"query": filters}})

        body = {
            "size": 0,
            "query": {
                "bool": {
                    "must": must,
                    "filter": [
                        {
                            "range": {
                                "@timestamp": {
                                    "gte": start_time.isoformat() + "Z",
                                    "lte": "now",
                                }
                            }
                        },
                        {"exists": {"field": metric_field}},
                    ],
                }
            },
            "aggs": {
                "over_time": {
                    "date_histogram": {
                        "field": "@timestamp",
                        "fixed_interval": interval,
                    },
                    "aggs": {
                        "metric_value": {stat: {"field": metric_field}},
                    },
                },
                "overall": {
                    "stats": {"field": metric_field},
                },
            },
        }

        data = _es_request("POST", f"/{index}/_search", json_body=body)

        aggs = data.get("aggregations", {})
        buckets = aggs.get("over_time", {}).get("buckets", [])
        overall = aggs.get("overall", {})

        datapoints = []
        for bucket in buckets:
            value = bucket.get("metric_value", {}).get("value")
            datapoints.append(
                {
                    "timestamp": bucket.get("key_as_string"),
                    "value": value,
                    "doc_count": bucket.get("doc_count"),
                }
            )

        return json.dumps(
            {
                "ok": True,
                "metric_field": metric_field,
                "stat": stat,
                "interval": interval,
                "datapoint_count": len(datapoints),
                "overall": {
                    "count": overall.get("count"),
                    "min": overall.get("min"),
                    "max": overall.get("max"),
                    "avg": overall.get("avg"),
                    "sum": overall.get("sum"),
                },
                "datapoints": datapoints,
            }
        )

    except ValueError as e:
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "hint": "Set ELASTICSEARCH_URL or ELASTICSEARCH_BASE_URL",
            }
        )
    except Exception as e:
        logger.error(f"elasticsearch_query_metrics error: {e}")
        return json.dumps({"ok": False, "error": str(e), "metric_field": metric_field})


@function_tool
def elasticsearch_list_indices(pattern: str = "*") -> str:
    """
    List Elasticsearch indices matching a pattern.

    Args:
        pattern: Index pattern (e.g., '*', 'logs-*', 'metricbeat-*')

    Returns:
        JSON with index names, document counts, sizes, and health
    """
    logger.info(f"elasticsearch_list_indices: pattern={pattern}")

    try:
        data = _es_request(
            "GET",
            f"/_cat/indices/{pattern}",
            params={"format": "json", "h": "index,docs.count,store.size,health,status"},
        )

        indices = []
        for idx in sorted(data, key=lambda x: x.get("index", "")):
            indices.append(
                {
                    "index": idx.get("index"),
                    "docs_count": idx.get("docs.count"),
                    "size": idx.get("store.size"),
                    "health": idx.get("health"),
                    "status": idx.get("status"),
                }
            )

        return json.dumps(
            {
                "ok": True,
                "index_count": len(indices),
                "indices": indices,
            }
        )

    except ValueError as e:
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "hint": "Set ELASTICSEARCH_URL or ELASTICSEARCH_BASE_URL",
            }
        )
    except Exception as e:
        logger.error(f"elasticsearch_list_indices error: {e}")
        return json.dumps({"ok": False, "error": str(e)})


@function_tool
def elasticsearch_get_cluster_stats() -> str:
    """
    Get Elasticsearch cluster health and statistics.

    Returns:
        JSON with cluster health, node count, shard status, and storage info
    """
    logger.info("elasticsearch_get_cluster_stats")

    try:
        health = _es_request("GET", "/_cluster/health")

        result = {
            "ok": True,
            "cluster_name": health.get("cluster_name"),
            "status": health.get("status"),
            "number_of_nodes": health.get("number_of_nodes"),
            "number_of_data_nodes": health.get("number_of_data_nodes"),
            "active_primary_shards": health.get("active_primary_shards"),
            "active_shards": health.get("active_shards"),
            "relocating_shards": health.get("relocating_shards"),
            "initializing_shards": health.get("initializing_shards"),
            "unassigned_shards": health.get("unassigned_shards"),
            "pending_tasks": health.get("number_of_pending_tasks"),
        }

        # Try to get storage stats
        try:
            stats = _es_request("GET", "/_cluster/stats")
            indices = stats.get("indices", {})
            result["total_indices"] = indices.get("count")
            result["total_docs"] = indices.get("docs", {}).get("count")
            store = indices.get("store", {})
            total_bytes = store.get("size_in_bytes", 0)
            result["total_storage_bytes"] = total_bytes
            result["total_storage_gb"] = round(total_bytes / (1024**3), 2)
        except Exception:
            pass

        return json.dumps(result)

    except ValueError as e:
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "hint": "Set ELASTICSEARCH_URL or ELASTICSEARCH_BASE_URL",
            }
        )
    except Exception as e:
        logger.error(f"elasticsearch_get_cluster_stats error: {e}")
        return json.dumps({"ok": False, "error": str(e)})


# Register tools
register_tool("elasticsearch_search_logs", elasticsearch_search_logs)
register_tool("elasticsearch_search", elasticsearch_search)
register_tool("elasticsearch_query_metrics", elasticsearch_query_metrics)
register_tool("elasticsearch_list_indices", elasticsearch_list_indices)
register_tool("elasticsearch_get_cluster_stats", elasticsearch_get_cluster_stats)

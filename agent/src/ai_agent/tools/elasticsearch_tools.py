"""Elasticsearch log search and analysis tools."""

import os
from datetime import datetime, timedelta
from typing import Any

from ..core.config_required import handle_integration_not_configured
from ..core.errors import ToolExecutionError
from ..core.execution_context import get_execution_context
from ..core.integration_errors import IntegrationNotConfiguredError
from ..core.logging import get_logger

logger = get_logger(__name__)


def _get_elasticsearch_config() -> dict:
    """Get Elasticsearch configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("elasticsearch")
        if (
            config
            and config.get("url")
            and config.get("username")
            and config.get("password")
        ):
            return config

    # 2. Try environment variables (dev/testing fallback)
    if (
        os.getenv("ELASTICSEARCH_URL")
        and os.getenv("ELASTICSEARCH_USERNAME")
        and os.getenv("ELASTICSEARCH_PASSWORD")
    ):
        return {
            "url": os.getenv("ELASTICSEARCH_URL"),
            "username": os.getenv("ELASTICSEARCH_USERNAME"),
            "password": os.getenv("ELASTICSEARCH_PASSWORD"),
        }

    # 3. Not configured - raise error
    raise IntegrationNotConfiguredError(
        integration_id="elasticsearch",
        tool_id="elasticsearch_tools",
        missing_fields=["url", "username", "password"],
    )


def _get_es_client():
    """Get Elasticsearch client."""
    try:
        from elasticsearch import Elasticsearch

        config = _get_elasticsearch_config()

        return Elasticsearch(
            [config["url"]], basic_auth=(config["username"], config["password"])
        )

    except ImportError:
        raise ToolExecutionError("elasticsearch", "elasticsearch package not installed")


def search_logs(
    query: str,
    index: str = "logs-*",
    time_range: str = "15m",
    size: int = 100,
    fields: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Search logs in Elasticsearch.

    Args:
        query: Lucene query string or message to search
        index: Index pattern (default: logs-*)
        time_range: Time range (e.g., '15m', '1h', '24h')
        size: Max results to return
        fields: Specific fields to return

    Returns:
        List of log entries
    """
    try:
        es = _get_es_client()

        # Parse time range
        if time_range.endswith("m"):
            minutes = int(time_range[:-1])
            start_time = datetime.utcnow() - timedelta(minutes=minutes)
        elif time_range.endswith("h"):
            hours = int(time_range[:-1])
            start_time = datetime.utcnow() - timedelta(hours=hours)
        else:
            start_time = datetime.utcnow() - timedelta(hours=1)

        # Build query
        body = {
            "query": {
                "bool": {
                    "must": [
                        {"query_string": {"query": query}},
                        {"range": {"@timestamp": {"gte": start_time.isoformat()}}},
                    ]
                }
            },
            "size": size,
            "sort": [{"@timestamp": "desc"}],
        }

        if fields:
            body["_source"] = fields

        response = es.search(index=index, body=body)

        hits = []
        for hit in response["hits"]["hits"]:
            hits.append(
                {
                    "timestamp": hit["_source"].get("@timestamp"),
                    "message": hit["_source"].get("message"),
                    "level": hit["_source"].get("level"),
                    "source": hit["_source"],
                    "score": hit["_score"],
                }
            )

        logger.info("elasticsearch_search_completed", query=query, hits=len(hits))
        return hits

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "search_logs", "elasticsearch")
    except Exception as e:
        logger.error("elasticsearch_search_failed", error=str(e), query=query)
        raise ToolExecutionError("search_logs", str(e), e)


def aggregate_errors_by_field(
    field: str, index: str = "logs-*", time_range: str = "1h", min_level: str = "error"
) -> list[dict[str, Any]]:
    """
    Aggregate errors by a specific field.

    Args:
        field: Field to aggregate by (e.g., 'error.type', 'service.name')
        index: Index pattern
        time_range: Time range
        min_level: Minimum log level (error, warn, info)

    Returns:
        List of aggregated results
    """
    try:
        es = _get_es_client()

        # Parse time range
        if time_range.endswith("h"):
            hours = int(time_range[:-1])
            start_time = datetime.utcnow() - timedelta(hours=hours)
        else:
            start_time = datetime.utcnow() - timedelta(hours=1)

        body = {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"level": min_level}},
                        {"range": {"@timestamp": {"gte": start_time.isoformat()}}},
                    ]
                }
            },
            "aggs": {"by_field": {"terms": {"field": field, "size": 20}}},
            "size": 0,
        }

        response = es.search(index=index, body=body)

        aggregations = []
        for bucket in response["aggregations"]["by_field"]["buckets"]:
            aggregations.append(
                {
                    "key": bucket["key"],
                    "count": bucket["doc_count"],
                }
            )

        logger.info(
            "elasticsearch_aggregate_completed", field=field, buckets=len(aggregations)
        )
        return aggregations

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "aggregate_errors_by_field", "elasticsearch"
        )
    except Exception as e:
        logger.error("elasticsearch_aggregate_failed", error=str(e), field=field)
        raise ToolExecutionError("aggregate_errors_by_field", str(e), e)


def elasticsearch_list_indices(pattern: str = "*") -> dict[str, Any]:
    """
    List all Elasticsearch indices matching a pattern.

    Args:
        pattern: Index pattern (default: * for all indices)

    Returns:
        Dictionary with index information
    """
    try:
        es = _get_es_client()

        response = es.cat.indices(
            index=pattern, format="json", h="index,docs.count,store.size,health,status"
        )

        indices = []
        for idx in response:
            indices.append(
                {
                    "name": idx.get("index"),
                    "doc_count": int(idx.get("docs.count", 0)),
                    "size": idx.get("store.size"),
                    "health": idx.get("health"),
                    "status": idx.get("status"),
                }
            )

        logger.info(
            "elasticsearch_list_indices_completed", pattern=pattern, count=len(indices)
        )
        return {
            "index_count": len(indices),
            "indices": indices,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "elasticsearch_list_indices", "elasticsearch"
        )
    except Exception as e:
        logger.error("elasticsearch_list_indices_failed", error=str(e), pattern=pattern)
        raise ToolExecutionError("elasticsearch_list_indices", str(e), e)


def elasticsearch_get_mapping(index: str) -> dict[str, Any]:
    """
    Get the mapping (schema) for an Elasticsearch index.

    Args:
        index: Index name

    Returns:
        Index mapping as dictionary
    """
    try:
        es = _get_es_client()

        response = es.indices.get_mapping(index=index)

        # Extract mappings
        mappings = {}
        for idx_name, idx_data in response.items():
            properties = idx_data.get("mappings", {}).get("properties", {})
            fields = []

            for field_name, field_info in properties.items():
                fields.append(
                    {
                        "name": field_name,
                        "type": field_info.get("type"),
                        "fields": field_info.get("fields"),
                    }
                )

            mappings[idx_name] = {
                "field_count": len(fields),
                "fields": fields,
            }

        logger.info("elasticsearch_get_mapping_completed", index=index)
        return {
            "index": index,
            "mappings": mappings,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "elasticsearch_get_mapping", "elasticsearch"
        )
    except Exception as e:
        logger.error("elasticsearch_get_mapping_failed", error=str(e), index=index)
        raise ToolExecutionError("elasticsearch_get_mapping", str(e), e)


def elasticsearch_bulk_index(
    index: str, documents: list[dict[str, Any]], id_field: str | None = None
) -> dict[str, Any]:
    """
    Bulk index documents into Elasticsearch.

    Args:
        index: Target index name
        documents: List of documents to index
        id_field: Optional field name to use as document ID

    Returns:
        Bulk operation results
    """
    try:
        from elasticsearch.helpers import bulk

        es = _get_es_client()

        # Prepare bulk actions
        actions = []
        for doc in documents:
            action = {"_index": index, "_source": doc}

            if id_field and id_field in doc:
                action["_id"] = doc[id_field]

            actions.append(action)

        # Execute bulk operation
        success, failed = bulk(es, actions, raise_on_error=False)

        logger.info(
            "elasticsearch_bulk_index_completed",
            index=index,
            success=success,
            failed=len(failed),
        )

        return {
            "success": success,
            "failed": len(failed),
            "total": len(documents),
            "errors": failed if failed else None,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "elasticsearch_bulk_index", "elasticsearch"
        )
    except Exception as e:
        logger.error("elasticsearch_bulk_index_failed", error=str(e), index=index)
        raise ToolExecutionError("elasticsearch_bulk_index", str(e), e)


def search_elasticsearch(
    index: str, query: dict[str, Any], time_range: str = "1h", size: int = 100
) -> str:
    """
    Search Elasticsearch using a full Elasticsearch Query DSL query.

    Args:
        index: Index pattern to search (e.g., "logs-*", "app-logs-2024-*")
        query: Full Elasticsearch Query DSL query as a dictionary
        time_range: Time range for @timestamp filter (e.g., '15m', '1h', '24h')
        size: Maximum number of results to return (default: 100)

    Returns:
        JSON string with search results including hits, total count, and aggregations

    Example query:
        {
            "query": {
                "bool": {
                    "must": [
                        {"match": {"message": "error"}},
                        {"term": {"level": "ERROR"}}
                    ]
                }
            }
        }
    """
    try:
        import json

        es = _get_es_client()

        # Parse time range
        if time_range.endswith("m"):
            minutes = int(time_range[:-1])
            start_time = datetime.utcnow() - timedelta(minutes=minutes)
        elif time_range.endswith("h"):
            hours = int(time_range[:-1])
            start_time = datetime.utcnow() - timedelta(hours=hours)
        elif time_range.endswith("d"):
            days = int(time_range[:-1])
            start_time = datetime.utcnow() - timedelta(days=days)
        else:
            start_time = datetime.utcnow() - timedelta(hours=1)

        # Build search body with time filter
        search_body = query.copy()

        # Add time range filter if @timestamp field exists
        if "query" in search_body:
            if "bool" not in search_body["query"]:
                search_body["query"] = {"bool": {"must": [search_body["query"]]}}

            if "must" not in search_body["query"]["bool"]:
                search_body["query"]["bool"]["must"] = []

            search_body["query"]["bool"]["must"].append(
                {"range": {"@timestamp": {"gte": start_time.isoformat()}}}
            )
        else:
            search_body["query"] = {
                "bool": {
                    "must": [{"range": {"@timestamp": {"gte": start_time.isoformat()}}}]
                }
            }

        search_body["size"] = size
        search_body["sort"] = [{"@timestamp": "desc"}]

        # Execute search
        response = es.search(index=index, body=search_body)

        # Format results
        results = {
            "total_hits": response["hits"]["total"]["value"],
            "took_ms": response["took"],
            "hits": [],
            "aggregations": response.get("aggregations", {}),
        }

        for hit in response["hits"]["hits"]:
            results["hits"].append(
                {
                    "timestamp": hit["_source"].get("@timestamp"),
                    "index": hit["_index"],
                    "id": hit["_id"],
                    "score": hit["_score"],
                    "source": hit["_source"],
                }
            )

        logger.info(
            "search_elasticsearch_completed", index=index, hits=len(results["hits"])
        )
        return json.dumps(results, indent=2, default=str)

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "search_elasticsearch", "elasticsearch"
        )
    except Exception as e:
        logger.error("search_elasticsearch_failed", error=str(e), index=index)
        raise ToolExecutionError("search_elasticsearch", str(e), e)


def get_elasticsearch_stats(index: str | None = None) -> str:
    """
    Get Elasticsearch cluster and index statistics.

    Args:
        index: Optional index pattern to get stats for specific indices.
               If None, returns cluster-wide stats.

    Returns:
        JSON string with cluster health, node info, and index statistics
    """
    try:
        import json

        es = _get_es_client()

        stats = {}

        # Get cluster health
        health = es.cluster.health()
        stats["cluster"] = {
            "name": health["cluster_name"],
            "status": health["status"],
            "number_of_nodes": health["number_of_nodes"],
            "number_of_data_nodes": health["number_of_data_nodes"],
            "active_primary_shards": health["active_primary_shards"],
            "active_shards": health["active_shards"],
            "relocating_shards": health["relocating_shards"],
            "initializing_shards": health["initializing_shards"],
            "unassigned_shards": health["unassigned_shards"],
            "delayed_unassigned_shards": health.get("delayed_unassigned_shards", 0),
            "number_of_pending_tasks": health["number_of_pending_tasks"],
            "number_of_in_flight_fetch": health["number_of_in_flight_fetch"],
        }

        # Get cluster stats
        cluster_stats = es.cluster.stats()
        stats["storage"] = {
            "total_bytes": cluster_stats["indices"]["store"]["size_in_bytes"],
            "total_gb": round(
                cluster_stats["indices"]["store"]["size_in_bytes"] / (1024**3), 2
            ),
        }

        stats["documents"] = {
            "total_count": cluster_stats["indices"]["docs"]["count"],
            "deleted_count": cluster_stats["indices"]["docs"]["deleted"],
        }

        # Get index-specific stats if requested
        if index:
            index_stats = es.indices.stats(index=index)

            stats["indices"] = {}
            for idx_name, idx_data in index_stats["indices"].items():
                stats["indices"][idx_name] = {
                    "primaries": {
                        "docs_count": idx_data["primaries"]["docs"]["count"],
                        "docs_deleted": idx_data["primaries"]["docs"]["deleted"],
                        "store_size_bytes": idx_data["primaries"]["store"][
                            "size_in_bytes"
                        ],
                        "store_size_mb": round(
                            idx_data["primaries"]["store"]["size_in_bytes"] / (1024**2),
                            2,
                        ),
                    },
                    "total": {
                        "docs_count": idx_data["total"]["docs"]["count"],
                        "store_size_bytes": idx_data["total"]["store"]["size_in_bytes"],
                        "store_size_mb": round(
                            idx_data["total"]["store"]["size_in_bytes"] / (1024**2), 2
                        ),
                    },
                    "health": "N/A",  # Would need separate call to get per-index health
                }

            # Get index health
            index_health = es.cat.indices(
                index=index, format="json", h="index,health,status"
            )
            for idx in index_health:
                idx_name = idx["index"]
                if idx_name in stats["indices"]:
                    stats["indices"][idx_name]["health"] = idx["health"]
                    stats["indices"][idx_name]["status"] = idx["status"]

        logger.info("get_elasticsearch_stats_completed", index=index or "cluster")
        return json.dumps(stats, indent=2, default=str)

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "get_elasticsearch_stats", "elasticsearch"
        )
    except Exception as e:
        logger.error("get_elasticsearch_stats_failed", error=str(e), index=index)
        raise ToolExecutionError("get_elasticsearch_stats", str(e), e)


# List of all Elasticsearch tools for registration
ELASTICSEARCH_TOOLS = [
    search_logs,
    aggregate_errors_by_field,
    elasticsearch_list_indices,
    elasticsearch_get_mapping,
    elasticsearch_bulk_index,
    search_elasticsearch,
    get_elasticsearch_stats,
]

"""
Log Analysis Tools - Partition-first log analysis across multiple backends.

These tools implement the "never load all data" philosophy:
1. Always get statistics first
2. Use intelligent sampling strategies
3. Progressive drill-down based on findings

Supported backends: Elasticsearch, Coralogix, Datadog, Splunk, CloudWatch
"""

import json
import os
import re
from abc import ABC, abstractmethod
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from agents import function_tool

from ..core.config_required import handle_integration_not_configured
from ..core.errors import ToolExecutionError
from ..core.execution_context import get_execution_context
from ..core.integration_errors import IntegrationNotConfiguredError
from ..core.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Time Range Parsing Utilities
# =============================================================================


def _parse_time_range(time_range: str) -> timedelta:
    """Parse time range string to timedelta."""
    if time_range.endswith("m"):
        return timedelta(minutes=int(time_range[:-1]))
    elif time_range.endswith("h"):
        return timedelta(hours=int(time_range[:-1]))
    elif time_range.endswith("d"):
        return timedelta(days=int(time_range[:-1]))
    else:
        return timedelta(hours=1)


def _get_time_bounds(time_range: str) -> tuple:
    """Get start and end time from time range string."""
    end_time = datetime.utcnow()
    delta = _parse_time_range(time_range)
    start_time = end_time - delta
    return start_time, end_time


# =============================================================================
# Backend Abstraction Layer
# =============================================================================


class LogBackend(ABC):
    """Abstract base class for log backends."""

    @abstractmethod
    def get_statistics(
        self, service: str | None, start_time: datetime, end_time: datetime, **kwargs
    ) -> dict[str, Any]:
        """Get aggregated statistics without raw logs."""
        pass

    @abstractmethod
    def sample_logs(
        self,
        strategy: str,
        service: str | None,
        start_time: datetime,
        end_time: datetime,
        sample_size: int,
        **kwargs,
    ) -> dict[str, Any]:
        """Sample logs using specified strategy."""
        pass

    @abstractmethod
    def search_by_pattern(
        self,
        pattern: str,
        service: str | None,
        start_time: datetime,
        end_time: datetime,
        max_results: int,
        **kwargs,
    ) -> dict[str, Any]:
        """Search logs by pattern."""
        pass

    @abstractmethod
    def get_logs_around_time(
        self,
        timestamp: datetime,
        window_before: int,
        window_after: int,
        service: str | None,
        **kwargs,
    ) -> dict[str, Any]:
        """Get logs around a specific timestamp."""
        pass


class ElasticsearchBackend(LogBackend):
    """Elasticsearch log backend."""

    def _get_client(self):
        """Get Elasticsearch client."""
        try:
            from elasticsearch import Elasticsearch
        except ImportError:
            raise ToolExecutionError(
                "elasticsearch", "elasticsearch package not installed"
            )

        context = get_execution_context()
        if context:
            config = context.get_integration_config("elasticsearch")
            if config and config.get("url"):
                return Elasticsearch(
                    [config["url"]],
                    basic_auth=(config.get("username"), config.get("password")),
                )

        if os.getenv("ELASTICSEARCH_URL"):
            return Elasticsearch(
                [os.getenv("ELASTICSEARCH_URL")],
                basic_auth=(
                    os.getenv("ELASTICSEARCH_USERNAME"),
                    os.getenv("ELASTICSEARCH_PASSWORD"),
                ),
            )

        raise IntegrationNotConfiguredError(
            integration_id="elasticsearch",
            tool_id="log_analysis_tools",
            missing_fields=["url", "username", "password"],
        )

    def get_statistics(
        self,
        service: str | None,
        start_time: datetime,
        end_time: datetime,
        index_pattern: str = "logs-*",
        **kwargs,
    ) -> dict[str, Any]:
        """Get Elasticsearch log statistics."""
        es = self._get_client()

        # Build query with optional service filter
        must_clauses = [
            {
                "range": {
                    "@timestamp": {
                        "gte": start_time.isoformat(),
                        "lte": end_time.isoformat(),
                    }
                }
            }
        ]
        if service:
            must_clauses.append({"term": {"service.name": service}})

        body = {
            "query": {"bool": {"must": must_clauses}},
            "size": 0,
            "aggs": {
                "severity_counts": {"terms": {"field": "level", "size": 10}},
                "top_patterns": {"terms": {"field": "message.keyword", "size": 10}},
                "time_buckets": {
                    "date_histogram": {"field": "@timestamp", "fixed_interval": "5m"}
                },
                "top_services": {"terms": {"field": "service.name", "size": 10}},
                "error_count": {
                    "filter": {
                        "terms": {"level": ["ERROR", "CRITICAL", "error", "critical"]}
                    }
                },
            },
        }

        response = es.search(index=index_pattern, body=body)

        total_count = response["hits"]["total"]["value"]
        error_count = response["aggregations"]["error_count"]["doc_count"]

        severity_dist = {
            b["key"]: b["doc_count"]
            for b in response["aggregations"]["severity_counts"]["buckets"]
        }

        top_patterns = [
            {"pattern": b["key"][:100], "count": b["doc_count"]}
            for b in response["aggregations"]["top_patterns"]["buckets"]
        ]

        time_buckets = [
            {"timestamp": b["key_as_string"], "count": b["doc_count"]}
            for b in response["aggregations"]["time_buckets"]["buckets"]
        ]

        top_services = [
            {"service": b["key"], "count": b["doc_count"]}
            for b in response["aggregations"]["top_services"]["buckets"]
        ]

        return {
            "total_count": total_count,
            "error_count": error_count,
            "error_rate_percent": (
                round(error_count / total_count * 100, 2) if total_count > 0 else 0
            ),
            "severity_distribution": severity_dist,
            "top_error_patterns": top_patterns,
            "time_buckets": time_buckets,
            "top_services": top_services,
        }

    def sample_logs(
        self,
        strategy: str,
        service: str | None,
        start_time: datetime,
        end_time: datetime,
        sample_size: int,
        index_pattern: str = "logs-*",
        anomaly_timestamp: datetime | None = None,
        window_seconds: int = 60,
        **kwargs,
    ) -> dict[str, Any]:
        """Sample Elasticsearch logs."""
        es = self._get_client()

        must_clauses = [
            {
                "range": {
                    "@timestamp": {
                        "gte": start_time.isoformat(),
                        "lte": end_time.isoformat(),
                    }
                }
            }
        ]
        if service:
            must_clauses.append({"term": {"service.name": service}})

        # Apply strategy-specific filters
        if strategy == "errors_only":
            must_clauses.append(
                {"terms": {"level": ["ERROR", "CRITICAL", "error", "critical"]}}
            )
        elif strategy == "around_anomaly" and anomaly_timestamp:
            window_start = anomaly_timestamp - timedelta(seconds=window_seconds)
            window_end = anomaly_timestamp + timedelta(seconds=window_seconds)
            must_clauses = [
                {
                    "range": {
                        "@timestamp": {
                            "gte": window_start.isoformat(),
                            "lte": window_end.isoformat(),
                        }
                    }
                }
            ]
            if service:
                must_clauses.append({"term": {"service.name": service}})

        body = {
            "query": {"bool": {"must": must_clauses}},
            "size": sample_size,
            "sort": [{"@timestamp": "desc"}],
        }

        # For first_last strategy, get first and last N/2 logs
        if strategy == "first_last":
            body["size"] = sample_size // 2
            body["sort"] = [{"@timestamp": "asc"}]
            first_response = es.search(index=index_pattern, body=body)

            body["sort"] = [{"@timestamp": "desc"}]
            last_response = es.search(index=index_pattern, body=body)

            hits = first_response["hits"]["hits"] + last_response["hits"]["hits"]
            total_matched = first_response["hits"]["total"]["value"]
        elif strategy == "random":
            body["query"]["bool"]["must"].append(
                {"function_score": {"random_score": {}}}
            )
            response = es.search(index=index_pattern, body=body)
            hits = response["hits"]["hits"]
            total_matched = response["hits"]["total"]["value"]
        else:
            response = es.search(index=index_pattern, body=body)
            hits = response["hits"]["hits"]
            total_matched = response["hits"]["total"]["value"]

        logs = []
        for hit in hits[:sample_size]:
            source = hit["_source"]
            logs.append(
                {
                    "timestamp": source.get("@timestamp"),
                    "service": (
                        source.get("service", {}).get("name")
                        if isinstance(source.get("service"), dict)
                        else source.get("service")
                    ),
                    "level": source.get("level"),
                    "message": source.get("message", "")[:500],
                    "trace_id": source.get("trace_id") or source.get("traceId"),
                }
            )

        return {
            "strategy_used": strategy,
            "sample_size": len(logs),
            "total_matched": total_matched,
            "coverage_percent": (
                round(len(logs) / total_matched * 100, 2) if total_matched > 0 else 0
            ),
            "logs": logs,
        }

    def search_by_pattern(
        self,
        pattern: str,
        service: str | None,
        start_time: datetime,
        end_time: datetime,
        max_results: int,
        index_pattern: str = "logs-*",
        **kwargs,
    ) -> dict[str, Any]:
        """Search Elasticsearch by pattern."""
        es = self._get_client()

        must_clauses = [
            {
                "range": {
                    "@timestamp": {
                        "gte": start_time.isoformat(),
                        "lte": end_time.isoformat(),
                    }
                }
            },
            {"query_string": {"query": f"*{pattern}*", "default_field": "message"}},
        ]
        if service:
            must_clauses.append({"term": {"service.name": service}})

        body = {
            "query": {"bool": {"must": must_clauses}},
            "size": max_results,
            "sort": [{"@timestamp": "desc"}],
            "highlight": {
                "fields": {"message": {}},
                "pre_tags": [">>>"],
                "post_tags": ["<<<"],
            },
        }

        response = es.search(index=index_pattern, body=body)

        matches = []
        for hit in response["hits"]["hits"]:
            source = hit["_source"]
            matches.append(
                {
                    "timestamp": source.get("@timestamp"),
                    "service": (
                        source.get("service", {}).get("name")
                        if isinstance(source.get("service"), dict)
                        else source.get("service")
                    ),
                    "level": source.get("level"),
                    "message": source.get("message", "")[:500],
                    "highlight": hit.get("highlight", {}).get("message", []),
                }
            )

        return {
            "pattern": pattern,
            "total_matches": response["hits"]["total"]["value"],
            "returned": len(matches),
            "matches": matches,
        }

    def get_logs_around_time(
        self,
        timestamp: datetime,
        window_before: int,
        window_after: int,
        service: str | None,
        index_pattern: str = "logs-*",
        max_results: int = 100,
        **kwargs,
    ) -> dict[str, Any]:
        """Get Elasticsearch logs around a timestamp."""
        es = self._get_client()

        window_start = timestamp - timedelta(seconds=window_before)
        window_end = timestamp + timedelta(seconds=window_after)

        must_clauses = [
            {
                "range": {
                    "@timestamp": {
                        "gte": window_start.isoformat(),
                        "lte": window_end.isoformat(),
                    }
                }
            }
        ]
        if service:
            must_clauses.append({"term": {"service.name": service}})

        body = {
            "query": {"bool": {"must": must_clauses}},
            "size": max_results,
            "sort": [{"@timestamp": "asc"}],
        }

        response = es.search(index=index_pattern, body=body)

        logs_before = []
        logs_at = []
        logs_after = []

        for hit in response["hits"]["hits"]:
            source = hit["_source"]
            log_ts_str = source.get("@timestamp", "")

            log_entry = {
                "timestamp": log_ts_str,
                "service": (
                    source.get("service", {}).get("name")
                    if isinstance(source.get("service"), dict)
                    else source.get("service")
                ),
                "level": source.get("level"),
                "message": source.get("message", "")[:300],
            }

            try:
                log_ts = datetime.fromisoformat(
                    log_ts_str.replace("Z", "+00:00")
                ).replace(tzinfo=None)
                if log_ts < timestamp - timedelta(seconds=1):
                    logs_before.append(log_entry)
                elif log_ts > timestamp + timedelta(seconds=1):
                    logs_after.append(log_entry)
                else:
                    logs_at.append(log_entry)
            except (ValueError, TypeError):
                logs_at.append(log_entry)

        return {
            "target_timestamp": timestamp.isoformat(),
            "window": {
                "start": window_start.isoformat(),
                "end": window_end.isoformat(),
            },
            "total_logs": len(logs_before) + len(logs_at) + len(logs_after),
            "logs_before": logs_before[-20:],
            "logs_at": logs_at[:20],
            "logs_after": logs_after[:20],
        }


class CoralogixBackend(LogBackend):
    """Coralogix log backend."""

    def _get_config(self) -> dict:
        """Get Coralogix configuration."""
        context = get_execution_context()
        if context:
            config = context.get_integration_config("coralogix")
            if config and config.get("api_key"):
                api_key = config.get("api_key", "")
                region = config.get("region", "cx498")
                logger.info(
                    "coralogix_config_loaded",
                    source="execution_context",
                    region=region,
                    api_key_prefix=api_key[:10] + "..." if api_key else "None",
                    api_key_length=len(api_key),
                )
                return config

        if os.getenv("CORALOGIX_API_KEY"):
            api_key = os.getenv("CORALOGIX_API_KEY")
            region = os.getenv("CORALOGIX_REGION", "cx498")
            logger.info(
                "coralogix_config_loaded",
                source="environment",
                region=region,
                api_key_prefix=api_key[:10] + "..." if api_key else "None",
            )
            return {
                "api_key": api_key,
                "region": region,
            }

        raise IntegrationNotConfiguredError(
            integration_id="coralogix",
            tool_id="log_analysis_tools",
            missing_fields=["api_key", "region"],
        )

    def _query(
        self, query: str, start_time: datetime, end_time: datetime, limit: int = 100
    ) -> list[dict]:
        """Execute Coralogix DataPrime query."""
        import httpx

        config = self._get_config()
        region = config.get("region", "cx498")
        api_key = config["api_key"]

        url = f"https://ng-api-http.{region}.coralogix.com/api/v1/dataprime/query"

        auth_value = (
            api_key if api_key.lower().startswith("bearer ") else f"Bearer {api_key}"
        )
        headers = {"Authorization": auth_value, "Content-Type": "application/json"}

        payload = {
            "query": query,
            "metadata": {
                "startDate": start_time.isoformat() + "Z",
                "endDate": end_time.isoformat() + "Z",
                "tier": "TIER_FREQUENT_SEARCH",
            },
            "limit": limit,
        }

        logger.info(
            "coralogix_query_request",
            url=url,
            region=region,
            query=query[:200],
            api_key_prefix=api_key[:15] + "..." if api_key else "None",
            start_time=payload["metadata"]["startDate"],
            end_time=payload["metadata"]["endDate"],
        )

        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, headers=headers, json=payload)
            logger.info(
                "coralogix_query_response",
                status_code=response.status_code,
                response_length=len(response.text),
            )
            if response.status_code >= 400:
                error_detail = response.text[:1000] if response.text else "No details"
                logger.error(
                    "coralogix_query_failed",
                    status_code=response.status_code,
                    region=region,
                    api_key_prefix=api_key[:15] + "...",
                    error_detail=error_detail,
                    query=query,
                )
                raise Exception(
                    f"Coralogix API error {response.status_code} (region={region}, key={api_key[:15]}...): {error_detail}"
                )

            results = []
            for line in response.text.strip().split("\n"):
                if line.strip():
                    try:
                        obj = json.loads(line)
                        if "result" in obj and "results" in obj["result"]:
                            for item in obj["result"]["results"]:
                                # Parse userData JSON string if present
                                if "userData" in item:
                                    try:
                                        user_data = json.loads(item["userData"])
                                        # Merge labels into user_data for easier access
                                        for label in item.get("labels", []):
                                            user_data[label["key"]] = label["value"]
                                        # Merge metadata into user_data
                                        for meta in item.get("metadata", []):
                                            user_data[meta["key"]] = meta["value"]
                                        results.append(user_data)
                                    except json.JSONDecodeError:
                                        results.append(item)
                                else:
                                    results.append(item)
                    except json.JSONDecodeError:
                        continue

            return results

    def get_statistics(
        self, service: str | None, start_time: datetime, end_time: datetime, **kwargs
    ) -> dict[str, Any]:
        """Get Coralogix log statistics."""
        # Get total count and severity distribution
        query = "source logs | groupby $m.severity aggregate count() as cnt"
        if service:
            query = f"source logs | filter $l.subsystemname == '{service}' | groupby $m.severity aggregate count() as cnt"

        results = self._query(query, start_time, end_time, limit=20)

        # Coralogix returns severity as strings like "Info", "Error", "Warning", "Critical"
        # or as numeric strings "1"-"6" depending on configuration
        severity_map = {
            "1": "DEBUG",
            "2": "VERBOSE",
            "3": "INFO",
            "4": "WARNING",
            "5": "ERROR",
            "6": "CRITICAL",
        }
        error_severities = {"5", "6", "Error", "Critical", "ERROR", "CRITICAL"}
        severity_dist = {}
        total_count = 0
        error_count = 0

        for r in results:
            sev = str(r.get("severity", ""))
            cnt = int(r.get("cnt", 0))
            # Normalize severity name
            display_sev = severity_map.get(sev, sev)
            severity_dist[display_sev] = cnt
            total_count += cnt
            if sev in error_severities:
                error_count += cnt

        # Get top patterns - use unquoted uppercase severity names (Coralogix requirement)
        # Cast body to string for groupby
        pattern_query = "source logs | filter $m.severity == ERROR || $m.severity == CRITICAL | groupby $d.logRecord.body:string aggregate count() as cnt | orderby cnt desc | limit 10"
        if service:
            pattern_query = f"source logs | filter $l.subsystemname == '{service}' | filter $m.severity == ERROR || $m.severity == CRITICAL | groupby $d.logRecord.body:string aggregate count() as cnt | orderby cnt desc | limit 10"

        pattern_results = self._query(pattern_query, start_time, end_time, limit=10)
        top_patterns = [
            {"pattern": r.get("body", "")[:100], "count": r.get("cnt", 0)}
            for r in pattern_results
        ]

        return {
            "total_count": total_count,
            "error_count": error_count,
            "error_rate_percent": (
                round(error_count / total_count * 100, 2) if total_count > 0 else 0
            ),
            "severity_distribution": severity_dist,
            "top_error_patterns": top_patterns,
            "time_buckets": [],
            "top_services": [],
        }

    def sample_logs(
        self,
        strategy: str,
        service: str | None,
        start_time: datetime,
        end_time: datetime,
        sample_size: int,
        **kwargs,
    ) -> dict[str, Any]:
        """Sample Coralogix logs."""
        if strategy == "errors_only":
            # Use unquoted uppercase severity names (Coralogix requirement)
            query = f"source logs | filter $m.severity == ERROR || $m.severity == CRITICAL | limit {sample_size}"
            if service:
                query = f"source logs | filter $l.subsystemname == '{service}' | filter $m.severity == ERROR || $m.severity == CRITICAL | limit {sample_size}"
        else:
            query = f"source logs | limit {sample_size}"
            if service:
                query = f"source logs | filter $l.subsystemname == '{service}' | limit {sample_size}"

        results = self._query(query, start_time, end_time, limit=sample_size)

        logs = []
        for r in results:
            logs.append(
                {
                    "timestamp": r.get("timestamp", ""),
                    "service": r.get("subsystemname", ""),
                    "level": r.get("severity", ""),
                    "message": str(r.get("body", ""))[:500],
                    "trace_id": r.get("traceId"),
                }
            )

        return {
            "strategy_used": strategy,
            "sample_size": len(logs),
            "total_matched": len(logs),
            "coverage_percent": 100.0 if len(logs) < sample_size else 0,
            "logs": logs,
        }

    def search_by_pattern(
        self,
        pattern: str,
        service: str | None,
        start_time: datetime,
        end_time: datetime,
        max_results: int,
        **kwargs,
    ) -> dict[str, Any]:
        """Search Coralogix by pattern."""
        query = f"source logs | filter $d.logRecord.body contains '{pattern}' | limit {max_results}"
        if service:
            query = f"source logs | filter $l.subsystemname == '{service}' | filter $d.logRecord.body contains '{pattern}' | limit {max_results}"

        results = self._query(query, start_time, end_time, limit=max_results)

        matches = []
        for r in results:
            matches.append(
                {
                    "timestamp": r.get("timestamp", ""),
                    "service": r.get("subsystemname", ""),
                    "level": r.get("severity", ""),
                    "message": str(r.get("body", ""))[:500],
                }
            )

        return {
            "pattern": pattern,
            "total_matches": len(matches),
            "returned": len(matches),
            "matches": matches,
        }

    def get_logs_around_time(
        self,
        timestamp: datetime,
        window_before: int,
        window_after: int,
        service: str | None,
        max_results: int = 100,
        **kwargs,
    ) -> dict[str, Any]:
        """Get Coralogix logs around a timestamp."""
        window_start = timestamp - timedelta(seconds=window_before)
        window_end = timestamp + timedelta(seconds=window_after)

        query = f"source logs | limit {max_results}"
        if service:
            query = f"source logs | filter $l.subsystemname == '{service}' | limit {max_results}"

        results = self._query(query, window_start, window_end, limit=max_results)

        logs = []
        for r in results:
            logs.append(
                {
                    "timestamp": r.get("timestamp", ""),
                    "service": r.get("subsystemname", ""),
                    "level": r.get("severity", ""),
                    "message": str(r.get("body", ""))[:300],
                }
            )

        return {
            "target_timestamp": timestamp.isoformat(),
            "window": {
                "start": window_start.isoformat(),
                "end": window_end.isoformat(),
            },
            "total_logs": len(logs),
            "logs_before": [],
            "logs_at": logs,
            "logs_after": [],
        }


class DatadogBackend(LogBackend):
    """Datadog log backend."""

    def _get_config(self) -> dict:
        """Get Datadog configuration."""
        context = get_execution_context()
        if context:
            config = context.get_integration_config("datadog")
            if config and config.get("api_key") and config.get("app_key"):
                return config

        if os.getenv("DD_API_KEY") and os.getenv("DD_APP_KEY"):
            return {
                "api_key": os.getenv("DD_API_KEY"),
                "app_key": os.getenv("DD_APP_KEY"),
                "site": os.getenv("DD_SITE", "datadoghq.com"),
            }

        raise IntegrationNotConfiguredError(
            integration_id="datadog",
            tool_id="log_analysis_tools",
            missing_fields=["api_key", "app_key"],
        )

    def _search_logs(
        self, query: str, start_time: datetime, end_time: datetime, limit: int
    ) -> list[dict]:
        """Search Datadog logs."""
        import httpx

        config = self._get_config()
        site = config.get("site", "datadoghq.com")

        url = f"https://api.{site}/api/v2/logs/events/search"
        headers = {
            "DD-API-KEY": config["api_key"],
            "DD-APPLICATION-KEY": config["app_key"],
            "Content-Type": "application/json",
        }

        payload = {
            "filter": {
                "query": query,
                "from": start_time.isoformat() + "Z",
                "to": end_time.isoformat() + "Z",
            },
            "page": {"limit": limit},
            "sort": "-timestamp",
        }

        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            return data.get("data", [])

    def get_statistics(
        self, service: str | None, start_time: datetime, end_time: datetime, **kwargs
    ) -> dict[str, Any]:
        """Get Datadog log statistics."""
        query = "status:(error OR critical)"
        if service:
            query = f"service:{service} {query}"

        results = self._search_logs(query, start_time, end_time, 100)
        error_count = len(results)

        all_query = "*"
        if service:
            all_query = f"service:{service}"
        all_results = self._search_logs(all_query, start_time, end_time, 1)

        return {
            "total_count": len(all_results),
            "error_count": error_count,
            "error_rate_percent": 0,
            "severity_distribution": {},
            "top_error_patterns": [],
            "time_buckets": [],
            "top_services": [],
        }

    def sample_logs(
        self,
        strategy: str,
        service: str | None,
        start_time: datetime,
        end_time: datetime,
        sample_size: int,
        **kwargs,
    ) -> dict[str, Any]:
        """Sample Datadog logs."""
        if strategy == "errors_only":
            query = "status:(error OR critical)"
        else:
            query = "*"

        if service:
            query = f"service:{service} {query}"

        results = self._search_logs(query, start_time, end_time, sample_size)

        logs = []
        for r in results:
            attrs = r.get("attributes", {})
            logs.append(
                {
                    "timestamp": attrs.get("timestamp", ""),
                    "service": attrs.get("service", ""),
                    "level": attrs.get("status", ""),
                    "message": attrs.get("message", "")[:500],
                    "trace_id": attrs.get("trace_id"),
                }
            )

        return {
            "strategy_used": strategy,
            "sample_size": len(logs),
            "total_matched": len(logs),
            "coverage_percent": 100.0,
            "logs": logs,
        }

    def search_by_pattern(
        self,
        pattern: str,
        service: str | None,
        start_time: datetime,
        end_time: datetime,
        max_results: int,
        **kwargs,
    ) -> dict[str, Any]:
        """Search Datadog by pattern."""
        query = f"*{pattern}*"
        if service:
            query = f"service:{service} {query}"

        results = self._search_logs(query, start_time, end_time, max_results)

        matches = []
        for r in results:
            attrs = r.get("attributes", {})
            matches.append(
                {
                    "timestamp": attrs.get("timestamp", ""),
                    "service": attrs.get("service", ""),
                    "level": attrs.get("status", ""),
                    "message": attrs.get("message", "")[:500],
                }
            )

        return {
            "pattern": pattern,
            "total_matches": len(matches),
            "returned": len(matches),
            "matches": matches,
        }

    def get_logs_around_time(
        self,
        timestamp: datetime,
        window_before: int,
        window_after: int,
        service: str | None,
        max_results: int = 100,
        **kwargs,
    ) -> dict[str, Any]:
        """Get Datadog logs around a timestamp."""
        window_start = timestamp - timedelta(seconds=window_before)
        window_end = timestamp + timedelta(seconds=window_after)

        query = "*"
        if service:
            query = f"service:{service}"

        results = self._search_logs(query, window_start, window_end, max_results)

        logs = []
        for r in results:
            attrs = r.get("attributes", {})
            logs.append(
                {
                    "timestamp": attrs.get("timestamp", ""),
                    "service": attrs.get("service", ""),
                    "level": attrs.get("status", ""),
                    "message": attrs.get("message", "")[:300],
                }
            )

        return {
            "target_timestamp": timestamp.isoformat(),
            "window": {
                "start": window_start.isoformat(),
                "end": window_end.isoformat(),
            },
            "total_logs": len(logs),
            "logs_before": [],
            "logs_at": logs,
            "logs_after": [],
        }


class CloudWatchBackend(LogBackend):
    """AWS CloudWatch Logs backend."""

    def _get_client(self):
        """Get CloudWatch Logs client."""
        try:
            import boto3
        except ImportError:
            raise ToolExecutionError("cloudwatch", "boto3 package not installed")

        context = get_execution_context()
        if context:
            config = context.get_integration_config("aws")
            if config:
                return boto3.client(
                    "logs",
                    region_name=config.get("region", "us-west-2"),
                    aws_access_key_id=config.get("access_key_id"),
                    aws_secret_access_key=config.get("secret_access_key"),
                )

        return boto3.client("logs")

    def get_statistics(
        self,
        service: str | None,
        start_time: datetime,
        end_time: datetime,
        log_group: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Get CloudWatch log statistics using Logs Insights."""
        client = self._get_client()

        log_group_name = (
            log_group or f"/aws/lambda/{service}" if service else "/aws/lambda"
        )

        query = """
        fields @timestamp, @message, @logStream
        | stats count() as total,
                count(*) filter @message like /(?i)error|exception|fail/ as error_count
        """

        response = client.start_query(
            logGroupName=log_group_name,
            startTime=int(start_time.timestamp()),
            endTime=int(end_time.timestamp()),
            queryString=query,
            limit=1,
        )

        query_id = response["queryId"]

        import time

        for _ in range(30):
            result = client.get_query_results(queryId=query_id)
            if result["status"] == "Complete":
                break
            time.sleep(1)

        total_count = 0
        error_count = 0

        for row in result.get("results", []):
            for field in row:
                if field["field"] == "total":
                    total_count = int(field["value"])
                elif field["field"] == "error_count":
                    error_count = int(field["value"])

        return {
            "total_count": total_count,
            "error_count": error_count,
            "error_rate_percent": (
                round(error_count / total_count * 100, 2) if total_count > 0 else 0
            ),
            "severity_distribution": {},
            "top_error_patterns": [],
            "time_buckets": [],
            "top_services": [],
        }

    def sample_logs(
        self,
        strategy: str,
        service: str | None,
        start_time: datetime,
        end_time: datetime,
        sample_size: int,
        log_group: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Sample CloudWatch logs."""
        client = self._get_client()

        log_group_name = (
            log_group or f"/aws/lambda/{service}" if service else "/aws/lambda"
        )

        if strategy == "errors_only":
            filter_pattern = "?ERROR ?Exception ?error ?exception ?fail"
        else:
            filter_pattern = ""

        response = client.filter_log_events(
            logGroupName=log_group_name,
            startTime=int(start_time.timestamp() * 1000),
            endTime=int(end_time.timestamp() * 1000),
            filterPattern=filter_pattern,
            limit=sample_size,
        )

        logs = []
        for event in response.get("events", []):
            logs.append(
                {
                    "timestamp": datetime.fromtimestamp(
                        event["timestamp"] / 1000
                    ).isoformat(),
                    "service": service or "unknown",
                    "level": (
                        "ERROR"
                        if "error" in event.get("message", "").lower()
                        else "INFO"
                    ),
                    "message": event.get("message", "")[:500],
                    "trace_id": None,
                }
            )

        return {
            "strategy_used": strategy,
            "sample_size": len(logs),
            "total_matched": len(logs),
            "coverage_percent": 100.0,
            "logs": logs,
        }

    def search_by_pattern(
        self,
        pattern: str,
        service: str | None,
        start_time: datetime,
        end_time: datetime,
        max_results: int,
        log_group: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Search CloudWatch by pattern."""
        client = self._get_client()

        log_group_name = (
            log_group or f"/aws/lambda/{service}" if service else "/aws/lambda"
        )

        response = client.filter_log_events(
            logGroupName=log_group_name,
            startTime=int(start_time.timestamp() * 1000),
            endTime=int(end_time.timestamp() * 1000),
            filterPattern=pattern,
            limit=max_results,
        )

        matches = []
        for event in response.get("events", []):
            matches.append(
                {
                    "timestamp": datetime.fromtimestamp(
                        event["timestamp"] / 1000
                    ).isoformat(),
                    "service": service or "unknown",
                    "level": "INFO",
                    "message": event.get("message", "")[:500],
                }
            )

        return {
            "pattern": pattern,
            "total_matches": len(matches),
            "returned": len(matches),
            "matches": matches,
        }

    def get_logs_around_time(
        self,
        timestamp: datetime,
        window_before: int,
        window_after: int,
        service: str | None,
        log_group: str | None = None,
        max_results: int = 100,
        **kwargs,
    ) -> dict[str, Any]:
        """Get CloudWatch logs around a timestamp."""
        client = self._get_client()

        window_start = timestamp - timedelta(seconds=window_before)
        window_end = timestamp + timedelta(seconds=window_after)
        log_group_name = (
            log_group or f"/aws/lambda/{service}" if service else "/aws/lambda"
        )

        response = client.filter_log_events(
            logGroupName=log_group_name,
            startTime=int(window_start.timestamp() * 1000),
            endTime=int(window_end.timestamp() * 1000),
            limit=max_results,
        )

        logs = []
        for event in response.get("events", []):
            logs.append(
                {
                    "timestamp": datetime.fromtimestamp(
                        event["timestamp"] / 1000
                    ).isoformat(),
                    "service": service or "unknown",
                    "level": "INFO",
                    "message": event.get("message", "")[:300],
                }
            )

        return {
            "target_timestamp": timestamp.isoformat(),
            "window": {
                "start": window_start.isoformat(),
                "end": window_end.isoformat(),
            },
            "total_logs": len(logs),
            "logs_before": [],
            "logs_at": logs,
            "logs_after": [],
        }


class SplunkBackend(LogBackend):
    """Splunk log backend."""

    def _get_config(self) -> dict:
        """Get Splunk configuration."""
        context = get_execution_context()
        if context:
            config = context.get_integration_config("splunk")
            if config and config.get("host") and config.get("token"):
                return config

        if os.getenv("SPLUNK_HOST") and os.getenv("SPLUNK_TOKEN"):
            return {
                "host": os.getenv("SPLUNK_HOST"),
                "token": os.getenv("SPLUNK_TOKEN"),
                "port": int(os.getenv("SPLUNK_PORT", "8089")),
            }

        raise IntegrationNotConfiguredError(
            integration_id="splunk",
            tool_id="log_analysis_tools",
            missing_fields=["host", "token"],
        )

    def _search(
        self, query: str, start_time: datetime, end_time: datetime
    ) -> list[dict]:
        """Execute Splunk search."""
        import httpx

        config = self._get_config()
        url = (
            f"https://{config['host']}:{config.get('port', 8089)}/services/search/jobs"
        )

        headers = {
            "Authorization": f"Bearer {config['token']}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        search_query = f"search {query} earliest={start_time.strftime('%Y-%m-%dT%H:%M:%S')} latest={end_time.strftime('%Y-%m-%dT%H:%M:%S')}"

        with httpx.Client(timeout=60.0, verify=False) as client:
            response = client.post(
                url,
                headers=headers,
                data={
                    "search": search_query,
                    "output_mode": "json",
                    "exec_mode": "oneshot",
                },
            )
            response.raise_for_status()
            data = response.json()
            return data.get("results", [])

    def get_statistics(
        self, service: str | None, start_time: datetime, end_time: datetime, **kwargs
    ) -> dict[str, Any]:
        """Get Splunk log statistics."""
        query = 'index=* | stats count as total, count(eval(log_level="ERROR" OR log_level="CRITICAL")) as error_count'
        if service:
            query = f'index=* service="{service}" | stats count as total, count(eval(log_level="ERROR" OR log_level="CRITICAL")) as error_count'

        try:
            results = self._search(query, start_time, end_time)
            total = int(results[0].get("total", 0)) if results else 0
            errors = int(results[0].get("error_count", 0)) if results else 0
        except Exception:
            total, errors = 0, 0

        return {
            "total_count": total,
            "error_count": errors,
            "error_rate_percent": round(errors / total * 100, 2) if total > 0 else 0,
            "severity_distribution": {},
            "top_error_patterns": [],
            "time_buckets": [],
            "top_services": [],
        }

    def sample_logs(
        self,
        strategy: str,
        service: str | None,
        start_time: datetime,
        end_time: datetime,
        sample_size: int,
        **kwargs,
    ) -> dict[str, Any]:
        """Sample Splunk logs."""
        if strategy == "errors_only":
            query = (
                f"index=* (log_level=ERROR OR log_level=CRITICAL) | head {sample_size}"
            )
        else:
            query = f"index=* | head {sample_size}"

        if service:
            query = query.replace("index=*", f'index=* service="{service}"')

        try:
            results = self._search(query, start_time, end_time)
        except Exception:
            results = []

        logs = [
            {
                "timestamp": r.get("_time", ""),
                "service": r.get("service", ""),
                "level": r.get("log_level", "INFO"),
                "message": r.get("_raw", "")[:500],
                "trace_id": r.get("trace_id"),
            }
            for r in results
        ]

        return {
            "strategy_used": strategy,
            "sample_size": len(logs),
            "total_matched": len(logs),
            "coverage_percent": 100.0,
            "logs": logs,
        }

    def search_by_pattern(
        self,
        pattern: str,
        service: str | None,
        start_time: datetime,
        end_time: datetime,
        max_results: int,
        **kwargs,
    ) -> dict[str, Any]:
        """Search Splunk by pattern."""
        query = f'index=* "{pattern}" | head {max_results}'
        if service:
            query = query.replace("index=*", f'index=* service="{service}"')

        try:
            results = self._search(query, start_time, end_time)
        except Exception:
            results = []

        return {
            "pattern": pattern,
            "total_matches": len(results),
            "returned": len(results),
            "matches": [
                {
                    "timestamp": r.get("_time"),
                    "service": r.get("service"),
                    "level": r.get("log_level"),
                    "message": r.get("_raw", "")[:500],
                }
                for r in results
            ],
        }

    def get_logs_around_time(
        self,
        timestamp: datetime,
        window_before: int,
        window_after: int,
        service: str | None,
        max_results: int = 100,
        **kwargs,
    ) -> dict[str, Any]:
        """Get Splunk logs around a timestamp."""
        window_start = timestamp - timedelta(seconds=window_before)
        window_end = timestamp + timedelta(seconds=window_after)

        query = f"index=* | head {max_results}"
        if service:
            query = query.replace("index=*", f'index=* service="{service}"')

        try:
            results = self._search(query, window_start, window_end)
        except Exception:
            results = []

        return {
            "target_timestamp": timestamp.isoformat(),
            "window": {
                "start": window_start.isoformat(),
                "end": window_end.isoformat(),
            },
            "total_logs": len(results),
            "logs_before": [],
            "logs_at": [
                {"timestamp": r.get("_time"), "message": r.get("_raw", "")[:300]}
                for r in results
            ],
            "logs_after": [],
        }


# =============================================================================
# Backend Factory
# =============================================================================


def _get_backend(log_source: str) -> LogBackend:
    """Get the appropriate log backend."""
    if log_source == "auto":
        context = get_execution_context()
        if context:
            if context.get_integration_config("elasticsearch"):
                return ElasticsearchBackend()
            if context.get_integration_config("coralogix"):
                return CoralogixBackend()
            if context.get_integration_config("datadog"):
                return DatadogBackend()
            if context.get_integration_config("splunk"):
                return SplunkBackend()

        if os.getenv("ELASTICSEARCH_URL"):
            return ElasticsearchBackend()
        if os.getenv("CORALOGIX_API_KEY"):
            return CoralogixBackend()
        if os.getenv("DD_API_KEY"):
            return DatadogBackend()
        if os.getenv("SPLUNK_HOST"):
            return SplunkBackend()

        return CloudWatchBackend()

    backends = {
        "elasticsearch": ElasticsearchBackend,
        "coralogix": CoralogixBackend,
        "datadog": DatadogBackend,
        "splunk": SplunkBackend,
        "cloudwatch": CloudWatchBackend,
    }

    backend_class = backends.get(log_source.lower())
    if not backend_class:
        raise ToolExecutionError("log_analysis", f"Unknown log source: {log_source}")

    return backend_class()


# =============================================================================
# Tool Functions
# =============================================================================


@function_tool
def get_log_statistics(
    service: str | None = None,
    time_range: str = "1h",
    log_source: str = "auto",
    index_pattern: str | None = None,
    log_group: str | None = None,
) -> str:
    """
    Get aggregated statistics about logs WITHOUT returning raw log entries.

    ALWAYS call this FIRST before any log analysis to understand:
    - Total log volume (to decide if sampling is needed)
    - Error rate and severity distribution
    - Top error patterns and their counts
    - Most active services/sources

    This is a MANDATORY first step - never jump to raw log searches.

    Example:
        get_log_statistics(service="payment-service", time_range="1h")

    Args:
        service: Optional service name to filter logs
        time_range: Time range to analyze (e.g., '15m', '1h', '24h')
        log_source: Log backend to query. Options:
            - 'auto': Auto-detect based on configured integrations (default)
            - 'elasticsearch': Query Elasticsearch/OpenSearch
            - 'coralogix': Query Coralogix
            - 'datadog': Query Datadog Logs
            - 'splunk': Query Splunk
            - 'cloudwatch': Query AWS CloudWatch Logs
        index_pattern: [Elasticsearch only] Index pattern (e.g., 'logs-*', 'app-logs-2024.*')
        log_group: [CloudWatch only] Log group name (e.g., '/aws/lambda/my-function')

    Returns:
        JSON with:
        - total_count: Total log entries in time range
        - error_count: Logs with ERROR/CRITICAL severity
        - error_rate_percent: Error rate as percentage
        - severity_distribution: Count by severity level
        - top_error_patterns: Top 10 error message patterns with counts
        - top_services: Top 10 services by log volume
        - time_buckets: Log volume per time bucket (for spike detection)
        - recommendation: What to do next based on volume
    """
    try:
        start_time, end_time = _get_time_bounds(time_range)
        backend = _get_backend(log_source)

        kwargs = {}
        if index_pattern:
            kwargs["index_pattern"] = index_pattern
        if log_group:
            kwargs["log_group"] = log_group

        result = backend.get_statistics(service, start_time, end_time, **kwargs)

        # Add recommendation based on volume
        total = result.get("total_count", 0)
        if total > 100000:
            result["recommendation"] = (
                f"High volume ({total:,} logs). Use narrow time range and sampling."
            )
        elif total > 10000:
            result["recommendation"] = (
                f"Moderate volume ({total:,} logs). Sampling recommended."
            )
        else:
            result["recommendation"] = (
                f"Low volume ({total:,} logs). Safe to sample errors directly."
            )

        result["time_range"] = time_range
        result["log_source"] = log_source

        logger.info(
            "get_log_statistics_completed",
            service=service,
            total=total,
            errors=result.get("error_count", 0),
        )
        return json.dumps(result, indent=2, default=str)

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "get_log_statistics")
    except Exception as e:
        logger.error("get_log_statistics_failed", error=str(e), service=service)
        return json.dumps({"error": str(e), "tool": "get_log_statistics"})


@function_tool
def sample_logs(
    strategy: str = "errors_only",
    service: str | None = None,
    time_range: str = "1h",
    sample_size: int = 50,
    anomaly_timestamp: str | None = None,
    window_seconds: int = 60,
    log_source: str = "auto",
    index_pattern: str | None = None,
    log_group: str | None = None,
    severity_filter: str | None = None,
) -> str:
    """
    Sample logs using intelligent strategies to get representative data.

    NEVER request all logs - use this tool to get a manageable sample.

    Example:
        sample_logs(strategy="errors_only", service="api-gateway", time_range="30m")

    Strategies:
    - errors_only: Only return ERROR and CRITICAL logs (best for incident investigation)
    - around_anomaly: Logs within window of a specific timestamp (requires anomaly_timestamp)

    Args:
        strategy: Sampling strategy ('errors_only' or 'around_anomaly')
        service: Optional service name to filter
        time_range: Time range to sample from (e.g., '15m', '1h', '24h')
        sample_size: Maximum number of logs to return (default 50)
        anomaly_timestamp: [around_anomaly only] ISO timestamp (e.g., '2024-01-15T10:32:45Z')
        window_seconds: [around_anomaly only] Seconds before/after anomaly (default 60)
        log_source: Log backend ('auto', 'elasticsearch', 'coralogix', 'datadog', 'splunk', 'cloudwatch')
        index_pattern: [Elasticsearch only] Index pattern (e.g., 'logs-*')
        log_group: [CloudWatch only] Log group name
        severity_filter: Minimum severity level (e.g., 'WARNING', 'ERROR')

    Returns:
        JSON with sampled logs and sampling metadata
    """
    try:
        start_time, end_time = _get_time_bounds(time_range)
        backend = _get_backend(log_source)

        kwargs = {
            "window_seconds": window_seconds,
        }
        if index_pattern:
            kwargs["index_pattern"] = index_pattern
        if log_group:
            kwargs["log_group"] = log_group
        if anomaly_timestamp:
            kwargs["anomaly_timestamp"] = datetime.fromisoformat(
                anomaly_timestamp.replace("Z", "")
            )
        if severity_filter:
            kwargs["severity_filter"] = severity_filter

        result = backend.sample_logs(
            strategy, service, start_time, end_time, sample_size, **kwargs
        )

        # Add pattern summary from sampled logs
        if result.get("logs"):
            messages = [log.get("message", "") for log in result["logs"]]
            pattern_counts = Counter()
            for msg in messages:
                # Simple pattern extraction - first 50 chars
                pattern = msg[:50] if msg else "empty"
                pattern_counts[pattern] += 1

            result["pattern_summary"] = [
                {"pattern": p[:50], "count_in_sample": c}
                for p, c in pattern_counts.most_common(5)
            ]

        result["time_range"] = time_range
        result["log_source"] = log_source

        logger.info(
            "sample_logs_completed",
            strategy=strategy,
            service=service,
            sample_size=len(result.get("logs", [])),
        )
        return json.dumps(result, indent=2, default=str)

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "sample_logs")
    except Exception as e:
        logger.error("sample_logs_failed", error=str(e), strategy=strategy)
        return json.dumps({"error": str(e), "tool": "sample_logs"})


@function_tool
def search_logs_by_pattern(
    pattern: str,
    service: str | None = None,
    time_range: str = "1h",
    context_lines: int = 2,
    max_results: int = 50,
    case_sensitive: bool = False,
    log_source: str = "auto",
    index_pattern: str | None = None,
    log_group: str | None = None,
) -> str:
    """
    Search for logs matching a specific pattern with context.

    Use for:
    - Finding specific error messages
    - Tracing exceptions with stack traces
    - Searching for transaction/trace IDs

    Example:
        search_logs_by_pattern(pattern="NullPointerException", service="order-service")
        search_logs_by_pattern(pattern="trace-id-12345")

    Args:
        pattern: String or regex pattern to search for
        service: Optional service name to filter
        time_range: Time range to search (e.g., '15m', '1h', '24h')
        context_lines: Number of log lines before/after match to include (default 2)
        max_results: Maximum matches to return (default 50)
        case_sensitive: Whether search is case-sensitive (default False)
        log_source: Log backend ('auto', 'elasticsearch', 'coralogix', 'datadog', 'splunk', 'cloudwatch')
        index_pattern: [Elasticsearch only] Index pattern (e.g., 'logs-*')
        log_group: [CloudWatch only] Log group name

    Returns:
        JSON with matching logs and context
    """
    try:
        start_time, end_time = _get_time_bounds(time_range)
        backend = _get_backend(log_source)

        kwargs = {
            "context_lines": context_lines,
            "case_sensitive": case_sensitive,
        }
        if index_pattern:
            kwargs["index_pattern"] = index_pattern
        if log_group:
            kwargs["log_group"] = log_group

        result = backend.search_by_pattern(
            pattern, service, start_time, end_time, max_results, **kwargs
        )
        result["time_range"] = time_range
        result["log_source"] = log_source

        logger.info(
            "search_logs_by_pattern_completed",
            pattern=pattern[:50],
            matches=result.get("total_matches", 0),
        )
        return json.dumps(result, indent=2, default=str)

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "search_logs_by_pattern")
    except Exception as e:
        logger.error(
            "search_logs_by_pattern_failed", error=str(e), pattern=pattern[:50]
        )
        return json.dumps({"error": str(e), "tool": "search_logs_by_pattern"})


@function_tool
def get_logs_around_timestamp(
    timestamp: str,
    window_before_seconds: int = 30,
    window_after_seconds: int = 30,
    service: str | None = None,
    severity_filter: str | None = None,
    max_results: int = 100,
    log_source: str = "auto",
    index_pattern: str | None = None,
    log_group: str | None = None,
) -> str:
    """
    Get logs around a specific timestamp for temporal correlation.

    Use when you've identified an anomaly or event and want to see
    what happened immediately before and after.

    Example:
        get_logs_around_timestamp(
            timestamp="2024-01-15T10:32:45Z",
            service="payment-service",
            window_before_seconds=60
        )

    Args:
        timestamp: ISO timestamp of the event (e.g., '2024-01-15T10:32:45Z')
        window_before_seconds: Seconds before event to include (default 30)
        window_after_seconds: Seconds after event to include (default 30)
        service: Optional service name to filter
        severity_filter: Minimum severity to include (e.g., 'WARNING', 'ERROR')
        max_results: Maximum logs to return (default 100)
        log_source: Log backend ('auto', 'elasticsearch', 'coralogix', 'datadog', 'splunk', 'cloudwatch')
        index_pattern: [Elasticsearch only] Index pattern (e.g., 'logs-*')
        log_group: [CloudWatch only] Log group name

    Returns:
        JSON with logs before/during/after the timestamp, plus timeline_summary
    """
    try:
        ts = datetime.fromisoformat(timestamp.replace("Z", ""))
        backend = _get_backend(log_source)

        kwargs = {"max_results": max_results}
        if index_pattern:
            kwargs["index_pattern"] = index_pattern
        if log_group:
            kwargs["log_group"] = log_group
        if severity_filter:
            kwargs["severity_filter"] = severity_filter

        result = backend.get_logs_around_time(
            ts, window_before_seconds, window_after_seconds, service, **kwargs
        )
        result["log_source"] = log_source

        # Add timeline summary
        total_before = len(result.get("logs_before", []))
        total_at = len(result.get("logs_at", []))
        total_after = len(result.get("logs_after", []))
        result["timeline_summary"] = (
            f"{total_before} logs before, {total_at} at event, {total_after} after"
        )

        logger.info(
            "get_logs_around_timestamp_completed",
            timestamp=timestamp,
            total=result.get("total_logs", 0),
        )
        return json.dumps(result, indent=2, default=str)

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "get_logs_around_timestamp")
    except Exception as e:
        logger.error(
            "get_logs_around_timestamp_failed", error=str(e), timestamp=timestamp
        )
        return json.dumps({"error": str(e), "tool": "get_logs_around_timestamp"})


@function_tool
def correlate_logs_with_events(
    service: str,
    time_range: str = "1h",
    event_types: list[str] | None = None,
    log_source: str = "auto",
    index_pattern: str | None = None,
    log_group: str | None = None,
) -> str:
    """
    Correlate error logs with system events (deployments, restarts, etc.).

    This helps identify if errors started after a specific event.

    Event types searched:
    - deployment: New version deployed
    - restart: Pod/container restart
    - scaling: Replica count change
    - config_change: Configuration update

    Args:
        service: Service name to analyze
        time_range: Time range to analyze (e.g., '1h', '24h')
        event_types: Types of events to correlate with (default: all)
        log_source: Log backend for logs
        index_pattern: Elasticsearch index pattern
        log_group: CloudWatch log group

    Returns:
        JSON with events and correlated log patterns
    """
    try:
        start_time, end_time = _get_time_bounds(time_range)
        backend = _get_backend(log_source)

        # Get error logs
        kwargs = {}
        if index_pattern:
            kwargs["index_pattern"] = index_pattern
        if log_group:
            kwargs["log_group"] = log_group

        error_result = backend.sample_logs(
            "errors_only", service, start_time, end_time, 100, **kwargs
        )

        # Try to find deployment/restart events in logs
        events = []

        # Search for deployment patterns
        deploy_patterns = ["deployed", "deployment", "release", "version"]
        for pattern in deploy_patterns:
            try:
                deploy_result = backend.search_by_pattern(
                    pattern, service, start_time, end_time, 10, **kwargs
                )
                for match in deploy_result.get("matches", [])[:3]:
                    events.append(
                        {
                            "type": "deployment",
                            "timestamp": match.get("timestamp"),
                            "details": {"message": match.get("message", "")[:100]},
                        }
                    )
            except Exception:
                pass

        # Search for restart patterns
        restart_patterns = ["restart", "OOMKilled", "SIGTERM", "starting"]
        for pattern in restart_patterns:
            try:
                restart_result = backend.search_by_pattern(
                    pattern, service, start_time, end_time, 10, **kwargs
                )
                for match in restart_result.get("matches", [])[:3]:
                    events.append(
                        {
                            "type": "restart",
                            "timestamp": match.get("timestamp"),
                            "details": {"message": match.get("message", "")[:100]},
                        }
                    )
            except Exception:
                pass

        # Deduplicate events
        seen = set()
        unique_events = []
        for e in events:
            key = (e["type"], e["timestamp"])
            if key not in seen:
                seen.add(key)
                unique_events.append(e)

        # Sort events by timestamp
        unique_events.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        result = {
            "service": service,
            "time_range": time_range,
            "events_found": unique_events[:10],
            "error_count": len(error_result.get("logs", [])),
            "correlations": [],
            "insight": "",
        }

        if unique_events and error_result.get("logs"):
            result["insight"] = (
                f"Found {len(unique_events)} system events and {len(error_result.get('logs', []))} errors. Check if errors correlate with events."
            )
        elif error_result.get("logs"):
            result["insight"] = (
                f"Found {len(error_result.get('logs', []))} errors but no obvious system events. May be application-level issue."
            )
        else:
            result["insight"] = (
                "No significant errors or events found in the time range."
            )

        logger.info(
            "correlate_logs_with_events_completed",
            service=service,
            events=len(unique_events),
        )
        return json.dumps(result, indent=2, default=str)

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "correlate_logs_with_events")
    except Exception as e:
        logger.error("correlate_logs_with_events_failed", error=str(e), service=service)
        return json.dumps({"error": str(e), "tool": "correlate_logs_with_events"})


@function_tool
def extract_log_signatures(
    service: str | None = None,
    time_range: str = "1h",
    severity_filter: str = "ERROR",
    max_signatures: int = 20,
    log_source: str = "auto",
    index_pattern: str | None = None,
    log_group: str | None = None,
) -> str:
    """
    Extract and cluster similar log messages into signatures.

    This groups similar logs together by normalizing:
    - Variable parts (IDs, timestamps, numbers)
    - Stack traces (group by exception type)
    - Similar message patterns

    Use to understand the variety of issues without reading every log.

    Args:
        service: Optional service name to filter
        time_range: Time range to analyze (e.g., '1h', '24h')
        severity_filter: Minimum severity level (default: ERROR)
        max_signatures: Maximum number of signatures to return (default 20)
        log_source: Log backend to query
        index_pattern: Elasticsearch index pattern
        log_group: CloudWatch log group

    Returns:
        JSON with log signatures and their frequencies
    """
    try:
        start_time, end_time = _get_time_bounds(time_range)
        backend = _get_backend(log_source)

        kwargs = {}
        if index_pattern:
            kwargs["index_pattern"] = index_pattern
        if log_group:
            kwargs["log_group"] = log_group

        # Get a sample of error logs
        sample_result = backend.sample_logs(
            "errors_only", service, start_time, end_time, 200, **kwargs
        )
        logs = sample_result.get("logs", [])

        # Normalize and cluster messages
        def normalize_message(msg: str) -> str:
            """Normalize a log message by replacing variables with placeholders."""
            if not msg:
                return "empty"

            # Replace common variable patterns
            normalized = msg
            # UUIDs
            normalized = re.sub(
                r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                "{uuid}",
                normalized,
                flags=re.I,
            )
            # Numbers
            normalized = re.sub(r"\b\d+\b", "{num}", normalized)
            # IP addresses
            normalized = re.sub(
                r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "{ip}", normalized
            )
            # Timestamps
            normalized = re.sub(
                r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}", "{timestamp}", normalized
            )
            # Hex strings
            normalized = re.sub(r"\b[0-9a-f]{16,}\b", "{hex}", normalized, flags=re.I)

            return normalized[:100]

        signature_counts = Counter()
        signature_examples = {}
        signature_services = {}
        signature_first_seen = {}
        signature_last_seen = {}

        for log in logs:
            msg = log.get("message", "")
            sig = normalize_message(msg)
            signature_counts[sig] += 1

            if sig not in signature_examples:
                signature_examples[sig] = msg[:200]
                signature_first_seen[sig] = log.get("timestamp", "")
                signature_services[sig] = set()

            signature_last_seen[sig] = log.get("timestamp", "")
            if log.get("service"):
                signature_services[sig].add(log["service"])

        total_analyzed = len(logs)
        signatures = []

        for i, (pattern, count) in enumerate(
            signature_counts.most_common(max_signatures)
        ):
            signatures.append(
                {
                    "id": i + 1,
                    "pattern": pattern,
                    "count": count,
                    "percentage": (
                        round(count / total_analyzed * 100, 1)
                        if total_analyzed > 0
                        else 0
                    ),
                    "first_seen": signature_first_seen.get(pattern, ""),
                    "last_seen": signature_last_seen.get(pattern, ""),
                    "sample_message": signature_examples.get(pattern, ""),
                    "affected_services": list(signature_services.get(pattern, set())),
                    "severity": severity_filter,
                }
            )

        # Generate insight
        if signatures:
            top_pct = signatures[0]["percentage"] if signatures else 0
            insight = f"{len(signatures)} unique error patterns. Top pattern accounts for {top_pct}% of errors."
        else:
            insight = "No error patterns found in the time range."

        result = {
            "total_logs_analyzed": total_analyzed,
            "unique_signatures": len(signatures),
            "signatures": signatures,
            "insight": insight,
            "time_range": time_range,
            "log_source": log_source,
        }

        logger.info(
            "extract_log_signatures_completed",
            service=service,
            signatures=len(signatures),
        )
        return json.dumps(result, indent=2, default=str)

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "extract_log_signatures")
    except Exception as e:
        logger.error("extract_log_signatures_failed", error=str(e), service=service)
        return json.dumps({"error": str(e), "tool": "extract_log_signatures"})


@function_tool
def detect_log_anomalies(
    service: str | None = None,
    time_range: str = "1h",
    metric: str = "error_count",
    pattern: str | None = None,
    granularity: str = "5m",
    log_source: str = "auto",
    index_pattern: str | None = None,
    log_group: str | None = None,
) -> str:
    """
    Detect anomalies in log volume patterns over time.

    This analyzes log volume time series to find:
    - Sudden spikes in error rates
    - Unusual drops in log volume
    - Pattern frequency anomalies

    Args:
        service: Optional service name to filter
        time_range: Time range to analyze (e.g., '1h', '24h')
        metric: What to measure (error_count, total_volume, specific_pattern)
        pattern: Pattern to track for specific_pattern metric
        granularity: Time bucket size for aggregation (e.g., '1m', '5m')
        log_source: Log backend to query
        index_pattern: Elasticsearch index pattern
        log_group: CloudWatch log group

    Returns:
        JSON with anomaly detection results
    """
    try:
        start_time, end_time = _get_time_bounds(time_range)
        backend = _get_backend(log_source)

        kwargs = {}
        if index_pattern:
            kwargs["index_pattern"] = index_pattern
        if log_group:
            kwargs["log_group"] = log_group

        # Get statistics which include time buckets
        stats = backend.get_statistics(service, start_time, end_time, **kwargs)
        time_buckets = stats.get("time_buckets", [])

        if not time_buckets or len(time_buckets) < 3:
            return json.dumps(
                {
                    "anomalies_found": False,
                    "message": "Insufficient data for anomaly detection",
                    "time_range": time_range,
                }
            )

        # Simple anomaly detection using z-score
        counts = [b.get("count", 0) for b in time_buckets]

        if len(counts) < 3:
            return json.dumps(
                {
                    "anomalies_found": False,
                    "message": "Insufficient data points",
                    "time_range": time_range,
                }
            )

        mean = sum(counts) / len(counts)
        variance = sum((x - mean) ** 2 for x in counts) / len(counts)
        std_dev = variance**0.5 if variance > 0 else 1

        anomalies = []
        for i, bucket in enumerate(time_buckets):
            count = bucket.get("count", 0)
            z_score = (count - mean) / std_dev if std_dev > 0 else 0

            if abs(z_score) > 2:
                anomaly_type = "spike" if z_score > 0 else "drop"
                anomalies.append(
                    {
                        "timestamp": bucket.get("timestamp"),
                        "count": count,
                        "z_score": round(z_score, 2),
                        "type": anomaly_type,
                        "description": f"{'Unusually high' if z_score > 0 else 'Unusually low'} log volume ({count} vs avg {round(mean)})",
                    }
                )

        result = {
            "anomalies_found": len(anomalies) > 0,
            "anomaly_count": len(anomalies),
            "anomalies": anomalies[:10],
            "statistics": {
                "mean": round(mean, 2),
                "std_dev": round(std_dev, 2),
                "min": min(counts),
                "max": max(counts),
                "data_points": len(counts),
            },
            "time_range": time_range,
            "granularity": granularity,
            "metric": metric,
            "log_source": log_source,
        }

        if anomalies:
            spike_count = sum(1 for a in anomalies if a["type"] == "spike")
            drop_count = len(anomalies) - spike_count
            result["insight"] = (
                f"Detected {spike_count} spike(s) and {drop_count} drop(s) in log volume."
            )
        else:
            result["insight"] = "No significant anomalies detected in the time range."

        logger.info(
            "detect_log_anomalies_completed", service=service, anomalies=len(anomalies)
        )
        return json.dumps(result, indent=2, default=str)

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "detect_log_anomalies")
    except Exception as e:
        logger.error("detect_log_anomalies_failed", error=str(e), service=service)
        return json.dumps({"error": str(e), "tool": "detect_log_anomalies"})


# =============================================================================
# Tool Registration
# =============================================================================

LOG_ANALYSIS_TOOLS = [
    get_log_statistics,
    sample_logs,
    search_logs_by_pattern,
    get_logs_around_timestamp,
    correlate_logs_with_events,
    extract_log_signatures,
    detect_log_anomalies,
]

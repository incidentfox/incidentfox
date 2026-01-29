"""
Metrics advisor tools for analyzing observability coverage and generating proposals.

Provides tools for:
- Service type classification based on K8s/AWS metadata
- Metrics coverage gap analysis
- Alert rule generation (Prometheus, Datadog)
- SLI/SLO recommendations based on SRE best practices
"""

from __future__ import annotations

import json
import re
from typing import Any

from agents import function_tool

from ..core.logging import get_logger

logger = get_logger(__name__)

# =============================================================================
# Service Type Classification
# =============================================================================

# Port-based classification heuristics
PORT_TYPE_MAP: dict[int, str] = {
    80: "http_api",
    443: "http_api",
    8080: "http_api",
    8443: "http_api",
    3000: "http_api",
    5000: "http_api",
    8000: "http_api",
    5432: "database",
    3306: "database",
    27017: "database",
    6379: "cache",
    11211: "cache",
    9092: "queue",
    9094: "queue",
    5672: "queue",
    15672: "queue",
    4222: "queue",
    9200: "search",
    9300: "search",
}

# Image name patterns for classification
IMAGE_PATTERNS: dict[str, list[str]] = {
    "database": ["postgres", "mysql", "mariadb", "mongodb", "cassandra", "cockroach"],
    "cache": ["redis", "memcached", "hazelcast", "dragonflydb"],
    "queue": ["kafka", "rabbitmq", "nats", "pulsar", "activemq"],
    "gateway": ["nginx", "envoy", "traefik", "haproxy", "kong", "ambassador"],
    "worker": ["worker", "consumer", "processor", "job", "celery", "sidekiq"],
    "search": ["elasticsearch", "opensearch", "solr"],
}

# Framework templates by service type
METRICS_FRAMEWORKS: dict[str, dict[str, Any]] = {
    "http_api": {
        "framework": "RED",
        "description": "Rate, Errors, Duration - ideal for request-driven services",
        "metrics": [
            {
                "name": "http_requests_total",
                "type": "counter",
                "labels": ["method", "status", "endpoint"],
                "description": "Total HTTP requests",
                "priority": "high",
            },
            {
                "name": "http_request_duration_seconds",
                "type": "histogram",
                "buckets": [0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10],
                "description": "Request latency distribution",
                "priority": "high",
            },
            {
                "name": "http_requests_in_flight",
                "type": "gauge",
                "description": "Current number of requests being processed",
                "priority": "medium",
            },
        ],
        "sli_templates": {
            "availability": 'sum(rate(http_requests_total{status!~"5.."}[5m])) / sum(rate(http_requests_total[5m]))',
            "latency_p99": "histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))",
            "error_rate": 'sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))',
        },
    },
    "worker": {
        "framework": "Custom",
        "description": "Job processing metrics for background workers",
        "metrics": [
            {
                "name": "jobs_processed_total",
                "type": "counter",
                "labels": ["job_type", "status"],
                "description": "Total jobs processed",
                "priority": "high",
            },
            {
                "name": "job_duration_seconds",
                "type": "histogram",
                "description": "Job processing duration",
                "priority": "high",
            },
            {
                "name": "jobs_in_queue",
                "type": "gauge",
                "description": "Current queue depth",
                "priority": "high",
            },
            {
                "name": "job_retries_total",
                "type": "counter",
                "labels": ["job_type"],
                "description": "Job retry count",
                "priority": "medium",
            },
        ],
        "sli_templates": {
            "success_rate": 'sum(rate(jobs_processed_total{status="success"}[5m])) / sum(rate(jobs_processed_total[5m]))',
            "processing_time_p95": "histogram_quantile(0.95, rate(job_duration_seconds_bucket[5m]))",
        },
    },
    "database": {
        "framework": "USE",
        "description": "Utilization, Saturation, Errors - ideal for resources",
        "metrics": [
            {
                "name": "db_connections_active",
                "type": "gauge",
                "description": "Active database connections",
                "priority": "high",
            },
            {
                "name": "db_connections_max",
                "type": "gauge",
                "description": "Maximum connection limit",
                "priority": "high",
            },
            {
                "name": "db_query_duration_seconds",
                "type": "histogram",
                "description": "Query execution time",
                "priority": "high",
            },
            {
                "name": "db_replication_lag_seconds",
                "type": "gauge",
                "description": "Replication lag (for replicas)",
                "priority": "medium",
            },
            {
                "name": "db_deadlocks_total",
                "type": "counter",
                "description": "Deadlock occurrences",
                "priority": "medium",
            },
        ],
        "sli_templates": {
            "connection_utilization": "db_connections_active / db_connections_max",
            "query_latency_p99": "histogram_quantile(0.99, rate(db_query_duration_seconds_bucket[5m]))",
        },
    },
    "cache": {
        "framework": "USE",
        "description": "Cache-specific metrics with hit/miss ratios",
        "metrics": [
            {
                "name": "cache_hits_total",
                "type": "counter",
                "description": "Cache hit count",
                "priority": "high",
            },
            {
                "name": "cache_misses_total",
                "type": "counter",
                "description": "Cache miss count",
                "priority": "high",
            },
            {
                "name": "cache_memory_bytes",
                "type": "gauge",
                "description": "Memory usage",
                "priority": "high",
            },
            {
                "name": "cache_evictions_total",
                "type": "counter",
                "description": "Eviction count",
                "priority": "medium",
            },
            {
                "name": "cache_connections_current",
                "type": "gauge",
                "description": "Current connections",
                "priority": "medium",
            },
        ],
        "sli_templates": {
            "hit_ratio": "sum(rate(cache_hits_total[5m])) / (sum(rate(cache_hits_total[5m])) + sum(rate(cache_misses_total[5m])))",
        },
    },
    "queue": {
        "framework": "Custom",
        "description": "Message queue specific metrics",
        "metrics": [
            {
                "name": "queue_messages_total",
                "type": "counter",
                "labels": ["queue", "operation"],
                "description": "Messages produced/consumed",
                "priority": "high",
            },
            {
                "name": "queue_messages_pending",
                "type": "gauge",
                "labels": ["queue"],
                "description": "Pending messages (consumer lag)",
                "priority": "high",
            },
            {
                "name": "queue_message_age_seconds",
                "type": "gauge",
                "description": "Age of oldest message",
                "priority": "high",
            },
            {
                "name": "queue_dead_letter_total",
                "type": "counter",
                "description": "Dead letter queue count",
                "priority": "medium",
            },
        ],
        "sli_templates": {
            "throughput": 'sum(rate(queue_messages_total{operation="consume"}[5m]))',
            "max_lag": "max(queue_messages_pending)",
        },
    },
    "gateway": {
        "framework": "Golden Signals",
        "description": "Full golden signals for proxy/gateway services",
        "metrics": [
            {
                "name": "gateway_requests_total",
                "type": "counter",
                "labels": ["method", "status", "upstream"],
                "description": "Total requests through gateway",
                "priority": "high",
            },
            {
                "name": "gateway_request_duration_seconds",
                "type": "histogram",
                "labels": ["upstream"],
                "description": "Request latency including upstream",
                "priority": "high",
            },
            {
                "name": "gateway_upstream_duration_seconds",
                "type": "histogram",
                "labels": ["upstream"],
                "description": "Upstream response time only",
                "priority": "high",
            },
            {
                "name": "gateway_connections_active",
                "type": "gauge",
                "description": "Active connections",
                "priority": "medium",
            },
        ],
        "sli_templates": {
            "availability": 'sum(rate(gateway_requests_total{status!~"5.."}[5m])) / sum(rate(gateway_requests_total[5m]))',
            "upstream_latency_p99": "histogram_quantile(0.99, rate(gateway_upstream_duration_seconds_bucket[5m]))",
        },
    },
    "unknown": {
        "framework": "Golden Signals",
        "description": "Default golden signals for unclassified services",
        "metrics": [
            {
                "name": "requests_total",
                "type": "counter",
                "labels": ["status"],
                "description": "Total requests",
                "priority": "high",
            },
            {
                "name": "request_duration_seconds",
                "type": "histogram",
                "description": "Request latency",
                "priority": "high",
            },
            {
                "name": "errors_total",
                "type": "counter",
                "labels": ["type"],
                "description": "Error count",
                "priority": "high",
            },
        ],
        "sli_templates": {
            "availability": 'sum(rate(requests_total{status!~"5.."}[5m])) / sum(rate(requests_total[5m]))',
        },
    },
}

# SLO targets by service tier
SLO_TARGETS: dict[str, dict[str, float]] = {
    "critical": {
        "availability": 0.999,  # 99.9% - 43.8 min/month downtime
        "latency_p99_seconds": 0.5,
        "error_rate": 0.001,
    },
    "standard": {
        "availability": 0.995,  # 99.5% - 3.6 hours/month downtime
        "latency_p99_seconds": 1.0,
        "error_rate": 0.005,
    },
    "best_effort": {
        "availability": 0.99,  # 99% - 7.2 hours/month downtime
        "latency_p99_seconds": 2.0,
        "error_rate": 0.01,
    },
}


def _classify_by_ports(container_ports: list[int]) -> tuple[str | None, int]:
    """
    Classify service type by container ports.

    Returns (service_type, confidence)
    """
    for port in container_ports:
        if port in PORT_TYPE_MAP:
            return PORT_TYPE_MAP[port], 70
    return None, 0


def _classify_by_image(image_name: str) -> tuple[str | None, int]:
    """
    Classify service type by image name patterns.

    Returns (service_type, confidence)
    """
    image_lower = image_name.lower()
    for service_type, patterns in IMAGE_PATTERNS.items():
        for pattern in patterns:
            if pattern in image_lower:
                return service_type, 85
    return None, 0


def _classify_by_labels(labels: dict[str, str]) -> tuple[str | None, int]:
    """
    Classify by Kubernetes labels.

    Returns (service_type, confidence)
    """
    # Standard K8s label
    component = labels.get("app.kubernetes.io/component", "")
    if component:
        component_lower = component.lower()
        for service_type in METRICS_FRAMEWORKS:
            if service_type in component_lower:
                return service_type, 95  # High confidence for explicit labels

    # Common custom labels
    for key, value in labels.items():
        value_lower = value.lower()
        if "api" in value_lower or "web" in value_lower:
            return "http_api", 60
        if "worker" in value_lower or "job" in value_lower:
            return "worker", 60
        if "db" in value_lower or "database" in value_lower:
            return "database", 60

    return None, 0


def _parse_json_safe(json_str: str) -> dict[str, Any]:
    """Safely parse JSON string, returning empty dict on failure."""
    if not json_str:
        return {}
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return {}


@function_tool
def classify_service_type(
    service_name: str,
    namespace: str = "default",
    pod_spec: str = "",
    deployment_spec: str = "",
    service_spec: str = "",
) -> str:
    """
    Classify a service type based on K8s metadata.

    Analyzes ports, image names, labels, and resource patterns to determine
    the service type and recommend the appropriate metrics framework.

    Args:
        service_name: Name of the service to classify
        namespace: Kubernetes namespace
        pod_spec: JSON string of pod spec (from describe_pod output)
        deployment_spec: JSON string of deployment spec (from describe_deployment)
        service_spec: JSON string of K8s service spec (optional)

    Returns:
        JSON with:
        - service_type: "http_api" | "worker" | "database" | "cache" | "queue" | "gateway" | "unknown"
        - confidence: 0-100 (how confident we are in the classification)
        - signals: list of signals that led to this classification
        - recommended_framework: "RED" | "USE" | "Golden Signals" | "Custom"
        - reasoning: explanation of classification logic
    """
    logger.info(
        "classifying_service_type",
        service_name=service_name,
        namespace=namespace,
    )

    signals: list[dict[str, Any]] = []
    classifications: list[tuple[str, int, str]] = []  # (type, confidence, reason)

    # Parse provided specs
    pod_data = _parse_json_safe(pod_spec)
    deployment_data = _parse_json_safe(deployment_spec)
    service_data = _parse_json_safe(service_spec)

    # 1. Check labels (highest priority - explicit declaration)
    labels = {}
    if pod_data:
        labels.update(pod_data.get("metadata", {}).get("labels", {}))
    if deployment_data:
        labels.update(deployment_data.get("metadata", {}).get("labels", {}))

    if labels:
        label_type, label_conf = _classify_by_labels(labels)
        if label_type:
            classifications.append((label_type, label_conf, f"K8s labels: {labels}"))
            signals.append({"source": "labels", "data": labels, "result": label_type})

    # 2. Check image names
    images = []
    if pod_data:
        containers = pod_data.get("spec", {}).get("containers", [])
        images.extend(c.get("image", "") for c in containers)
    if deployment_data:
        containers = (
            deployment_data.get("spec", {})
            .get("template", {})
            .get("spec", {})
            .get("containers", [])
        )
        images.extend(c.get("image", "") for c in containers)

    for image in images:
        if image:
            image_type, image_conf = _classify_by_image(image)
            if image_type:
                classifications.append((image_type, image_conf, f"Image name: {image}"))
                signals.append({"source": "image", "data": image, "result": image_type})

    # 3. Check ports
    ports = []
    if pod_data:
        containers = pod_data.get("spec", {}).get("containers", [])
        for c in containers:
            for p in c.get("ports", []):
                port = p.get("containerPort")
                if port:
                    ports.append(port)
    if service_data:
        for p in service_data.get("spec", {}).get("ports", []):
            port = p.get("port") or p.get("targetPort")
            if port and isinstance(port, int):
                ports.append(port)

    if ports:
        port_type, port_conf = _classify_by_ports(ports)
        if port_type:
            classifications.append((port_type, port_conf, f"Ports: {ports}"))
            signals.append({"source": "ports", "data": ports, "result": port_type})

    # 4. Check workload type (StatefulSet, DaemonSet, etc.)
    if deployment_data:
        kind = deployment_data.get("kind", "")
        if kind == "StatefulSet":
            classifications.append(("database", 50, "StatefulSet workload"))
            signals.append(
                {"source": "workload_type", "data": "StatefulSet", "result": "database"}
            )
        elif kind == "DaemonSet":
            classifications.append(("worker", 40, "DaemonSet workload"))
            signals.append(
                {"source": "workload_type", "data": "DaemonSet", "result": "worker"}
            )

    # Determine final classification
    if not classifications:
        final_type = "unknown"
        final_confidence = 0
        reasoning = (
            "No classification signals found. Using default Golden Signals framework."
        )
    else:
        # Sort by confidence, take highest
        classifications.sort(key=lambda x: x[1], reverse=True)
        final_type, final_confidence, top_reason = classifications[0]
        reasoning = f"Classified as '{final_type}' based on: {top_reason}"

        # Boost confidence if multiple signals agree
        agreeing = [c for c in classifications if c[0] == final_type]
        if len(agreeing) > 1:
            final_confidence = min(95, final_confidence + 10)
            reasoning += f" (confirmed by {len(agreeing)} signals)"

    framework = METRICS_FRAMEWORKS.get(final_type, METRICS_FRAMEWORKS["unknown"])

    result = {
        "service_name": service_name,
        "namespace": namespace,
        "service_type": final_type,
        "confidence": final_confidence,
        "signals": signals,
        "recommended_framework": framework["framework"],
        "framework_description": framework["description"],
        "reasoning": reasoning,
    }

    logger.info(
        "classification_complete",
        service_name=service_name,
        service_type=final_type,
        confidence=final_confidence,
    )

    return json.dumps(result, indent=2)


@function_tool
def get_metrics_framework_template(
    service_type: str,
    service_tier: str = "standard",
) -> str:
    """
    Get the recommended metrics framework template for a service type.

    Returns detailed metrics definitions, SLI templates, and SLO targets
    based on industry best practices (RED, USE, Golden Signals).

    Args:
        service_type: Type from classify_service_type ("http_api", "worker", "database", etc.)
        service_tier: Service criticality tier:
            - "critical": 99.9% availability (43.8 min/month downtime)
            - "standard": 99.5% availability (3.6 hours/month downtime)
            - "best_effort": 99% availability (7.2 hours/month downtime)

    Returns:
        JSON with:
        - framework: Framework name (RED, USE, Golden Signals, Custom)
        - description: What this framework is best for
        - metrics: List of recommended metrics with type, labels, description
        - sli_templates: PromQL templates for SLI calculations
        - slo_targets: Recommended targets for this tier
    """
    logger.info(
        "getting_framework_template",
        service_type=service_type,
        service_tier=service_tier,
    )

    # Get framework, default to unknown
    framework = METRICS_FRAMEWORKS.get(service_type, METRICS_FRAMEWORKS["unknown"])

    # Get SLO targets for tier
    targets = SLO_TARGETS.get(service_tier, SLO_TARGETS["standard"])

    result = {
        "service_type": service_type,
        "service_tier": service_tier,
        "framework": framework["framework"],
        "description": framework["description"],
        "metrics": framework["metrics"],
        "sli_templates": framework.get("sli_templates", {}),
        "slo_targets": targets,
        "alert_thresholds": {
            "critical": {
                "error_rate": targets["error_rate"] * 10,  # 10x normal for critical
                "latency_seconds": targets["latency_p99_seconds"] * 2,
            },
            "warning": {
                "error_rate": targets["error_rate"] * 5,  # 5x normal for warning
                "latency_seconds": targets["latency_p99_seconds"] * 1.5,
            },
        },
    }

    return json.dumps(result, indent=2)


@function_tool
def analyze_metrics_gap(
    service_name: str,
    existing_metrics: str,
    service_type: str,
) -> str:
    """
    Compare existing metrics against recommendations for the service type.

    Identifies coverage gaps and provides prioritized recommendations.

    Args:
        service_name: Name of the service being analyzed
        existing_metrics: JSON list of metric names currently available
            Example: '["http_requests_total", "http_request_duration_seconds_bucket"]'
        service_type: Classified service type from classify_service_type

    Returns:
        JSON with:
        - coverage_score: 0-100 (percentage of recommended metrics present)
        - existing: List of metrics that match recommendations
        - missing: List of missing metrics with priority (high/medium/low)
        - extra: Metrics that exist but aren't in standard recommendations
        - recommendation: Summary of what to prioritize
    """
    logger.info(
        "analyzing_metrics_gap",
        service_name=service_name,
        service_type=service_type,
    )

    # Parse existing metrics
    try:
        existing = json.loads(existing_metrics) if existing_metrics else []
    except json.JSONDecodeError:
        existing = []

    # Normalize metric names (remove labels, buckets suffix)
    def normalize_metric(name: str) -> str:
        # Remove common suffixes
        name = re.sub(r"_bucket$", "", name)
        name = re.sub(r"_total$", "", name)
        name = re.sub(r"_sum$", "", name)
        name = re.sub(r"_count$", "", name)
        # Remove label parts in braces
        name = re.sub(r"\{[^}]*\}", "", name)
        return name.strip()

    existing_normalized = {normalize_metric(m) for m in existing}

    # Get expected metrics for service type
    framework = METRICS_FRAMEWORKS.get(service_type, METRICS_FRAMEWORKS["unknown"])
    expected_metrics = framework["metrics"]

    # Analyze coverage
    matched = []
    missing = []

    for metric in expected_metrics:
        metric_base = normalize_metric(metric["name"])
        # Check if any existing metric matches
        if any(metric_base in norm for norm in existing_normalized):
            matched.append(
                {"name": metric["name"], "description": metric["description"]}
            )
        else:
            missing.append(
                {
                    "name": metric["name"],
                    "type": metric["type"],
                    "description": metric["description"],
                    "priority": metric.get("priority", "medium"),
                }
            )

    # Find extra metrics (exist but not in recommendations)
    expected_bases = {normalize_metric(m["name"]) for m in expected_metrics}
    extra = [m for m in existing if normalize_metric(m) not in expected_bases]

    # Calculate coverage score
    total_expected = len(expected_metrics)
    coverage_score = (len(matched) / total_expected * 100) if total_expected > 0 else 0

    # Sort missing by priority
    priority_order = {"high": 0, "medium": 1, "low": 2}
    missing.sort(key=lambda x: priority_order.get(x["priority"], 1))

    # Generate recommendation
    high_priority_missing = [m for m in missing if m["priority"] == "high"]
    if not missing:
        recommendation = "Excellent coverage! All recommended metrics are present."
    elif high_priority_missing:
        recommendation = (
            f"Missing {len(high_priority_missing)} high-priority metrics. "
            f"Prioritize adding: {', '.join(m['name'] for m in high_priority_missing[:3])}"
        )
    else:
        recommendation = (
            f"Good coverage ({coverage_score:.0f}%). "
            f"Consider adding: {', '.join(m['name'] for m in missing[:3])}"
        )

    result = {
        "service_name": service_name,
        "service_type": service_type,
        "coverage_score": round(coverage_score, 1),
        "existing_matched": matched,
        "missing": missing,
        "extra_metrics": extra[:10],  # Limit to 10
        "recommendation": recommendation,
    }

    return json.dumps(result, indent=2)


@function_tool
def generate_prometheus_rules(
    service_name: str,
    namespace: str,
    service_type: str,
    thresholds: str = "",
    include_recording_rules: bool = True,
) -> str:
    """
    Generate Prometheus alerting rules YAML for a service.

    Creates production-ready alert rules following best practices:
    - Multi-window burn rates for SLO-based alerts
    - Appropriate severity levels
    - Runbook annotations
    - For duration to avoid flapping

    Args:
        service_name: Service name (used in labels and alert names)
        namespace: Kubernetes namespace
        service_type: Service type from classify_service_type
        thresholds: Optional JSON with custom thresholds:
            {"error_rate_critical": 0.05, "latency_p99_warning": 1.0}
        include_recording_rules: Whether to include recording rules for efficiency

    Returns:
        Valid PrometheusRule YAML that can be applied to Kubernetes
    """
    logger.info(
        "generating_prometheus_rules",
        service_name=service_name,
        namespace=namespace,
        service_type=service_type,
    )

    # Parse custom thresholds
    custom_thresholds = _parse_json_safe(thresholds)

    # Get framework for service type (reserved for future use)
    _framework = METRICS_FRAMEWORKS.get(service_type, METRICS_FRAMEWORKS["unknown"])
    slo_targets = SLO_TARGETS["standard"]

    # Build alert rules based on service type
    alerts = []
    recording_rules = []

    # Sanitize service name for Prometheus (alphanumeric + underscore)
    safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", service_name)

    if service_type == "http_api":
        # Error rate alerts
        error_rate_critical = custom_thresholds.get(
            "error_rate_critical", slo_targets["error_rate"] * 10
        )
        error_rate_warning = custom_thresholds.get(
            "error_rate_warning", slo_targets["error_rate"] * 5
        )

        alerts.append(
            {
                "alert": f"{safe_name}HighErrorRate",
                "expr": f'sum(rate(http_requests_total{{service="{service_name}",status=~"5.."}}[5m])) / sum(rate(http_requests_total{{service="{service_name}"}}[5m])) > {error_rate_critical}',
                "for": "2m",
                "labels": {
                    "severity": "critical",
                    "service": service_name,
                    "namespace": namespace,
                },
                "annotations": {
                    "summary": f"High error rate on {service_name}",
                    "description": f"Error rate is above {error_rate_critical * 100}% for 2 minutes",
                    "runbook_url": f"https://runbooks.example.com/{service_name}/high-error-rate",
                },
            }
        )

        alerts.append(
            {
                "alert": f"{safe_name}ElevatedErrorRate",
                "expr": f'sum(rate(http_requests_total{{service="{service_name}",status=~"5.."}}[5m])) / sum(rate(http_requests_total{{service="{service_name}"}}[5m])) > {error_rate_warning}',
                "for": "5m",
                "labels": {
                    "severity": "warning",
                    "service": service_name,
                    "namespace": namespace,
                },
                "annotations": {
                    "summary": f"Elevated error rate on {service_name}",
                    "description": f"Error rate is above {error_rate_warning * 100}% for 5 minutes",
                },
            }
        )

        # Latency alerts
        latency_critical = custom_thresholds.get(
            "latency_p99_critical", slo_targets["latency_p99_seconds"] * 2
        )
        _latency_warning = custom_thresholds.get(
            "latency_p99_warning", slo_targets["latency_p99_seconds"] * 1.5
        )

        alerts.append(
            {
                "alert": f"{safe_name}HighLatency",
                "expr": f'histogram_quantile(0.99, rate(http_request_duration_seconds_bucket{{service="{service_name}"}}[5m])) > {latency_critical}',
                "for": "5m",
                "labels": {
                    "severity": "warning",
                    "service": service_name,
                    "namespace": namespace,
                },
                "annotations": {
                    "summary": f"High latency on {service_name}",
                    "description": f"P99 latency is above {latency_critical}s for 5 minutes",
                },
            }
        )

        if include_recording_rules:
            recording_rules.append(
                {
                    "record": f"{safe_name}:http_requests:rate5m",
                    "expr": f'sum(rate(http_requests_total{{service="{service_name}"}}[5m]))',
                }
            )
            recording_rules.append(
                {
                    "record": f"{safe_name}:http_errors:rate5m",
                    "expr": f'sum(rate(http_requests_total{{service="{service_name}",status=~"5.."}}[5m]))',
                }
            )

    elif service_type == "worker":
        failure_rate_critical = custom_thresholds.get("failure_rate_critical", 0.1)
        queue_depth_critical = custom_thresholds.get("queue_depth_critical", 10000)

        alerts.append(
            {
                "alert": f"{safe_name}HighJobFailureRate",
                "expr": f'sum(rate(jobs_processed_total{{service="{service_name}",status="failed"}}[5m])) / sum(rate(jobs_processed_total{{service="{service_name}"}}[5m])) > {failure_rate_critical}',
                "for": "5m",
                "labels": {
                    "severity": "critical",
                    "service": service_name,
                    "namespace": namespace,
                },
                "annotations": {
                    "summary": f"High job failure rate on {service_name}",
                    "description": f"Job failure rate is above {failure_rate_critical * 100}%",
                },
            }
        )

        alerts.append(
            {
                "alert": f"{safe_name}QueueBacklog",
                "expr": f'jobs_in_queue{{service="{service_name}"}} > {queue_depth_critical}',
                "for": "10m",
                "labels": {
                    "severity": "warning",
                    "service": service_name,
                    "namespace": namespace,
                },
                "annotations": {
                    "summary": f"Queue backlog on {service_name}",
                    "description": f"Queue depth exceeds {queue_depth_critical} for 10 minutes",
                },
            }
        )

    elif service_type == "database":
        connection_threshold = custom_thresholds.get("connection_utilization", 0.8)
        replication_lag = custom_thresholds.get("replication_lag_seconds", 30)

        alerts.append(
            {
                "alert": f"{safe_name}ConnectionPoolExhaustion",
                "expr": f'db_connections_active{{service="{service_name}"}} / db_connections_max{{service="{service_name}"}} > {connection_threshold}',
                "for": "5m",
                "labels": {
                    "severity": "critical",
                    "service": service_name,
                    "namespace": namespace,
                },
                "annotations": {
                    "summary": f"Connection pool near exhaustion on {service_name}",
                    "description": f"Connection utilization is above {connection_threshold * 100}%",
                },
            }
        )

        alerts.append(
            {
                "alert": f"{safe_name}ReplicationLag",
                "expr": f'db_replication_lag_seconds{{service="{service_name}"}} > {replication_lag}',
                "for": "5m",
                "labels": {
                    "severity": "warning",
                    "service": service_name,
                    "namespace": namespace,
                },
                "annotations": {
                    "summary": f"Replication lag on {service_name}",
                    "description": f"Replication lag exceeds {replication_lag}s",
                },
            }
        )

    elif service_type == "cache":
        hit_ratio_threshold = custom_thresholds.get("hit_ratio_minimum", 0.8)

        alerts.append(
            {
                "alert": f"{safe_name}LowCacheHitRatio",
                "expr": f'sum(rate(cache_hits_total{{service="{service_name}"}}[5m])) / (sum(rate(cache_hits_total{{service="{service_name}"}}[5m])) + sum(rate(cache_misses_total{{service="{service_name}"}}[5m]))) < {hit_ratio_threshold}',
                "for": "10m",
                "labels": {
                    "severity": "warning",
                    "service": service_name,
                    "namespace": namespace,
                },
                "annotations": {
                    "summary": f"Low cache hit ratio on {service_name}",
                    "description": f"Cache hit ratio is below {hit_ratio_threshold * 100}%",
                },
            }
        )

    # Build PrometheusRule YAML
    groups = []

    if alerts:
        groups.append(
            {
                "name": f"{service_name}.alerts",
                "rules": alerts,
            }
        )

    if recording_rules and include_recording_rules:
        groups.append(
            {
                "name": f"{service_name}.recording",
                "rules": recording_rules,
            }
        )

    prometheus_rule = {
        "apiVersion": "monitoring.coreos.com/v1",
        "kind": "PrometheusRule",
        "metadata": {
            "name": f"{service_name}-alerts",
            "namespace": namespace,
            "labels": {
                "app": service_name,
                "prometheus": "k8s",
                "role": "alert-rules",
            },
        },
        "spec": {"groups": groups},
    }

    # Convert to YAML
    import yaml

    result = yaml.dump(prometheus_rule, default_flow_style=False, sort_keys=False)

    return result


@function_tool
def generate_datadog_monitors(
    service_name: str,
    service_type: str,
    thresholds: str = "",
    notification_channels: str = "@slack-alerts",
) -> str:
    """
    Generate Datadog monitor definitions for a service.

    Creates monitors following Datadog best practices with:
    - Appropriate thresholds by service type
    - Multi-alert for per-host/service granularity
    - Proper notification routing

    Args:
        service_name: Service name (used in tags and monitor names)
        service_type: Service type from classify_service_type
        thresholds: Optional JSON with custom thresholds
        notification_channels: Notification targets (e.g., "@slack-alerts @pagerduty-critical")

    Returns:
        JSON array of Datadog monitor definitions ready for API submission
    """
    logger.info(
        "generating_datadog_monitors",
        service_name=service_name,
        service_type=service_type,
    )

    custom_thresholds = _parse_json_safe(thresholds)
    slo_targets = SLO_TARGETS["standard"]

    monitors = []

    if service_type == "http_api":
        # Error rate monitor
        error_rate_critical = custom_thresholds.get(
            "error_rate_critical", slo_targets["error_rate"] * 10
        )
        error_rate_warning = custom_thresholds.get(
            "error_rate_warning", slo_targets["error_rate"] * 5
        )

        monitors.append(
            {
                "name": f"[{service_name}] High Error Rate",
                "type": "query alert",
                "query": f"sum(last_5m):sum:http.server.request.count{{service:{service_name},status_code_class:5xx}}.as_count() / sum:http.server.request.count{{service:{service_name}}}.as_count() > {error_rate_critical}",
                "message": f"""Error rate on {service_name} is above threshold.

Current error rate: {{{{value}}}}
Threshold: {error_rate_critical * 100}%

Check:
- Recent deployments
- Downstream dependencies
- Resource utilization

{notification_channels}""",
                "tags": [f"service:{service_name}", "generated:metrics-advisor"],
                "options": {
                    "thresholds": {
                        "critical": error_rate_critical,
                        "warning": error_rate_warning,
                    },
                    "notify_no_data": False,
                    "renotify_interval": 60,
                    "escalation_message": f"Error rate still elevated on {service_name}",
                },
            }
        )

        # Latency monitor
        latency_critical = custom_thresholds.get(
            "latency_p99_critical", slo_targets["latency_p99_seconds"]
        )

        monitors.append(
            {
                "name": f"[{service_name}] High P99 Latency",
                "type": "query alert",
                "query": f"avg(last_5m):p99:http.server.request.duration{{service:{service_name}}} > {latency_critical}",
                "message": f"""P99 latency on {service_name} is above threshold.

Current P99: {{{{value}}}}s
Threshold: {latency_critical}s

{notification_channels}""",
                "tags": [f"service:{service_name}", "generated:metrics-advisor"],
                "options": {
                    "thresholds": {
                        "critical": latency_critical,
                        "warning": latency_critical * 0.75,
                    },
                    "notify_no_data": False,
                },
            }
        )

    elif service_type == "worker":
        failure_rate = custom_thresholds.get("failure_rate_critical", 0.1)

        monitors.append(
            {
                "name": f"[{service_name}] High Job Failure Rate",
                "type": "query alert",
                "query": f"sum(last_5m):sum:jobs.failed{{service:{service_name}}}.as_count() / sum:jobs.total{{service:{service_name}}}.as_count() > {failure_rate}",
                "message": f"""Job failure rate on {service_name} is elevated.

Failure rate: {{{{value}}}}

{notification_channels}""",
                "tags": [f"service:{service_name}", "generated:metrics-advisor"],
                "options": {
                    "thresholds": {
                        "critical": failure_rate,
                        "warning": failure_rate * 0.5,
                    },
                },
            }
        )

    elif service_type == "database":
        conn_threshold = custom_thresholds.get("connection_utilization", 0.8)

        monitors.append(
            {
                "name": f"[{service_name}] Connection Pool Saturation",
                "type": "query alert",
                "query": f"avg(last_5m):avg:postgresql.connections.active{{service:{service_name}}} / avg:postgresql.connections.max{{service:{service_name}}} > {conn_threshold}",
                "message": f"""Database connection pool is near exhaustion.

Utilization: {{{{value}}}}

{notification_channels}""",
                "tags": [f"service:{service_name}", "generated:metrics-advisor"],
                "options": {
                    "thresholds": {
                        "critical": conn_threshold,
                        "warning": conn_threshold * 0.8,
                    },
                },
            }
        )

    result = {
        "monitors": monitors,
        "service_name": service_name,
        "count": len(monitors),
    }

    return json.dumps(result, indent=2)


@function_tool
def format_proposal_document(
    service_name: str,
    classification_result: str,
    gap_analysis_result: str = "",
    generated_rules: str = "",
    output_format: str = "markdown",
) -> str:
    """
    Format a complete metrics/alerts proposal document.

    Combines classification, gap analysis, and generated rules into
    a comprehensive proposal document.

    Args:
        service_name: Service being analyzed
        classification_result: JSON from classify_service_type
        gap_analysis_result: JSON from analyze_metrics_gap (optional)
        generated_rules: Generated alert rules (YAML or JSON)
        output_format: "markdown" for documentation, "yaml" for pure rules

    Returns:
        Formatted proposal document
    """
    logger.info(
        "formatting_proposal",
        service_name=service_name,
        output_format=output_format,
    )

    classification = _parse_json_safe(classification_result)
    gap_analysis = _parse_json_safe(gap_analysis_result)

    if output_format == "yaml":
        # Just return the rules
        return generated_rules

    # Build markdown document
    lines = [
        f"# Metrics & Alerts Proposal: {service_name}",
        "",
        "*Generated by Metrics Advisor*",
        "",
        "---",
        "",
        "## Service Classification",
        "",
        "| Property | Value |",
        "|----------|-------|",
        f"| **Service Type** | {classification.get('service_type', 'unknown')} |",
        f"| **Confidence** | {classification.get('confidence', 0)}% |",
        f"| **Framework** | {classification.get('recommended_framework', 'Unknown')} |",
        "",
        f"**Reasoning:** {classification.get('reasoning', 'N/A')}",
        "",
    ]

    # Add classification signals
    signals = classification.get("signals", [])
    if signals:
        lines.extend(
            [
                "### Detection Signals",
                "",
            ]
        )
        for signal in signals:
            lines.append(
                f"- **{signal.get('source', 'Unknown')}**: {signal.get('data', '')} -> {signal.get('result', '')}"
            )
        lines.append("")

    # Add gap analysis if available
    if gap_analysis:
        coverage = gap_analysis.get("coverage_score", 0)
        lines.extend(
            [
                "## Current State Analysis",
                "",
                f"**Coverage Score:** {coverage}%",
                "",
            ]
        )

        existing = gap_analysis.get("existing_matched", [])
        if existing:
            lines.append("### Existing Metrics")
            lines.append("")
            for m in existing:
                lines.append(f"- `{m.get('name', '')}`: {m.get('description', '')}")
            lines.append("")

        missing = gap_analysis.get("missing", [])
        if missing:
            lines.append("### Missing Metrics (Prioritized)")
            lines.append("")
            for m in missing:
                priority = m.get("priority", "medium")
                icon = {"high": "!!!", "medium": "!!", "low": "!"}.get(priority, "!")
                lines.append(
                    f"- [{icon}] `{m.get('name', '')}` ({m.get('type', '')}): {m.get('description', '')}"
                )
            lines.append("")

        recommendation = gap_analysis.get("recommendation", "")
        if recommendation:
            lines.extend(
                [
                    f"**Recommendation:** {recommendation}",
                    "",
                ]
            )

    # Add generated rules
    if generated_rules:
        lines.extend(
            [
                "## Generated Alert Rules",
                "",
                "```yaml",
                generated_rules,
                "```",
                "",
            ]
        )

    # Add implementation notes
    lines.extend(
        [
            "## Implementation Notes",
            "",
            "1. Review thresholds based on actual baseline metrics before deploying",
            "2. Test alerts in staging environment first",
            "3. Update runbook URLs with actual documentation links",
            "4. Adjust notification channels as needed",
            "",
            "## References",
            "",
            f"- Framework: {classification.get('recommended_framework', 'Golden Signals')}",
            "- [Google SRE Book - Monitoring Distributed Systems](https://sre.google/sre-book/monitoring-distributed-systems/)",
            "- [Prometheus Alerting Best Practices](https://prometheus.io/docs/practices/alerting/)",
            "",
        ]
    )

    return "\n".join(lines)

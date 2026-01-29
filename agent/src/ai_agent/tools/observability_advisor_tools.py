"""
Observability Advisor tools for building data-driven alert rules.

These tools help organizations set up or improve their monitoring by:
1. Computing metric baselines from historical data
2. Suggesting data-driven thresholds based on SRE best practices (RED/USE/Golden Signals)
3. Generating alert rules in multiple formats (Prometheus, Datadog, CloudWatch, docs)

Designed for:
- Companies with little telemetry/alerting setup
- Organizations with arbitrary thresholds causing noisy or insensitive alerts
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from agents import function_tool

from ..core.logging import get_logger

logger = get_logger(__name__)


class ServiceType(str, Enum):
    """Service classification for determining relevant metrics."""

    HTTP_API = "http_api"
    WORKER = "worker"
    DATABASE = "database"
    CACHE = "cache"
    GATEWAY = "gateway"
    QUEUE = "queue"


class MetricSource(str, Enum):
    """Supported metric backends."""

    PROMETHEUS = "prometheus"
    DATADOG = "datadog"
    CLOUDWATCH = "cloudwatch"


class OutputFormat(str, Enum):
    """Alert rule output formats."""

    PROMETHEUS_YAML = "prometheus_yaml"
    DATADOG_JSON = "datadog_json"
    CLOUDWATCH_JSON = "cloudwatch_json"
    PROPOSAL_DOC = "proposal_doc"


# =============================================================================
# SRE Framework Definitions
# =============================================================================

# RED Method (Request-driven services): Rate, Errors, Duration
RED_METRICS = {
    "rate": {
        "description": "Request throughput (requests/second)",
        "prometheus": "rate(http_requests_total[5m])",
        "datadog": "sum:trace.servlet.request.hits{*}.as_rate()",
        "cloudwatch": "AWS/ApiGateway/Count",
    },
    "errors": {
        "description": "Error rate (5xx responses / total)",
        "prometheus": "sum(rate(http_requests_total{status=~'5..'}[5m])) / sum(rate(http_requests_total[5m]))",
        "datadog": "sum:trace.servlet.request.errors{*}.as_count() / sum:trace.servlet.request.hits{*}.as_count()",
        "cloudwatch": "AWS/ApiGateway/5XXError",
    },
    "duration": {
        "description": "Request latency (p50, p95, p99)",
        "prometheus": "histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))",
        "datadog": "avg:trace.servlet.request{*}",
        "cloudwatch": "AWS/ApiGateway/Latency",
    },
}

# USE Method (Resources): Utilization, Saturation, Errors
USE_METRICS = {
    "utilization": {
        "description": "Resource usage as percentage of capacity",
        "prometheus": "avg(node_cpu_seconds_total{mode!='idle'})",
        "datadog": "avg:system.cpu.user{*}",
        "cloudwatch": "AWS/EC2/CPUUtilization",
    },
    "saturation": {
        "description": "Queue depth / work pending",
        "prometheus": "node_load1",
        "datadog": "avg:system.load.1{*}",
        "cloudwatch": "AWS/SQS/ApproximateNumberOfMessagesVisible",
    },
    "errors": {
        "description": "Hardware/system errors",
        "prometheus": "node_disk_io_time_seconds_total",
        "datadog": "avg:system.io.await{*}",
        "cloudwatch": "AWS/EC2/StatusCheckFailed",
    },
}

# Golden Signals (Google SRE): Latency, Traffic, Errors, Saturation
GOLDEN_SIGNALS = ["latency", "traffic", "errors", "saturation"]

# Default thresholds based on industry best practices
DEFAULT_THRESHOLDS = {
    "error_rate_warning": 0.01,  # 1%
    "error_rate_critical": 0.05,  # 5%
    "latency_p99_warning_ms": 500,
    "latency_p99_critical_ms": 2000,
    "cpu_warning_percent": 70,
    "cpu_critical_percent": 90,
    "memory_warning_percent": 80,
    "memory_critical_percent": 95,
    "disk_warning_percent": 80,
    "disk_critical_percent": 90,
}

# Service type to recommended metrics mapping
SERVICE_METRICS = {
    ServiceType.HTTP_API: ["rate", "errors", "duration", "saturation"],
    ServiceType.WORKER: ["rate", "errors", "duration", "queue_depth", "utilization"],
    ServiceType.DATABASE: [
        "connections",
        "query_time",
        "replication_lag",
        "disk_usage",
        "cpu",
    ],
    ServiceType.CACHE: ["hit_rate", "memory_usage", "evictions", "connections"],
    ServiceType.GATEWAY: ["rate", "errors", "duration", "connections", "bandwidth"],
    ServiceType.QUEUE: ["queue_depth", "age_of_oldest", "throughput", "dlq_count"],
}


def _calculate_percentile(values: list[float], p: float) -> float:
    """Calculate the p-th percentile of values."""
    if not values:
        return 0.0
    sorted_values = sorted(values)
    idx = int(len(sorted_values) * p / 100)
    return sorted_values[min(idx, len(sorted_values) - 1)]


def _calculate_baseline(values: list[float]) -> dict[str, float]:
    """Calculate comprehensive baseline statistics for a metric."""
    if not values or len(values) < 3:
        return {
            "ok": False,
            "error": "Insufficient data points (need at least 3)",
        }

    return {
        "ok": True,
        "count": len(values),
        "mean": round(statistics.mean(values), 4),
        "median": round(statistics.median(values), 4),
        "stdev": round(statistics.stdev(values) if len(values) > 1 else 0, 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "p50": round(_calculate_percentile(values, 50), 4),
        "p90": round(_calculate_percentile(values, 90), 4),
        "p95": round(_calculate_percentile(values, 95), 4),
        "p99": round(_calculate_percentile(values, 99), 4),
    }


@function_tool
def compute_metric_baseline(
    service_name: str,
    metric_values: str,
    metric_name: str = "metric",
    service_type: str = "http_api",
    lookback_description: str = "7 days",
) -> str:
    """
    Compute baseline statistics for a metric to inform alert thresholds.

    This tool analyzes historical metric data to establish what "normal" looks like
    for a service. Use this before setting alert thresholds to ensure data-driven
    alerting rather than arbitrary values.

    The output includes percentiles (p50, p90, p95, p99) which are essential for
    SLO-based alerting. For example:
    - Use p50 for typical behavior
    - Use p95 for "most of the time" SLOs
    - Use p99 for edge cases and capacity planning

    Args:
        service_name: Name of the service being analyzed
        metric_values: JSON array of historical metric values
                       (e.g., "[1.2, 1.5, 1.3, 2.1, 1.4, ...]")
        metric_name: Name of the metric (e.g., "latency_seconds", "error_rate")
        service_type: Type of service for context (http_api, worker, database,
                      cache, gateway, queue)
        lookback_description: Human-readable description of the time period
                              (e.g., "7 days", "30 days")

    Returns:
        JSON with comprehensive baseline statistics including percentiles,
        distribution analysis, and recommendations for threshold setting.

    Example:
        compute_metric_baseline(
            service_name="payment-api",
            metric_values="[0.12, 0.15, 0.11, 0.18, 0.13, 0.14, ...]",
            metric_name="latency_p99_seconds",
            service_type="http_api",
            lookback_description="7 days"
        )
    """
    try:
        values = json.loads(metric_values)
        if not isinstance(values, list):
            return json.dumps(
                {"ok": False, "error": "metric_values must be a JSON array"}
            )

        float_values = [float(v) for v in values]
        baseline = _calculate_baseline(float_values)

        if not baseline.get("ok"):
            return json.dumps(baseline)

        # Analyze distribution characteristics
        mean = baseline["mean"]
        stdev = baseline["stdev"]
        p99 = baseline["p99"]
        p50 = baseline["p50"]

        # Coefficient of variation (CV) - measure of relative variability
        cv = (stdev / mean * 100) if mean > 0 else 0

        # Skewness indicator (simplified)
        skewness = (
            "right_skewed"
            if p99 > mean * 2
            else "symmetric" if abs(mean - p50) < stdev * 0.5 else "left_skewed"
        )

        # Long tail analysis
        p99_to_p50_ratio = p99 / p50 if p50 > 0 else 0
        has_long_tail = p99_to_p50_ratio > 3

        # Generate threshold recommendations
        recommendations = _generate_threshold_recommendations(
            metric_name, baseline, service_type
        )

        result = {
            "ok": True,
            "service_name": service_name,
            "metric_name": metric_name,
            "service_type": service_type,
            "lookback_period": lookback_description,
            "baseline": baseline,
            "distribution": {
                "type": skewness,
                "coefficient_of_variation": round(cv, 2),
                "has_long_tail": has_long_tail,
                "p99_to_p50_ratio": round(p99_to_p50_ratio, 2),
            },
            "recommendations": recommendations,
            "next_steps": [
                "Use suggest_alert_thresholds() to get specific threshold values",
                "Review recommendations against your SLO targets",
                "Use generate_alert_rules() to create alerting config",
            ],
        }

        logger.info(
            "metric_baseline_computed",
            service=service_name,
            metric=metric_name,
            data_points=len(float_values),
        )
        return json.dumps(result)

    except json.JSONDecodeError as e:
        return json.dumps({"ok": False, "error": f"Invalid JSON: {e}"})
    except Exception as e:
        logger.error("compute_baseline_failed", error=str(e))
        return json.dumps({"ok": False, "error": str(e)})


def _generate_threshold_recommendations(
    metric_name: str, baseline: dict, service_type: str
) -> dict[str, Any]:
    """Generate threshold recommendations based on metric type and baseline."""
    metric_lower = metric_name.lower()
    recommendations = {}

    # Error rate thresholds
    if "error" in metric_lower:
        recommendations["warning"] = max(
            baseline["p95"],
            DEFAULT_THRESHOLDS["error_rate_warning"],
        )
        recommendations["critical"] = max(
            baseline["p99"] * 2,
            DEFAULT_THRESHOLDS["error_rate_critical"],
        )
        recommendations["reasoning"] = (
            "Error rate thresholds set above p95 baseline to avoid noise, "
            "with critical at 2x p99 to catch real issues."
        )

    # Latency thresholds
    elif any(x in metric_lower for x in ["latency", "duration", "time"]):
        # Use p95 for warning, p99 * 1.5 for critical
        recommendations["warning"] = baseline["p95"]
        recommendations["critical"] = baseline["p99"] * 1.5
        recommendations["reasoning"] = (
            "Latency thresholds based on historical percentiles. "
            "Warning at p95 catches degradation early, critical at 1.5x p99."
        )

    # CPU/Memory thresholds
    elif any(x in metric_lower for x in ["cpu", "memory", "mem"]):
        recommendations["warning"] = min(
            baseline["p95"] + 10,
            DEFAULT_THRESHOLDS.get(f"{metric_lower}_warning_percent", 80),
        )
        recommendations["critical"] = min(
            baseline["p99"] + 10,
            DEFAULT_THRESHOLDS.get(f"{metric_lower}_critical_percent", 95),
        )
        recommendations["reasoning"] = (
            "Resource thresholds set with headroom above p95/p99. "
            "Allows for normal variation while catching resource exhaustion."
        )

    # Generic thresholds for unknown metrics
    else:
        recommendations["warning"] = baseline["p95"]
        recommendations["critical"] = baseline["p99"] * 2
        recommendations["reasoning"] = (
            "Generic thresholds: warning at p95, critical at 2x p99. "
            "Adjust based on the specific metric's behavior."
        )

    recommendations["baseline_used"] = {
        "p95": baseline["p95"],
        "p99": baseline["p99"],
        "mean": baseline["mean"],
    }

    return recommendations


@function_tool
def suggest_alert_thresholds(
    service_name: str,
    service_type: str = "http_api",
    baselines: str = "{}",
    slo_availability: float = 99.9,
    slo_latency_p99_ms: float = 500,
    custom_targets: str = "{}",
) -> str:
    """
    Generate data-driven alert threshold recommendations for a service.

    This tool combines baseline statistics with SLO targets to produce
    actionable alert thresholds. It follows SRE best practices:
    - RED method for request-driven services
    - USE method for resource utilization
    - Golden Signals for overall health

    Args:
        service_name: Name of the service
        service_type: Type of service (http_api, worker, database, cache, gateway, queue)
        baselines: JSON object with baseline stats per metric
                   (output from compute_metric_baseline)
                   Format: {"metric_name": {"p50": ..., "p95": ..., "p99": ..., ...}}
        slo_availability: Target availability percentage (default: 99.9%)
        slo_latency_p99_ms: Target p99 latency in milliseconds (default: 500ms)
        custom_targets: JSON object with custom thresholds to override defaults
                        Format: {"error_rate_warning": 0.02, "cpu_critical_percent": 85}

    Returns:
        JSON with comprehensive threshold recommendations organized by:
        - RED metrics (rate, errors, duration)
        - USE metrics (utilization, saturation, errors)
        - Service-specific recommendations

    Example:
        suggest_alert_thresholds(
            service_name="payment-api",
            service_type="http_api",
            baselines='{"latency_p99": {"p50": 0.1, "p95": 0.3, "p99": 0.5}}',
            slo_availability=99.95,
            slo_latency_p99_ms=300
        )
    """
    try:
        baseline_data = json.loads(baselines) if baselines != "{}" else {}
        custom = json.loads(custom_targets) if custom_targets != "{}" else {}

        # Calculate error budget from SLO
        error_budget = (100 - slo_availability) / 100  # e.g., 0.001 for 99.9%

        # Get recommended metrics for service type
        try:
            svc_type = ServiceType(service_type)
        except ValueError:
            svc_type = ServiceType.HTTP_API

        recommended_metrics = SERVICE_METRICS.get(
            svc_type, SERVICE_METRICS[ServiceType.HTTP_API]
        )

        # Build threshold recommendations
        thresholds = {
            "service_name": service_name,
            "service_type": service_type,
            "slo_targets": {
                "availability": slo_availability,
                "latency_p99_ms": slo_latency_p99_ms,
                "error_budget": round(error_budget, 6),
            },
            "recommended_metrics": recommended_metrics,
            "alerts": [],
        }

        # RED Metrics for request-driven services
        if svc_type in [ServiceType.HTTP_API, ServiceType.GATEWAY]:
            thresholds["alerts"].extend(
                _generate_red_alerts(
                    service_name,
                    baseline_data,
                    error_budget,
                    slo_latency_p99_ms,
                    custom,
                )
            )

        # USE Metrics for all services
        thresholds["alerts"].extend(
            _generate_use_alerts(service_name, baseline_data, custom)
        )

        # Service-specific alerts
        if svc_type == ServiceType.DATABASE:
            thresholds["alerts"].extend(
                _generate_database_alerts(service_name, baseline_data, custom)
            )
        elif svc_type == ServiceType.QUEUE:
            thresholds["alerts"].extend(
                _generate_queue_alerts(service_name, baseline_data, custom)
            )
        elif svc_type == ServiceType.CACHE:
            thresholds["alerts"].extend(
                _generate_cache_alerts(service_name, baseline_data, custom)
            )

        thresholds["summary"] = {
            "total_alerts": len(thresholds["alerts"]),
            "by_severity": {
                "critical": len(
                    [a for a in thresholds["alerts"] if a.get("severity") == "critical"]
                ),
                "warning": len(
                    [a for a in thresholds["alerts"] if a.get("severity") == "warning"]
                ),
            },
            "methodology": "SRE best practices (RED/USE/Golden Signals)",
        }

        thresholds["next_steps"] = [
            "Review thresholds against your team's context",
            "Use generate_alert_rules() to create configuration",
            "Test in staging before production deployment",
        ]

        logger.info(
            "alert_thresholds_suggested",
            service=service_name,
            alerts=len(thresholds["alerts"]),
        )
        return json.dumps(thresholds)

    except json.JSONDecodeError as e:
        return json.dumps({"ok": False, "error": f"Invalid JSON: {e}"})
    except Exception as e:
        logger.error("suggest_thresholds_failed", error=str(e))
        return json.dumps({"ok": False, "error": str(e)})


def _generate_red_alerts(
    service_name: str,
    baselines: dict,
    error_budget: float,
    latency_target_ms: float,
    custom: dict,
) -> list[dict]:
    """Generate RED method alerts."""
    alerts = []

    # Error Rate Alert (based on error budget)
    error_warning = custom.get("error_rate_warning", error_budget * 0.5)
    error_critical = custom.get("error_rate_critical", error_budget)

    alerts.append(
        {
            "name": f"{service_name}_error_rate_warning",
            "metric": "error_rate",
            "condition": "greater_than",
            "threshold": error_warning,
            "duration": "5m",
            "severity": "warning",
            "description": f"Error rate exceeds {error_warning*100:.2f}% (50% of error budget)",
            "methodology": "RED",
        }
    )

    alerts.append(
        {
            "name": f"{service_name}_error_rate_critical",
            "metric": "error_rate",
            "condition": "greater_than",
            "threshold": error_critical,
            "duration": "5m",
            "severity": "critical",
            "description": f"Error rate exceeds {error_critical*100:.2f}% (100% of error budget)",
            "methodology": "RED",
        }
    )

    # Latency Alert (based on SLO target and baseline)
    latency_baseline = baselines.get("latency_p99", {})
    latency_warning = custom.get(
        "latency_warning_ms", latency_baseline.get("p95", latency_target_ms * 0.8)
    )
    latency_critical = custom.get("latency_critical_ms", latency_target_ms)

    alerts.append(
        {
            "name": f"{service_name}_latency_p99_warning",
            "metric": "latency_p99",
            "condition": "greater_than",
            "threshold": latency_warning / 1000,  # Convert to seconds
            "duration": "5m",
            "severity": "warning",
            "description": f"p99 latency exceeds {latency_warning}ms",
            "methodology": "RED",
        }
    )

    alerts.append(
        {
            "name": f"{service_name}_latency_p99_critical",
            "metric": "latency_p99",
            "condition": "greater_than",
            "threshold": latency_critical / 1000,
            "duration": "5m",
            "severity": "critical",
            "description": f"p99 latency exceeds SLO target of {latency_critical}ms",
            "methodology": "RED",
        }
    )

    return alerts


def _generate_use_alerts(
    service_name: str, baselines: dict, custom: dict
) -> list[dict]:
    """Generate USE method alerts for resource utilization."""
    alerts = []

    # CPU Utilization
    cpu_warning = custom.get(
        "cpu_warning_percent", DEFAULT_THRESHOLDS["cpu_warning_percent"]
    )
    cpu_critical = custom.get(
        "cpu_critical_percent", DEFAULT_THRESHOLDS["cpu_critical_percent"]
    )

    alerts.append(
        {
            "name": f"{service_name}_cpu_warning",
            "metric": "cpu_utilization_percent",
            "condition": "greater_than",
            "threshold": cpu_warning,
            "duration": "10m",
            "severity": "warning",
            "description": f"CPU utilization exceeds {cpu_warning}%",
            "methodology": "USE",
        }
    )

    alerts.append(
        {
            "name": f"{service_name}_cpu_critical",
            "metric": "cpu_utilization_percent",
            "condition": "greater_than",
            "threshold": cpu_critical,
            "duration": "5m",
            "severity": "critical",
            "description": f"CPU utilization exceeds {cpu_critical}%",
            "methodology": "USE",
        }
    )

    # Memory Utilization
    mem_warning = custom.get(
        "memory_warning_percent", DEFAULT_THRESHOLDS["memory_warning_percent"]
    )
    mem_critical = custom.get(
        "memory_critical_percent", DEFAULT_THRESHOLDS["memory_critical_percent"]
    )

    alerts.append(
        {
            "name": f"{service_name}_memory_warning",
            "metric": "memory_utilization_percent",
            "condition": "greater_than",
            "threshold": mem_warning,
            "duration": "10m",
            "severity": "warning",
            "description": f"Memory utilization exceeds {mem_warning}%",
            "methodology": "USE",
        }
    )

    alerts.append(
        {
            "name": f"{service_name}_memory_critical",
            "metric": "memory_utilization_percent",
            "condition": "greater_than",
            "threshold": mem_critical,
            "duration": "5m",
            "severity": "critical",
            "description": f"Memory utilization exceeds {mem_critical}%",
            "methodology": "USE",
        }
    )

    return alerts


def _generate_database_alerts(
    service_name: str, baselines: dict, custom: dict
) -> list[dict]:
    """Generate database-specific alerts."""
    alerts = []

    # Connection pool saturation
    alerts.append(
        {
            "name": f"{service_name}_connections_warning",
            "metric": "connection_count",
            "condition": "greater_than",
            "threshold": custom.get("connection_warning_percent", 80),
            "duration": "5m",
            "severity": "warning",
            "description": "Connection pool utilization exceeds 80%",
            "methodology": "Database",
        }
    )

    # Replication lag
    alerts.append(
        {
            "name": f"{service_name}_replication_lag_critical",
            "metric": "replication_lag_seconds",
            "condition": "greater_than",
            "threshold": custom.get("replication_lag_critical_seconds", 30),
            "duration": "5m",
            "severity": "critical",
            "description": "Replication lag exceeds 30 seconds",
            "methodology": "Database",
        }
    )

    # Slow queries
    alerts.append(
        {
            "name": f"{service_name}_slow_queries_warning",
            "metric": "slow_query_count",
            "condition": "greater_than",
            "threshold": custom.get("slow_query_threshold", 10),
            "duration": "5m",
            "severity": "warning",
            "description": "High number of slow queries detected",
            "methodology": "Database",
        }
    )

    return alerts


def _generate_queue_alerts(
    service_name: str, baselines: dict, custom: dict
) -> list[dict]:
    """Generate queue-specific alerts."""
    alerts = []

    # Queue depth
    alerts.append(
        {
            "name": f"{service_name}_queue_depth_warning",
            "metric": "queue_depth",
            "condition": "greater_than",
            "threshold": custom.get("queue_depth_warning", 1000),
            "duration": "10m",
            "severity": "warning",
            "description": "Queue depth exceeds warning threshold",
            "methodology": "Queue",
        }
    )

    # Age of oldest message
    alerts.append(
        {
            "name": f"{service_name}_oldest_message_critical",
            "metric": "oldest_message_age_seconds",
            "condition": "greater_than",
            "threshold": custom.get("oldest_message_critical_seconds", 3600),
            "duration": "5m",
            "severity": "critical",
            "description": "Oldest message in queue is over 1 hour old",
            "methodology": "Queue",
        }
    )

    # Dead letter queue
    alerts.append(
        {
            "name": f"{service_name}_dlq_messages",
            "metric": "dlq_message_count",
            "condition": "greater_than",
            "threshold": custom.get("dlq_threshold", 0),
            "duration": "1m",
            "severity": "warning",
            "description": "Messages detected in dead letter queue",
            "methodology": "Queue",
        }
    )

    return alerts


def _generate_cache_alerts(
    service_name: str, baselines: dict, custom: dict
) -> list[dict]:
    """Generate cache-specific alerts."""
    alerts = []

    # Hit rate
    alerts.append(
        {
            "name": f"{service_name}_cache_hit_rate_warning",
            "metric": "cache_hit_rate",
            "condition": "less_than",
            "threshold": custom.get("cache_hit_rate_warning", 0.8),
            "duration": "15m",
            "severity": "warning",
            "description": "Cache hit rate below 80%",
            "methodology": "Cache",
        }
    )

    # Evictions
    alerts.append(
        {
            "name": f"{service_name}_cache_evictions_critical",
            "metric": "eviction_rate",
            "condition": "greater_than",
            "threshold": custom.get("eviction_rate_critical", 100),
            "duration": "5m",
            "severity": "critical",
            "description": "High cache eviction rate indicates memory pressure",
            "methodology": "Cache",
        }
    )

    return alerts


@function_tool
def generate_alert_rules(
    service_name: str,
    recommendations: str,
    output_format: str = "prometheus_yaml",
    namespace: str = "default",
    notification_channel: str = "#alerts",
    additional_labels: str = "{}",
) -> str:
    """
    Generate alert rules from threshold recommendations.

    This tool converts the output from suggest_alert_thresholds() into
    production-ready alert configuration in your preferred format.

    Supported formats:
    - prometheus_yaml: Prometheus alerting rules (PrometheusRule CRD)
    - datadog_json: Datadog monitor definitions
    - cloudwatch_json: CloudWatch Alarms configuration
    - proposal_doc: Markdown document for review

    Args:
        service_name: Name of the service
        recommendations: JSON output from suggest_alert_thresholds()
        output_format: Target format (prometheus_yaml, datadog_json,
                       cloudwatch_json, proposal_doc)
        namespace: Kubernetes namespace or service namespace (for labels)
        notification_channel: Slack channel or notification target
        additional_labels: JSON object with extra labels to add
                           Format: {"team": "platform", "env": "production"}

    Returns:
        Alert configuration in the requested format, ready for deployment.

    Example:
        generate_alert_rules(
            service_name="payment-api",
            recommendations='{"alerts": [...]}',
            output_format="prometheus_yaml",
            namespace="payments",
            notification_channel="#payments-alerts"
        )
    """
    try:
        recs = json.loads(recommendations)
        labels = json.loads(additional_labels) if additional_labels != "{}" else {}

        alerts = recs.get("alerts", [])
        if not alerts:
            return json.dumps(
                {
                    "ok": False,
                    "error": "No alerts found in recommendations",
                }
            )

        try:
            fmt = OutputFormat(output_format)
        except ValueError:
            fmt = OutputFormat.PROPOSAL_DOC

        if fmt == OutputFormat.PROMETHEUS_YAML:
            output = _generate_prometheus_rules(
                service_name, alerts, namespace, notification_channel, labels
            )
        elif fmt == OutputFormat.DATADOG_JSON:
            output = _generate_datadog_monitors(
                service_name, alerts, notification_channel, labels
            )
        elif fmt == OutputFormat.CLOUDWATCH_JSON:
            output = _generate_cloudwatch_alarms(
                service_name, alerts, notification_channel, labels
            )
        else:  # PROPOSAL_DOC
            output = _generate_proposal_doc(
                service_name, alerts, recs.get("slo_targets", {}), namespace
            )

        result = {
            "ok": True,
            "service_name": service_name,
            "output_format": output_format,
            "alerts_generated": len(alerts),
            "output": output,
        }

        logger.info(
            "alert_rules_generated",
            service=service_name,
            format=output_format,
            count=len(alerts),
        )
        return json.dumps(result)

    except json.JSONDecodeError as e:
        return json.dumps({"ok": False, "error": f"Invalid JSON: {e}"})
    except Exception as e:
        logger.error("generate_rules_failed", error=str(e))
        return json.dumps({"ok": False, "error": str(e)})


def _generate_prometheus_rules(
    service_name: str,
    alerts: list[dict],
    namespace: str,
    notification_channel: str,
    labels: dict,
) -> str:
    """Generate Prometheus alerting rules YAML."""
    rules = []
    for alert in alerts:
        # Map metric to PromQL expression
        metric = alert["metric"]
        threshold = alert["threshold"]
        condition = alert["condition"]
        duration = alert["duration"]

        # Build PromQL expression
        if metric == "error_rate":
            expr = f'sum(rate(http_requests_total{{service="{service_name}",status=~"5.."}}[5m])) / sum(rate(http_requests_total{{service="{service_name}"}}[5m])) > {threshold}'
        elif metric == "latency_p99":
            expr = f'histogram_quantile(0.99, rate(http_request_duration_seconds_bucket{{service="{service_name}"}}[5m])) > {threshold}'
        elif metric == "cpu_utilization_percent":
            expr = f'avg(rate(container_cpu_usage_seconds_total{{namespace="{namespace}",pod=~"{service_name}-.*"}}[5m])) * 100 > {threshold}'
        elif metric == "memory_utilization_percent":
            expr = f'avg(container_memory_usage_bytes{{namespace="{namespace}",pod=~"{service_name}-.*"}} / container_memory_limit_bytes{{namespace="{namespace}",pod=~"{service_name}-.*"}}) * 100 > {threshold}'
        else:
            # Generic expression
            operator = ">" if condition == "greater_than" else "<"
            expr = f'{metric}{{service="{service_name}"}} {operator} {threshold}'

        rule = {
            "alert": alert["name"],
            "expr": expr,
            "for": duration,
            "labels": {
                "severity": alert["severity"],
                "service": service_name,
                "namespace": namespace,
                **labels,
            },
            "annotations": {
                "summary": alert["description"],
                "description": f'{alert["description"]}. Methodology: {alert.get("methodology", "SRE")}',
                "runbook_url": f"https://runbooks.example.com/{service_name}/{alert['metric']}",
            },
        }
        rules.append(rule)

    # Format as PrometheusRule CRD
    prometheus_rule = {
        "apiVersion": "monitoring.coreos.com/v1",
        "kind": "PrometheusRule",
        "metadata": {
            "name": f"{service_name}-alerts",
            "namespace": namespace,
            "labels": {
                "app": service_name,
                "prometheus": "k8s",
                **labels,
            },
        },
        "spec": {
            "groups": [
                {
                    "name": f"{service_name}.rules",
                    "rules": rules,
                }
            ]
        },
    }

    import yaml

    try:
        return yaml.dump(prometheus_rule, default_flow_style=False, sort_keys=False)
    except ImportError:
        # Fallback to JSON if yaml not available
        return json.dumps(prometheus_rule, indent=2)


def _generate_datadog_monitors(
    service_name: str,
    alerts: list[dict],
    notification_channel: str,
    labels: dict,
) -> str:
    """Generate Datadog monitor definitions."""
    monitors = []
    for alert in alerts:
        metric = alert["metric"]
        threshold = alert["threshold"]
        condition = alert["condition"]

        # Map metric to Datadog query
        if metric == "error_rate":
            query = f"sum:trace.servlet.request.errors{{service:{service_name}}}.as_rate() / sum:trace.servlet.request.hits{{service:{service_name}}}.as_rate()"
        elif metric == "latency_p99":
            query = f"p99:trace.servlet.request{{service:{service_name}}}"
        elif metric == "cpu_utilization_percent":
            query = f"avg:docker.cpu.usage{{service:{service_name}}}"
        elif metric == "memory_utilization_percent":
            query = f"avg:docker.mem.in_use{{service:{service_name}}}"
        else:
            query = f"avg:{metric}{{service:{service_name}}}"

        comparator = ">" if condition == "greater_than" else "<"

        monitor = {
            "name": f"[{service_name}] {alert['description']}",
            "type": "metric alert",
            "query": f"{query} {comparator} {threshold}",
            "message": f"""
{alert["description"]}

Methodology: {alert.get("methodology", "SRE")}

@{notification_channel}

{{{{#is_alert}}}}
Alert triggered: {{{{value}}}}
{{{{/is_alert}}}}

{{{{#is_recovery}}}}
Alert recovered
{{{{/is_recovery}}}}
""".strip(),
            "tags": [
                f"service:{service_name}",
                f"severity:{alert['severity']}",
                f"methodology:{alert.get('methodology', 'sre')}",
            ]
            + [f"{k}:{v}" for k, v in labels.items()],
            "options": {
                "thresholds": {
                    "critical": threshold,
                    "warning": (
                        threshold * 0.8
                        if condition == "greater_than"
                        else threshold * 1.2
                    ),
                },
                "notify_no_data": True,
                "no_data_timeframe": 10,
                "require_full_window": True,
                "include_tags": True,
                "evaluation_delay": 60,
            },
        }
        monitors.append(monitor)

    return json.dumps({"monitors": monitors}, indent=2)


def _generate_cloudwatch_alarms(
    service_name: str,
    alerts: list[dict],
    notification_channel: str,
    labels: dict,
) -> str:
    """Generate CloudWatch Alarms configuration."""
    alarms = []
    for alert in alerts:
        metric = alert["metric"]
        threshold = alert["threshold"]
        condition = alert["condition"]

        # Parse duration to periods
        duration = alert["duration"]
        if duration.endswith("m"):
            evaluation_periods = int(duration[:-1]) // 5  # 5-minute periods
        else:
            evaluation_periods = 1

        # Map metric to CloudWatch
        metric_mapping = {
            "error_rate": {"namespace": "AWS/ApiGateway", "metric_name": "5XXError"},
            "latency_p99": {"namespace": "AWS/ApiGateway", "metric_name": "Latency"},
            "cpu_utilization_percent": {
                "namespace": "AWS/ECS",
                "metric_name": "CPUUtilization",
            },
            "memory_utilization_percent": {
                "namespace": "AWS/ECS",
                "metric_name": "MemoryUtilization",
            },
        }

        cw_metric = metric_mapping.get(
            metric, {"namespace": "Custom", "metric_name": metric}
        )

        alarm = {
            "AlarmName": alert["name"],
            "AlarmDescription": alert["description"],
            "MetricName": cw_metric["metric_name"],
            "Namespace": cw_metric["namespace"],
            "Statistic": "Average",
            "Period": 300,
            "EvaluationPeriods": max(evaluation_periods, 1),
            "Threshold": threshold,
            "ComparisonOperator": (
                "GreaterThanThreshold"
                if condition == "greater_than"
                else "LessThanThreshold"
            ),
            "Dimensions": [
                {"Name": "ServiceName", "Value": service_name},
            ],
            "AlarmActions": [
                f"arn:aws:sns:us-east-1:123456789012:{notification_channel.replace('#', '')}"
            ],
            "Tags": [
                {"Key": "Service", "Value": service_name},
                {"Key": "Severity", "Value": alert["severity"]},
                {"Key": "Methodology", "Value": alert.get("methodology", "SRE")},
            ]
            + [{"Key": k, "Value": v} for k, v in labels.items()],
        }
        alarms.append(alarm)

    return json.dumps({"alarms": alarms}, indent=2)


def _generate_proposal_doc(
    service_name: str,
    alerts: list[dict],
    slo_targets: dict,
    namespace: str,
) -> str:
    """Generate a markdown proposal document for review."""
    doc = f"""# Alert Configuration Proposal: {service_name}

## Overview

This document proposes alert configurations for **{service_name}** based on SRE best practices
and data-driven thresholds.

## SLO Targets

| Target | Value |
|--------|-------|
| Availability | {slo_targets.get('availability', 99.9)}% |
| Latency (p99) | {slo_targets.get('latency_p99_ms', 500)}ms |
| Error Budget | {slo_targets.get('error_budget', 0.001) * 100:.3f}% |

## Proposed Alerts

"""

    # Group alerts by methodology
    by_method = {}
    for alert in alerts:
        method = alert.get("methodology", "Other")
        if method not in by_method:
            by_method[method] = []
        by_method[method].append(alert)

    for method, method_alerts in by_method.items():
        doc += f"### {method} Methodology\n\n"
        doc += "| Alert | Metric | Threshold | Duration | Severity |\n"
        doc += "|-------|--------|-----------|----------|----------|\n"

        for alert in method_alerts:
            condition = ">" if alert["condition"] == "greater_than" else "<"
            doc += f"| {alert['name']} | {alert['metric']} | {condition} {alert['threshold']} | {alert['duration']} | {alert['severity']} |\n"

        doc += "\n"

    doc += f"""## Implementation Notes

1. **Namespace**: {namespace}
2. **Notification Channel**: Configure based on your team's preferences
3. **Testing**: Deploy to staging first and verify thresholds
4. **Iteration**: Adjust thresholds based on alert frequency after 1-2 weeks

## Approval

- [ ] Platform team review
- [ ] Service owner approval
- [ ] SRE sign-off

## Next Steps

1. Generate configuration using `generate_alert_rules()` with desired format
2. Apply to staging environment
3. Monitor for 1 week
4. Adjust thresholds if needed
5. Deploy to production

---
*Generated by IncidentFox Observability Advisor*
"""

    return doc


# List of tools for registration
OBSERVABILITY_ADVISOR_TOOLS = [
    compute_metric_baseline,
    suggest_alert_thresholds,
    generate_alert_rules,
]

"""
Metrics collection and export for Prometheus and CloudWatch.

Features:
- Prometheus metrics export
- CloudWatch metrics for AWS
- Agent execution metrics
- Tool usage metrics
- Error tracking
"""

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import wraps
from typing import Any

import boto3
from botocore.exceptions import ClientError
from prometheus_client import REGISTRY, Counter, Gauge, Histogram, generate_latest

logger = logging.getLogger(__name__)


@dataclass
class MetricsConfig:
    """Configuration for the metrics system."""

    enabled: bool = True
    cloudwatch_enabled: bool = False
    cloudwatch_namespace: str = "IncidentFox"


# Prometheus Metrics
agent_requests_total = Counter(
    "agent_requests_total",
    "Total number of agent requests",
    ["agent_name", "status"],
)

agent_duration_seconds = Histogram(
    "agent_duration_seconds",
    "Agent execution duration in seconds",
    ["agent_name"],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0],
)

tool_calls_total = Counter(
    "tool_calls_total",
    "Total number of tool calls",
    ["tool_name", "status"],
)

tool_duration_seconds = Histogram(
    "tool_duration_seconds",
    "Tool execution duration in seconds",
    ["tool_name"],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0],
)

llm_tokens_total = Counter(
    "llm_tokens_total",
    "Total LLM tokens used",
    ["model", "type"],  # type: completion or prompt
)

llm_requests_total = Counter(
    "llm_requests_total",
    "Total LLM API requests",
    ["model", "status"],
)

active_agents = Gauge(
    "active_agents",
    "Number of currently active agents",
)

errors_total = Counter(
    "errors_total",
    "Total number of errors",
    ["error_type", "component"],
)


class MetricsCollector:
    """Metrics collector that supports both Prometheus and CloudWatch."""

    def __init__(self, config: MetricsConfig):
        """Initialize metrics collector."""
        self.config = config
        self.cloudwatch = None

        if config.cloudwatch_enabled:
            self._setup_cloudwatch()

    def _setup_cloudwatch(self) -> None:
        """Setup CloudWatch client."""
        try:
            self.cloudwatch = boto3.client("cloudwatch")
            logger.info(
                "CloudWatch metrics enabled (namespace=%s)", self.config.cloudwatch_namespace
            )
        except Exception as e:
            logger.error("Failed to setup CloudWatch: %s", e)

    def record_agent_request(
        self,
        agent_name: str,
        duration: float,
        status: str = "success",
        token_usage: dict | None = None,
    ) -> None:
        """
        Record an agent request.

        Args:
            agent_name: Name of the agent
            duration: Execution duration in seconds
            status: success or error
            token_usage: Optional token usage dict with 'prompt' and 'completion'
        """
        agent_requests_total.labels(agent_name=agent_name, status=status).inc()
        agent_duration_seconds.labels(agent_name=agent_name).observe(duration)

        if self.cloudwatch:
            self._put_cloudwatch_metrics(
                [
                    {
                        "MetricName": "AgentRequests",
                        "Value": 1,
                        "Unit": "Count",
                        "Dimensions": [
                            {"Name": "AgentName", "Value": agent_name},
                            {"Name": "Status", "Value": status},
                        ],
                    },
                    {
                        "MetricName": "AgentDuration",
                        "Value": duration,
                        "Unit": "Seconds",
                        "Dimensions": [{"Name": "AgentName", "Value": agent_name}],
                    },
                ]
            )

        if token_usage:
            model = token_usage.get("model", "unknown")
            prompt_tokens = token_usage.get("prompt_tokens", 0)
            completion_tokens = token_usage.get("completion_tokens", 0)

            llm_tokens_total.labels(model=model, type="prompt").inc(prompt_tokens)
            llm_tokens_total.labels(model=model, type="completion").inc(
                completion_tokens
            )

    def record_tool_call(
        self, tool_name: str, duration: float, status: str = "success"
    ) -> None:
        """Record a tool call."""
        tool_calls_total.labels(tool_name=tool_name, status=status).inc()
        tool_duration_seconds.labels(tool_name=tool_name).observe(duration)

        if self.cloudwatch:
            self._put_cloudwatch_metrics(
                [
                    {
                        "MetricName": "ToolCalls",
                        "Value": 1,
                        "Unit": "Count",
                        "Dimensions": [
                            {"Name": "ToolName", "Value": tool_name},
                            {"Name": "Status", "Value": status},
                        ],
                    },
                    {
                        "MetricName": "ToolDuration",
                        "Value": duration,
                        "Unit": "Seconds",
                        "Dimensions": [{"Name": "ToolName", "Value": tool_name}],
                    },
                ]
            )

    def record_error(self, error_type: str, component: str) -> None:
        """Record an error."""
        errors_total.labels(error_type=error_type, component=component).inc()

        if self.cloudwatch:
            self._put_cloudwatch_metrics(
                [
                    {
                        "MetricName": "Errors",
                        "Value": 1,
                        "Unit": "Count",
                        "Dimensions": [
                            {"Name": "ErrorType", "Value": error_type},
                            {"Name": "Component", "Value": component},
                        ],
                    }
                ]
            )

    def _put_cloudwatch_metrics(self, metrics: list[dict]) -> None:
        """Put metrics to CloudWatch."""
        if not self.cloudwatch:
            return

        try:
            self.cloudwatch.put_metric_data(
                Namespace=self.config.cloudwatch_namespace,
                MetricData=metrics,
            )
        except ClientError as e:
            logger.error("Failed to put CloudWatch metrics: %s", e)

    @contextmanager
    def track_agent_execution(self, agent_name: str):
        """
        Context manager to track agent execution time.

        Usage:
            with metrics.track_agent_execution("my_agent"):
                # agent code here
        """
        active_agents.inc()
        start_time = time.perf_counter()
        status = "success"

        try:
            yield
        except Exception as e:
            status = "error"
            self.record_error(type(e).__name__, agent_name)
            raise
        finally:
            duration = time.perf_counter() - start_time
            active_agents.dec()
            self.record_agent_request(agent_name, duration, status)

    @contextmanager
    def track_tool_execution(self, tool_name: str):
        """Context manager to track tool execution time."""
        start_time = time.perf_counter()
        status = "success"

        try:
            yield
        except Exception as e:
            status = "error"
            self.record_error(type(e).__name__, tool_name)
            raise
        finally:
            duration = time.perf_counter() - start_time
            self.record_tool_call(tool_name, duration, status)

    def get_prometheus_metrics(self) -> bytes:
        """Get Prometheus metrics in text format."""
        return generate_latest(REGISTRY)


# Global metrics collector instance
_metrics_collector: MetricsCollector | None = None


def get_metrics_collector() -> MetricsCollector:
    """Get the global metrics collector instance."""
    if _metrics_collector is None:
        raise RuntimeError(
            "Metrics collector not initialized. Call setup_metrics() first."
        )
    return _metrics_collector


def setup_metrics(config: MetricsConfig | None = None) -> MetricsCollector:
    """Setup metrics collector."""
    global _metrics_collector
    if config is None:
        config = MetricsConfig()
    _metrics_collector = MetricsCollector(config)
    logger.info("Metrics setup complete (prometheus_enabled=%s)", config.enabled)
    return _metrics_collector


# Decorators for easy metric tracking
def track_agent_metrics(agent_name: str):
    """Decorator to track agent execution metrics."""

    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            collector = get_metrics_collector()
            with collector.track_agent_execution(agent_name):
                return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            collector = get_metrics_collector()
            with collector.track_agent_execution(agent_name):
                return func(*args, **kwargs)

        import inspect

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


def track_tool_metrics(tool_name: str):
    """Decorator to track tool execution metrics."""

    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            collector = get_metrics_collector()
            with collector.track_tool_execution(tool_name):
                return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            collector = get_metrics_collector()
            with collector.track_tool_execution(tool_name):
                return func(*args, **kwargs)

        import inspect

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator

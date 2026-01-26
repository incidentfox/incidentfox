from __future__ import annotations

from prometheus_client import Counter, Histogram

# Keep label cardinality low (only a few endpoints exist).
HTTP_REQUESTS_TOTAL = Counter(
    "config_service_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "config_service_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

AUTH_FAILURES_TOTAL = Counter(
    "config_service_auth_failures_total",
    "Total authentication failures",
    ["reason"],
)

CONFIG_UPDATES_TOTAL = Counter(
    "config_service_config_updates_total",
    "Total successful team config updates",
    [],
)

CONFIG_CACHE_EVENTS_TOTAL = Counter(
    "config_service_config_cache_events_total",
    "Config cache events",
    ["kind", "result"],
)

ADMIN_ACTIONS_TOTAL = Counter(
    "config_service_admin_actions_total",
    "Total admin actions",
    ["action", "outcome"],
)

FEEDBACK_TOTAL = Counter(
    "incidentfox_agent_feedback_total",
    "Total agent feedback received",
    ["feedback_type", "source"],  # feedback_type: positive/negative, source: slack/github
)

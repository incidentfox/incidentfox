"""Domain to integration ID mapping.

Maps target hostnames to integration IDs for credential lookup.
When requests come through proxy (envoy:8001), use path-based routing.
"""

DOMAIN_TO_INTEGRATION: dict[str, str] = {
    # Anthropic
    "api.anthropic.com": "anthropic",
    # Coralogix (all regions)
    "api.coralogix.com": "coralogix",
    "api.us1.coralogix.com": "coralogix",
    "api.us2.coralogix.com": "coralogix",
    "api.eu1.coralogix.com": "coralogix",
    "api.eu2.coralogix.com": "coralogix",
    "api.ap1.coralogix.com": "coralogix",
    "api.ap2.coralogix.com": "coralogix",
    "api.ap3.coralogix.com": "coralogix",
    # Coralogix NG API (DataPrime)
    "ng-api-http.coralogix.com": "coralogix",
    "ng-api-http.cx498.coralogix.com": "coralogix",
    "ng-api-http.us1.coralogix.com": "coralogix",
    "ng-api-http.us2.coralogix.com": "coralogix",
    "ng-api-http.eu1.coralogix.com": "coralogix",
    "ng-api-http.eu2.coralogix.com": "coralogix",
    "ng-api-http.ap1.coralogix.com": "coralogix",
    "ng-api-http.ap2.coralogix.com": "coralogix",
    # Datadog (all regions)
    "api.datadoghq.com": "datadog",
    "api.us3.datadoghq.com": "datadog",
    "api.us5.datadoghq.com": "datadog",
    "api.datadoghq.eu": "datadog",
    "api.ddog-gov.com": "datadog",
    "api.ap1.datadoghq.com": "datadog",
    # Grafana Cloud
    "grafana.com": "grafana",
    "grafana.net": "grafana",
    # Loki (Grafana Cloud)
    "logs-prod-us-central1.grafana.net": "loki",
    "logs-prod-eu-west-0.grafana.net": "loki",
    "logs-prod3.grafana.net": "loki",
    # Splunk Cloud
    "splunkcloud.com": "splunk",
    # Elasticsearch Cloud
    "elastic-cloud.com": "elasticsearch",
    "found.io": "elasticsearch",
}

# Wildcard domain patterns (suffix match)
# These are checked if exact match fails
WILDCARD_DOMAINS: dict[str, str] = {
    # Grafana Cloud - any *.grafana.net or *.grafana.com
    ".grafana.net": "grafana",
    ".grafana.com": "grafana",
    # Loki - logs-*.grafana.net
    "logs-prod-us-central1.grafana.net": "loki",
    "logs-prod-eu-west-0.grafana.net": "loki",
    # Elasticsearch Cloud
    ".es.amazonaws.com": "elasticsearch",
    ".elastic-cloud.com": "elasticsearch",
    ".found.io": "elasticsearch",
    # Splunk Cloud
    ".splunkcloud.com": "splunk",
    # Datadog (catch subdomains)
    ".datadoghq.com": "datadog",
    ".datadoghq.eu": "datadog",
    ".ddog-gov.com": "datadog",
}

# Path prefixes for proxy mode (when host is envoy:8001, localhost:8001, etc.)
# Order matters: more specific paths should come first
PATH_TO_INTEGRATION: dict[str, str] = {
    # Anthropic
    "/v1/": "anthropic",  # Anthropic API
    "/api/event_logging/": "anthropic",  # Anthropic telemetry
    # Coralogix
    "/api/v1/dataprime/": "coralogix",  # Coralogix DataPrime
    "/api/v1/query": "coralogix",  # Coralogix query
    # Datadog
    "/api/v1/validate": "datadog",
    "/api/v1/monitor": "datadog",
    "/api/v1/events": "datadog",
    "/api/v1/metrics": "datadog",
    "/api/v2/logs": "datadog",
    "/api/v2/series": "datadog",
    # Elasticsearch
    "/_cluster/": "elasticsearch",
    "/_cat/": "elasticsearch",
    "/_search": "elasticsearch",
    "/_bulk": "elasticsearch",
    # Grafana
    "/api/datasources": "grafana",
    "/api/dashboards": "grafana",
    "/api/search": "grafana",
    "/api/alerts": "grafana",
    "/api/annotations": "grafana",
    # Prometheus (via Grafana datasource proxy)
    # Note: /api/v1/query conflicts with Coralogix, use host-based routing
    "/api/datasources/proxy/": "prometheus",  # Grafana datasource proxy pattern
    # Loki
    "/loki/api/v1/": "loki",
    # Splunk
    "/services/search/": "splunk",
    "/servicesNS/": "splunk",
    # Jaeger
    "/api/traces": "jaeger",
    "/api/services": "jaeger",
}

# Hosts that use path-based routing (static list)
PROXY_HOSTS = {"envoy:8001", "localhost:8001", "127.0.0.1:8001"}


def is_proxy_host(host: str) -> bool:
    """Check if host should use path-based routing.

    Handles:
    - Static proxy hosts (envoy:8001, etc.)
    - Any localhost/127.0.0.1 with any port (for internal proxies)
    """
    if host in PROXY_HOSTS:
        return True
    # Handle any localhost port (e.g., 127.0.0.1:45667 from lmnr proxy)
    if host.startswith("127.0.0.1:") or host.startswith("localhost:"):
        return True
    return False


def get_integration_for_host(host: str, path: str = "") -> str | None:
    """Get integration ID for a given host and path.

    Args:
        host: The target hostname (e.g., "api.anthropic.com" or "envoy:8001")
        path: The request path (e.g., "/v1/messages" or "/api/v1/dataprime/query")

    Returns:
        Integration ID (e.g., "anthropic") or None if not mapped
    """
    # Strip port if present for domain matching
    host_without_port = host.split(":")[0] if ":" in host else host

    # For proxy hosts, use path-based routing
    if is_proxy_host(host):
        for path_prefix, integration_id in PATH_TO_INTEGRATION.items():
            if path.startswith(path_prefix):
                return integration_id
        return None

    # Direct lookup by host (exact match)
    if host_without_port in DOMAIN_TO_INTEGRATION:
        return DOMAIN_TO_INTEGRATION[host_without_port]

    # Try wildcard/suffix match
    for suffix, integration_id in WILDCARD_DOMAINS.items():
        if host_without_port.endswith(suffix):
            return integration_id

    return None

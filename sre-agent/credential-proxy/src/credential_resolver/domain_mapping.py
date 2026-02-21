# Copyright 2026 IncidentFox, Inc.
#
# Licensed under the Business Source License 1.1 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://github.com/incidentfox/incidentfox/blob/main/LICENSE-ENTERPRISE
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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
    # Confluence (Atlassian Cloud)
    "atlassian.net": "confluence",
    # Honeycomb (US and EU regions)
    "api.honeycomb.io": "honeycomb",
    "api.eu1.honeycomb.io": "honeycomb",
    # ClickUp
    "api.clickup.com": "clickup",
    # Sentry
    "sentry.io": "sentry",
    # PagerDuty
    "api.pagerduty.com": "pagerduty",
    # GitLab
    "gitlab.com": "gitlab",
    # New Relic
    "api.newrelic.com": "newrelic",
    "api.eu.newrelic.com": "newrelic",
    # Blameless
    "api.blameless.io": "blameless",
    # FireHydrant
    "api.firehydrant.io": "firehydrant",
    # VictoriaMetrics / VictoriaLogs (managed cloud)
    "cloud.victoriametrics.com": "victoriametrics",
    # Amplitude (US and EU regions)
    "amplitude.com": "amplitude",
    "analytics.eu.amplitude.com": "amplitude",
    # Vercel
    "api.vercel.com": "vercel",
}

# Path prefixes for proxy mode (when host is envoy:8001, localhost:8001, etc.)
PATH_TO_INTEGRATION: dict[str, str] = {
    "/v1/": "anthropic",  # Anthropic API
    "/api/event_logging/": "anthropic",  # Anthropic telemetry
    "/api/v1/dataprime/": "coralogix",  # Coralogix DataPrime
    "/api/v1/query": "coralogix",  # Coralogix query
    "/honeycomb/": "honeycomb",  # Honeycomb API
    "/clickup/": "clickup",  # ClickUp API
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
    # For proxy hosts, use path-based routing
    if is_proxy_host(host):
        for path_prefix, integration_id in PATH_TO_INTEGRATION.items():
            if path.startswith(path_prefix):
                return integration_id
        return None

    # Direct lookup by host
    if host in DOMAIN_TO_INTEGRATION:
        return DOMAIN_TO_INTEGRATION[host]

    # Try wildcard match for subdomains
    for domain, integration_id in DOMAIN_TO_INTEGRATION.items():
        if host.endswith(domain.lstrip("*")):
            return integration_id

    return None

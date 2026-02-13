"""Credential resolver ext_authz service.

Injects credentials for outgoing requests based on JWT-authenticated sandbox identity.
Supports multiple credential sources:
- environment: Load from env vars (local dev, self-hosted)
- config_service: Fetch from Config Service (SaaS)

Security: Sandboxes are UNTRUSTED (could execute malicious code via prompt injection).
JWT validation ensures only legitimate sandboxes get credentials:
1. Server generates JWT with tenant/team when creating sandbox
2. JWT is embedded in per-sandbox Envoy config
3. Envoy adds x-sandbox-jwt header to ext_authz requests
4. We validate JWT and extract tenant/team (ignoring spoofed headers)
"""

import logging
import os
from contextlib import asynccontextmanager

from cachetools import TTLCache
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel

from .config_client import ConfigServiceClient
from .domain_mapping import get_integration_for_host
from .jwt_auth import validate_sandbox_jwt

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Credential source: "config_service" (SaaS) or "environment" (local/self-hosted)
CREDENTIAL_SOURCE = os.getenv("CREDENTIAL_SOURCE", "environment")

# JWT validation mode: "strict" (require valid JWT) or "permissive" (allow missing JWT for local dev)
JWT_MODE = os.getenv("JWT_MODE", "strict")

# Cache for credentials (5-minute TTL)
credential_cache: TTLCache = TTLCache(maxsize=1000, ttl=300)

# Config Service client (only initialized if needed)
config_client: ConfigServiceClient | None = None

# Environment-based credentials (for local/self-hosted mode)
# Loaded at startup from environment variables
ENV_CREDENTIALS: dict[str, dict] = {}


def load_env_credentials() -> dict[str, dict]:
    """Load credentials from environment variables.

    Supports all observability backends for self-hosted/local mode:
    - Anthropic: LLM API
    - Coralogix: Log aggregation
    - Confluence: Documentation
    - Datadog: Monitoring (requires both API key and App key)
    - Elasticsearch: Search/logging
    - Grafana: Dashboards/visualization
    - Prometheus: Metrics
    - Jaeger: Distributed tracing
    - GitHub: Code repository
    - Honeycomb: Observability
    """
    return {
        "anthropic": {
            "api_key": os.getenv("ANTHROPIC_API_KEY"),
        },
        "coralogix": {
            "api_key": os.getenv("CORALOGIX_API_KEY"),
            "domain": os.getenv("CORALOGIX_DOMAIN"),
            "region": os.getenv("CORALOGIX_REGION"),
        },
        "confluence": {
            "domain": os.getenv("CONFLUENCE_URL"),
            "email": os.getenv("CONFLUENCE_EMAIL"),
            "api_key": os.getenv("CONFLUENCE_API_TOKEN"),
        },
        "datadog": {
            "api_key": os.getenv("DD_API_KEY") or os.getenv("DATADOG_API_KEY"),
            "app_key": os.getenv("DD_APP_KEY") or os.getenv("DATADOG_APP_KEY"),
            "site": os.getenv("DD_SITE", "datadoghq.com"),
        },
        "elasticsearch": {
            "domain": os.getenv("ELASTICSEARCH_URL"),
            "api_key": os.getenv("ELASTICSEARCH_API_KEY"),
            "username": os.getenv("ELASTICSEARCH_USER"),
        },
        "grafana": {
            "domain": os.getenv("GRAFANA_URL"),
            "api_key": os.getenv("GRAFANA_API_KEY") or os.getenv("GRAFANA_TOKEN"),
        },
        "prometheus": {
            "domain": os.getenv("PROMETHEUS_URL"),
            "api_key": os.getenv("PROMETHEUS_TOKEN"),
        },
        "jaeger": {
            "domain": os.getenv("JAEGER_URL"),
            "api_key": os.getenv("JAEGER_TOKEN"),
        },
        "github": {
            "api_key": os.getenv("GITHUB_TOKEN"),
            "domain": os.getenv("GITHUB_ENTERPRISE_URL"),  # Optional, for GHE
        },
        "honeycomb": {
            "api_key": os.getenv("HONEYCOMB_API_KEY"),
            "dataset": os.getenv("HONEYCOMB_DATASET"),
            "domain": os.getenv(
                "HONEYCOMB_DOMAIN"
            ),  # Optional: defaults to api.honeycomb.io
        },
        "clickup": {
            "api_key": os.getenv("CLICKUP_API_TOKEN"),
            "team_id": os.getenv("CLICKUP_TEAM_ID"),
        },
        "loki": {
            "domain": os.getenv("LOKI_URL"),
            "api_key": os.getenv("LOKI_TOKEN"),
        },
        "splunk": {
            "domain": os.getenv("SPLUNK_URL"),
            "api_key": os.getenv("SPLUNK_TOKEN"),
        },
        "sentry": {
            "api_key": os.getenv("SENTRY_AUTH_TOKEN"),
            "organization": os.getenv("SENTRY_ORGANIZATION"),
            "project": os.getenv("SENTRY_PROJECT"),
            "domain": os.getenv("SENTRY_URL"),
        },
        "pagerduty": {
            "api_key": os.getenv("PAGERDUTY_API_KEY"),
        },
        "gitlab": {
            "api_key": os.getenv("GITLAB_TOKEN"),
            "domain": os.getenv("GITLAB_URL"),
        },
        # LLM model preference (per-tenant model selection)
        "llm": {
            "model": os.getenv("LLM_MODEL"),
        },
        # LLM providers (for multi-model support via LLM proxy)
        "openai": {
            "api_key": os.getenv("OPENAI_API_KEY"),
        },
        "gemini": {
            "api_key": os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"),
        },
        "openrouter": {
            "api_key": os.getenv("OPENROUTER_API_KEY"),
        },
        "deepseek": {
            "api_key": os.getenv("DEEPSEEK_API_KEY"),
        },
        "azure": {
            "api_key": os.getenv("AZURE_API_KEY"),
            "api_base": os.getenv("AZURE_API_BASE"),
            "api_version": os.getenv("AZURE_API_VERSION", "2024-06-01"),
        },
        "azure_ai": {
            "api_key": os.getenv("AZURE_AI_API_KEY"),
            "api_base": os.getenv("AZURE_AI_API_BASE"),
        },
        "bedrock": {
            "api_key": os.getenv("AWS_BEARER_TOKEN_BEDROCK"),
            "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID"),
            "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
            "aws_region_name": os.getenv("AWS_REGION", "us-east-1"),
        },
        "mistral": {
            "api_key": os.getenv("MISTRAL_API_KEY"),
        },
        "cohere": {
            "api_key": os.getenv("COHERE_API_KEY"),
        },
        "together_ai": {
            "api_key": os.getenv("TOGETHER_API_KEY"),
        },
        "groq": {
            "api_key": os.getenv("GROQ_API_KEY"),
        },
        "fireworks_ai": {
            "api_key": os.getenv("FIREWORKS_API_KEY"),
        },
        "xai": {
            "api_key": os.getenv("XAI_API_KEY"),
        },
        "moonshot": {
            "api_key": os.getenv("MOONSHOT_API_KEY"),
        },
        "minimax": {
            "api_key": os.getenv("MINIMAX_API_KEY"),
        },
        "vertex_ai": {
            "project": os.getenv("VERTEX_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT"),
            "location": os.getenv("VERTEX_LOCATION", "us-central1"),
            "service_account_json": os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON"),
        },
        "ollama": {
            "host": os.getenv("OLLAMA_HOST", "http://localhost:11434"),
        },
        "jira": {
            "domain": os.getenv("JIRA_URL"),
            "email": os.getenv("JIRA_EMAIL"),
            "api_key": os.getenv("JIRA_API_TOKEN"),
        },
        "newrelic": {
            "api_key": os.getenv("NEWRELIC_API_KEY"),
            "account_id": os.getenv("NEWRELIC_ACCOUNT_ID"),
        },
        "cloudwatch": {
            "access_key_id": os.getenv("AWS_ACCESS_KEY_ID"),
            "secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
            "region": os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
        },
        "opensearch": {
            "domain": os.getenv("OPENSEARCH_URL"),
            "username": os.getenv("OPENSEARCH_USERNAME"),
            "password": os.getenv("OPENSEARCH_PASSWORD"),
        },
        "blameless": {
            "api_key": os.getenv("BLAMELESS_API_KEY"),
            "domain": os.getenv("BLAMELESS_URL"),
        },
        "firehydrant": {
            "api_key": os.getenv("FIREHYDRANT_API_KEY"),
        },
        "victoriametrics": {
            "domain": os.getenv("VICTORIAMETRICS_URL"),
            "api_key": os.getenv("VICTORIAMETRICS_TOKEN"),
        },
    }


def mask_secret(value: str | None, visible_chars: int = 6) -> str:
    """Mask a secret, showing only first few characters."""
    if not value:
        return "(not set)"
    if len(value) <= visible_chars:
        return "*" * len(value)
    return value[:visible_chars] + "..." + "*" * 8


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    global config_client, ENV_CREDENTIALS

    logger.info(
        f"Starting credential-resolver with source={CREDENTIAL_SOURCE}, jwt_mode={JWT_MODE}"
    )

    if CREDENTIAL_SOURCE == "config_service":
        config_client = ConfigServiceClient()
        logger.info("Config Service client initialized")
    else:
        ENV_CREDENTIALS = load_env_credentials()
        # Check which integrations are configured using shared validation
        configured = [
            k for k, v in ENV_CREDENTIALS.items() if is_integration_configured(k, v)
        ]
        logger.info(f"Environment credentials loaded for: {configured}")

        # Debug: show masked credentials to verify they're loaded
        for integration, creds in ENV_CREDENTIALS.items():
            if is_integration_configured(integration, creds):
                # Log the primary credential for each type
                if integration == "datadog":
                    logger.info(
                        f"  {integration}: api_key={mask_secret(creds.get('api_key'))}, "
                        f"app_key={mask_secret(creds.get('app_key'))}, site={creds.get('site')}"
                    )
                elif integration in [
                    "confluence",
                    "grafana",
                    "elasticsearch",
                    "prometheus",
                    "jaeger",
                ]:
                    logger.info(
                        f"  {integration}: domain={creds.get('domain') or '(not set)'}, "
                        f"api_key={mask_secret(creds.get('api_key'))}"
                    )
                else:
                    logger.info(
                        f"  {integration}: api_key={mask_secret(creds.get('api_key'))}"
                    )

    yield

    if config_client:
        await config_client.close()


app = FastAPI(
    title="Credential Resolver",
    description="ext_authz service for credential injection with JWT authentication",
    version="0.2.0",
    lifespan=lifespan,
)


class ExtAuthzResponse(BaseModel):
    """Response model for ext_authz check."""

    status: str = "ok"
    headers: dict[str, str] = {}


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "source": CREDENTIAL_SOURCE, "jwt_mode": JWT_MODE}


@app.get("/api/integrations")
async def list_integrations(request: Request):
    """List available integrations for this tenant/team.

    Returns non-sensitive metadata about which integrations are configured.
    This can be used in system prompts to inform the agent what's available.

    Security: Tenant/team context is extracted from the validated JWT.
    """
    logger.info("Integration list request")

    # Validate JWT and extract tenant context
    tenant_id, team_id, sandbox_name = await extract_tenant_context(request)

    logger.info(
        f"Integration list: tenant={tenant_id}, team={team_id}, sandbox={sandbox_name}"
    )

    # Check which integrations are configured
    # All active integrations from onboarding.py (excludes anthropic - that's the LLM provider)
    ACTIVE_INTEGRATIONS = [
        "coralogix",
        "incident_io",
        "confluence",
        "grafana",
        "elasticsearch",
        "datadog",
        "prometheus",
        "jaeger",
        "kubernetes",
        "github",
        "honeycomb",
        "clickup",
        "loki",
        "splunk",
        "sentry",
        "pagerduty",
        "gitlab",
        "jira",
        "newrelic",
        "opensearch",
        "blameless",
        "firehydrant",
        "victoriametrics",
    ]

    available = []
    for integration_id in ACTIVE_INTEGRATIONS:
        creds = await get_credentials(tenant_id, team_id, integration_id)
        if is_integration_configured(integration_id, creds):
            # Return non-sensitive metadata only
            metadata = get_integration_metadata(integration_id, creds)
            available.append({"id": integration_id, **metadata})

    return {"integrations": available}


def is_integration_configured(integration_id: str, creds: dict | None) -> bool:
    """Check if an integration has valid credentials configured.

    Each integration has different required fields based on its authentication method.
    See slack-bot/onboarding.py for field definitions.
    """
    if not creds:
        return False

    # Integrations that require domain + api_key
    if integration_id in ["confluence", "grafana", "kubernetes"]:
        return bool(creds.get("domain") and creds.get("api_key"))

    # Datadog requires api_key + app_key + site (domain)
    if integration_id == "datadog":
        return bool(creds.get("api_key") and creds.get("app_key") and creds.get("site"))

    # Elasticsearch: domain required, credentials optional (some clusters are open)
    if integration_id == "elasticsearch":
        return bool(creds.get("domain"))

    # Prometheus/Jaeger/VictoriaMetrics: only domain required (auth optional)
    if integration_id in ["prometheus", "jaeger", "victoriametrics"]:
        return bool(creds.get("domain"))

    # GitHub: api_key required (domain optional for GHE)
    if integration_id == "github":
        return bool(creds.get("api_key"))

    # Honeycomb: api_key required (domain optional, defaults to api.honeycomb.io)
    if integration_id == "honeycomb":
        return bool(creds.get("api_key"))

    # ClickUp: api_key required (team_id optional, can be auto-detected)
    if integration_id == "clickup":
        return bool(creds.get("api_key"))

    # Loki: domain required (auth optional)
    if integration_id == "loki":
        return bool(creds.get("domain"))

    # Splunk: domain + api_key required
    if integration_id == "splunk":
        return bool(creds.get("domain") and creds.get("api_key"))

    # Sentry: api_key + organization required (domain optional for self-hosted)
    if integration_id == "sentry":
        return bool(creds.get("api_key") and creds.get("organization"))

    # PagerDuty: api_key required (SaaS-only at api.pagerduty.com)
    if integration_id == "pagerduty":
        return bool(creds.get("api_key"))

    # GitLab: api_key required (domain optional, defaults to gitlab.com)
    if integration_id == "gitlab":
        return bool(creds.get("api_key"))

    # LLM model preference
    if integration_id == "llm":
        return bool(creds.get("model"))

    # LLM providers (api_key based)
    if integration_id in [
        "openai",
        "gemini",
        "openrouter",
        "deepseek",
        "mistral",
        "cohere",
        "together_ai",
        "groq",
        "fireworks_ai",
        "xai",
        "moonshot",
        "minimax",
    ]:
        return bool(creds.get("api_key"))
    if integration_id == "azure":
        return bool(creds.get("api_key") and creds.get("api_base"))
    if integration_id == "azure_ai":
        return bool(creds.get("api_key") and creds.get("api_base"))
    if integration_id == "bedrock":
        has_api_key = bool(creds.get("api_key"))
        has_iam = bool(
            creds.get("aws_access_key_id") and creds.get("aws_secret_access_key")
        )
        return has_api_key or has_iam
    if integration_id == "vertex_ai":
        return bool(creds.get("project"))
    if integration_id == "ollama":
        return bool(creds.get("host"))

    # Jira: domain + email + api_key required (Basic auth)
    if integration_id == "jira":
        return bool(creds.get("domain") and creds.get("email") and creds.get("api_key"))

    # New Relic: api_key required (account_id optional)
    if integration_id == "newrelic":
        return bool(creds.get("api_key"))

    # OpenSearch: domain required (auth optional, some clusters are open)
    if integration_id == "opensearch":
        return bool(creds.get("domain"))

    # Blameless: api_key required (SaaS at api.blameless.io)
    if integration_id == "blameless":
        return bool(creds.get("api_key"))

    # FireHydrant: api_key required (SaaS at api.firehydrant.io)
    if integration_id == "firehydrant":
        return bool(creds.get("api_key"))

    # Default: api_key required (coralogix, incident_io, etc.)
    return bool(creds.get("api_key"))


def get_integration_metadata(integration_id: str, creds: dict) -> dict:
    """Get non-sensitive metadata about an integration.

    SECURITY: Never return secrets (api_key, api_token, password, etc).
    Only return configuration metadata that helps the agent use the integration.
    """
    if integration_id == "confluence":
        # Return domain URL so agent knows which Confluence instance
        return {"url": creds.get("domain")}

    elif integration_id == "coralogix":
        # Return domain/region for API endpoint construction
        return {
            "domain": creds.get("domain"),
            "region": creds.get("region"),
        }

    elif integration_id == "datadog":
        # Return site for API endpoint construction
        return {"site": creds.get("site")}

    elif integration_id == "grafana":
        # Return URL so agent knows which Grafana instance
        return {"url": creds.get("domain")}

    elif integration_id == "elasticsearch":
        # Return URL and optional default index pattern
        metadata = {"url": creds.get("domain")}
        if creds.get("index_pattern"):
            metadata["index_pattern"] = creds.get("index_pattern")
        return metadata

    elif integration_id == "prometheus":
        # Return URL
        return {"url": creds.get("domain")}

    elif integration_id == "jaeger":
        # Return URL
        return {"url": creds.get("domain")}

    elif integration_id == "kubernetes":
        # Return URL and optional default namespace
        metadata = {"url": creds.get("domain")}
        if creds.get("namespace"):
            metadata["namespace"] = creds.get("namespace")
        return metadata

    elif integration_id == "github":
        # Return enterprise URL if configured (None means github.com)
        metadata = {}
        if creds.get("domain"):
            metadata["url"] = creds.get("domain")
        if creds.get("default_org"):
            metadata["default_org"] = creds.get("default_org")
        return metadata

    elif integration_id == "honeycomb":
        # Return domain (defaults to api.honeycomb.io if not set)
        return {"url": creds.get("domain") or "https://api.honeycomb.io"}

    elif integration_id == "clickup":
        # Return team_id if configured
        metadata = {"url": "https://api.clickup.com"}
        if creds.get("team_id"):
            metadata["team_id"] = creds.get("team_id")
        return metadata

    elif integration_id == "loki":
        # Return URL
        return {"url": creds.get("domain")}

    elif integration_id == "splunk":
        # Return URL
        return {"url": creds.get("domain")}

    elif integration_id == "sentry":
        # Return org, project, and URL (defaults to sentry.io)
        metadata = {
            "url": creds.get("domain") or "https://sentry.io",
            "organization": creds.get("organization"),
        }
        if creds.get("project"):
            metadata["project"] = creds.get("project")
        return metadata

    elif integration_id == "pagerduty":
        # SaaS-only, fixed URL
        return {"url": "https://api.pagerduty.com"}

    elif integration_id == "gitlab":
        # Return URL (defaults to gitlab.com)
        return {"url": creds.get("domain") or "https://gitlab.com"}

    elif integration_id == "victoriametrics":
        # Return URL
        return {"url": creds.get("domain")}

    # Default: just indicate it's configured (incident_io, etc.)
    return {}


# IMPORTANT: Route ordering matters in FastAPI/Starlette!
# More specific routes MUST be declared BEFORE catch-all routes.
# /confluence/{path:path} must come before /{path:path}


async def generic_proxy(
    integration_id: str,
    path: str,
    request: Request,
    require_api_key: bool = True,
    ssl_verify: bool = True,
) -> Response:
    """Generic reverse proxy for integrations with customer-specific URLs.

    Since customer URLs are specific (e.g., grafana.company.com), we can't use
    Envoy's static routing. This proxy:
    1. Validates JWT and extracts tenant context
    2. Looks up the customer's URL and credentials
    3. Forwards the request with auth headers
    4. Returns the response

    Security: Credentials never leave this service.

    Args:
        integration_id: Integration name (e.g., "grafana", "elasticsearch")
        path: Request path to forward
        request: Original FastAPI request
        require_api_key: Whether to require api_key (False for optional auth)
        ssl_verify: Whether to verify SSL certificates
    """
    import re

    import httpx

    logger.info(f"{integration_id.title()} proxy: {request.method} /{path}")

    # Validate JWT and extract tenant context
    tenant_id, team_id, sandbox_name = await extract_tenant_context(request)

    logger.info(
        f"{integration_id.title()} proxy: tenant={tenant_id}, team={team_id}, sandbox={sandbox_name}"
    )

    # Get credentials
    creds = await get_credentials(tenant_id, team_id, integration_id)
    if not creds or not creds.get("domain"):
        logger.error(f"{integration_id.title()} not configured for tenant={tenant_id}")
        raise HTTPException(
            status_code=404,
            detail=f"{integration_id.title()} integration not configured",
        )

    if require_api_key and not creds.get("api_key"):
        logger.error(f"{integration_id.title()} api_key missing for tenant={tenant_id}")
        raise HTTPException(
            status_code=404,
            detail=f"{integration_id.title()} credentials incomplete",
        )

    # Build target URL from 'domain' field
    # Domain may include paths, extract just scheme + host
    domain = creds.get("domain", "")
    match = re.match(r"(https?://[^/]+)", domain)
    if match:
        base_url = match.group(1)
    else:
        # Add https if missing
        if not domain.startswith(("http://", "https://")):
            domain = f"https://{domain}"
        base_url = domain.rstrip("/")

    target_url = f"{base_url}/{path}"
    logger.info(f"{integration_id.title()} proxy: forwarding to {target_url}")

    # Build auth headers
    auth_headers = build_auth_headers(integration_id, creds)

    # Forward the request
    forward_headers = {
        "Content-Type": request.headers.get("Content-Type", "application/json"),
        "Accept": request.headers.get("Accept", "application/json"),
        **auth_headers,
    }

    # Get query params
    query_params = dict(request.query_params)

    try:
        async with httpx.AsyncClient(timeout=30.0, verify=ssl_verify) as client:
            body = None
            if request.method in ["POST", "PUT", "PATCH"]:
                body = await request.body()

            response = await client.request(
                method=request.method,
                url=target_url,
                headers=forward_headers,
                params=query_params,
                content=body,
            )

            return Response(
                content=response.content,
                status_code=response.status_code,
                headers={
                    "Content-Type": response.headers.get(
                        "Content-Type", "application/json"
                    )
                },
            )

    except httpx.TimeoutException:
        logger.error(f"{integration_id.title()} request timeout: {target_url}")
        raise HTTPException(
            status_code=504, detail=f"{integration_id.title()} request timed out"
        )
    except httpx.RequestError as e:
        logger.error(f"{integration_id.title()} request error: {e}")
        raise HTTPException(
            status_code=502, detail=f"{integration_id.title()} request failed: {e}"
        )


@app.api_route(
    "/confluence/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def confluence_proxy(path: str, request: Request):
    """Reverse proxy for Confluence API requests.

    Since Confluence URLs are customer-specific (e.g., mycompany.atlassian.net),
    we can't use Envoy's static routing. Instead, this endpoint acts as a reverse
    proxy that:
    1. Validates JWT and extracts tenant context
    2. Looks up the customer's Confluence URL and credentials
    3. Forwards the request with Basic auth to their Confluence instance
    4. Returns the response

    Security: Credentials never leave this service.

    Example:
        Sandbox calls: http://credential-resolver:8002/confluence/wiki/rest/api/content
        This proxies to: https://customer.atlassian.net/wiki/rest/api/content
    """
    import re

    import httpx

    logger.info(f"Confluence proxy: {request.method} /{path}")

    # Validate JWT and extract tenant context
    tenant_id, team_id, sandbox_name = await extract_tenant_context(request)

    logger.info(
        f"Confluence proxy: tenant={tenant_id}, team={team_id}, sandbox={sandbox_name}"
    )

    # Get Confluence credentials
    # Config Service stores: domain (URL), email, api_key
    creds = await get_credentials(tenant_id, team_id, "confluence")
    if not creds or not creds.get("domain") or not creds.get("api_key"):
        logger.error(f"Confluence not configured for tenant={tenant_id}")
        raise HTTPException(
            status_code=404,
            detail="Confluence integration not configured",
        )

    # Build target URL from 'domain' field
    # Domain may include paths like /wiki/home, extract just scheme + host
    domain = creds.get("domain", "")
    match = re.match(r"(https?://[^/]+)", domain)
    if match:
        confluence_url = match.group(1)
    else:
        confluence_url = domain.rstrip("/")

    target_url = f"{confluence_url}/{path}"
    logger.info(f"Confluence proxy: forwarding to {target_url}")

    # Build auth headers
    auth_headers = build_auth_headers("confluence", creds)

    # Forward the request
    # Copy relevant headers from original request
    forward_headers = {
        "Content-Type": request.headers.get("Content-Type", "application/json"),
        "Accept": request.headers.get("Accept", "application/json"),
        **auth_headers,
    }

    # Get query params
    query_params = dict(request.query_params)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Get request body if present
            body = None
            if request.method in ["POST", "PUT", "PATCH"]:
                body = await request.body()

            response = await client.request(
                method=request.method,
                url=target_url,
                headers=forward_headers,
                params=query_params,
                content=body,
            )

            # Return the response with same status and content
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers={
                    "Content-Type": response.headers.get(
                        "Content-Type", "application/json"
                    )
                },
            )

    except httpx.TimeoutException:
        logger.error(f"Confluence request timeout: {target_url}")
        raise HTTPException(status_code=504, detail="Confluence request timed out")
    except httpx.RequestError as e:
        logger.error(f"Confluence request error: {e}")
        raise HTTPException(status_code=502, detail=f"Confluence request failed: {e}")


# Additional integration proxies for customer-specific URLs
# These use the generic_proxy helper


@app.api_route(
    "/grafana/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def grafana_proxy(path: str, request: Request):
    """Reverse proxy for Grafana API requests."""
    return await generic_proxy("grafana", path, request)


@app.api_route(
    "/elasticsearch/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def elasticsearch_proxy(path: str, request: Request):
    """Reverse proxy for Elasticsearch API requests."""
    # Elasticsearch may have open clusters, so api_key not always required
    # Also disable SSL verify for self-signed certs (common in enterprise)
    return await generic_proxy(
        "elasticsearch", path, request, require_api_key=False, ssl_verify=False
    )


@app.api_route(
    "/prometheus/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def prometheus_proxy(path: str, request: Request):
    """Reverse proxy for Prometheus API requests."""
    # Prometheus auth is optional (many internal deployments are open)
    return await generic_proxy("prometheus", path, request, require_api_key=False)


@app.api_route(
    "/jaeger/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def jaeger_proxy(path: str, request: Request):
    """Reverse proxy for Jaeger API requests.

    Jaeger is often deployed with a /jaeger base path (common in OpenTelemetry demos
    and Kubernetes deployments). If the domain doesn't already include /jaeger or
    similar path, we prepend /jaeger to API requests.

    Examples:
        - Domain: http://jaeger.example.com -> forwards to http://jaeger.example.com/jaeger/api/...
        - Domain: http://jaeger.example.com/jaeger -> forwards to http://jaeger.example.com/jaeger/api/...
    """
    import re

    import httpx

    logger.info(f"Jaeger proxy: {request.method} /{path}")

    # Validate JWT and extract tenant context
    tenant_id, team_id, sandbox_name = await extract_tenant_context(request)

    # Get Jaeger credentials
    creds = await get_credentials(tenant_id, team_id, "jaeger")
    if not creds or not creds.get("domain"):
        logger.error(f"Jaeger not configured for tenant={tenant_id}")
        raise HTTPException(
            status_code=404,
            detail="Jaeger integration not configured",
        )

    # Build target URL from 'domain' field
    domain = creds.get("domain", "")
    match = re.match(r"(https?://[^/]+)(.*)", domain)
    if match:
        base_url = match.group(1)
        existing_path = match.group(2).strip("/")
    else:
        if not domain.startswith(("http://", "https://")):
            domain = f"http://{domain}"
        base_url = domain.rstrip("/")
        existing_path = ""

    # Check if the domain already includes a base path like /jaeger
    # If not, prepend /jaeger (common for OpenTelemetry demo deployments)
    if existing_path:
        # Domain already has a path (e.g., http://example.com/jaeger)
        target_url = f"{base_url}/{existing_path}/{path}"
    elif path.startswith("api/"):
        # No existing path and requesting API - prepend /jaeger
        # This handles the common case where Jaeger UI is at /jaeger/ui/
        # and API is at /jaeger/api/
        target_url = f"{base_url}/jaeger/{path}"
    else:
        # Other paths, forward as-is
        target_url = f"{base_url}/{path}"

    logger.info(f"Jaeger proxy: forwarding to {target_url}")

    # Build auth headers (Jaeger typically doesn't need auth)
    auth_headers = build_auth_headers("jaeger", creds)

    forward_headers = {
        "Content-Type": request.headers.get("Content-Type", "application/json"),
        "Accept": request.headers.get("Accept", "application/json"),
        **auth_headers,
    }

    query_params = dict(request.query_params)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            body = None
            if request.method in ["POST", "PUT", "PATCH"]:
                body = await request.body()

            response = await client.request(
                method=request.method,
                url=target_url,
                headers=forward_headers,
                params=query_params,
                content=body,
            )

            return Response(
                content=response.content,
                status_code=response.status_code,
                headers={
                    "Content-Type": response.headers.get(
                        "Content-Type", "application/json"
                    )
                },
            )

    except httpx.TimeoutException:
        logger.error(f"Jaeger request timeout: {target_url}")
        raise HTTPException(status_code=504, detail="Jaeger request timed out")
    except httpx.RequestError as e:
        logger.error(f"Jaeger request error: {e}")
        raise HTTPException(status_code=502, detail=f"Jaeger request failed: {e}")


@app.api_route(
    "/github/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def github_proxy(path: str, request: Request):
    """Reverse proxy for GitHub API requests (for GitHub Enterprise).

    Note: For github.com, clients can use the fixed URL directly.
    This proxy is for GitHub Enterprise with customer-specific URLs.
    """
    return await generic_proxy("github", path, request)


@app.api_route(
    "/honeycomb/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def honeycomb_proxy(path: str, request: Request):
    """Reverse proxy for Honeycomb API requests.

    Honeycomb uses X-Honeycomb-Team header for authentication.
    Domain defaults to api.honeycomb.io (US) but can be api.eu1.honeycomb.io (EU).
    """
    import httpx

    logger.info(f"Honeycomb proxy: {request.method} /{path}")

    # Validate JWT and extract tenant context
    tenant_id, team_id, sandbox_name = await extract_tenant_context(request)

    # Get Honeycomb credentials
    creds = await get_credentials(tenant_id, team_id, "honeycomb")
    if not creds or not creds.get("api_key"):
        logger.error(f"Honeycomb not configured for tenant={tenant_id}")
        raise HTTPException(
            status_code=404,
            detail="Honeycomb integration not configured",
        )

    # Build Honeycomb API URL (default to US region)
    domain = creds.get("domain", "https://api.honeycomb.io")
    if not domain.startswith(("http://", "https://")):
        domain = f"https://{domain}"
    target_url = f"{domain.rstrip('/')}/1/{path}"
    logger.info(f"Honeycomb proxy: forwarding to {target_url}")

    # Build auth headers
    auth_headers = build_auth_headers("honeycomb", creds)

    forward_headers = {
        "Content-Type": request.headers.get("Content-Type", "application/json"),
        "Accept": request.headers.get("Accept", "application/json"),
        **auth_headers,
    }

    query_params = dict(request.query_params)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            body = None
            if request.method in ["POST", "PUT", "PATCH"]:
                body = await request.body()

            response = await client.request(
                method=request.method,
                url=target_url,
                headers=forward_headers,
                params=query_params,
                content=body,
            )

            return Response(
                content=response.content,
                status_code=response.status_code,
                headers={
                    "Content-Type": response.headers.get(
                        "Content-Type", "application/json"
                    )
                },
            )

    except httpx.TimeoutException:
        logger.error(f"Honeycomb request timeout: {target_url}")
        raise HTTPException(status_code=504, detail="Honeycomb request timed out")
    except httpx.RequestError as e:
        logger.error(f"Honeycomb request error: {e}")
        raise HTTPException(status_code=502, detail=f"Honeycomb request failed: {e}")


@app.api_route(
    "/clickup/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def clickup_proxy(path: str, request: Request):
    """Reverse proxy for ClickUp API requests.

    ClickUp uses Authorization header with the API token.
    """
    import httpx

    logger.info(f"ClickUp proxy: {request.method} /{path}")

    # Validate JWT and extract tenant context
    tenant_id, team_id, sandbox_name = await extract_tenant_context(request)

    # Get ClickUp credentials
    creds = await get_credentials(tenant_id, team_id, "clickup")
    if not creds or not creds.get("api_key"):
        logger.error(f"ClickUp not configured for tenant={tenant_id}")
        raise HTTPException(
            status_code=404,
            detail="ClickUp integration not configured",
        )

    # Build ClickUp API URL
    target_url = f"https://api.clickup.com/api/v2/{path}"
    logger.info(f"ClickUp proxy: forwarding to {target_url}")

    # Build auth headers
    auth_headers = build_auth_headers("clickup", creds)

    forward_headers = {
        "Content-Type": request.headers.get("Content-Type", "application/json"),
        "Accept": request.headers.get("Accept", "application/json"),
        **auth_headers,
    }

    query_params = dict(request.query_params)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            body = None
            if request.method in ["POST", "PUT", "PATCH"]:
                body = await request.body()

            response = await client.request(
                method=request.method,
                url=target_url,
                headers=forward_headers,
                params=query_params,
                content=body,
            )

            return Response(
                content=response.content,
                status_code=response.status_code,
                headers={
                    "Content-Type": response.headers.get(
                        "Content-Type", "application/json"
                    )
                },
            )

    except httpx.TimeoutException:
        logger.error(f"ClickUp request timeout: {target_url}")
        raise HTTPException(status_code=504, detail="ClickUp request timed out")
    except httpx.RequestError as e:
        logger.error(f"ClickUp request error: {e}")
        raise HTTPException(status_code=502, detail=f"ClickUp request failed: {e}")


@app.api_route(
    "/datadog/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def datadog_proxy(path: str, request: Request):
    """Reverse proxy for Datadog API requests.

    Datadog has site-specific URLs (us1.datadoghq.com, eu1.datadoghq.com, etc.)
    stored in the 'site' field. We use 'domain' generically here.
    """
    import httpx

    logger.info(f"Datadog proxy: {request.method} /{path}")

    # Validate JWT and extract tenant context
    tenant_id, team_id, sandbox_name = await extract_tenant_context(request)

    # Get Datadog credentials (uses 'site' not 'domain')
    # Datadog requires api_key, app_key, and site for most API calls
    creds = await get_credentials(tenant_id, team_id, "datadog")
    if not creds or not creds.get("site") or not creds.get("api_key"):
        logger.error(f"Datadog not configured for tenant={tenant_id}")
        raise HTTPException(
            status_code=404,
            detail="Datadog integration not configured",
        )

    if not creds.get("app_key"):
        logger.error(
            f"Datadog app_key missing for tenant={tenant_id}. "
            "Most Datadog API endpoints require both api_key and app_key."
        )
        raise HTTPException(
            status_code=404,
            detail="Datadog integration incomplete: app_key required",
        )

    # Build Datadog API URL from site
    site = creds.get("site", "datadoghq.com")
    target_url = f"https://api.{site}/{path}"
    logger.info(f"Datadog proxy: forwarding to {target_url}")

    # Debug: Log credential presence (not values) for troubleshooting
    api_key = creds.get("api_key", "")
    app_key = creds.get("app_key", "")
    logger.info(
        f"Datadog credentials: api_key={len(api_key)}chars, app_key={len(app_key)}chars, "
        f"api_key_prefix={api_key[:4] if len(api_key) >= 4 else 'N/A'}..., "
        f"app_key_prefix={app_key[:4] if len(app_key) >= 4 else 'N/A'}..."
    )

    # Build auth headers
    auth_headers = build_auth_headers("datadog", creds)

    forward_headers = {
        "Content-Type": request.headers.get("Content-Type", "application/json"),
        "Accept": request.headers.get("Accept", "application/json"),
        **auth_headers,
    }

    query_params = dict(request.query_params)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            body = None
            if request.method in ["POST", "PUT", "PATCH"]:
                body = await request.body()

            response = await client.request(
                method=request.method,
                url=target_url,
                headers=forward_headers,
                params=query_params,
                content=body,
            )

            # Log non-2xx responses for debugging
            if response.status_code >= 400:
                logger.warning(
                    f"Datadog API returned {response.status_code} for {target_url}: "
                    f"{response.text[:500] if response.text else 'no body'}"
                )

            return Response(
                content=response.content,
                status_code=response.status_code,
                headers={
                    "Content-Type": response.headers.get(
                        "Content-Type", "application/json"
                    )
                },
            )

    except httpx.TimeoutException:
        logger.error(f"Datadog request timeout: {target_url}")
        raise HTTPException(status_code=504, detail="Datadog request timed out")
    except httpx.RequestError as e:
        logger.error(f"Datadog request error: {e}")
        raise HTTPException(status_code=502, detail=f"Datadog request failed: {e}")


@app.api_route(
    "/loki/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def loki_proxy(path: str, request: Request):
    """Reverse proxy for Loki API requests.

    Loki auth is optional (many internal deployments are open).
    """
    return await generic_proxy("loki", path, request, require_api_key=False)


@app.api_route(
    "/splunk/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def splunk_proxy(path: str, request: Request):
    """Reverse proxy for Splunk API requests."""
    return await generic_proxy("splunk", path, request)


@app.api_route(
    "/sentry/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def sentry_proxy(path: str, request: Request):
    """Reverse proxy for Sentry API requests.

    Defaults to sentry.io but supports self-hosted Sentry instances.
    """
    import httpx

    logger.info(f"Sentry proxy: {request.method} /{path}")

    # Validate JWT and extract tenant context
    tenant_id, team_id, sandbox_name = await extract_tenant_context(request)

    # Get Sentry credentials
    creds = await get_credentials(tenant_id, team_id, "sentry")
    if not creds or not creds.get("api_key"):
        logger.error(f"Sentry not configured for tenant={tenant_id}")
        raise HTTPException(
            status_code=404,
            detail="Sentry integration not configured",
        )

    # Build Sentry API URL (default to sentry.io)
    domain = creds.get("domain", "https://sentry.io")
    if not domain.startswith(("http://", "https://")):
        domain = f"https://{domain}"
    target_url = f"{domain.rstrip('/')}/api/0/{path}"
    logger.info(f"Sentry proxy: forwarding to {target_url}")

    # Build auth headers
    auth_headers = build_auth_headers("sentry", creds)

    forward_headers = {
        "Content-Type": request.headers.get("Content-Type", "application/json"),
        "Accept": request.headers.get("Accept", "application/json"),
        **auth_headers,
    }

    query_params = dict(request.query_params)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            body = None
            if request.method in ["POST", "PUT", "PATCH"]:
                body = await request.body()

            response = await client.request(
                method=request.method,
                url=target_url,
                headers=forward_headers,
                params=query_params,
                content=body,
            )

            return Response(
                content=response.content,
                status_code=response.status_code,
                headers={
                    "Content-Type": response.headers.get(
                        "Content-Type", "application/json"
                    )
                },
            )

    except httpx.TimeoutException:
        logger.error(f"Sentry request timeout: {target_url}")
        raise HTTPException(status_code=504, detail="Sentry request timed out")
    except httpx.RequestError as e:
        logger.error(f"Sentry request error: {e}")
        raise HTTPException(status_code=502, detail=f"Sentry request failed: {e}")


@app.api_route(
    "/pagerduty/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def pagerduty_proxy(path: str, request: Request):
    """Reverse proxy for PagerDuty API requests.

    PagerDuty is SaaS-only at api.pagerduty.com.
    """
    import httpx

    logger.info(f"PagerDuty proxy: {request.method} /{path}")

    # Validate JWT and extract tenant context
    tenant_id, team_id, sandbox_name = await extract_tenant_context(request)

    # Get PagerDuty credentials
    creds = await get_credentials(tenant_id, team_id, "pagerduty")
    if not creds or not creds.get("api_key"):
        logger.error(f"PagerDuty not configured for tenant={tenant_id}")
        raise HTTPException(
            status_code=404,
            detail="PagerDuty integration not configured",
        )

    # Build PagerDuty API URL (always api.pagerduty.com)
    target_url = f"https://api.pagerduty.com/{path}"
    logger.info(f"PagerDuty proxy: forwarding to {target_url}")

    # Build auth headers
    auth_headers = build_auth_headers("pagerduty", creds)

    forward_headers = {
        "Content-Type": request.headers.get("Content-Type", "application/json"),
        "Accept": request.headers.get("Accept", "application/json"),
        **auth_headers,
    }

    query_params = dict(request.query_params)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            body = None
            if request.method in ["POST", "PUT", "PATCH"]:
                body = await request.body()

            response = await client.request(
                method=request.method,
                url=target_url,
                headers=forward_headers,
                params=query_params,
                content=body,
            )

            return Response(
                content=response.content,
                status_code=response.status_code,
                headers={
                    "Content-Type": response.headers.get(
                        "Content-Type", "application/json"
                    )
                },
            )

    except httpx.TimeoutException:
        logger.error(f"PagerDuty request timeout: {target_url}")
        raise HTTPException(status_code=504, detail="PagerDuty request timed out")
    except httpx.RequestError as e:
        logger.error(f"PagerDuty request error: {e}")
        raise HTTPException(status_code=502, detail=f"PagerDuty request failed: {e}")


@app.api_route(
    "/gitlab/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def gitlab_proxy(path: str, request: Request):
    """Reverse proxy for GitLab API requests.

    Defaults to gitlab.com but supports self-hosted GitLab instances.
    """
    import httpx

    logger.info(f"GitLab proxy: {request.method} /{path}")

    # Validate JWT and extract tenant context
    tenant_id, team_id, sandbox_name = await extract_tenant_context(request)

    # Get GitLab credentials
    creds = await get_credentials(tenant_id, team_id, "gitlab")
    if not creds or not creds.get("api_key"):
        logger.error(f"GitLab not configured for tenant={tenant_id}")
        raise HTTPException(
            status_code=404,
            detail="GitLab integration not configured",
        )

    # Build GitLab API URL (default to gitlab.com)
    domain = creds.get("domain", "https://gitlab.com")
    if not domain.startswith(("http://", "https://")):
        domain = f"https://{domain}"
    target_url = f"{domain.rstrip('/')}/api/v4/{path}"
    logger.info(f"GitLab proxy: forwarding to {target_url}")

    # Build auth headers
    auth_headers = build_auth_headers("gitlab", creds)

    forward_headers = {
        "Content-Type": request.headers.get("Content-Type", "application/json"),
        "Accept": request.headers.get("Accept", "application/json"),
        **auth_headers,
    }

    query_params = dict(request.query_params)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            body = None
            if request.method in ["POST", "PUT", "PATCH"]:
                body = await request.body()

            response = await client.request(
                method=request.method,
                url=target_url,
                headers=forward_headers,
                params=query_params,
                content=body,
            )

            return Response(
                content=response.content,
                status_code=response.status_code,
                headers={
                    "Content-Type": response.headers.get(
                        "Content-Type", "application/json"
                    )
                },
            )

    except httpx.TimeoutException:
        logger.error(f"GitLab request timeout: {target_url}")
        raise HTTPException(status_code=504, detail="GitLab request timed out")
    except httpx.RequestError as e:
        logger.error(f"GitLab request error: {e}")
        raise HTTPException(status_code=502, detail=f"GitLab request failed: {e}")


# LLM proxy routes: /v1/messages, /v1/messages/count_tokens, /api/event_logging/*
# Must be registered BEFORE the catch-all /{path:path} route
from .llm_proxy import router as llm_router

app.include_router(llm_router)


@app.api_route(
    "/check", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]
)
@app.api_route(
    "/jira/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def jira_proxy(path: str, request: Request):
    """Reverse proxy for Jira API requests.

    Jira Cloud uses customer-specific URLs (e.g., mycompany.atlassian.net).
    Routes requests to the customer's Jira REST API v3.
    """
    import httpx

    logger.info(f"Jira proxy: {request.method} /{path}")

    # Validate JWT and extract tenant context
    tenant_id, team_id, sandbox_name = await extract_tenant_context(request)

    # Get Jira credentials
    creds = await get_credentials(tenant_id, team_id, "jira")
    if not creds or not creds.get("domain") or not creds.get("api_key"):
        logger.error(f"Jira not configured for tenant={tenant_id}")
        raise HTTPException(
            status_code=404,
            detail="Jira integration not configured",
        )

    # Build Jira API URL from domain
    import re

    domain = creds.get("domain", "")
    match = re.match(r"(https?://[^/]+)", domain)
    if match:
        jira_url = match.group(1)
    else:
        if not domain.startswith(("http://", "https://")):
            domain = f"https://{domain}"
        jira_url = domain.rstrip("/")

    target_url = f"{jira_url}/rest/api/3/{path}"
    logger.info(f"Jira proxy: forwarding to {target_url}")

    # Build auth headers
    auth_headers = build_auth_headers("jira", creds)

    forward_headers = {
        "Content-Type": request.headers.get("Content-Type", "application/json"),
        "Accept": request.headers.get("Accept", "application/json"),
        **auth_headers,
    }

    query_params = dict(request.query_params)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            body = None
            if request.method in ["POST", "PUT", "PATCH"]:
                body = await request.body()

            response = await client.request(
                method=request.method,
                url=target_url,
                headers=forward_headers,
                params=query_params,
                content=body,
            )

            return Response(
                content=response.content,
                status_code=response.status_code,
                headers={
                    "Content-Type": response.headers.get(
                        "Content-Type", "application/json"
                    )
                },
            )

    except httpx.TimeoutException:
        logger.error(f"Jira request timeout: {target_url}")
        raise HTTPException(status_code=504, detail="Jira request timed out")
    except httpx.RequestError as e:
        logger.error(f"Jira request error: {e}")
        raise HTTPException(status_code=502, detail=f"Jira request failed: {e}")


@app.api_route(
    "/newrelic/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def newrelic_proxy(path: str, request: Request):
    """Reverse proxy for New Relic API requests.

    New Relic is SaaS at api.newrelic.com (US) or api.eu.newrelic.com (EU).
    """
    import httpx

    logger.info(f"New Relic proxy: {request.method} /{path}")

    # Validate JWT and extract tenant context
    tenant_id, team_id, sandbox_name = await extract_tenant_context(request)

    # Get New Relic credentials
    creds = await get_credentials(tenant_id, team_id, "newrelic")
    if not creds or not creds.get("api_key"):
        logger.error(f"New Relic not configured for tenant={tenant_id}")
        raise HTTPException(
            status_code=404,
            detail="New Relic integration not configured",
        )

    # Build New Relic API URL (default to US region)
    domain = creds.get("domain", "https://api.newrelic.com")
    if not domain.startswith(("http://", "https://")):
        domain = f"https://{domain}"
    target_url = f"{domain.rstrip('/')}/{path}"
    logger.info(f"New Relic proxy: forwarding to {target_url}")

    # Build auth headers
    auth_headers = build_auth_headers("newrelic", creds)

    forward_headers = {
        "Content-Type": request.headers.get("Content-Type", "application/json"),
        "Accept": request.headers.get("Accept", "application/json"),
        **auth_headers,
    }

    query_params = dict(request.query_params)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            body = None
            if request.method in ["POST", "PUT", "PATCH"]:
                body = await request.body()

            response = await client.request(
                method=request.method,
                url=target_url,
                headers=forward_headers,
                params=query_params,
                content=body,
            )

            return Response(
                content=response.content,
                status_code=response.status_code,
                headers={
                    "Content-Type": response.headers.get(
                        "Content-Type", "application/json"
                    )
                },
            )

    except httpx.TimeoutException:
        logger.error(f"New Relic request timeout: {target_url}")
        raise HTTPException(status_code=504, detail="New Relic request timed out")
    except httpx.RequestError as e:
        logger.error(f"New Relic request error: {e}")
        raise HTTPException(status_code=502, detail=f"New Relic request failed: {e}")


@app.api_route(
    "/opensearch/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def opensearch_proxy(path: str, request: Request):
    """Reverse proxy for OpenSearch API requests.

    OpenSearch uses customer-specific URLs with Basic auth (username:password).
    """
    return await generic_proxy("opensearch", path, request, require_api_key=False)


@app.api_route(
    "/blameless/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def blameless_proxy(path: str, request: Request):
    """Reverse proxy for Blameless API requests.

    Blameless is SaaS at api.blameless.io.
    """
    import httpx

    logger.info(f"Blameless proxy: {request.method} /{path}")

    # Validate JWT and extract tenant context
    tenant_id, team_id, sandbox_name = await extract_tenant_context(request)

    # Get Blameless credentials
    creds = await get_credentials(tenant_id, team_id, "blameless")
    if not creds or not creds.get("api_key"):
        logger.error(f"Blameless not configured for tenant={tenant_id}")
        raise HTTPException(
            status_code=404,
            detail="Blameless integration not configured",
        )

    # Build Blameless API URL (default to api.blameless.io)
    domain = creds.get("domain", "https://api.blameless.io")
    if not domain.startswith(("http://", "https://")):
        domain = f"https://{domain}"
    target_url = f"{domain.rstrip('/')}/{path}"
    logger.info(f"Blameless proxy: forwarding to {target_url}")

    # Build auth headers
    auth_headers = build_auth_headers("blameless", creds)

    forward_headers = {
        "Content-Type": request.headers.get("Content-Type", "application/json"),
        "Accept": request.headers.get("Accept", "application/json"),
        **auth_headers,
    }

    query_params = dict(request.query_params)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            body = None
            if request.method in ["POST", "PUT", "PATCH"]:
                body = await request.body()

            response = await client.request(
                method=request.method,
                url=target_url,
                headers=forward_headers,
                params=query_params,
                content=body,
            )

            return Response(
                content=response.content,
                status_code=response.status_code,
                headers={
                    "Content-Type": response.headers.get(
                        "Content-Type", "application/json"
                    )
                },
            )

    except httpx.TimeoutException:
        logger.error(f"Blameless request timeout: {target_url}")
        raise HTTPException(status_code=504, detail="Blameless request timed out")
    except httpx.RequestError as e:
        logger.error(f"Blameless request error: {e}")
        raise HTTPException(status_code=502, detail=f"Blameless request failed: {e}")


@app.api_route(
    "/firehydrant/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def firehydrant_proxy(path: str, request: Request):
    """Reverse proxy for FireHydrant API requests.

    FireHydrant is SaaS at api.firehydrant.io.
    """
    import httpx

    logger.info(f"FireHydrant proxy: {request.method} /{path}")

    # Validate JWT and extract tenant context
    tenant_id, team_id, sandbox_name = await extract_tenant_context(request)

    # Get FireHydrant credentials
    creds = await get_credentials(tenant_id, team_id, "firehydrant")
    if not creds or not creds.get("api_key"):
        logger.error(f"FireHydrant not configured for tenant={tenant_id}")
        raise HTTPException(
            status_code=404,
            detail="FireHydrant integration not configured",
        )

    # Build FireHydrant API URL (always api.firehydrant.io)
    target_url = f"https://api.firehydrant.io/{path}"
    logger.info(f"FireHydrant proxy: forwarding to {target_url}")

    # Build auth headers
    auth_headers = build_auth_headers("firehydrant", creds)

    forward_headers = {
        "Content-Type": request.headers.get("Content-Type", "application/json"),
        "Accept": request.headers.get("Accept", "application/json"),
        **auth_headers,
    }

    query_params = dict(request.query_params)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            body = None
            if request.method in ["POST", "PUT", "PATCH"]:
                body = await request.body()

            response = await client.request(
                method=request.method,
                url=target_url,
                headers=forward_headers,
                params=query_params,
                content=body,
            )

            return Response(
                content=response.content,
                status_code=response.status_code,
                headers={
                    "Content-Type": response.headers.get(
                        "Content-Type", "application/json"
                    )
                },
            )

    except httpx.TimeoutException:
        logger.error(f"FireHydrant request timeout: {target_url}")
        raise HTTPException(status_code=504, detail="FireHydrant request timed out")
    except httpx.RequestError as e:
        logger.error(f"FireHydrant request error: {e}")
        raise HTTPException(status_code=502, detail=f"FireHydrant request failed: {e}")


@app.api_route(
    "/victoriametrics/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def victoriametrics_proxy(path: str, request: Request):
    """Reverse proxy for VictoriaMetrics/VictoriaLogs API requests.

    VictoriaMetrics auth is optional (many internal deployments are open).
    Supports both VictoriaMetrics (metrics) and VictoriaLogs (logs) endpoints.
    """
    return await generic_proxy("victoriametrics", path, request, require_api_key=False)


@app.api_route(
    "/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]
)
async def ext_authz_check(request: Request, path: str = ""):
    """Handle ext_authz check from Envoy.

    Envoy sends the original request method and path to the auth service.
    We accept any path and check authorization based on x-original-host header.

    Security: Tenant/team context is extracted from the validated JWT,
    not from headers (which could be spoofed by malicious code in sandbox).
    """
    logger.info(f"ext_authz check: {request.method} {request.url.path}")

    # 1. Validate JWT and extract tenant context
    tenant_id, team_id, sandbox_name = await extract_tenant_context(request)

    # 2. Determine integration from target host and path
    target_host = request.headers.get("x-original-host", "")
    request_path = request.url.path
    # Strip ext_authz path_prefix if present (envoy prepends /extauthz to avoid
    # hitting LLM proxy routes, but we need the original path for integration mapping)
    if request_path.startswith("/extauthz"):
        request_path = request_path[len("/extauthz") :]
    logger.info(f"Target host: {target_host}, path: {request_path}")
    integration_id = get_integration_for_host(target_host, request_path)
    logger.info(f"Integration ID mapped: {integration_id}")

    if not integration_id:
        # Passthrough - no credential injection needed
        logger.warning(f"No integration mapping for host: {target_host}")
        return Response(status_code=200)

    logger.info(
        f"Credential request: tenant={tenant_id}, team={team_id}, "
        f"sandbox={sandbox_name}, integration={integration_id}, host={target_host}"
    )

    # 3. Get credentials and validate based on integration type
    creds = await get_credentials(tenant_id, team_id, integration_id)

    # Check if credentials are configured (uses shared logic)
    if not is_integration_configured(integration_id, creds):
        logger.error(
            f"No credentials found for {integration_id} "
            f"(tenant={tenant_id}, team={team_id})"
        )
        raise HTTPException(
            status_code=500,
            detail=f"Credentials not configured for {integration_id}",
        )

    # 4. Build auth headers and return them as HTTP response headers
    # Envoy's ext_authz will forward these based on allowed_upstream_headers config
    headers_to_add = build_auth_headers(integration_id, creds)

    # 5. Add tenant context headers (needed by LLM proxy and other internal services)
    headers_to_add["x-tenant-id"] = tenant_id
    headers_to_add["x-team-id"] = team_id

    # 6. Add LLM model override if configured
    llm_model = os.getenv("LLM_MODEL", "")
    if llm_model:
        headers_to_add["x-llm-model"] = llm_model

    logger.info(
        f"Injecting headers for {integration_id}: {list(headers_to_add.keys())}"
    )

    return Response(status_code=200, headers=headers_to_add)


async def extract_tenant_context(request: Request) -> tuple[str, str, str]:
    """Extract tenant/team context from JWT (secure) or headers (permissive mode).

    Security: In strict mode (production), we ONLY trust the JWT.
    In permissive mode (local dev), we fall back to headers if JWT is missing.

    Returns:
        Tuple of (tenant_id, team_id, sandbox_name)
    """
    jwt_token = request.headers.get("x-sandbox-jwt", "")

    # Try to validate JWT
    claims = validate_sandbox_jwt(jwt_token)

    if claims:
        logger.debug(f"JWT validated for sandbox: {claims.sandbox_name}")
        return claims.tenant_id, claims.team_id, claims.sandbox_name

    # JWT validation failed
    if JWT_MODE == "strict":
        logger.error("JWT validation failed in strict mode - rejecting request")
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing sandbox JWT",
        )

    # Permissive mode: fall back to headers (for local dev only)
    logger.warning("JWT validation failed - falling back to headers (permissive mode)")
    tenant_id = request.headers.get("x-tenant-id", "local")
    team_id = request.headers.get("x-team-id", "local")
    return tenant_id, team_id, "unknown"


async def get_credentials(
    tenant_id: str, team_id: str, integration_id: str
) -> dict | None:
    """Get credentials from configured source."""
    if CREDENTIAL_SOURCE == "environment":
        # Local/self-hosted: load from env vars
        return ENV_CREDENTIALS.get(integration_id)

    # SaaS: fetch from Config Service (cached)
    cache_key = (tenant_id, team_id, integration_id)
    if cache_key in credential_cache:
        return credential_cache[cache_key]

    if config_client is None:
        logger.error("Config Service client not initialized")
        return None

    creds = await config_client.get_integration_config(
        tenant_id, team_id, integration_id
    )
    if creds:
        credential_cache[cache_key] = creds

    return creds


def build_auth_headers(integration_id: str, creds: dict) -> dict[str, str]:
    """Build authentication headers for the integration.

    For customers using our shared Anthropic key, adds attribution metadata for cost tracking.
    This applies to ALL customers using our key (trial users AND paid users who don't BYOK).

    Note: Some integrations (like Confluence) use direct credential fetch instead of
    proxy injection because their client libraries manage auth internally.
    """
    import base64

    if integration_id == "anthropic":
        api_key = creds.get("api_key", "")
        headers = {"x-api-key": api_key}

        # Add attribution for ALL customers using our shared key (for cost tracking/billing)
        # This includes: trial users + paid users who choose not to bring their own key
        workspace = creds.get("workspace_attribution")
        if workspace:
            # Use custom header for internal attribution tracking
            # Note: Anthropic forwards custom headers in their logs for cost analysis
            headers["x-incidentfox-workspace"] = workspace
            headers["x-incidentfox-tenant"] = workspace  # Redundant but explicit
            logger.info(f"Added cost attribution for workspace: {workspace}")

        return headers

    elif integration_id == "coralogix":
        # Coralogix uses Bearer token
        api_key = creds.get("api_key", "")
        return {"Authorization": f"Bearer {api_key}"}

    elif integration_id == "confluence":
        # Confluence uses Basic auth (email:api_key base64 encoded)
        email = creds.get("email", "")
        api_key = creds.get("api_key", "")
        if email and api_key:
            auth_string = f"{email}:{api_key}"
            encoded = base64.b64encode(auth_string.encode()).decode()
            return {"Authorization": f"Basic {encoded}"}
        logger.warning("Confluence credentials incomplete for Basic auth")
        return {}

    elif integration_id == "datadog":
        # Datadog uses two API keys in headers
        return {
            "DD-API-KEY": creds.get("api_key", ""),
            "DD-APPLICATION-KEY": creds.get("app_key", ""),
        }

    elif integration_id == "elasticsearch":
        # Elasticsearch uses Basic auth (username:password) or API key
        username = creds.get("username", "")
        api_key = creds.get("api_key", "")
        if username and api_key:
            # Basic auth mode
            auth_string = f"{username}:{api_key}"
            encoded = base64.b64encode(auth_string.encode()).decode()
            return {"Authorization": f"Basic {encoded}"}
        elif api_key:
            # API key mode (already base64 encoded id:key format)
            return {"Authorization": f"ApiKey {api_key}"}
        # No auth (open cluster)
        return {}

    elif integration_id == "github":
        # GitHub uses Bearer token
        api_key = creds.get("api_key", "")
        return {"Authorization": f"Bearer {api_key}"}

    elif integration_id == "incident_io":
        # incident.io uses Bearer token
        api_key = creds.get("api_key", "")
        return {"Authorization": f"Bearer {api_key}"}

    elif integration_id in ["grafana", "prometheus", "kubernetes", "victoriametrics"]:
        # These use Bearer token
        api_key = creds.get("api_key", "")
        if api_key:
            return {"Authorization": f"Bearer {api_key}"}
        return {}

    elif integration_id == "jaeger":
        # Jaeger typically doesn't need auth, but support Bearer if provided
        api_key = creds.get("api_key", "")
        if api_key:
            return {"Authorization": f"Bearer {api_key}"}
        return {}

    elif integration_id == "honeycomb":
        # Honeycomb uses X-Honeycomb-Team header
        api_key = creds.get("api_key", "")
        return {"X-Honeycomb-Team": api_key}

    elif integration_id == "clickup":
        # ClickUp uses Authorization header with API token
        api_key = creds.get("api_key", "")
        return {"Authorization": api_key}

    elif integration_id == "loki":
        # Loki uses Bearer token (optional - some deployments are open)
        api_key = creds.get("api_key", "")
        if api_key:
            return {"Authorization": f"Bearer {api_key}"}
        return {}

    elif integration_id == "splunk":
        # Splunk uses Bearer token
        api_key = creds.get("api_key", "")
        return {"Authorization": f"Bearer {api_key}"}

    elif integration_id == "sentry":
        # Sentry uses Bearer token
        api_key = creds.get("api_key", "")
        return {"Authorization": f"Bearer {api_key}"}

    elif integration_id == "pagerduty":
        # PagerDuty uses Token-based auth
        api_key = creds.get("api_key", "")
        return {"Authorization": f"Token token={api_key}"}

    elif integration_id == "gitlab":
        # GitLab uses PRIVATE-TOKEN header
        api_key = creds.get("api_key", "")
        return {"PRIVATE-TOKEN": api_key}

    elif integration_id in [
        "openai",
        "gemini",
        "openrouter",
        "deepseek",
        "azure",
        "azure_ai",
        "mistral",
        "cohere",
        "together_ai",
        "groq",
        "fireworks_ai",
        "xai",
        "moonshot",
        "minimax",
    ]:
        # LLM providers use Bearer token
        api_key = creds.get("api_key", "")
        return {"Authorization": f"Bearer {api_key}"}

    elif integration_id in ["ollama", "bedrock", "vertex_ai"]:
        # Ollama/Bedrock/Vertex AI don't use HTTP auth headers
        return {}

    elif integration_id == "jira":
        # Jira Cloud uses Basic auth (email:api_token base64 encoded)
        email = creds.get("email", "")
        api_key = creds.get("api_key", "")
        if email and api_key:
            auth_string = f"{email}:{api_key}"
            encoded = base64.b64encode(auth_string.encode()).decode()
            return {"Authorization": f"Basic {encoded}"}
        logger.warning("Jira credentials incomplete for Basic auth")
        return {}

    elif integration_id == "newrelic":
        # New Relic uses Api-Key header
        api_key = creds.get("api_key", "")
        return {"Api-Key": api_key}

    elif integration_id == "opensearch":
        # OpenSearch uses Basic auth (username:password)
        username = creds.get("username", "")
        password = creds.get("password", "")
        if username and password:
            auth_string = f"{username}:{password}"
            encoded = base64.b64encode(auth_string.encode()).decode()
            return {"Authorization": f"Basic {encoded}"}
        # No auth (open cluster)
        return {}

    elif integration_id == "blameless":
        # Blameless uses Bearer token
        api_key = creds.get("api_key", "")
        return {"Authorization": f"Bearer {api_key}"}

    elif integration_id == "firehydrant":
        # FireHydrant uses Bearer token
        api_key = creds.get("api_key", "")
        return {"Authorization": f"Bearer {api_key}"}

    # Default: Bearer token
    api_key = creds.get("api_key", "")
    return {"Authorization": f"Bearer {api_key}"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8002)

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

    Supports all observability backends:
    - Anthropic: AI/LLM API
    - Coralogix: Log aggregation
    - Datadog: Monitoring platform (requires both API key and App key)
    - Elasticsearch: Search/logging (API key or user/password)
    - Grafana: Dashboards/visualization
    - Prometheus: Metrics (usually through Grafana, or direct)
    - Loki: Log aggregation (Grafana ecosystem)
    - Splunk: Log aggregation
    - Jaeger: Distributed tracing
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
        "datadog": {
            "api_key": os.getenv("DD_API_KEY") or os.getenv("DATADOG_API_KEY"),
            "app_key": os.getenv("DD_APP_KEY") or os.getenv("DATADOG_APP_KEY"),
            "site": os.getenv("DD_SITE", "datadoghq.com"),
        },
        "elasticsearch": {
            # API Key (preferred for Elastic Cloud)
            "api_key": os.getenv("ES_API_KEY") or os.getenv("ELASTICSEARCH_API_KEY"),
            # Basic auth (user:password)
            "user": os.getenv("ES_USER") or os.getenv("ELASTICSEARCH_USER"),
            "password": os.getenv("ES_PASSWORD") or os.getenv("ELASTICSEARCH_PASSWORD"),
            # Bearer token (alternative)
            "token": os.getenv("ES_TOKEN") or os.getenv("ELASTICSEARCH_TOKEN"),
        },
        "grafana": {
            # Service account token (glsa_xxx) or API key
            "api_key": os.getenv("GRAFANA_API_KEY") or os.getenv("GRAFANA_TOKEN"),
            # Basic auth
            "user": os.getenv("GRAFANA_USER"),
            "password": os.getenv("GRAFANA_PASSWORD"),
        },
        "prometheus": {
            # Bearer token
            "token": os.getenv("PROMETHEUS_TOKEN"),
            # Basic auth
            "user": os.getenv("PROMETHEUS_USER"),
            "password": os.getenv("PROMETHEUS_PASSWORD"),
        },
        "loki": {
            # Bearer token or API key
            "api_key": os.getenv("LOKI_TOKEN") or os.getenv("LOKI_API_KEY"),
            # Basic auth (common for Grafana Cloud: user=tenant, password=token)
            "user": os.getenv("LOKI_USER"),
            "password": os.getenv("LOKI_PASSWORD"),
            # Multi-tenant org ID
            "org_id": os.getenv("LOKI_ORG_ID"),
        },
        "splunk": {
            # Splunk uses unique "Splunk <token>" auth scheme
            "token": os.getenv("SPLUNK_TOKEN") or os.getenv("SPLUNK_HEC_TOKEN"),
            # Basic auth
            "user": os.getenv("SPLUNK_USER"),
            "password": os.getenv("SPLUNK_PASSWORD"),
        },
        "jaeger": {
            # Bearer token (enterprise)
            "token": os.getenv("JAEGER_TOKEN"),
            # Basic auth
            "user": os.getenv("JAEGER_USER"),
            "password": os.getenv("JAEGER_PASSWORD"),
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
        configured = [k for k, v in ENV_CREDENTIALS.items() if has_valid_credentials(k, v)]
        logger.info(f"Environment credentials loaded for: {configured}")

        # Debug: show masked credentials to verify they're loaded
        for integration, creds in ENV_CREDENTIALS.items():
            if has_valid_credentials(integration, creds):
                # Show which credential type is configured
                if creds.get("api_key"):
                    logger.info(f"  {integration}: api_key={mask_secret(creds.get('api_key'))}")
                elif creds.get("token"):
                    logger.info(f"  {integration}: token={mask_secret(creds.get('token'))}")
                elif creds.get("user"):
                    logger.info(f"  {integration}: user={creds.get('user')}, password=***")
                # Special case: Datadog needs both keys
                if integration == "datadog" and creds.get("app_key"):
                    logger.info(f"  {integration}: app_key={mask_secret(creds.get('app_key'))}")

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


@app.api_route("/check", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
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

    # 3. Get credentials
    creds = await get_credentials(tenant_id, team_id, integration_id)
    if not creds or not has_valid_credentials(integration_id, creds):
        logger.error(
            f"No credentials found for {integration_id} (tenant={tenant_id}, team={team_id})"
        )
        raise HTTPException(
            status_code=500,
            detail=f"Credentials not configured for {integration_id}",
        )

    # 4. Build auth headers and return them as HTTP response headers
    # Envoy's ext_authz will forward these based on allowed_upstream_headers config
    headers_to_add = build_auth_headers(integration_id, creds)
    logger.info(f"Injecting headers for {integration_id}: {list(headers_to_add.keys())}")

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


async def get_credentials(tenant_id: str, team_id: str, integration_id: str) -> dict | None:
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

    creds = await config_client.get_integration_config(tenant_id, team_id, integration_id)
    if creds:
        credential_cache[cache_key] = creds

    return creds


def has_valid_credentials(integration_id: str, creds: dict) -> bool:
    """Check if credentials dict has required fields for the integration.

    Different integrations require different credential fields:
    - Datadog: api_key AND app_key (both required)
    - Elasticsearch: api_key OR (user AND password) OR token
    - Jaeger: may have no auth (internal), token, or user/password
    - Most others: api_key OR token OR (user AND password)
    """
    if not creds:
        return False

    # Datadog requires both keys
    if integration_id == "datadog":
        return bool(creds.get("api_key") and creds.get("app_key"))

    # Jaeger can run without auth internally
    if integration_id == "jaeger":
        # Any credential is valid, or no credentials is also valid
        return True

    # For most integrations: api_key, token, or user+password
    if creds.get("api_key"):
        return True
    if creds.get("token"):
        return True
    if creds.get("user") and creds.get("password"):
        return True

    return False


def build_auth_headers(integration_id: str, creds: dict) -> dict[str, str]:
    """Build authentication headers for the integration.

    Each backend has its own auth header format:
    - Anthropic: x-api-key header
    - Datadog: DD-API-KEY + DD-APPLICATION-KEY headers
    - Elasticsearch: Authorization: ApiKey (base64) or Basic auth
    - Grafana/Prometheus/Loki: Authorization: Bearer or Basic
    - Splunk: Authorization: Splunk <token> (unique scheme!)
    - Jaeger: Authorization: Bearer or Basic
    - Coralogix: Authorization: Bearer

    For Anthropic, adds attribution metadata for cost tracking when using shared key.
    """
    import base64

    api_key = creds.get("api_key", "")

    # === Anthropic ===
    if integration_id == "anthropic":
        headers = {"x-api-key": api_key}

        # Add attribution for ALL customers using our shared key (for cost tracking/billing)
        workspace = creds.get("workspace_attribution")
        if workspace:
            headers["x-incidentfox-workspace"] = workspace
            headers["x-incidentfox-tenant"] = workspace
            logger.info(f"Added cost attribution for workspace: {workspace}")

        return headers

    # === Datadog ===
    # Unique: requires TWO headers (API key + App key)
    elif integration_id == "datadog":
        headers = {}
        if api_key:
            headers["DD-API-KEY"] = api_key
        app_key = creds.get("app_key")
        if app_key:
            headers["DD-APPLICATION-KEY"] = app_key
        return headers

    # === Elasticsearch ===
    # Priority: API Key > Basic auth > Bearer token
    elif integration_id == "elasticsearch":
        # API Key (Elastic Cloud / Enterprise)
        if api_key:
            # API key can be "id:secret" or already base64 encoded
            if ":" in api_key:
                encoded = base64.b64encode(api_key.encode()).decode()
            else:
                encoded = api_key
            return {"Authorization": f"ApiKey {encoded}"}

        # Basic auth
        user = creds.get("user")
        password = creds.get("password")
        if user and password:
            encoded = base64.b64encode(f"{user}:{password}".encode()).decode()
            return {"Authorization": f"Basic {encoded}"}

        # Bearer token
        token = creds.get("token")
        if token:
            return {"Authorization": f"Bearer {token}"}

        return {}

    # === Grafana ===
    elif integration_id == "grafana":
        # Service account token or API key
        if api_key:
            # Check if it's user:pass format
            if ":" in api_key:
                encoded = base64.b64encode(api_key.encode()).decode()
                return {"Authorization": f"Basic {encoded}"}
            return {"Authorization": f"Bearer {api_key}"}

        # Explicit user/password
        user = creds.get("user")
        password = creds.get("password")
        if user and password:
            encoded = base64.b64encode(f"{user}:{password}".encode()).decode()
            return {"Authorization": f"Basic {encoded}"}

        return {}

    # === Prometheus ===
    elif integration_id == "prometheus":
        # Bearer token
        token = creds.get("token")
        if token:
            return {"Authorization": f"Bearer {token}"}

        # Basic auth
        user = creds.get("user")
        password = creds.get("password")
        if user and password:
            encoded = base64.b64encode(f"{user}:{password}".encode()).decode()
            return {"Authorization": f"Basic {encoded}"}

        return {}

    # === Loki ===
    elif integration_id == "loki":
        headers = {}

        # Multi-tenant org ID (always add if present)
        org_id = creds.get("org_id")
        if org_id:
            headers["X-Scope-OrgID"] = org_id

        # Bearer token
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
            return headers

        # Basic auth (Grafana Cloud pattern: user=tenant, password=token)
        user = creds.get("user")
        password = creds.get("password")
        if user and password:
            encoded = base64.b64encode(f"{user}:{password}".encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"
            return headers

        return headers

    # === Splunk ===
    # Unique: uses "Splunk" scheme, not "Bearer"
    elif integration_id == "splunk":
        token = creds.get("token")
        if token:
            return {"Authorization": f"Splunk {token}"}

        # Basic auth fallback
        user = creds.get("user")
        password = creds.get("password")
        if user and password:
            encoded = base64.b64encode(f"{user}:{password}".encode()).decode()
            return {"Authorization": f"Basic {encoded}"}

        return {}

    # === Jaeger ===
    elif integration_id == "jaeger":
        # Bearer token
        token = creds.get("token")
        if token:
            return {"Authorization": f"Bearer {token}"}

        # Basic auth
        user = creds.get("user")
        password = creds.get("password")
        if user and password:
            encoded = base64.b64encode(f"{user}:{password}".encode()).decode()
            return {"Authorization": f"Basic {encoded}"}

        # Jaeger often runs without auth internally
        return {}

    # === Coralogix ===
    elif integration_id == "coralogix":
        return {"Authorization": f"Bearer {api_key}"}

    # Default: Bearer token
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8002)

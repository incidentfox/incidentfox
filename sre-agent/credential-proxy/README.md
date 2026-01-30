# Credential Proxy

Envoy-based proxy that injects authentication credentials into outbound HTTP requests from sandboxes. This keeps secrets out of the agent environment - agents cannot access credentials even if compromised.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Sandbox Pod                               │
│  ┌──────────────┐     ┌─────────────────────────────────┐   │
│  │ Agent        │     │ Envoy Sidecar (:8001)           │   │
│  │              │────▶│  - Routes /v1/* to Anthropic    │   │
│  │ BASE_URL=    │     │  - Routes /api/v1/* to Coralogix│   │
│  │ localhost:   │     │  - Adds JWT header to ext_authz │   │
│  │ 8001         │     └─────────────────────────────────┘   │
│  └──────────────┘                    │                      │
│  Env: ANTHROPIC_BASE_URL, CORALOGIX_BASE_URL (no secrets)  │
└──────────────────────────────────────┼──────────────────────┘
                                       │ ext_authz + JWT
                                       ▼
┌─────────────────────────────────────────────────────────────┐
│  credential-resolver Service                                 │
│  - Validates sandbox JWT (cryptographic proof of identity)  │
│  - Extracts tenant/team from JWT (ignores spoofed headers)  │
│  - Fetches creds from Config Service (or env vars)          │
│  - Returns headers to inject (Authorization, X-API-Key)     │
└─────────────────────────────────────────────────────────────┘
```

## Security Model

Sandboxes are **UNTRUSTED** - they could execute malicious code via prompt injection.
JWT validation prevents credential theft:

1. Server generates a signed JWT when creating sandbox (contains tenant/team/sandbox identity)
2. JWT is embedded in **per-sandbox** Envoy ConfigMap as a static header
3. Envoy adds `x-sandbox-jwt` header to every ext_authz request
4. credential-resolver validates JWT signature and expiry
5. Tenant/team extracted from JWT claims (not spoofable headers)

### JWT Flow

```
sre-agent/auth.py          →  Generates JWT at sandbox creation
sandbox_manager.py         →  Embeds JWT in per-sandbox ConfigMap
Envoy sidecar              →  Adds x-sandbox-jwt header to requests
credential-resolver        →  Validates JWT, injects credentials
```

## Local Development

### Docker Compose (standalone proxy testing)

1. Copy `.env.example` to `../.env` and fill in your API keys:
   ```bash
   cp .env.example ../.env
   # Edit ../.env with your actual credentials
   ```

2. Start the proxy services:
   ```bash
   cd credential-proxy
   docker compose up -d
   ```

3. Test credential injection (uses BASE_URL approach):
   ```bash
   # Anthropic API through proxy
   curl http://localhost:8001/v1/messages \
     -H "Content-Type: application/json" \
     -H "anthropic-version: 2023-06-01" \
     -d '{"model": "claude-sonnet-4-20250514", "max_tokens": 100, "messages": [{"role": "user", "content": "Hi"}]}'
   ```

### Kind Cluster (full integration)

```bash
# From sre-agent directory
make setup-local  # One-time setup
make dev          # Run server with sandbox support
```

## Credential Sources

The credential-resolver supports multiple credential sources:

| Mode | CREDENTIAL_SOURCE | JWT_MODE | Use Case |
|------|-------------------|----------|----------|
| Environment | `environment` | `permissive` | Local dev |
| Environment | `environment` | `strict` | Self-hosted production |
| Config Service | `config_service` | `strict` | SaaS multi-tenant |

## Supported Integrations (Phase 1)

- **Anthropic API** (`/v1/*`, `/api/event_logging/*`): Injects `X-API-Key` header
- **Coralogix** (`/api/v1/dataprime/*`, `/api/v1/query*`): Injects `Authorization: Bearer` header

## Files

```
credential-proxy/
├── Dockerfile                    # credential-resolver image
├── pyproject.toml                # Python dependencies
├── docker-compose.yaml           # Local development
├── src/credential_resolver/
│   ├── __init__.py
│   ├── main.py                   # FastAPI ext_authz service
│   ├── jwt_auth.py               # JWT validation (resolver-side)
│   ├── config_client.py          # Config Service client
│   └── domain_mapping.py         # Path → integration mapping
├── envoy/
│   └── envoy-local.yaml          # Local dev Envoy config
└── k8s/
    ├── deployment.yaml           # Production (ECR image, strict JWT)
    ├── deployment-local.yaml     # Kind cluster (local image)
    ├── service.yaml              # ClusterIP service
    ├── serviceaccount.yaml       # ServiceAccount for pod
    ├── networkpolicy.yaml        # Restrict access to resolver
    ├── configmap-envoy.yaml      # Base Envoy config (production)
    └── configmap-envoy-local.yaml # Base Envoy config (Kind)
```

## Environment Variables

### credential-resolver

| Variable | Description | Default |
|----------|-------------|---------|
| `CREDENTIAL_SOURCE` | `environment` or `config_service` | `environment` |
| `JWT_MODE` | `strict` (require valid JWT) or `permissive` (allow missing) | `strict` |
| `JWT_SECRET` | Shared secret with sre-agent server | (required in strict mode) |
| `ANTHROPIC_API_KEY` | Anthropic API key | - |
| `CORALOGIX_API_KEY` | Coralogix API key | - |
| `CORALOGIX_DOMAIN` | Coralogix domain | - |

### sre-agent server

| Variable | Description |
|----------|-------------|
| `JWT_SECRET` | Shared secret for signing sandbox JWTs |
| `CREDENTIAL_RESOLVER_NAMESPACE` | K8s namespace where credential-resolver runs |

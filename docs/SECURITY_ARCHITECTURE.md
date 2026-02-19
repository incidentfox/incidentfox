# Security Architecture

> **Status**: Living document. Updated as audit findings are reviewed and remediated.
> **Last updated**: 2026-02-18 (Phase 1 Security Audit)

## Overview

IncidentFox is a multi-tenant AI SRE that runs in customer environments on AWS EKS. Each investigation runs in an isolated sandbox pod. The security model has three layers:

1. **Authentication & Authorization** — Who can trigger investigations and manage config
2. **Sandbox Isolation** — Preventing cross-tenant access during agent execution
3. **Credential Protection** — Ensuring API keys never reach untrusted code

## Authentication Flows

### 1. Slack → slack-bot → sre-agent (Current Production Path)

```
User @mentions bot in Slack
    ↓
slack-bot (Socket Mode, authenticated via SLACK_BOT_TOKEN + SLACK_APP_TOKEN)
    ↓ resolves org_id + team_node_id from Slack workspace/channel routing
    ↓ fetches team_token from config-service
    ↓
POST /investigate to sre-agent
    headers: Authorization: Bearer <INVESTIGATE_AUTH_TOKEN>
    body: { prompt, thread_id, tenant_id, team_id, team_token }
    ↓
sre-agent validates INVESTIGATE_AUTH_TOKEN, creates sandbox with JWT(tenant_id, team_id)
    ↓
credential-proxy validates JWT and injects team-scoped API keys
```

**Trust boundary**: slack-bot is trusted (it runs inside the cluster). The `tenant_id` and `team_id` in the `/investigate` request body come from slack-bot's internal routing — NOT from the Slack user.

**Auth**: The `/investigate`, `/interrupt`, and `/answer` endpoints require a shared service secret (`INVESTIGATE_AUTH_TOKEN`) in the `Authorization: Bearer` header. Both sre-agent and slack-bot read this from the same K8s Secret. In local dev (when the env var is unset), auth is disabled for convenience.

**FIXED (P0-1)**: Service-to-service auth added. Previously, the endpoint had no authentication — any pod with network access could forge tenant context.

### 2. Web UI → sre-agent (via orchestrator or direct)

```
User logs in to web_ui (cookie-based session)
    ↓
web_ui reads incidentfox_session_token cookie
    ↓
POST /api/team/agent/stream (Next.js API route)
    ↓ forwards to AGENT_SERVICE_URL /agents/{name}/run/stream
    ↓ includes X-IncidentFox-Team-Token + Authorization: Bearer {token}
    ↓
sre-agent (or orchestrator) validates the team token
```

**Note**: web_ui uses a different endpoint path (`/agents/{name}/run/stream`) than slack-bot (`/investigate`). The orchestrator path has proper token-based auth. The direct `/investigate` path does not.

### 3. Admin API (config-service)

```
Admin token (super-admin or org-admin) in Authorization header
    ↓
config-service authenticate_admin_request()
    ↓ checks in order:
    1. X-Internal-Service header (for agent service → config-service calls)
    2. ADMIN_TOKEN env var (super-admin break-glass)
    3. Org admin token from DB (per-org, scoped)
    4. OIDC JWT (if configured)
    ↓
AdminPrincipal { auth_kind, subject, email, org_id }
    ↓
check_org_access(principal, org_id) ← MUST be called per-endpoint
```

**FIXED (P0-2)**: `check_org_access()` is now called on every authenticated endpoint in both `admin.py` and `security.py`. Previously, all `security.py` endpoints and several `admin.py` endpoints were missing the check, allowing org-scoped admins to access other orgs' data.

### 4. Team API (config-service)

```
Team token (token_id.secret format) in Authorization header
    ↓
config-service require_team_auth()
    ↓ verifies token hash against DB (HMAC with TOKEN_PEPPER)
    ↓ returns TeamPrincipal { org_id, team_node_id }
    ↓
Team can only access its own config (enforced by DB queries filtering on org_id + team_node_id)
```

## Sandbox Isolation Model

Each investigation gets its own Kubernetes pod:

```
┌─ Sandbox Pod ──────────────────────────────────────┐
│                                                     │
│  ┌─ init container ─┐    ┌─ agent container ──────┐ │
│  │ JWT injected via  │    │ Claude Agent SDK       │ │
│  │ /tmp/sandbox-jwt  │───→│ skills + scripts       │ │
│  └───────────────────┘    │ ANTHROPIC_BASE_URL     │ │
│                           │  = http://envoy:8001   │ │
│                           │ ANTHROPIC_API_KEY       │ │
│                           │  = sk-placeholder      │ │
│                           └────────────┬───────────┘ │
│                                        │             │
│  ┌─ envoy sidecar ───────────────────┐ │             │
│  │ Reads JWT from /tmp/sandbox-jwt   │←┘             │
│  │ Adds x-sandbox-jwt header         │               │
│  │ Routes to credential-resolver     │               │
│  └────────────────┬──────────────────┘               │
└───────────────────┼──────────────────────────────────┘
                    │
    ┌─ credential-resolver (ext_authz) ─┐
    │ Validates JWT signature            │
    │ Extracts tenant_id, team_id        │
    │ Looks up team's API keys           │
    │ Injects real key into request      │
    │ Forwards to upstream API           │
    └────────────────────────────────────┘
```

**Design intent**: Sandboxes run untrusted code (agent output, prompt-injected commands). They should NEVER see real API keys.

**FIXED (P0-3)**: All direct secret mounts removed from sandbox pods. Gemini/OpenAI keys are injected by credential-resolver's LLM proxy (same path as Anthropic). Laminar/Langfuse keys removed entirely — observability is collected server-side.

**FIXED (P0-5)**: gVisor is now ON by default. Changed from opt-in (`USE_GVISOR=true`) to opt-out (`DISABLE_GVISOR=true`). Only local dev should disable gVisor.

## JWT Lifecycle

```
server.py → generate_sandbox_jwt()
    payload: { iss, aud, iat, exp, tenant_id, team_id, sandbox_name, thread_id }
    signed with: JWT_SECRET (HS256)
    TTL: 24 hours (default)
    ↓
JWT stored in _sessions dict (in-memory, per thread_id)
    reused across sandbox recreations if >30 min remaining
    ↓
Injected into sandbox via:
  - Direct creation: written to /tmp/sandbox-jwt in init container
  - Warm pool: POST /claim with JWT in body
    ↓
Envoy sidecar reads JWT file and adds as header on all ext_authz requests
    ↓
credential-resolver validates: signature, expiry, issuer, audience
    extracts: tenant_id, team_id for credential lookup
```

**KNOWN ISSUE (P1-7)**: JWT_SECRET has a hardcoded default (`"incidentfox-sandbox-jwt-secret-change-in-prod"`). If the env var is unset, this default is used silently. Anyone who knows the default can forge JWTs.

## RBAC Model (config-service)

```
Super-admin (ADMIN_TOKEN)
    └── Can access ALL orgs (org_id = None in AdminPrincipal)

Org admin (org admin token from DB)
    └── Can access ONE org (org_id = specific org in AdminPrincipal)
        └── check_org_access() enforces this boundary

Team token
    └── Can access ONE team's config within ONE org
        └── Scoped by org_id + team_node_id from DB lookup

Visitor (playground)
    └── Public read/write access for demo purposes
```

**KNOWN ISSUE (P1-10)**: `TeamPrincipal.can_write()` always returns `True` — visitors have full write access.

## Network Architecture

```
┌─ EKS Cluster ──────────────────────────────────────┐
│                                                     │
│  ┌─ incidentfox namespace ─────────────────────┐    │
│  │ slack-bot (Socket Mode, no ingress)         │    │
│  │ sre-agent (ClusterIP only)                  │    │
│  │ config-service (ClusterIP only)             │    │
│  │ credential-proxy (envoy + resolver)         │    │
│  │ web-ui (ALB ingress, HTTPS)                 │    │
│  │ orchestrator (ALB ingress for webhooks)     │    │
│  └─────────────────────────────────────────────┘    │
│                                                     │
│  ┌─ sandbox pods (dynamic, per-investigation) ─┐    │
│  │ Created by sre-agent sandbox_manager.py     │    │
│  │ Runtime: gVisor (when enabled)              │    │
│  │ Should only reach: DNS, credential-proxy    │    │
│  └─────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────┘
```

**FIXED (P0-4)**: Sandbox egress is restricted by NetworkPolicy (`sandbox-networkpolicy.yaml`). Pods with `incidentfox.io/isolation: sandbox` are allowed: DNS (53), credential-resolver (8002), config-service (8080), RAG (8000), sandbox-router (8080), and HTTP/HTTPS/K8s API (80, 443, 6443) to any IP **except** 169.254.0.0/16 (AWS metadata service blocked — prevents SSRF to node IAM). Phase 2: once all integrations route through credential-resolver, the general HTTP/HTTPS egress rule will be removed.

## Secrets Management

```
AWS Secrets Manager
    ↓ ExternalSecrets Operator (ESO)
K8s Secrets (auto-synced)
    ↓ mounted as env vars or files
Services (config-service, sre-agent, etc.)
```

**Pattern**: No hardcoded secrets in Helm values or Docker images. All secrets flow through AWS Secrets Manager → ESO → K8s Secrets.

**Exception**: `JWT_SECRET` has a hardcoded fallback default (see P1-7).

## Known Issues Summary

| ID | Severity | Component | Status |
|----|----------|-----------|--------|
| P0-1 | Critical | sre-agent/server.py | **FIXED** — Service-to-service auth via INVESTIGATE_AUTH_TOKEN |
| P0-2 | Critical | config_service/security.py + admin.py | **FIXED** — check_org_access() added to all endpoints |
| P0-3 | Critical | sre-agent/sandbox_manager.py | **FIXED** — All direct secret mounts removed from sandbox pods |
| P0-4 | Critical | sandbox networking | **FIXED** — NetworkPolicy restricts sandbox egress to required services only |
| P0-5 | Critical | sre-agent/sandbox_manager.py | **FIXED** — gVisor ON by default, opt-out via DISABLE_GVISOR |
| P1-7 | High | sre-agent/auth.py | OPEN — Hardcoded JWT_SECRET default |
| P1-10 | High | config_service/auth.py | OPEN — Visitor write access always enabled |

Full findings: `.context/findings/phase-1-security-findings.md`

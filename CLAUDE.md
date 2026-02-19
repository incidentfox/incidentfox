# IncidentFox — AI SRE Platform

## What this is

IncidentFox is a multi-tenant AI SRE that investigates production incidents via Slack. It's deployed to real customer environments on AWS EKS. Treat all changes as production changes.

## Architecture (what's alive)

```
Slack  → slack-bot (Bolt/Socket Mode) ─→ sre-agent (Claude Agent SDK) → gVisor sandbox
Web UI ─────────────────────────────────↗        ↕
                                           credential-proxy (Envoy)

config-service ← used by web_ui, slack-bot, orchestrator, credential-resolver
```

Two entry points for running agents: **Slack** (via slack-bot) and **web_ui** (directly). Both stream SSE from sre-agent.

**sre-agent** is the active agent. Runs in isolated gVisor K8s sandbox pods — each investigation gets its own sandbox. Uses Claude SDK with 45 skills (progressive knowledge loading) and scripts (Python/Bash integrations). No MCP tools — everything is skills + scripts.

**slack-bot** is the Slack UI layer. Connects via Socket Mode. Streams SSE from sre-agent. Handles multi-workspace OAuth, onboarding, feedback. Currently talks directly to sre-agent (not through orchestrator).

**web_ui** is both an admin console AND a second agent entry point (Next.js 16, pnpm). Connects to sre-agent via `AGENT_SERVICE_URL` (or orchestrator via `ORCHESTRATOR_URL`) for streaming agent runs with a chat-like `AgentRunnerModal`. Also proxies to config-service for identity/config/RBAC and ultimate_rag for knowledge base tree explorer + semantic search. Has team mode (dashboard, KB explorer, agent runs, tools/prompts config) and admin mode (org tree, tokens, audit logs, security policies). Auth via bearer tokens or optional OIDC.

**config-service** is the control plane. Hierarchical org→team config with deep merge (dicts merge, lists replace). Manages tokens, audit logging, RBAC. Teams authenticate with bearer tokens.

**orchestrator** routes webhooks (Slack, GitHub, PagerDuty, Incident.io, Blameless, FireHydrant) and handles team provisioning. Has output_handlers for posting agent results to GitHub PR/issue comments. Currently NOT in the active Slack path — slack-bot talks directly to sre-agent. web_ui can optionally route through orchestrator. Long-term, all surfaces should go through orchestrator.

**credential-proxy** (Envoy + credential-resolver) injects API keys into outbound requests so sandboxes never see secrets. JWT-based sandbox identity.

## Dead / deprecated code (do not extend)

- **dependency_service/** — Stub only (README.md, no code). Placeholder for premium feature.
- **correlation_service/** — Stub only (README.md, no code). Placeholder for premium feature.

**Removed**:
- `unified-agent/` — OpenHands SDK attempt. Deleted after all valuable tools were ported to sre-agent skills.
- `agent/` — Original OpenAI SDK agent. Deleted after prompts were migrated to `config_service/scripts/prompts/` and all tools ported to sre-agent skills.
- `knowledge_base/` — Original RAPTOR service. Deleted after raptor lib was copied to `ultimate_rag/raptor_lib/` and all imports updated. The Helm template (`knowledge-base.yaml`) remains but is disabled in all environments (`knowledgeBase.enabled: false`).

**Not deprecated** (despite being disabled in staging/prod):
- **ai_pipeline/** — Premium feature under active development. Disabled via `enabled: false` in all environments. Integrated with orchestrator, slack-bot, and web_ui.

The history: agent/ (OpenAI SDK) → sre-agent (Claude SDK) → unified-agent (OpenHands SDK, deleted) → back to sre-agent (Claude SDK). We standardized on sre-agent because its skills architecture is simpler and Claude SDK is better tested.

## Remaining work (agent/ and unified-agent/ are deleted)

All 45 tools have been ported to sre-agent skills. Prompts migrated to `config_service/scripts/prompts/`. GitHub output handler ported to orchestrator. Remaining items:

- **Config-driven subagents**: Port `agent_builder.py` pattern (topological sort, agent-as-tool, model alias resolution) to sre-agent for per-team agent customization via config-service.
- **Output handlers for Teams & Google Chat**: Port Adaptive Cards (Teams) and Card v2 (Google Chat) handlers to orchestrator (GitHub handler already done).
- **DB migration tools**: Flyway, Alembic, Prisma (low priority).
- **Schema Registry & Debezium tools** (low priority).

## Security audit status

A comprehensive 8-phase security audit was completed (see `.context/CODEBASE_AUDIT_PLAN.md`). 204 findings across P0–P3. 69 fixed, 135 deferred. All findings documented in `.context/findings/phase-{1..8}-*.md`. Key fixes: sandbox auth, pickle RCE prevention, XSS/CSRF fixes, securityContext on all Helm deployments, SQL injection prevention, path traversal guards.

## Environments & Clusters

| Env | EKS Cluster | Namespace | Region | Values File |
|-----|-------------|-----------|--------|-------------|
| **Staging** | incidentfox-demo | incidentfox | us-west-2 | values.staging.yaml |
| **Production** | incidentfox-prod | incidentfox-prod | us-west-2 | values.prod.yaml |

ECR registry: `103002841599.dkr.ecr.us-west-2.amazonaws.com`

There's also a `values.pilot.yaml` + terraform in `infra/terraform/envs/pilot/` as a reference template for self-hosted customer deployments. No persistent cluster — spin up on demand, tear down after eval.

## Deployment

Deploy via GitHub Actions: `.github/workflows/deploy-eks.yml` (manual trigger). Select environment (staging/production) and services (all or specific). Builds Docker images, pushes to ECR, deploys via Helm.

Helm chart: `charts/incidentfox/`. One chart, multiple values files per environment.

Secrets: AWS Secrets Manager → ExternalSecrets Operator → K8s Secrets. Never hardcode secrets.

## Local development

`make dev` starts the full local stack: postgres, config-service, credential-resolver, envoy, sre-agent. Only `ANTHROPIC_API_KEY` is required in `.env` (see `.env.example`).

`make dev-slack` adds the slack-bot (requires `SLACK_BOT_TOKEN` + `SLACK_APP_TOKEN` in `.env`).

The local stack builds all services from source. Config-service auto-runs alembic migrations and seeds local dev data (org=local, team=default). sre-agent loads team config from config-service via header-based auth (`INCIDENTFOX_TENANT_ID=local`, `INCIDENTFOX_TEAM_ID=default`).

**Note**: `local/docker-compose.yml` has been removed (it ran the deprecated agent/). Use the root docker-compose.yml instead. The `local/` directory now only contains `claude_code_pack/`, `incidentfox_cli/`, and test files.

## Key files

| File | What it does |
|------|-------------|
| sre-agent/agent.py | Claude SDK agent with skills, streaming, subagents |
| sre-agent/server.py | FastAPI server, sandbox lifecycle, file proxy for Slack |
| sre-agent/sandbox_manager.py | K8s sandbox CRD management (1700 lines) |
| sre-agent/sandbox_server.py | FastAPI inside the sandbox pod |
| slack-bot/app.py | Main Slack handler (8000+ lines — needs refactoring) |
| slack-bot/config_client.py | Config service client |
| slack-bot/modal_builder.py | Interactive modals (103KB) |
| config_service/src/api/main.py | Config API with hierarchical merge |
| orchestrator/src/.../webhooks/router.py | Webhook router (GitHub, PagerDuty, Incident.io, Blameless, FireHydrant) |
| orchestrator/src/.../output_handlers/ | Post agent results to GitHub PRs/issues |
| web_ui/src/app/ | Next.js app router pages (team + admin modes) |
| web_ui/src/app/api/ | API routes proxying to config-service, sre-agent, ultimate_rag |
| charts/incidentfox/ | Helm chart for all services |

## Patterns to follow

**Credentials**: Never put API keys in agent code. Route through credential-proxy. In sandbox: `ANTHROPIC_BASE_URL=http://envoy:8001` with a placeholder key.

**Skills over tools**: sre-agent uses `.claude/skills/*/SKILL.md` for progressive knowledge loading (~100 tokens metadata, full content on demand). Add new integrations as skills with scripts, not as Python tool functions.

**Config hierarchy**: Org config is the base. Team config overrides. Dicts merge recursively, lists replace entirely. Use `GET /api/v1/config/me/effective` to see resolved config.

**Error format**: Tools return `{"success": bool, "result": ..., "error": "..."}`.

**SSE streaming**: sre-agent streams events to slack-bot and web_ui. Event types defined in events.py. web_ui consumes them via `useAgentStream` hook.

## Conventions

- Python services use `uv` (sre-agent, config-service). Prefer uv for new work.
- web_ui is Next.js with pnpm.
- Linting: ruff. Config in ruff.toml.
- All services have Dockerfiles. sre-agent has Dockerfile (prod, hardened) and Dockerfile.simple (dev).
- K8s manifests live in each service's `k8s/` dir AND in `charts/incidentfox/templates/`.

## Architecture decisions pending

1. **Orchestrator integration**: sre-agent currently bypasses orchestrator and talks directly to slack-bot. This blocks non-Slack surfaces (MS Teams, Google Chat — secrets already in staging values). Need to abstract Slack-specific prompts and the file proxy server.
2. **Config-driven agents**: Port agent_builder.py pattern to sre-agent so teams can customize agents via config-service.
3. **Helm cleanup**: `knowledge-base.yaml` template still exists (disabled in all envs). Remove once confirmed no customer uses it. Also remove `knowledgeBase` sections from values files.

## Scratchpad

For multi-session work, write plans to `SCRATCHPAD.md` at the repo root. Read it at session start. Update it when making architectural decisions.

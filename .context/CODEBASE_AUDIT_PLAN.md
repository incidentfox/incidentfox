# IncidentFox Codebase Quality Audit — Master Plan

**Created**: 2026-02-16
**Owner**: CTO-level review, executed by AI agents in parallel workspaces
**Goal**: Thorough quality control of an AI-generated codebase before it ships to paying customers

---

## Context

This is a YC-backed startup's open-source product. Most code was written by AI agents with limited human review. The product is deployed to real customer environments on AWS EKS. We support Slack, web UI, and are adding MS Teams + Google Chat. We need to treat this as a production-grade audit — finding bugs, security holes, logic errors, dead code, and architectural inconsistencies before they become customer incidents.

**Codebase scope**: ~50-70K LOC across 6 active services, 6 deprecated services, Helm charts, Terraform, CI/CD workflows. ~1800 markdown files.

---

## Phase -1: Harvest & Port from Deprecated Services (Do Before Cleanup)

**Why first**: `agent/` has ~20K lines of production-tested tools and `unified-agent/` has a config-driven agent builder. Much of this is valuable and not yet in sre-agent. We need to extract what's useful BEFORE deleting these directories.

### Gap Analysis Summary

**What sre-agent already has** (24 skills, 116 scripts):
- K8s, GitHub, Slack, PagerDuty, Grafana, Coralogix, Datadog, Elasticsearch, Jaeger, Loki, Splunk, VictoriaMetrics, VictoriaLogs, Honeycomb, Confluence, ClickUp, RAPTOR knowledge base

**What agent/ has that sre-agent does NOT** (high-value unique tools):

| Tool | Lines | What it does | Priority |
|------|-------|-------------|----------|
| Azure tools | 1,532 | 20+ tools: VMs, AKS, Log Analytics (KQL), Cost Mgmt, App Insights, SQL, Cosmos | HIGH |
| PostgreSQL tools | 1,022 | 9 tools: replication monitoring, blocking queries, lock analysis | HIGH |
| MySQL tools | 760 | 7 tools: replication lag, InnoDB deadlock detection, Aurora-optimized | HIGH |
| Snowflake tools | 644 | 11 tools: incident-aware queries, ARR-at-risk, customer impact | HIGH |
| Kafka tools | 623 | 6 tools: consumer lag health assessment, broker info | HIGH |
| Jira tools | 544 | 7 tools: create/update issues, JQL search, epic management | HIGH |
| Sentry tools | 339 | 6 tools: issue tracking, project stats, releases | MEDIUM |
| Docker tools | 338 | 8 tools: ps, logs, inspect, exec, compose | MEDIUM |
| GCP tools | 330 | 5 tools: Compute, GKE, Cloud Functions, Cloud SQL | MEDIUM |
| BigQuery tools | 257 | 4 tools: query, datasets, tables, schema | MEDIUM |
| New Relic tools | 145 | 2 tools: NRQL queries, APM summary | MEDIUM |
| GitLab tools | 306 | 5 tools: projects, pipelines, MRs, comments | MEDIUM |
| Sourcegraph tools | 108 | 1 tool: cross-repo code search | LOW |
| Incident.io tools | ~350 | 8 tools: incident lifecycle | LOW |
| Opsgenie tools | ~400 | 9 tools: alert/on-call management | LOW |
| Blameless tools | ~350 | 8 tools: SRE incident mgmt, retrospectives | LOW |
| FireHydrant tools | ~350 | 8 tools: incident command, retrospectives | LOW |
| Notion tools | ~200 | 3 tools: documentation retrieval | LOW |
| Linear tools | ~200 | 4 tools: issue tracking (GraphQL) | LOW |
| Google Docs tools | ~200 | 3 tools: document reading | LOW |
| Flyway/Alembic/Prisma | ~1,100 | 25 tools: DB migration management | LOW |
| Schema Registry | ~300 | 8 tools: Avro/Protobuf schemas | LOW |
| Debezium tools | ~400 | 11 tools: CDC connector management | LOW |

**Architectural patterns to port** (from agent/ and unified-agent/):

| Pattern | Source | Lines | What it does | Priority |
|---------|--------|-------|-------------|----------|
| Config-driven agent builder | both | ~900 | Build agent hierarchies from JSON config, topological sort | CRITICAL |
| Output handlers (Teams, Google Chat) | agent/ | ~734 | Multi-surface agent output (Adaptive Cards, Card v2) | HIGH |
| MCP client integration | agent/ | 413 | Per-team MCP server discovery and lifecycle | HIGH |
| Human interaction protocol | agent/ | 316 | ask_human() with abstract channel interface | HIGH |
| A2A (Agent-to-Agent) protocol | agent/ | 239 | Remote agent delegation via JSON-RPC 2.0 | MEDIUM |
| Dynamic tool loader | agent/ | 1,473 | Conditional tool loading based on installed packages | MEDIUM |
| Proxy mode pattern | unified/ | all tools | Dual direct/credential-proxy mode for all tools | MEDIUM |
| Partial work summarization | agent/ | ~200 | LLM-based summary on MaxTurnsExceeded | LOW |
| Event stream registry | agent/ | ~200 | Nested agent visibility in streaming | LOW |

### -1A. Port HIGH priority tools as sre-agent skills ✅ COMPLETE

All 21 high-priority tools have been ported across 5 batches (172 files, ~11,780 lines). Merged in PR #413.

**Batch 1** (infrastructure): ✅ Azure, GCP, Docker
**Batch 2** (databases): ✅ PostgreSQL, MySQL, Snowflake, BigQuery
**Batch 3** (observability): ✅ Sentry, New Relic
**Batch 4** (collaboration): ✅ Jira, GitLab, Kafka
**Batch 5** (remaining): ✅ Incident.io, Opsgenie, Blameless, FireHydrant, Notion, Linear, Google Docs, Sourcegraph

**Not ported** (low priority):
- [ ] Port DB migration tools (Flyway, Alembic, Prisma)
- [ ] Port Schema Registry, Debezium tools

### -1B. Port architectural patterns

These require more careful integration into sre-agent's existing architecture:

- [ ] **Config-driven agent builder**: Port `agent_builder.py` pattern to sre-agent. This enables per-team agent customization via config-service JSON. Key features: topological sort, agent-as-tool, model alias resolution, tool enable/disable.
- [ ] **Output handlers for Teams & Google Chat**: Port the Adaptive Cards (Teams) and Card v2 (Google Chat) output handlers. These are needed for the orchestrator's multi-surface support.
- [ ] **MCP client integration**: Port the per-team MCP server discovery pattern so teams can bring their own MCP tools.
- [ ] **Human interaction protocol**: Port ask_human() with its abstract channel interface for human-in-the-loop workflows.
- [ ] **Proxy mode in all tools**: Ensure every new skill supports both direct API mode and credential-proxy mode.

### -1C. Validate ported tools work

- [ ] For each ported skill, verify it loads correctly in sre-agent
- [ ] Test at least one script from each skill against a mock or real endpoint
- [ ] Verify credential-proxy mode works for skills that need it
- [ ] Run the ported skills through the existing sre-agent test harness

### Execution strategy for Phase -1

This phase is highly parallelizable. Each tool port is independent:
- **12+ workspaces in parallel**: One per tool/skill batch
- **Estimated effort**: 1 session per simple tool (API wrapper), 2-3 sessions for complex tools (Azure, PostgreSQL, Kafka)
- **Architecture ports**: 1 dedicated workspace each, sequential within workspace

---

## Phase 0: Dead Code Removal (After Porting)

**Why first**: ~35MB of deprecated code makes every other review harder. Clean the house before inspecting it.

### 0A. Catalog what's actually deprecated ✅ COMPLETE
- [x] `unified-agent/` — DELETED. No external dependencies. All tools ported to sre-agent skills.
- [x] `agent/` — Cannot delete yet. `generate_golden_prompts.py` imports `ai_agent.prompts.*`. Docker Hub workflow builds it.
- [x] `knowledge_base/` — Cannot delete yet. `ultimate_rag/` has 21 imports from `knowledge_base.raptor` + Dockerfile COPY.
- [x] `ai_pipeline/` — NOT deprecated. Premium feature under active development, just not deployed.
- [x] `dependency_service/` — Stub only (README.md). Placeholder for premium feature.
- [x] `correlation_service/` — Stub only (README.md). Placeholder for premium feature.

### 0B. Extract value before deletion ✅ COMPLETE
- [x] All 21 high-priority tools ported to sre-agent skills (PR #413)
- [x] GitHub OutputHandler ported to orchestrator (PR #414)
- [x] Migrate `ai_agent.prompts.*` to `config_service/scripts/prompts/` (PR #415)
- [x] Copy `knowledge_base/raptor/` to `ultimate_rag/raptor_lib/` and update all imports (PR #415)
- [ ] Port `agent_builder.py` pattern for config-driven subagents (deferred — not blocking deletion)
- [ ] Port Teams & Google Chat output handlers (deferred — not blocking deletion)

### 0C. Remove dead code ✅ COMPLETE
- [x] Deleted `unified-agent/` directory (PR #415)
- [x] Removed `local/docker-compose.yml` (deprecated trial stack) (PR #415)
- [x] Updated CI workflows (removed agent/knowledge_base from Docker Hub publish, Trivy) (PR #415)
- [x] Deleted `agent/` directory (PR #415)
- [x] Deleted `knowledge_base/` directory (PR #415)
- [x] Updated `CLAUDE.md` to reflect all removals (PR #415)

---

## Phase 1: Security Audit (Critical Path)

**Why**: This runs in customer environments with access to their K8s clusters, cloud accounts, and secrets. A security bug here is an existential risk.

### 1A. Secrets & credential handling
- [ ] Audit credential-proxy (Envoy + credential-resolver): verify sandboxes truly never see plaintext secrets
- [ ] Review JWT auth flow: `sre-agent/credential-proxy/src/credential_resolver/jwt_auth.py`
- [ ] Check for hardcoded secrets, API keys, or tokens in code (not just .env files)
- [ ] Review `.env.example` — does it accidentally contain real values?
- [ ] Audit ExternalSecrets → K8s Secrets flow in Helm chart
- [ ] Review all `values.staging.yaml` / `values.prod.yaml` for leaked secrets
- [ ] Check gitleaks config (`.gitleaks.toml`) and history for any past leaks

### 1B. Sandbox security (gVisor)
- [ ] Review `sre-agent/sandbox_manager.py` (1700 lines) — this controls isolation
- [ ] Verify gVisor runtime is enforced, not optional
- [ ] Check sandbox pod specs for privilege escalation vectors (hostNetwork, hostPID, capabilities)
- [ ] Review `sre-agent/k8s/sandbox-template.yaml` and warmpool variants
- [ ] Verify network policies in `credential-proxy/k8s/networkpolicy.yaml`
- [ ] Check if sandbox pods can reach the internet directly (should go through credential-proxy)

### 1C. Auth & multi-tenancy
- [ ] Audit tenant isolation in config-service: can tenant A see tenant B's data?
- [ ] Review token hashing and auth in `config_service/src/api/routes/`
- [ ] Check RBAC implementation in config-service
- [ ] Review web_ui auth flow (next-auth, bearer tokens, OIDC)
- [ ] Audit `web_ui/src/app/api/_utils/upstream.ts` — this proxies to backend services
- [ ] Check for IDOR vulnerabilities in API routes (org/team ID validation)

### 1D. Input validation & injection
- [ ] Review all FastAPI endpoints for input validation (Pydantic models?)
- [ ] Check for SQL injection in config-service (SQLAlchemy usage, raw queries?)
- [ ] Look for command injection in sre-agent scripts
- [ ] Review Slack input handling in `slack-bot/app.py` (8000+ lines)
- [ ] Check webhook signature verification in orchestrator (`webhooks/signatures.py`)

### 1E. Docker & infrastructure security
- [ ] Audit all 16 Dockerfiles for best practices (non-root, minimal images, pinned versions)
- [ ] Review orchestrator Dockerfile CVE patching hack (setuptools vendor workaround)
- [ ] Check `.dockerignore` files exist and exclude sensitive files
- [ ] Review Terraform configs in `infra/` for security best practices
- [ ] Audit Karpenter NodePool config for over-permissive instance types
- [ ] Review IRSA (IAM Roles for Service Accounts) in Helm chart

---

## Phase 2: Core Logic Review — sre-agent

**Why**: This is the brain of the product. Bugs here mean wrong answers for customers during incidents.

### 2A. Agent core (`sre-agent/agent.py`)
- [ ] Read and understand the full agent loop
- [ ] Review Claude SDK usage — correct API patterns? Error handling?
- [ ] Check skill loading mechanism — race conditions? Memory leaks on long runs?
- [ ] Review subagent spawning logic
- [ ] Verify streaming (SSE) is robust — what happens on disconnect?
- [ ] Check for prompt injection vulnerabilities in skill content

### 2B. Server & API (`sre-agent/server.py`, `server_simple.py`)
- [ ] Review FastAPI routes — correct auth? Rate limiting?
- [ ] Check file proxy server (used by Slack for file sharing)
- [ ] Review SSE streaming implementation
- [ ] Check error handling — do errors leak internal details?
- [ ] Review health check endpoints

### 2C. Sandbox lifecycle (`sre-agent/sandbox_manager.py`)
- [ ] Review pod creation, lifecycle, and cleanup
- [ ] Check for resource leaks (orphaned pods, PVCs)
- [ ] Review warmpool logic — race conditions on pod claiming?
- [ ] Check timeout handling — do long-running investigations get cleaned up?
- [ ] Review `sandbox_server.py` — what runs inside the sandbox?

### 2D. Skills & scripts
- [ ] Audit all 24 skills in `sre-agent/.claude/skills/`
- [ ] Check for dangerous operations (kubectl delete, scaling to 0, etc.) — are they gated?
- [ ] Review remediation actions — what safeguards exist?
- [ ] Check script execution environment — proper sandboxing?

---

## Phase 3: Core Logic Review — config-service

**Why**: This is the control plane. Bugs here affect every team's config, auth, and audit trail.

### 3A. Config hierarchy & merge logic
- [ ] Review hierarchical merge: org → team, dicts merge, lists replace
- [ ] Test edge cases: deep nesting, conflicting keys, null values
- [ ] Review `config_v2.py` (9 classes) — is the v2 API correct?
- [ ] Check `effective config` endpoint behavior

### 3B. Database & migrations
- [ ] Review SQLAlchemy models in `src/db/models.py` (32 classes!)
- [ ] Check Alembic migrations for correctness and reversibility
- [ ] Review encryption implementation (`src/crypto/`)
- [ ] Check for N+1 query patterns
- [ ] Review connection pooling config

### 3C. API routes (massive surface area)
- [ ] `routes/admin.py` (14 classes) — admin operations
- [ ] `routes/internal.py` (42 classes!) — internal API
- [ ] `routes/security.py` (15 classes) — security policies
- [ ] `routes/team.py` (25 classes) — team management
- [ ] Review all route auth decorators — are they consistent?

### 3D. Run existing tests
- [ ] Run the 13 test files in `config_service/tests/`
- [ ] Identify gaps in test coverage
- [ ] Check for tests that pass trivially (always-true assertions)

---

## Phase 4: Core Logic Review — slack-bot

**Why**: This is the primary user-facing surface. The 8000+ line `app.py` is the biggest single-file risk.

### 4A. `app.py` structural review
- [ ] Map the 8000+ line file: what are the major sections?
- [ ] Identify dead code within app.py
- [ ] Check error handling — do Slack API errors crash the bot?
- [ ] Review multi-workspace OAuth handling
- [ ] Check onboarding flow logic
- [ ] Review SSE streaming from sre-agent — reconnection? Backpressure?

### 4B. `modal_builder.py` (103KB)
- [ ] Review modal construction — correct Slack Block Kit usage?
- [ ] Check for XSS in user-supplied content rendered in modals
- [ ] Verify input validation for modal submissions

### 4C. Supporting modules
- [ ] `config_client.py` — correct config-service integration?
- [ ] `installation_store.py` — OAuth token storage
- [ ] `markdown_utils.py` — Slack mrkdwn conversion

### 4D. Run existing tests
- [ ] Run slack-bot tests (test_assets.py, test_blocks.py, snapshots)
- [ ] Check snapshot replay tests — are they up to date?

---

## Phase 5: Core Logic Review — web_ui

**Why**: Customer-facing admin console. Zero tests currently.

### 5A. API routes audit
- [ ] Review all ~70 API route files in `web_ui/src/app/api/`
- [ ] Check upstream proxy pattern (`_utils/upstream.ts`) — proper error handling?
- [ ] Verify auth is enforced on every route
- [ ] Check for SSRF via proxy routes
- [ ] Review SSE streaming in `team/agent/stream/route.ts`

### 5B. Auth & session management
- [ ] Review `src/auth.ts` — next-auth configuration
- [ ] Check session/login and session/logout routes
- [ ] Review OIDC callback handling
- [ ] Check cookie security (httpOnly, secure, sameSite)

### 5C. Frontend components
- [ ] Review `AgentRunnerModal` — the chat-like agent interaction
- [ ] Check `useAgentStream` hook (307 lines) — SSE client logic
- [ ] Review admin mode components — org tree, tokens, audit logs
- [ ] Check for client-side data exposure (sensitive data in JS bundles?)

### 5D. Build & config
- [ ] Review `next.config.ts` — security headers? CSP?
- [ ] Check `package.json` — the `tar@7.5.7` security override, why?
- [ ] Verify TypeScript strict mode settings

---

## Phase 6: Core Logic Review — orchestrator

**Why**: Webhook router that will become the single entry point for all surfaces.

### 6A. Webhook handling
- [ ] Review signature verification for each webhook type (Slack, GitHub, PagerDuty, Incident.io)
- [ ] Check for replay attack protection
- [ ] Review rate limiting
- [ ] Check error handling — do webhook failures get retried? Dead-lettered?

### 6B. Team provisioning
- [ ] Review auto-provisioning for MS Teams and Google Chat
- [ ] Check for race conditions in provisioning
- [ ] Review thread reply support

### 6C. Run existing tests
- [ ] Run orchestrator tests (e2e + unit)
- [ ] Review RBAC matrix test
- [ ] Check golden path test

---

## Phase 7: Core Logic Review — ultimate_rag

**Why**: Knowledge base for the agent. Zero tests currently.

### 7A. API server
- [ ] Review `api/server.py` (54 classes!) — that's a massive file
- [ ] Check auth and multi-tenancy in RAG queries
- [ ] Review document ingestion pipeline
- [ ] Check for data isolation between teams

### 7B. Retrieval & reranking
- [ ] Review retrieval strategies (9 strategy classes)
- [ ] Check reranker implementation (7 classes)
- [ ] Verify embedding model configuration
- [ ] Review RAPTOR tree building logic

---

## Phase 8: Infrastructure & Deployment Review

### 8A. Helm chart
- [ ] Review all 27 templates in `charts/incidentfox/templates/`
- [ ] Check values.yaml defaults for security
- [ ] Compare staging vs production values — are there gaps?
- [ ] Validate pilot/customer template completeness
- [ ] Run `helm template` to check for rendering errors
- [ ] Check resource requests/limits for all pods

### 8B. CI/CD workflows
- [ ] Review all 12 GitHub Actions workflows
- [ ] Check for missing CI steps (no type checking, no integration tests in CI?)
- [ ] Review deploy-eks.yml — proper staging→prod promotion?
- [ ] Check secret handling in CI
- [ ] Review Trivy and gitleaks configs — what are they ignoring?

### 8C. Docker Compose (local dev)
- [ ] Test `make dev` — does it actually work?
- [ ] Verify root docker-compose.yml matches production architecture
- [ ] Check for port conflicts, volume mount issues

### 8D. Terraform
- [ ] Review `infra/terraform/` for each environment
- [ ] Check IAM policies — least privilege?
- [ ] Review VPC, security groups, NACLs
- [ ] Check EKS cluster config

---

## Phase 9: Documentation & Developer Experience

### 9A. Accuracy audit
- [ ] Compare CLAUDE.md architecture description with actual code — are they in sync?
- [ ] Review README.md — does getting started actually work?
- [ ] Check docs/ accuracy against current implementation
- [ ] Review CONTRIBUTING.md — does the development workflow work?
- [ ] Check all service READMEs for accuracy

### 9B. Missing documentation
- [ ] API documentation (OpenAPI specs for each service?)
- [ ] Runbook for common operational issues
- [ ] Incident response procedures
- [ ] Architecture decision records (ADRs)

### 9C. Code quality standards
- [ ] Review `ruff.toml` — it ignores bare excepts (E722), unused imports (F401), undefined names (F821). These should be fixed, not ignored.
- [ ] Add mypy or pyright to CI for type checking
- [ ] Add ESLint strict rules for web_ui
- [ ] Consider adding pre-commit hooks

---

## Phase 10: Testing & E2E Validation

### 10A. Local stack E2E
- [ ] Run `make dev` and verify all services start
- [ ] Create a test investigation via sre-agent API
- [ ] Verify config-service CRUD operations
- [ ] Test web_ui login and agent runner
- [ ] Test Slack integration if tokens available (`make dev-slack`)

### 10B. Write missing tests
- [ ] web_ui: at minimum, API route tests
- [ ] ultimate_rag: API and retrieval tests
- [ ] sre-agent: sandbox lifecycle tests
- [ ] Integration tests: config-service → sre-agent flow

### 10C. Load & stress testing
- [ ] Review existing `local/test_stress_e2e.py`
- [ ] Test concurrent investigations
- [ ] Test sandbox warmpool under load
- [ ] Test config-service with many teams

---

## Execution Strategy

### How to parallelize across Conductor workspaces

Each phase can be a separate workspace. Some can run in parallel:

| Wave | Phases | Can run in parallel? | Estimated effort |
|------|--------|---------------------|-----------------|
| **Wave 0** | Phase -1 (harvest & port from deprecated) | 12+ workspaces in parallel per tool | 1-3 sessions per tool |
| **Wave 1** | Phase 0 (dead code removal) | Solo — after porting done | 1 session |
| **Wave 2** | Phase 1 (security) | Solo — highest priority | 2-3 sessions |
| **Wave 3** | Phases 2, 3, 4, 5, 6, 7 (service reviews) | All 6 in parallel | 1-2 sessions each |
| **Wave 4** | Phase 8 (infra), Phase 9 (docs) | In parallel | 1 session each |
| **Wave 5** | Phase 10 (E2E testing) | After all reviews | 1-2 sessions |

### Output per phase

Each review phase should produce:
1. **Findings doc** (`.context/findings/phase-N-findings.md`) — bugs, issues, concerns with severity ratings
2. **Fix PRs** — actual code fixes for critical/high issues found
3. **Recommendations** — medium/low issues to address later

### Severity ratings
- **P0 (Critical)**: Security vulnerability, data leak, customer-facing bug
- **P1 (High)**: Logic error, race condition, reliability issue
- **P2 (Medium)**: Code quality, maintainability, tech debt
- **P3 (Low)**: Style, documentation, minor improvements

---

## Key Risks Identified During Recon

These are the areas I'm most concerned about based on initial exploration:

1. **slack-bot/app.py at 8000+ lines** — high probability of bugs hiding in a monolith
2. **ultimate_rag/api/server.py with 54 classes** — AI-generated god file, likely has issues
3. **config_service/src/api/routes/internal.py with 42 classes** — same concern
4. **Zero tests for web_ui and ultimate_rag** — these are customer-facing
5. **Ruff config ignores critical linting rules** — bare excepts, undefined names, unused vars
6. **Sandbox security** — the 1700-line sandbox_manager.py controls isolation for customer clusters
7. **Multi-tenant isolation** — one config-service DB serves all customers
8. **16 Dockerfiles with inconsistent patterns** — some run as root, some don't
9. **Duplicate K8s manifests** — both in service `k8s/` dirs and Helm templates
10. **No type checking in CI** — mypy/pyright not enforced

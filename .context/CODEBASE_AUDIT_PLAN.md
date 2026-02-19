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

## Phase 1: Security Audit (Critical Path) ✅ COMPLETE

**Why**: This runs in customer environments with access to their K8s clusters, cloud accounts, and secrets. A security bug here is an existential risk.

**Results**: 28 findings across P0-P2. All P0/P1 fixed. P2 fixed. See `.context/findings/phase-1-security-findings.md`.
**PRs**: #430 (longyi-07/p0-security-fixes)

### 1A. Secrets & credential handling ✅
- [x] Audit credential-proxy (Envoy + credential-resolver): verify sandboxes truly never see plaintext secrets
- [x] Review JWT auth flow: `sre-agent/credential-proxy/src/credential_resolver/jwt_auth.py`
- [x] Check for hardcoded secrets, API keys, or tokens in code (not just .env files)
- [x] Review `.env.example` — does it accidentally contain real values?
- [x] Audit ExternalSecrets → K8s Secrets flow in Helm chart
- [x] Review all `values.staging.yaml` / `values.prod.yaml` for leaked secrets
- [x] Check gitleaks config (`.gitleaks.toml`) and history for any past leaks
- **Fixed**: Hardcoded JWT default (P1-7), staging/prod secret separation (P1-11), Datadog key prefix in logs (P2-19), subscription status in logs (P2-20)

### 1B. Sandbox security (gVisor) ✅
- [x] Review `sre-agent/sandbox_manager.py` (1700 lines) — this controls isolation
- [x] Verify gVisor runtime is enforced, not optional
- [x] Check sandbox pod specs for privilege escalation vectors (hostNetwork, hostPID, capabilities)
- [x] Review `sre-agent/k8s/sandbox-template.yaml` and warmpool variants
- [x] Verify network policies in `credential-proxy/k8s/networkpolicy.yaml`
- [x] Check if sandbox pods can reach the internet directly (should go through credential-proxy)
- **Fixed**: /investigate auth (P0-1), admin route scoping (P0-2), direct secret mounts removed (P0-3), NetworkPolicy for egress (P0-4), gVisor mandatory (P0-5), warm pool claim auth (P1-8), claim race condition (P1-9), ConfigMap RBAC scoping (P1-13), immutable ConfigMaps (P2-28)

### 1C. Auth & multi-tenancy ✅
- [x] Audit tenant isolation in config-service: can tenant A see tenant B's data?
- [x] Review token hashing and auth in `config_service/src/api/routes/`
- [x] Check RBAC implementation in config-service
- [x] Review web_ui auth flow (next-auth, bearer tokens, OIDC)
- [x] Audit `web_ui/src/app/api/_utils/upstream.ts` — this proxies to backend services
- [x] Check for IDOR vulnerabilities in API routes (org/team ID validation)
- **Fixed**: Visitor write access check (P1-10)

### 1D. Input validation & injection ✅
- [x] Review all FastAPI endpoints for input validation (Pydantic models?)
- [x] Check for SQL injection in config-service (SQLAlchemy usage, raw queries?)
- [x] Look for command injection in sre-agent scripts
- [x] Review Slack input handling in `slack-bot/app.py` (8000+ lines)
- [x] Check webhook signature verification in orchestrator (`webhooks/signatures.py`)
- **Fixed**: kubectl arg validation (P1-14), path traversal in file extraction (P1-15), SSRF on file proxy (P2-21), flagd kubectl validation (P2-26), docker subcommand whitelist (P2-27)

### 1E. Docker & infrastructure security ✅
- [x] Audit all 16 Dockerfiles for best practices (non-root, minimal images, pinned versions)
- [x] Review orchestrator Dockerfile CVE patching hack (setuptools vendor workaround)
- [x] Check `.dockerignore` files exist and exclude sensitive files
- [x] Review Terraform configs in `infra/` for security best practices
- [x] Audit Karpenter NodePool config for over-permissive instance types
- [x] Review IRSA (IAM Roles for Service Accounts) in Helm chart
- **Fixed**: Non-root USER in 4 Dockerfiles (P2-16), .dockerignore for 5 services (P2-18), floating image tags pinned (P1-12)

---

## Phase 2: Core Logic Review — sre-agent ✅ COMPLETE

**Why**: This is the brain of the product. Bugs here mean wrong answers for customers during incidents.

**Results**: 38 findings (9 P0, 13 P1, 20 P2, 12 P3). 31 fixed, 7 deferred. See `.context/findings/phase-2-sre-agent-findings.md`.

### 2A. Agent core (`sre-agent/agent.py`) ✅
- [x] Read and understand the full agent loop
- [x] Review Claude SDK usage — correct API patterns? Error handling?
- [x] Check skill loading mechanism — race conditions? Memory leaks on long runs?
- [x] Review subagent spawning logic
- [x] Verify streaming (SSE) is robust — what happens on disconnect?
- [x] Check for prompt injection vulnerabilities in skill content
- **Fixed**: Path traversal (P0), error message sanitization (P0), concurrency guard (P1), cleanup unification (P1), log cleanup (P2)

### 2B. Server & API (`sre-agent/server.py`, `server_simple.py`) ✅
- [x] Review FastAPI routes — correct auth? Rate limiting?
- [x] Check file proxy server (used by Slack for file sharing)
- [x] Review SSE streaming implementation
- [x] Check error handling — do errors leak internal details?
- [x] Review health check endpoints
- **Fixed**: SSRF redirect following (P1), sessions cleanup (P1), Content-Disposition sanitization (P2), input size limits (P2)

### 2C. Sandbox lifecycle (`sre-agent/sandbox_manager.py`) ✅
- [x] Review pod creation, lifecycle, and cleanup
- [x] Check for resource leaks (orphaned pods, PVCs)
- [x] Review warmpool logic — race conditions on pod claiming?
- [x] Check timeout handling — do long-running investigations get cleaned up?
- [x] Review `sandbox_server.py` — what runs inside the sandbox?
- **Fixed**: SANDBOX_JWT env var removal (P0), immutable ConfigMaps (P2-28 from Phase 1)

### 2D. Skills & scripts ✅
- [x] Audit all 45 skills in `sre-agent/.claude/skills/`
- [x] Check for dangerous operations (kubectl delete, scaling to 0, etc.) — are they gated?
- [x] Review remediation actions — what safeguards exist?
- [x] Check script execution environment — proper sandboxing?
- **Fixed**: SQL injection in PostgreSQL/MySQL (P0), dead container_exec.py removed (P0), SA token CLI exposure (P0), RFC 1123 validation (P1), scale-to-zero gate (P1), TLS verify configurable (P1), Docker destructive ops blocked (P2), URL injection (P2), env var redaction expanded (P2)

---

## Phase 3: Core Logic Review — config-service ✅ COMPLETE

**Why**: This is the control plane. Bugs here affect every team's config, auth, and audit trail.

**Results**: 10 findings (1 P0, 2 P1, 4 P2, 3 P3). 3 fixed, 7 deferred. See `.context/findings/phase-3-config-service-findings.md`.

### 3A. Config hierarchy & merge logic ✅
- [x] Review hierarchical merge: org → team, dicts merge, lists replace
- [x] Test edge cases: deep nesting, conflicting keys, null values
- [x] Review `config_v2.py` (9 classes) — is the v2 API correct?
- [x] Check `effective config` endpoint behavior
- **Fixed**: Removed debug logging from config_v2.py (P2)

### 3B. Database & migrations ✅
- [x] Review SQLAlchemy models in `src/db/models.py` (32 classes!)
- [x] Check Alembic migrations for correctness and reversibility
- [x] Review encryption implementation (`src/crypto/`)
- [x] Check for N+1 query patterns
- [x] Review connection pooling config
- **Fixed**: Token expiration timezone handling (P0)

### 3C. API routes (massive surface area) ✅
- [x] `routes/admin.py` (14 classes) — admin operations
- [x] `routes/internal.py` (42 classes!) — internal API
- [x] `routes/security.py` (15 classes) — security policies
- [x] `routes/team.py` (25 classes) — team management
- [x] Review all route auth decorators — are they consistent?
- **Fixed**: Internal service authentication with shared secret (P1)

### 3D. Run existing tests
- [ ] Run the 13 test files in `config_service/tests/`
- [ ] Identify gaps in test coverage
- [ ] Check for tests that pass trivially (always-true assertions)

---

## Phase 4: Core Logic Review — slack-bot ✅ COMPLETE

**Status**: Audited — 12 findings (3 P0, 4 P1, 3 P2, 2 P3), all deferred. Findings require architectural changes (Redis state store, SSE backpressure) beyond audit scope.

See `.context/findings/phase-4-slack-bot-findings.md` for details.

---

## Phase 5: Core Logic Review — web_ui ✅ COMPLETE

**Status**: Audited — 13 findings (3 P0, 5 P1, 5 P2), 5 fixed, 8 deferred.

**Fixed**: XSS via dangerouslySetInnerHTML (P0), OIDC state validation CSRF (P0), missing auth on topology/nodes (P1), missing auth on integrations/schemas (P1), security headers in next.config (P2).

See `.context/findings/phase-5-web-ui-findings.md` for details.

---

## Phase 6: Core Logic Review — orchestrator ✅ COMPLETE

**Status**: Audited — 17 findings (0 P0, 4 P1, 6 P2, 7 P3), 4 P1 fixed, 13 deferred.

**Fixed**: SSRF URL scheme validation (P1), blocking event loop in PagerDuty/Blameless/FireHydrant handlers via asyncio.to_thread (P1 x3).

See `.context/findings/phase-6-orchestrator-findings.md` for details.

---

## Phase 7: Core Logic Review — ultimate_rag ✅ COMPLETE

**Status**: Audited — 25 findings (3 P0, 9 P1, 8 P2, 5 P3). 3 P0 fixed, 22 deferred.

**Fixed**: API key auth middleware (P0), restricted pickle unpickler for all deserialization (P0), path traversal in file ingestion (P0).

See `.context/findings/phase-7-ultimate-rag-findings.md` for details.

### 7A. API server ✅
- [x] Review `api/server.py` (54 classes!) — that's a massive file
- [x] Check auth and multi-tenancy in RAG queries
- [x] Review document ingestion pipeline
- [x] Check for data isolation between teams

### 7B. Retrieval & reranking ✅
- [x] Review retrieval strategies (9 strategy classes)
- [x] Check reranker implementation (7 classes)
- [x] Verify embedding model configuration
- [x] Review RAPTOR tree building logic

---

## Phase 8: Infrastructure & Deployment Review ✅ COMPLETE

**Status**: Audited — 33 findings (9 P0, 7 P1, 11 P2, 6 P3). 6 P0 fixed (securityContext), 27 deferred.

**Fixed**: SecurityContext added to 6 deployment templates (config-service, slack-bot, orchestrator, web-ui, ultimate-rag, k8s-gateway).

See `.context/findings/phase-8-infrastructure-findings.md` for details.

### 8A. Helm chart ✅
- [x] Review all 27 templates in `charts/incidentfox/templates/`
- [x] Check values.yaml defaults for security
- [x] Compare staging vs production values — are there gaps?
- [x] Validate pilot/customer template completeness
- [x] Check resource requests/limits for all pods

### 8B. CI/CD workflows ✅
- [x] Review all 12 GitHub Actions workflows
- [x] Check for missing CI steps (no type checking, no integration tests in CI?)
- [x] Review deploy-eks.yml — proper staging→prod promotion?
- [x] Check secret handling in CI
- [x] Review Trivy and gitleaks configs — what are they ignoring?

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

## Phase 9: Documentation & Developer Experience ✅ COMPLETE

Audited CLAUDE.md accuracy and ruff.toml lint suppressions. Found 3 real runtime bugs hidden by F821 suppression (missing import, wrong uuid reference, stale model name) — all fixed. Updated CLAUDE.md with 5 corrections. Documented 6 deferred recommendations for lint rule re-enablement. See `.context/findings/phase-9-documentation-findings.md`.

### 9A. Accuracy audit ✅
- [x] CLAUDE.md: Fixed 5 inaccuracies (orchestrator path, webhook list, skill count, output handlers, security audit status)
- [ ] README.md, CONTRIBUTING.md, service READMEs — deferred (docs accuracy, lower priority)

### 9B. Missing documentation — deferred
- OpenAPI specs, runbooks, ADRs, security architecture doc — all deferred to post-audit work

### 9C. Code quality standards ✅
- [x] ruff.toml audit: Found 315 suppressed violations. 3 were real P1 runtime bugs (fixed). Documented recommendations to re-enable F821, E722, F401.
- [ ] mypy/pyright, ESLint strict, pre-commit hooks — deferred

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

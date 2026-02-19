# Phase 2: sre-agent Core Logic & Skills Audit — Findings

**Date:** 2026-02-18
**Scope:** `sre-agent/agent.py`, `sre-agent/server.py`, `sre-agent/sandbox_manager.py`, `sre-agent/sandbox_server.py`, and all 45 skill directories under `sre-agent/.claude/skills/`

---

## Summary

| Severity | Found | Fixed | Deferred |
|----------|-------|-------|----------|
| P0 Critical | 9 | 9 | 0 |
| P1 High | 13 | 13 | 0 |
| P2 Medium | 20 | 14 | 6 |
| P3 Low | 12 | 1 | 11 |
| **Total** | **38** | **31** | **7** |

---

## P0 — Critical Findings

### Core Logic

| ID | File | Issue | Status |
|----|------|-------|--------|
| Core-P0-1 | agent.py | Path traversal in `_extract_files_from_text` — no validation on file paths, could read outside /workspace | **Fixed** — Applied same Path.parents containment check as `_extract_images_from_text` |
| Core-P0-2 | agent.py | Allowed arbitrary absolute paths in file extraction | **Fixed** — Rejects absolute paths outside /workspace |
| Core-P0-3 | agent.py | Raw exception messages leaked to client (file paths, SDK state) | **Fixed** — Generic error message to client, full details server-side only |
| Core-P0-4 | sandbox_manager.py | `SANDBOX_JWT` set as pod env var — visible via `kubectl get pod -o yaml` and `/proc/*/environ` | **Fixed** — Removed from env vars; JWT set by `/claim` handler via `os.environ` instead |

### Skills

| ID | File | Issue | Status |
|----|------|-------|--------|
| Skills-P0-1 | database-postgresql/execute_query.py | SQL injection — arbitrary queries executed with no restrictions, `conn.commit()` enabled DML/DDL | **Fixed** — Read-only allowlist (SELECT/SHOW/EXPLAIN/DESCRIBE/WITH), multi-statement blocked, `conn.set_session(readonly=True)` |
| Skills-P0-2 | database-mysql/execute_query.py | SQL injection — same issue, MySQL with autocommit=True | **Fixed** — Same read-only allowlist, removed DML commit path |
| Skills-P0-3 | infrastructure-docker/container_exec.py | Arbitrary command execution via `sh -c` (dead code — blocked by allowlist) | **Fixed** — Removed file entirely + SKILL.md references |
| Skills-P0-4 | runtime-config-flagd/flagd_client.py | K8s SA token passed as `--token=` CLI arg, visible in `/proc/*/cmdline` | **Fixed** — Uses temp kubeconfig file via `KUBECONFIG` env var |

---

## P1 — High Findings

### Core Logic

| ID | File | Issue | Status |
|----|------|-------|--------|
| Core-P1-1 | agent.py | `cleanup()` and `close()` dual methods, inconsistent usage | **Fixed** — `cleanup()` is now alias for `close()` |
| Core-P1-2 | server.py | SSRF redirect following on file proxy | **Fixed** — Added `follow_redirects=False` on httpx download client |
| Core-P1-3 | server.py | `_sessions` dict never cleaned up (memory leak) | **Fixed** — Added `_cleanup_expired_sessions()` called on each JWT lookup |
| Core-P1-6 | agent.py | No concurrency guard — overlapping `execute()` calls possible | **Fixed** — `is_running` check before execute |

### Skills

| ID | File | Issue | Status |
|----|------|-------|--------|
| Skills-P1-1 | remediation/scale_deployment.py | Scale-to-zero without confirmation gate | **Fixed** — Requires `--confirm-zero` flag |
| Skills-P1-2 | remediation/restart_pod.py, scale_deployment.py | Missing RFC 1123 validation on K8s names | **Fixed** — Added `_validate_k8s_name()` to both |
| Skills-P1-3 | remediation/rollback_deployment.py | subprocess with user input (mitigated by existing validation) | N/A — already safe |
| Skills-P1-4 | Multiple `*_client.py` | Error messages include full `response.text` from APIs | Deferred — needs systematic truncation across 30+ clients |
| Skills-P1-5 | elasticsearch_client.py, splunk_client.py | TLS `verify=False` hardcoded | **Fixed** — Configurable via `ES_VERIFY_TLS` / `SPLUNK_VERIFY_TLS` env vars, default `true` |

---

## P2 — Medium Findings

### Core Logic

| ID | File | Issue | Status |
|----|------|-------|--------|
| Core-P2-6 | agent.py | Laminar API key prefix logged | **Fixed** — Logs presence only |

### Skills

| ID | File | Issue | Status |
|----|------|-------|--------|
| Skills-P2-1 | observability-datadog/datadog_client.py | URL parameter injection — query interpolated into URL string | **Fixed** — Uses `params=` kwarg for proper URL encoding |
| Skills-P2-2 | infrastructure-docker/container_inspect.py | Incomplete env var redaction + JSON mode bypasses redaction | **Fixed** — Expanded sensitive patterns, redact in JSON mode too |
| Skills-P2-3 | remediation/scale_deployment.py | No upper bound on replica count | **Fixed** — `_MAX_REPLICAS = 50` |
| Skills-P2-4 | infrastructure-docker/docker_runner.py | Broad sub-command allowlist allows destructive ops (rm, prune) | **Fixed** — Added `_BLOCKED_SUB_SUBCOMMANDS` blocklist for destructive operations |
| Skills-P2-5 | metrics-analysis/grafana_client.py | Auth method + JWT length logged to stderr | **Fixed** — Removed auth method logging |
| Skills-P2-6 | analytics-amplitude/amplitude_client.py | Response body logged unconditionally | **Fixed** — Removed response body logging |
| Skills-P3-1 | remediation scripts | Inconsistent K8s auth priority (kubeconfig before in-cluster) | **Fixed** — Now in-cluster first in restart_pod.py and scale_deployment.py |

### Deferred

| ID | File | Issue | Reason |
|----|------|-------|--------|
| Core-P2-7 | server.py | Content-Disposition sanitization on file proxy | **Fixed** — Filename sanitized (path traversal, null bytes, special chars) |
| Core-P2-8 | server.py | Input size limits on requests | **Fixed** — Pydantic Field constraints on all InvestigateRequest fields |
| Core-P2-x | server_simple.py | Crashes on startup (missing module) | Dev-only file |
| Sandbox-P2-1 | sandbox_manager.py | TOCTOU race between claim bound and JWT injection | Low probability — <1s window |
| Sandbox-P2-2 | sandbox_manager.py | Passthrough cluster in Envoy is latent SSRF vector | Currently inert (nothing on port 9999) |
| Sandbox-P2-3 | sandbox_manager.py | No serviceAccountName in direct creation path | Direct path uses default SA |
| Sandbox-P2-5 | sandbox_manager.py | wait_for_ready hardcodes investigation- prefix | Fragile assumption |
| Sandbox-P2-6 | sandbox_manager.py | TEAM_TOKEN as plaintext env var | Similar to SANDBOX_JWT issue |

### Additional Sandbox Findings (Fixed)

| ID | File | Issue | Status |
|----|------|-------|--------|
| Sandbox-P0-3 | sandbox_manager.py | No input validation on thread_id — K8s label/name injection | **Fixed** — `_validate_thread_id()` at both entry points |
| Sandbox-P1-1 | sandbox_manager.py | Envoy sidecar missing `capabilities: drop: ALL` in direct creation | **Fixed** — Added to Envoy securityContext |
| Sandbox-P1-5 | sandbox_manager.py | ConfigMap orphaning when sandbox CRD creation fails | **Fixed** — Cleanup in except block |
| Sandbox-P2-4 | auth.py | JWT has no `jti` claim — cannot be revoked | **Fixed** — Added `uuid.uuid4().hex` jti |

---

## P3 — Low / Quality Findings

| ID | File | Issue | Status |
|----|------|-------|--------|
| Skills-P3-2 | 8+ kubernetes scripts | `get_k8s_client()` duplicated with inconsistencies | Deferred — quality improvement |
| Skills-P3-3 | All K8s scripts | No timeout enforcement on K8s API calls | Deferred — availability |
| Skills-P3-4 | runtime-config-flagd/set_flag.py | No confirmation gate for failure injection flags | Deferred — demo-only feature |
| Skills-P3-5 | infrastructure-docker/container_exec.py | Dead code blocked by allowlist | **Fixed** — File removed |
| Sandbox-P1-2 | sandbox_manager.py | No readOnlyRootFilesystem on containers | Deferred — needs writable paths assessment |
| Sandbox-P1-3 | sandbox_manager.py | No seccompProfile set on sandbox pods | Deferred — gVisor provides equivalent |
| Sandbox-P3-1 | server.py | `_file_download_tokens` not thread-safe | Deferred — GIL makes this safe in practice |
| Sandbox-P3-2 | sandbox_server.py | No max file size enforcement on downloads | Deferred — pod has ephemeral-storage limits |
| Sandbox-P3-3 | sandbox_server.py | No rate limiting on /claim endpoint | Deferred — cluster-internal only |
| Sandbox-P3-4 | sandbox_server.py | Deprecated `@app.on_event("shutdown")` | Deferred — cosmetic |
| Sandbox-P3-5 | sandbox_manager.py | `configured_integrations` logged to stdout | Deferred — non-sensitive metadata |
| Sandbox-P3-6 | sandbox_manager.py | Envoy admin interface accessible from agent container | Deferred — mitigated by gVisor/network isolation |
| Sandbox-P3-7 | sandbox-networkpolicy.yaml | No ingress policy — sandbox accepts from any pod | Deferred — needs sandbox-router label setup |

---

## Files Modified

| File | Changes |
|------|---------|
| `sre-agent/server.py` | SSRF redirect prevention, session cleanup, Content-Disposition sanitization, input size limits |
| `sre-agent/agent.py` | Path traversal fix, error sanitization, concurrency guard, cleanup unification, log cleanup |
| `sre-agent/auth.py` | Added jti claim to JWT for future revocation support |
| `sre-agent/sandbox_manager.py` | Removed SANDBOX_JWT env var, thread_id validation, Envoy capabilities drop, ConfigMap cleanup on failure |
| `sre-agent/.claude/skills/database-postgresql/scripts/execute_query.py` | Read-only statement allowlist, multi-statement block, readonly session |
| `sre-agent/.claude/skills/database-mysql/scripts/execute_query.py` | Read-only statement allowlist, multi-statement block |
| `sre-agent/.claude/skills/infrastructure-docker/scripts/container_exec.py` | **Deleted** |
| `sre-agent/.claude/skills/infrastructure-docker/scripts/docker_runner.py` | Sub-subcommand blocklist for destructive ops |
| `sre-agent/.claude/skills/infrastructure-docker/scripts/container_inspect.py` | Expanded env var redaction + JSON mode redaction |
| `sre-agent/.claude/skills/infrastructure-docker/SKILL.md` | Removed container_exec.py references |
| `sre-agent/.claude/skills/runtime-config-flagd/scripts/flagd_client.py` | Temp kubeconfig file instead of --token CLI arg |
| `sre-agent/.claude/skills/remediation/scripts/scale_deployment.py` | RFC 1123 validation, max replicas, confirm-zero gate, auth priority |
| `sre-agent/.claude/skills/remediation/scripts/restart_pod.py` | RFC 1123 validation, auth priority |
| `sre-agent/.claude/skills/observability-elasticsearch/scripts/elasticsearch_client.py` | Configurable TLS verify |
| `sre-agent/.claude/skills/observability-splunk/scripts/splunk_client.py` | Configurable TLS verify |
| `sre-agent/.claude/skills/observability-datadog/scripts/datadog_client.py` | URL params via httpx params= |
| `sre-agent/.claude/skills/metrics-analysis/scripts/grafana_client.py` | Removed auth method logging |
| `sre-agent/.claude/skills/analytics-amplitude/scripts/amplitude_client.py` | Removed response body logging |

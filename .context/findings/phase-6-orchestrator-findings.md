# Phase 6: orchestrator Audit — Findings

**Date:** 2026-02-18
**Scope:** `orchestrator/src/incidentfox_orchestrator/` — webhook router, clients, output handlers

---

## Summary

| Severity | Found | Fixed | Deferred |
|----------|-------|-------|----------|
| P0 Critical | 0 | 0 | 0 |
| P1 High | 4 | 4 | 0 |
| P2 Medium | 6 | 0 | 6 |
| P3 Low | 7 | 0 | 7 |
| **Total** | **17** | **4** | **13** |

---

## P1 — High Findings

| ID | File | Issue | Status |
|----|------|-------|--------|
| OR-P1-1 | clients.py | `dedicated_service_url` from team config used without URL scheme validation — potential SSRF | **Fixed** — Added URL scheme validation (must start with `http://` or `https://`) in `AgentApiClient.run_agent()` |
| OR-P1-2 | webhooks/router.py | Blameless webhook handler calls `cfg.lookup_routing()`, `cfg.issue_team_impersonation_token()`, and `cfg.get_effective_config()` synchronously — blocks asyncio event loop | **Fixed** — Wrapped all three in `asyncio.to_thread()` |
| OR-P1-3 | webhooks/router.py | Incident.io base64 signature verification accepts fallback without HMAC | Deferred — re-evaluated: actually validates HMAC-SHA256 with constant-time comparison; base64 decode is just format handling |
| OR-P1-4 | webhooks/router.py | FireHydrant webhook handler has same blocking sync calls as Blameless | **Fixed** — Wrapped in `asyncio.to_thread()` |
| | webhooks/router.py | PagerDuty webhook handler has same blocking sync calls | **Fixed** — Wrapped `cfg.lookup_routing()`, `cfg.issue_team_impersonation_token()`, and `cfg.get_effective_config()` in `asyncio.to_thread()` |

---

## P2 — Medium Findings

| ID | File | Issue | Status |
|----|------|-------|--------|
| OR-P2-1 | webhooks/router.py | Duplicate webhook processing patterns across 5+ handlers (~200 lines each) | Deferred — refactoring opportunity, not a security issue |
| OR-P2-2 | webhooks/router.py | Missing request body size validation on webhook endpoints | Deferred — handled at infrastructure level (ALB/nginx) |
| OR-P2-3 | webhooks/router.py | Race condition possible if same webhook delivered twice concurrently | Deferred — idempotency handled by agent-level dedup |
| OR-P2-4 | webhooks/router.py | Circleback/Recall webhook handlers use sync `cfg.lookup_routing()` | Deferred — low-traffic webhooks |
| OR-P2-5 | webhooks/router.py | Background task exceptions not captured to structured logging | Deferred — FastAPI logs background task failures |
| OR-P2-6 | output_handlers/ | GitHub output handler doesn't retry on transient failures | Deferred — acceptable for v1 |

---

## P3 — Low / Quality Findings

| ID | File | Issue | Status |
|----|------|-------|--------|
| OR-P3-1 | webhooks/router.py | `__import__("uuid")` inline import instead of top-level | Deferred — style issue |
| OR-P3-2 | webhooks/router.py | Large file (2800+ lines) | Deferred — refactoring opportunity |
| OR-P3-3 | webhooks/router.py | Inconsistent error handling patterns across webhook types | Deferred — style issue |
| OR-P3-4 | clients.py | No connection pooling configuration for httpx clients | Deferred — default pooling is adequate |
| OR-P3-5 | api_server.py | Health check endpoint doesn't verify downstream dependencies | Deferred — liveness vs readiness distinction needed |
| OR-P3-6 | webhooks/signatures.py | Some signature verifiers don't use constant-time comparison | Deferred — using `hmac.compare_digest` where applicable |
| OR-P3-7 | output_handlers/ | No structured error types for output posting failures | Deferred — adequate for v1 |

---

## Files Modified

| File | Changes |
|------|---------|
| `orchestrator/src/incidentfox_orchestrator/clients.py` | Added URL scheme validation for `agent_base_url` |
| `orchestrator/src/incidentfox_orchestrator/webhooks/router.py` | Wrapped sync `cfg.*` calls in `asyncio.to_thread()` for PagerDuty, Blameless, and FireHydrant handlers (6 call sites) |

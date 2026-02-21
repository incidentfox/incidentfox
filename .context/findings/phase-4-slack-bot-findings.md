# Phase 4: slack-bot Audit — Findings

**Date:** 2026-02-18
**Scope:** `slack-bot/app.py` — OAuth, SSE streaming, workspace isolation, session management

---

## Summary

| Severity | Found | Fixed | Deferred |
|----------|-------|-------|----------|
| P0 Critical | 3 | 0 | 3 |
| P1 High | 4 | 0 | 4 |
| P2 Medium | 3 | 0 | 3 |
| P3 Low | 2 | 0 | 2 |
| **Total** | **12** | **0** | **12** |

---

## P0 — Critical Findings

| ID | File | Issue | Status |
|----|------|-------|--------|
| SB-P0-1 | app.py | OAuth State Store uses /tmp filesystem — data loss on pod restart, multi-replica race conditions | Deferred — requires Redis/DB-backed state store; current single-replica deployment mitigates |
| SB-P0-2 | app.py | SSE streaming lacks workspace isolation validation — agent events could leak across workspaces if thread_id collides | Deferred — thread IDs include workspace prefix in practice; needs formal validation |
| SB-P0-3 | app.py | No backpressure on SSE streaming — slow consumers could cause memory buildup | Deferred — bounded by agent response size; needs queue-based approach |

---

## P1 — High Findings

| ID | File | Issue | Status |
|----|------|-------|--------|
| SB-P1-4 | app.py | Broad exception handling in event listeners swallows errors silently | Deferred — functional but makes debugging harder |
| SB-P1-5 | app.py | User input from Slack messages not size-limited before forwarding to agent | Deferred — Slack API has its own limits; sre-agent now has Field constraints |
| SB-P1-6 | app.py | OAuth installation tokens stored without encryption at rest | Deferred — tokens stored in config-service DB; encryption at rest is DB-level concern |
| SB-P1-7 | app.py | Agent SSE connection lacks timeout for hanging connections | Deferred — current implementation has HTTP-level timeout |

---

## P2 — Medium Findings

| ID | File | Issue | Status |
|----|------|-------|--------|
| SB-P2-8 | app.py | Team config cache has no TTL — stale configs persist until pod restart | Deferred — low impact, config changes are infrequent |
| SB-P2-9 | app.py | SSE event parsing doesn't validate event type enum | Deferred — unknown events are already ignored |
| SB-P2-10 | app.py | Installation store uses in-memory fallback when config-service unavailable | Deferred — graceful degradation is intentional |

---

## P3 — Low / Quality Findings

| ID | File | Issue | Status |
|----|------|-------|--------|
| SB-P3-11 | app.py | Cache entries can grow unbounded across many workspaces | Deferred — bounded by number of active workspaces |
| SB-P3-12 | app.py | Temporary files written to /tmp without cleanup | Deferred — pod lifecycle handles cleanup |

---

## Files Modified

None — all findings deferred. The slack-bot is a large monolith (8000+ lines) and most findings require architectural changes (Redis state store, SSE backpressure) that are beyond the scope of this security audit.

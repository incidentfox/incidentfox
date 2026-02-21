# Phase 3: config-service Audit — Findings

**Date:** 2026-02-18
**Scope:** `config_service/src/` — API routes, models, auth, crypto, config merge

---

## Summary

| Severity | Found | Fixed | Deferred |
|----------|-------|-------|----------|
| P0 Critical | 1 | 1 | 0 |
| P1 High | 2 | 1 | 1 |
| P2 Medium | 4 | 1 | 3 |
| P3 Low | 3 | 0 | 3 |
| **Total** | **10** | **3** | **7** |

---

## P0 — Critical Findings

| ID | File | Issue | Status |
|----|------|-------|--------|
| CS-P0-1 | src/db/models.py | Token `is_expired()` uses naive `datetime.utcnow()` compared against potentially tz-aware `expires_at` — could allow expired tokens through | **Fixed** — Uses `datetime.now(timezone.utc)` with safe tz normalization |

---

## P1 — High Findings

| ID | File | Issue | Status |
|----|------|-------|--------|
| CS-P1-1 | src/api/routes/internal.py | Internal service auth accepts ANY header value — no secret verification | **Fixed** — Added `INTERNAL_SERVICE_SECRET` env var with `secrets.compare_digest()` |
| CS-P1-2 | src/core/impersonation.py | `extract_visitor_session_id()` decodes JWT without signature verification | Deferred — intentional for heartbeat pre-auth; full verification in request handler |

---

## P2 — Medium Findings

| ID | File | Issue | Status |
|----|------|-------|--------|
| CS-P2-1 | src/api/routes/config_v2.py | Debug logging with emoji markers left in production code | **Fixed** — Removed all `🔍 DEBUG` logger.info calls |
| CS-P2-2 | src/api/routes/config_v2.py | TODO comments for missing permission checks (approval workflow, org-only access) | Deferred — feature not yet needed |
| CS-P2-3 | src/api/routes/k8s_clusters.py | TODO comments for missing internal service auth on K8s heartbeat routes | Deferred — cluster-internal only |
| CS-P2-4 | src/api/auth.py | Broad `except Exception` blocks swallow errors during auth fallthrough | Deferred — functional but makes debugging harder |

---

## P3 — Low / Quality Findings

| ID | File | Issue | Status |
|----|------|-------|--------|
| CS-P3-1 | src/db/models.py | `datetime.utcnow` used as column defaults (~60 occurrences) | Deferred — works correctly with PostgreSQL DateTime(timezone=True) |
| CS-P3-2 | src/api/routes/ | Large route files (admin.py 2042, internal.py 2900, team.py 1884 lines) | Deferred — refactoring opportunity |
| CS-P3-3 | src/db/repository.py | No eager loading on list queries — potential N+1 | Deferred — performance optimization |

---

## Files Modified

| File | Changes |
|------|---------|
| `config_service/src/db/models.py` | Fixed `is_expired()` timezone handling in TeamToken and OrgAdminToken |
| `config_service/src/api/routes/internal.py` | Added `INTERNAL_SERVICE_SECRET` verification to `require_internal_service()` |
| `config_service/src/api/routes/config_v2.py` | Removed debug logging |

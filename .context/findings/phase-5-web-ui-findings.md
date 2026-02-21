# Phase 5: web_ui Audit — Findings

**Date:** 2026-02-18
**Scope:** `web_ui/src/` — API routes, auth, components, Next.js config

---

## Summary

| Severity | Found | Fixed | Deferred |
|----------|-------|-------|----------|
| P0 Critical | 3 | 2 | 1 |
| P1 High | 5 | 2 | 3 |
| P2 Medium | 5 | 1 | 4 |
| P3 Low | 0 | 0 | 0 |
| **Total** | **13** | **5** | **8** |

---

## P0 — Critical Findings

| ID | File | Issue | Status |
|----|------|-------|--------|
| WU-P0-1 | src/app/api/auth/callback/route.ts | OIDC callback missing state validation — CSRF allows attacker-initiated login | **Fixed** — Added `ifx_oidc_state` cookie validation with `crypto.timingSafeEqual`, open redirect prevention via `safeReturnTo()`, org_id sanitization, PKCE verifier passthrough, cookie cleanup |
| WU-P0-2 | src/app/api/admin/ | SSRF via unsanitized URL construction in admin routes | Deferred — false positive: orgId from Next.js dynamic route params can't contain path separators, `new URL(path, base)` stays within origin, all admin routes require auth |
| WU-P0-3 | src/components/investigation/MessageBubble.tsx | XSS via `dangerouslySetInnerHTML` with unsanitized agent output | **Fixed** — Added `escapeHtml()` function that escapes &, <, >, ", ' before regex-based markdown replacement |

---

## P1 — High Findings

| ID | File | Issue | Status |
|----|------|-------|--------|
| WU-P1-4 | src/app/api/topology/nodes/route.ts | Missing authentication — anyone can query org topology | **Fixed** — Added `getUpstreamAuthHeaders()` check, returns 401 if no auth, forwards auth to upstream |
| WU-P1-5 | src/app/api/v1/integrations/schemas/route.ts | Missing authentication — anyone can query integration schemas | **Fixed** — Added `getUpstreamAuthHeaders()` check, returns 401 if no auth, forwards auth to upstream |
| WU-P1-6 | src/app/api/team/agent/stream/ | SSE stream missing content validation from agent | Deferred — agent output is trusted internal service |
| WU-P1-7 | src/app/api/auth/callback/route.ts | Cookie secure flag inconsistent (based on NODE_ENV) | Deferred — correct for local development; production always sets secure |
| WU-P1-8 | next.config.ts | Credential exposure risk via `CONFIG_SERVICE_URL` in rewrites | Deferred — rewrites are server-side only, URL not exposed to client |

---

## P2 — Medium Findings

| ID | File | Issue | Status |
|----|------|-------|--------|
| WU-P2-9 | src/app/api/auth/callback/route.ts | OIDC state cookie not cleaned up after use | **Fixed** (as part of P0-1) — cookies deleted after successful auth |
| WU-P2-10 | src/app/api/ | Dynamic API route construction from user params without validation | Deferred — Next.js route params are framework-validated |
| WU-P2-11 | src/app/api/ | No CSRF protection on state-changing API routes | Deferred — SameSite=lax cookies provide baseline CSRF protection |
| WU-P2-12 | src/app/api/ | No rate limiting on API routes | Deferred — handled at infrastructure level (ALB/nginx) |
| WU-P2-13 | next.config.ts | Missing security headers (CSP, X-Frame-Options, etc.) | **Fixed** — Added X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy headers |

---

## Files Modified

| File | Changes |
|------|---------|
| `web_ui/src/components/investigation/MessageBubble.tsx` | Added `escapeHtml()` before `dangerouslySetInnerHTML` regex |
| `web_ui/src/app/api/auth/callback/route.ts` | Added OIDC state validation, open redirect prevention, org_id sanitization, PKCE verifier, cookie cleanup |
| `web_ui/src/app/api/topology/nodes/route.ts` | Added auth check via `getUpstreamAuthHeaders()` |
| `web_ui/src/app/api/v1/integrations/schemas/route.ts` | Added auth check via `getUpstreamAuthHeaders()` |
| `web_ui/next.config.ts` | Added security response headers |

# Phase 7: Ultimate RAG Security Audit Findings

**Date**: 2026-02-18
**Scope**: `ultimate_rag/` — API server, persistence, ingestion, retrieval, RAPTOR bridge
**Status**: 3 P0 fixed, 22 deferred

## Summary

| Severity | Count | Fixed | Deferred |
|----------|-------|-------|----------|
| P0 | 3 | 3 | 0 |
| P1 | 9 | 0 | 9 |
| P2 | 8 | 0 | 8 |
| P3 | 5 | 0 | 5 |
| **Total** | **25** | **3** | **22** |

---

## P0 — Critical (3 findings, 3 FIXED)

### RAG-001: No Authentication on API Endpoints ✅ FIXED
- **File**: `ultimate_rag/api/server.py` lines 832-839, 851+
- **Issue**: CORS `allow_origins=["*"]`, no auth on any endpoint. Any pod in the cluster could query/modify/delete all knowledge across all customers.
- **Fix**: Added API key auth middleware (`RAG_API_KEY` env var). When set, all routes except `/health`, `/docs`, `/openapi.json` require `Authorization: Bearer <key>` or `X-API-Key` header. CORS restricted to configured origins. Helm template updated with optional `ragApiKey` secret reference.

### RAG-002: Pickle Deserialization RCE ✅ FIXED
- **File**: `ultimate_rag/core/persistence.py` lines 144, 204, 246, 259
- **Issue**: `pickle.load()` and `pickle.loads()` used without validation. Crafted pickle payloads enable arbitrary code execution.
- **Fix**: Created `_RestrictedUnpickler` that only allows safe built-in types (dict, list, str, int, float, etc.) plus specific RAPTOR module classes (`raptor.tree_structures`, `raptor.tree_builder`). Replaced all `pickle.load`/`pickle.loads` calls across 4 files: `persistence.py`, `raptor/bridge.py`, `raptor_lib/RetrievalAugmentation.py`, `raptor_lib/tree_merge.py`.

### RAG-003: Path Traversal in File Ingestion ✅ FIXED
- **File**: `ultimate_rag/api/server.py` lines 990-1009
- **Issue**: `request.file_path` passed directly to `processor.process_file()` without validation. Attacker could specify `../../etc/passwd`.
- **Fix**: Added path validation — resolved path must be within `RAPTOR_TREES_DIR`. Error messages sanitized to not leak internal paths.

---

## P1 — High (9 findings, all deferred)

### RAG-004: ReDoS in JSON Extraction Regex
- **File**: `ultimate_rag/ingestion/extractors.py` line 220
- **Issue**: `r"\[.*\]"` with `re.DOTALL` — unbounded greedy pattern risks catastrophic backtracking.
- **Recommendation**: Use non-greedy `r"\[.*?\]"` or JSON parser instead.

### RAG-005: ReDoS in Number Extraction
- **File**: `ultimate_rag/api/server.py` lines 2894-2903
- **Issue**: Complex regex applied to potentially large contradiction texts without size limits.

### RAG-006: No Size Limits on Document Ingestion
- **File**: `ultimate_rag/api/server.py` lines 942-1170
- **Issue**: No max content size, no batch limits. Can exhaust memory/API quotas.
- **Recommendation**: Add `max_length` to content fields, limit batch size.

### RAG-007: Missing Timeout on Embedding API Calls
- **File**: `ultimate_rag/api/server.py` line 1058
- **Issue**: Embedding calls retry up to 12 times with no overall timeout.

### RAG-008: Inconsistent Tree Name Validation
- **File**: `ultimate_rag/api/server.py` lines 1067, 1762-1781
- **Issue**: Tree name validated with `^[a-zA-Z0-9_-]+$` at creation but not at query time.

### RAG-009: CQL Injection in Confluence Source
- **File**: `ultimate_rag/ingestion/sources.py` line 537
- **Issue**: CQL query built with string interpolation, no escaping of `space_key`.

### RAG-010: SSRF in Confluence Base URL
- **File**: `ultimate_rag/ingestion/sources.py` lines 447, 482
- **Issue**: `base_url` accepted without domain validation.

### RAG-011: Git Command Injection
- **File**: `ultimate_rag/ingestion/sources.py` lines 348, 381
- **Issue**: `repo_url` and `branch` used in git commands without sanitization. Partially mitigated by list-form subprocess.

### RAG-012: No Rate Limiting
- **File**: `ultimate_rag/api/server.py` lines 813-843
- **Issue**: No per-IP or per-token rate limits on any endpoint.

---

## P2 — Medium (8 findings, all deferred)

### RAG-013: Error Messages Leak Internal Details
- **File**: `ultimate_rag/api/server.py` (multiple locations)
- **Issue**: `raise HTTPException(500, str(e))` exposes file paths and internals.

### RAG-014: No Max Length on Query String
- **File**: `ultimate_rag/api/server.py` line 55
- **Issue**: `query: str` has no max_length constraint.

### RAG-015: Weak Contradiction Detection
- **File**: `ultimate_rag/api/server.py` lines 2859-2927
- **Issue**: Pattern-based detection easily bypassed with synonyms.

### RAG-016: Unbounded Tree Depth/Memory Growth
- **File**: `ultimate_rag/raptor_lib/cluster_tree_builder.py` lines 79-250+
- **Issue**: No max depth or node count limits in tree construction.

### RAG-017: LLM Injection via Entity Names
- **File**: `ultimate_rag/api/server.py` line 2929+
- **Issue**: Entity names from user content used in LLM prompts without escaping.

### RAG-018: Insufficient Security Event Logging
- **Issue**: No audit logging for sensitive operations (ingest, teach, delete).

### RAG-019: No Encryption of Data at Rest
- **File**: `ultimate_rag/core/persistence.py`
- **Issue**: Trees saved as plaintext pickle/JSON to disk and S3.

### RAG-020: Unvalidated Filters Dictionary
- **File**: `ultimate_rag/api/server.py` line 60
- **Issue**: `filters: Dict[str, Any]` passed to retriever without type checking.

---

## P3 — Low (5 findings, all deferred)

### RAG-021: Missing Type Hints in Critical Functions
### RAG-022: Hardcoded Model Names (OpenAI)
### RAG-023: No Embedding Service Health Check
### RAG-024: Weak MD5 Content Hash for Deduplication
### RAG-025: No Validation of Metadata Size

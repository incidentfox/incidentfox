# Integration Cheat Sheet

Lessons learned from fixing Confluence integration. Reference this when adding or debugging other integrations.

---

## 1. JWT Authentication (CRITICAL)

**Problem**: Credential-resolver requires `x-sandbox-jwt` header in strict mode (production). Client code sending `X-Tenant-Id`/`X-Team-Id` headers will get 401 Unauthorized.

**Fix**:
- Ensure `SANDBOX_JWT` env var is passed to sandbox (in `sandbox_manager.py`)
- Client code must send JWT in `X-Sandbox-JWT` header
- Example from `confluence_client.py`:
```python
sandbox_jwt = os.getenv("SANDBOX_JWT")
if sandbox_jwt:
    headers["X-Sandbox-JWT"] = sandbox_jwt
```

**Files to check**:
- `sre-agent/sandbox_manager.py` - env var injection
- Client scripts in `.claude/skills/*/scripts/` - header construction

---

## 2. Field Name Mismatches (VERY COMMON)

**Problem**: Config Service stores fields with different names than what credential-resolver code expects.

**Config Service field names by integration** (from onboarding.py):

| Integration | Required Fields | Optional Fields |
|-------------|-----------------|-----------------|
| coralogix | `api_key`, `domain` | |
| incident_io | `api_key` | |
| confluence | `api_key`, `email`, `domain` | |
| grafana | `api_key`, `domain` | |
| elasticsearch | `domain` | `username`, `api_key`, `index_pattern` |
| datadog | `api_key`, `app_key`, `site`* | |
| prometheus | `domain` | `api_key` |
| jaeger | `domain` | |
| kubernetes | `api_key`, `domain` | `namespace` |
| github | `api_key` | `domain` (GHE), `default_org` |

*Note: Datadog UI field is `domain`, but stored/retrieved as `site`

**How to verify**: Check what Config Service actually returns:
```bash
curl -s "http://config-service-svc:8080/api/v1/config/me" \
  -H "X-Org-Id: slack-TENANT_ID" \
  -H "X-Team-Node-Id: default" | jq '.effective_config.integrations.INTEGRATION_NAME'
```

**Files to update when fixing field names**:
1. `main.py` → `is_integration_configured()` - check correct fields exist
2. `main.py` → `get_integration_metadata()` - return correct metadata field
3. `main.py` → `build_auth_headers()` - read correct credential fields
4. `main.py` → proxy endpoint (if exists) - read correct fields for URL/auth

---

## 3. URL Parsing & Normalization

**Problem**: Users paste full URLs with paths (e.g., `https://company.atlassian.net/wiki/spaces/ENG`), but we only need base URL.

**Bad approach**: Parse at request time in credential-resolver
**Good approach**: Normalize at input time in `slack-bot/onboarding.py`

**Example - Extract base URL**:
```python
import re
from urllib.parse import urlparse

def extract_base_url(input_str: str) -> tuple[bool, str, str]:
    """Extract base URL (scheme + host) from any URL."""
    if not input_str:
        return False, "", "URL is required"

    input_str = input_str.strip()
    if not input_str.startswith(("http://", "https://")):
        input_str = f"https://{input_str}"

    try:
        parsed = urlparse(input_str)
        hostname = parsed.hostname
        if not hostname:
            return False, "", "Could not parse URL"

        scheme = parsed.scheme or "https"
        base_url = f"{scheme}://{hostname}"
        return True, base_url, ""
    except Exception:
        return False, "", "Invalid URL format"
```

**Files to update**:
- `slack-bot/onboarding.py` - add `extract_<integration>_url()` function
- `slack-bot/app.py` - call extraction in field validation (around line 4700)

---

## 4. FastAPI Route Ordering (GOTCHA!)

**Problem**: FastAPI/Starlette matches routes in declaration order. Catch-all routes (`/{path:path}`) will match everything if declared first.

**Symptom**: Logs show `ext_authz check: GET /confluence/...` instead of `Confluence proxy: ...`

**Fix**: Declare specific routes BEFORE catch-all routes:
```python
# CORRECT ORDER:
@app.api_route("/confluence/{path:path}", ...)  # Specific - FIRST
async def confluence_proxy(...): ...

@app.api_route("/{path:path}", ...)  # Catch-all - LAST
async def ext_authz_check(...): ...
```

**Add a comment** to prevent future mistakes:
```python
# IMPORTANT: Route ordering matters in FastAPI/Starlette!
# More specific routes MUST be declared BEFORE catch-all routes.
```

---

## 5. Proxy Mode vs Direct Mode

**Proxy mode** (production):
- Requests go through credential-resolver which injects auth headers
- `<INTEGRATION>_BASE_URL` points to credential-resolver endpoint
- Example: `CONFLUENCE_BASE_URL=http://credential-resolver:8002/confluence`

**Direct mode** (local dev):
- Client has credentials directly in env vars
- No credential-resolver involved
- Example: `CONFLUENCE_URL`, `CONFLUENCE_EMAIL`, `CONFLUENCE_API_TOKEN`

**Client code must support both**:
```python
def get_api_url(path: str) -> str:
    # Proxy mode (production)
    proxy_url = os.getenv("CONFLUENCE_BASE_URL")
    if proxy_url:
        return f"{proxy_url.rstrip('/')}{path}"

    # Direct mode (local dev)
    url = os.getenv("CONFLUENCE_URL")
    if url:
        return f"{url.rstrip('/')}{path}"

    raise RuntimeError("No URL configured")
```

---

## 6. Auth Header Construction

Different integrations use different auth schemes:

| Integration | Auth Type | Header Format |
|-------------|-----------|---------------|
| Anthropic | API Key | `x-api-key: {api_key}` |
| Coralogix | Bearer | `Authorization: Bearer {api_key}` |
| Confluence | Basic | `Authorization: Basic {base64(email:api_key)}` |
| Datadog | Two Keys | `DD-API-KEY: {api_key}`, `DD-APPLICATION-KEY: {app_key}` |
| Elasticsearch | Basic/ApiKey | `Authorization: Basic {base64(user:pass)}` or `Authorization: ApiKey {key}` |
| GitHub | Bearer | `Authorization: Bearer {token}` |
| Grafana | Bearer | `Authorization: Bearer {api_key}` |
| incident.io | Bearer | `Authorization: Bearer {api_key}` |
| Jaeger | Bearer (optional) | `Authorization: Bearer {api_key}` |
| Kubernetes | Bearer | `Authorization: Bearer {api_key}` |
| Prometheus | Bearer (optional) | `Authorization: Bearer {api_key}` |

**Example - Basic auth**:
```python
import base64
email = creds.get("email", "")
api_key = creds.get("api_key", "")
auth_string = f"{email}:{api_key}"
encoded = base64.b64encode(auth_string.encode()).decode()
headers["Authorization"] = f"Basic {encoded}"
```

---

## 7. Integration Detection Functions

Update these functions in `main.py` for each integration:

### `is_integration_configured()`
Check if required credentials exist:
```python
def is_integration_configured(integration_id: str, creds: dict | None) -> bool:
    if not creds:
        return False
    if integration_id == "confluence":
        return bool(creds.get("domain") and creds.get("api_key"))
    elif integration_id == "coralogix":
        return bool(creds.get("api_key") and creds.get("domain"))
    # Add other integrations...
    return bool(creds.get("api_key"))
```

### `get_integration_metadata()`
Return non-sensitive config for agent context:
```python
def get_integration_metadata(integration_id: str, creds: dict) -> dict:
    if integration_id == "confluence":
        return {"url": creds.get("domain")}  # URL is non-sensitive
    elif integration_id == "coralogix":
        return {"domain": creds.get("domain"), "region": creds.get("region")}
    # NEVER return api_key, api_token, password, etc.
    return {}
```

---

## 8. Environment Variables for Sandbox

Ensure these are passed to sandbox in `sandbox_manager.py`:

```python
env_vars = [
    # Auth
    {"name": "SANDBOX_JWT", "value": jwt_token},

    # Integration base URLs (for proxy mode)
    {"name": "CONFLUENCE_BASE_URL", "value": "http://credential-resolver:8002/confluence"},
    {"name": "CORALOGIX_BASE_URL", "value": "..."},

    # Integration metadata (non-sensitive, for agent context)
    {"name": "CONFIGURED_INTEGRATIONS", "value": json.dumps(integrations_list)},
]
```

---

## 9. Debugging Checklist

When an integration isn't working:

1. **Check logs for which route is being hit**:
   ```
   ext_authz check: GET /...  → Wrong route (catch-all)
   <Integration> proxy: GET /...  → Correct route
   ```

2. **Check JWT is being sent**:
   ```bash
   echo $SANDBOX_JWT  # Should have value
   ```

3. **Check Config Service returns credentials**:
   ```bash
   curl -s "http://config-service:8080/api/v1/config/me" \
     -H "X-Org-Id: slack-TENANT" -H "X-Team-Node-Id: default" | jq
   ```

4. **Test credential-resolver proxy directly**:
   ```bash
   curl -v "http://credential-resolver:8002/<integration>/..." \
     -H "X-Sandbox-JWT: $SANDBOX_JWT"
   ```

5. **Check field names match** between Config Service response and code

6. **Check route ordering** in main.py

---

## 10. Files to Touch for New Integration

1. **credential-resolver/main.py**:
   - `ACTIVE_INTEGRATIONS` list in `list_integrations()` - add new integration ID
   - `is_integration_configured()` - add field checks
   - `get_integration_metadata()` - add metadata extraction
   - `build_auth_headers()` - add auth header construction
   - Add proxy endpoint if needed (customer-specific URLs)
   - Ensure route ordering is correct

2. **sandbox_manager.py**:
   - Add `<INTEGRATION>_BASE_URL` env var
   - Update `CONFIGURED_INTEGRATIONS` logic

3. **slack-bot/onboarding.py**:
   - Add URL extraction/validation function if needed

4. **slack-bot/app.py**:
   - Add field validation logic if needed

5. **.claude/skills/<skill>/scripts/**:
   - Update client to support proxy mode with JWT auth

---

## Quick Reference: Common Errors

| Error | Likely Cause |
|-------|--------------|
| `401 Unauthorized` | Missing/invalid JWT, or using X-Tenant-Id instead of X-Sandbox-JWT |
| `404 Not Found` (from credential-resolver) | Integration not configured for tenant |
| `500 Credentials not configured` | Field name mismatch - code checking wrong field |
| `504 Gateway Timeout` | Upstream service unreachable, or wrong target URL |
| `Expecting value: line 1 column 1` | Empty response - check URL and auth |
| Requests going to wrong handler | Route ordering issue |

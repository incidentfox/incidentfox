# IncidentFox API Flows

**Last Updated:** 2026-01-11
**Target Audience:** Internal Developers

---

## Overview

This document details the end-to-end API flows through the IncidentFox system, showing how requests traverse through services, including request/response payloads, authentication, and error handling.

---

## Flow 1: Slack @mention → Agent Run → Slack Response

**Trigger:** User mentions @IncidentFox in Slack channel

### Step-by-Step Flow

```
┌─────────┐         ┌──────────────┐         ┌────────────┐         ┌────────┐
│  Slack  │────1───>│ Orchestrator │────2───>│   Config   │────3───>│ Agent  │
│         │<───8────│              │         │  Service   │         │        │
└─────────┘         └──────────────┘         └────────────┘         └────────┘
                           │                        │                    │
                           └────────4───────────────┘                    │
                                                                         │
                                    ┌────────────────────────────────────┘
                                    │
                                    5. Agent posts directly to Slack
                                    │
                                    └────────────────────────────────────>
```

### Detailed Steps

#### 1. Slack → Orchestrator: Event Webhook

**Request:**
```http
POST https://orchestrator.incidentfox.ai/webhooks/slack/events
Content-Type: application/json
X-Slack-Signature: v0=...
X-Slack-Request-Timestamp: 1234567890

{
  "type": "event_callback",
  "event": {
    "type": "app_mention",
    "user": "U123ABC",
    "text": "<@U_BOT_ID> investigate high error rate",
    "channel": "C0A4967KRBM",
    "ts": "1234567890.123456",
    "thread_ts": "1234567890.123456"
  }
}
```

**Orchestrator Actions:**
- Verify X-Slack-Signature (HMAC-SHA256 with `SLACK_SIGNING_SECRET`)
- Return 200 OK immediately (Slack requires response within 3 seconds)
- Process asynchronously

**Response:**
```http
HTTP/1.1 200 OK
Content-Type: text/plain

OK
```

---

#### 2. Orchestrator → Config Service: Routing Lookup

**Request:**
```http
POST http://incidentfox-config-service.incidentfox.svc.cluster.local:8080/api/v1/internal/routing/lookup
Content-Type: application/json
X-Internal-Service: orchestrator

{
  "identifiers": {
    "slack_channel_id": "C0A4967KRBM"
  }
}
```

**Response:**
```json
{
  "found": true,
  "org_id": "extend",
  "team_node_id": "extend-sre",
  "matched_by": "slack_channel_id",
  "routing_config": {
    "slack_channel_ids": ["C0A4967KRBM"],
    "services": ["payment", "checkout"]
  }
}
```

**Error Cases:**
- 404: No team found for channel → Orchestrator logs warning, no action taken
- 500: Config Service down → Orchestrator returns error, logs incident

---

#### 3. Config Service → Database: Get Team Config

**Internal Query:**
```sql
-- Get team lineage for config inheritance
WITH RECURSIVE lineage AS (
  SELECT node_id, parent_id, node_type, 0 AS depth
  FROM org_nodes
  WHERE org_id = 'extend' AND node_id = 'extend-sre'

  UNION ALL

  SELECT n.node_id, n.parent_id, n.node_type, l.depth + 1
  FROM org_nodes n
  JOIN lineage l ON n.node_id = l.parent_id
  WHERE n.org_id = 'extend'
)
SELECT * FROM lineage ORDER BY depth DESC;

-- Get configs for all nodes in lineage
SELECT node_id, config_json
FROM node_configs
WHERE org_id = 'extend' AND node_id IN (...)
ORDER BY depth DESC;
```

**Config Merging:**
1. Start with base defaults (from `get_full_default_config()`)
2. Apply org config
3. Apply team config
4. Deep merge (dicts merge, lists replace)
5. Add tool catalog
6. Filter disabled tools

---

#### 4. Orchestrator → Agent: Trigger Run

**Request:**
```http
POST http://incidentfox-agent.incidentfox.svc.cluster.local:8080/api/v1/agent/run
Content-Type: application/json
Authorization: Bearer <impersonation_token>

{
  "org_id": "extend",
  "team_node_id": "extend-sre",
  "agent_name": "planner",
  "message": "investigate high error rate",
  "output_destinations": [
    {
      "type": "slack",
      "channel_id": "C0A4967KRBM",
      "thread_ts": "1234567890.123456",
      "user_id": "U123ABC"
    }
  ],
  "context": {
    "trigger_source": "slack",
    "trigger_id": "slack_event_1234"
  }
}
```

**Agent Actions:**
1. Validate impersonation token
2. Fetch team config from Config Service
3. Build dynamic agent from config
4. Execute agent with tools
5. Post results to Slack directly

---

#### 5. Agent → Slack: Post Initial Message

**Request:**
```http
POST https://slack.com/api/chat.postMessage
Authorization: Bearer xoxb-...
Content-Type: application/json

{
  "channel": "C0A4967KRBM",
  "thread_ts": "1234567890.123456",
  "blocks": [
    {
      "type": "header",
      "text": {
        "type": "plain_text",
        "text": "🔍 Investigating: high error rate"
      }
    },
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "*Status:* Initializing investigation..."
      }
    }
  ]
}
```

**Response:**
```json
{
  "ok": true,
  "channel": "C0A4967KRBM",
  "ts": "1234567890.234567",
  "message": {
    "text": "...",
    "blocks": [...]
  }
}
```

Agent stores `ts` for updating the message.

---

#### 6. Agent: Execute Investigation

**Internal Flow:**
1. **Planner Agent** analyzes request
2. Delegates to **Investigation Agent**
3. Investigation Agent uses tools:
   - `kubectl_get_pods()` - Check pod status
   - `get_pod_logs()` - Fetch error logs
   - `search_coralogix_logs()` - Query observability
   - `get_recent_incidents()` - Check historical data

**Tool Execution Pattern:**
Each tool receives `execution_context`:
```python
execution_context = {
    "org_id": "extend",
    "team_node_id": "extend-sre",
    "user_id": "U123ABC",
    "correlation_id": "run_abc123",
    "tool_configs": {
        "search_coralogix_logs": {
            "default_time_range": "1h"
        }
    }
}

result = search_coralogix_logs(
    execution_context,
    query="source logs | filter $m.severity >= 5",
    time_range_minutes=60
)
```

---

#### 7. Agent → Slack: Update with Progress

**Request (Update Message):**
```http
POST https://slack.com/api/chat.update
Authorization: Bearer xoxb-...
Content-Type: application/json

{
  "channel": "C0A4967KRBM",
  "ts": "1234567890.234567",
  "blocks": [
    {
      "type": "header",
      "text": {
        "type": "plain_text",
        "text": "🔍 Investigation: high error rate"
      }
    },
    {
      "type": "section",
      "fields": [
        {"type": "mrkdwn", "text": "*Phase 1:* ✅ Pod Status"},
        {"type": "mrkdwn", "text": "*Phase 2:* ⏳ Log Analysis"},
        {"type": "mrkdwn", "text": "*Phase 3:* ⏸️ Metrics"},
        {"type": "mrkdwn", "text": "*Phase 4:* ⏸️ Root Cause"}
      ]
    }
  ]
}
```

Agent updates message in real-time as investigation progresses.

---

#### 8. Agent → Slack: Post Final Results

**Request:**
```http
POST https://slack.com/api/chat.update
Authorization: Bearer xoxb-...
Content-Type: application/json

{
  "channel": "C0A4967KRBM",
  "ts": "1234567890.234567",
  "blocks": [
    {
      "type": "header",
      "text": {
        "type": "plain_text",
        "text": "✅ Investigation Complete: high error rate"
      }
    },
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "*Root Cause:* Payment service pod restarting due to OOM\\n*Affected Services:* payment, checkout\\n*Evidence:* See logs below..."
      }
    },
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "*Recommendations:*\\n• Increase memory limit to 2Gi\\n• Review memory leak in payment service\\n• Scale horizontally to 3 replicas"
      }
    },
    {
      "type": "actions",
      "elements": [
        {
          "type": "button",
          "text": {"type": "plain_text", "text": "View Details"},
          "value": "run_abc123"
        }
      ]
    }
  ]
}
```

---

### Sequence Diagram

```mermaid
sequenceDiagram
    participant User
    participant Slack
    participant Orchestrator
    participant ConfigService
    participant Agent

    User->>Slack: @mention IncidentFox
    Slack->>Orchestrator: POST /webhooks/slack/events
    Orchestrator-->>Slack: 200 OK (within 3s)

    Orchestrator->>ConfigService: POST /api/v1/internal/routing/lookup
    ConfigService-->>Orchestrator: {org_id, team_node_id}

    Orchestrator->>Agent: POST /api/v1/agent/run
    Agent->>Slack: POST /chat.postMessage (initial)

    loop Investigation
        Agent->>Agent: Execute tools
        Agent->>Slack: POST /chat.update (progress)
    end

    Agent->>Slack: POST /chat.update (final results)
    Agent-->>Orchestrator: 200 OK {run_id}
```

---

## Flow 2: Config Inheritance & Resolution

**Trigger:** Agent requests effective config for team

### Step-by-Step Flow

#### 1. Agent → Config Service: Get Effective Config

**Request:**
```http
GET http://incidentfox-config-service.incidentfox.svc.cluster.local:8080/api/v1/config/me/effective
Authorization: Bearer extend.extend-sre.J2KnE8rVmCfPWq...
```

**Config Service Actions:**
1. Validate bearer token
2. Extract `org_id` and `team_node_id` from token
3. Get lineage (org → team hierarchy)
4. Fetch configs for all nodes in lineage
5. Merge configs (deepmerge)
6. Add tool catalog
7. Filter disabled tools
8. Return effective config

---

#### 2. Database: Lineage Query

**SQL:**
```sql
-- Recursive CTE to get full lineage
WITH RECURSIVE lineage AS (
  -- Start with team node
  SELECT
    node_id,
    parent_id,
    node_type,
    name,
    0 AS depth
  FROM org_nodes
  WHERE org_id = 'extend' AND node_id = 'extend-sre'

  UNION ALL

  -- Recursively get parents
  SELECT
    n.node_id,
    n.parent_id,
    n.node_type,
    n.name,
    l.depth + 1
  FROM org_nodes n
  INNER JOIN lineage l ON n.node_id = l.parent_id
  WHERE n.org_id = 'extend'
)
SELECT * FROM lineage
ORDER BY depth DESC;  -- Root first, team last
```

**Result:**
```
node_id        | parent_id | node_type | depth
---------------|-----------|-----------|------
extend         | NULL      | org       | 2
extend-group   | extend    | group     | 1
extend-sre     | extend-group | team  | 0
```

---

#### 3. Database: Config Query

**SQL:**
```sql
SELECT
  node_id,
  config_json,
  version,
  updated_at
FROM node_configs
WHERE org_id = 'extend'
  AND node_id IN ('extend', 'extend-group', 'extend-sre')
ORDER BY
  CASE node_id
    WHEN 'extend' THEN 1
    WHEN 'extend-group' THEN 2
    WHEN 'extend-sre' THEN 3
  END;
```

**Result:**
```json
[
  {
    "node_id": "extend",
    "config_json": {
      "agents": {
        "planner": {"model": "gpt-4o", "tools": [...]}
      },
      "integrations": {...}
    }
  },
  {
    "node_id": "extend-group",
    "config_json": {
      "team_disabled_tool_ids": ["delete_resource"]
    }
  },
  {
    "node_id": "extend-sre",
    "config_json": {
      "mcp_servers": [{...}],
      "team_enabled_tool_ids": ["kubectl_exec"]
    }
  }
]
```

---

#### 4. Config Merging Logic

**Python Implementation:**
```python
def deep_merge_dicts(configs: List[Dict]) -> Dict:
    """Merge configs with inheritance.

    Rules:
    - Dicts: Merge recursively
    - Lists: Replace entirely (child overrides parent)
    - Scalars: Replace
    """
    result = {}
    for config in configs:
        for key, value in config.items():
            if key not in result:
                result[key] = value
            elif isinstance(value, dict) and isinstance(result[key], dict):
                # Recursive merge for dicts
                result[key] = deep_merge_dicts([result[key], value])
            else:
                # Replace for lists and scalars
                result[key] = value
    return result

# Merge order: base defaults → org → group → team
base_defaults = get_full_default_config(db)
org_config = configs['extend']
group_config = configs['extend-group']
team_config = configs['extend-sre']

effective = deep_merge_dicts([
    base_defaults,
    org_config,
    group_config,
    team_config
])
```

**Example Merge:**
```python
# Base defaults
{
  "agents": {
    "planner": {"model": "gpt-4o", "tools": ["tool1", "tool2"]}
  }
}

# Org config (adds integration)
{
  "integrations": {
    "slack": {"enabled": true}
  }
}

# Group config (disables a tool)
{
  "team_disabled_tool_ids": ["tool2"]
}

# Team config (adds MCP server)
{
  "mcp_servers": [
    {"name": "filesystem", "command": "mcp-server-filesystem"}
  ]
}

# EFFECTIVE CONFIG (merged)
{
  "agents": {
    "planner": {"model": "gpt-4o", "tools": ["tool1", "tool2"]}
  },
  "integrations": {
    "slack": {"enabled": true}
  },
  "team_disabled_tool_ids": ["tool2"],
  "mcp_servers": [
    {"name": "filesystem", "command": "mcp-server-filesystem"}
  ]
}
```

---

#### 5. Tool Filtering

**After merging, apply tool filtering:**
```python
# Get all available tools
all_tools = get_tools_catalog()['tools']  # 300+ built-in tools

# Apply team_disabled_tool_ids (blacklist)
disabled_ids = effective.get('team_disabled_tool_ids', [])
enabled_tools = [t for t in all_tools if t['id'] not in disabled_ids]

# Apply team_enabled_tool_ids (whitelist for restricted tools)
enabled_ids = effective.get('team_enabled_tool_ids', [])
# Some tools require explicit enabling (e.g., kubectl_exec, delete_*)
restricted_tools = [t for t in all_tools if t.get('restricted', False)]
for tool in restricted_tools:
    if tool['id'] not in enabled_ids:
        enabled_tools.remove(tool)

effective['available_tools'] = enabled_tools
```

---

#### 6. Response: Effective Config

**Response:**
```json
{
  "org_id": "extend",
  "team_node_id": "extend-sre",
  "agents": {
    "planner": {
      "model": "gpt-4o",
      "prompt": {
        "system": "You are an expert SRE...",
        "instructions": [...]
      },
      "tools": ["tool1", "tool2", "tool3"],
      "sub_agents": ["k8s_agent", "aws_agent"]
    },
    "k8s_agent": {...},
    "aws_agent": {...}
  },
  "integrations": {
    "slack": {"channel": "C0A4967KRBM"},
    "github": {...},
    "datadog": {...}
  },
  "mcp_servers": [
    {
      "name": "filesystem",
      "command": "mcp-server-filesystem",
      "args": ["--root", "/workspace"]
    }
  ],
  "team_disabled_tool_ids": ["delete_resource", "kubectl_delete"],
  "team_enabled_tool_ids": ["kubectl_exec"],
  "built_in_tools": [
    {
      "id": "kubectl_get_pods",
      "name": "Get Kubernetes Pods",
      "category": "kubernetes",
      "integration_dependencies": []
    },
    ...
  ],
  "output_config": {
    "default_destinations": ["slack"],
    "trigger_overrides": {
      "github": ["slack", "github_pr_comment"]
    }
  }
}
```

---

## Flow 3: Team Provisioning

**Trigger:** Admin creates new team via API or UI

### Step-by-Step Flow

#### 1. Admin → Orchestrator: Provision Team

**Request:**
```http
POST https://orchestrator.incidentfox.ai/api/v1/admin/provision/team
Authorization: Bearer <admin_token>
Content-Type: application/json

{
  "org_id": "acme",
  "team_node_id": "platform-sre",
  "name": "Platform SRE Team",
  "slack_channel_ids": ["C123456"],
  "github_repos": ["acme/platform"],
  "pipeline_schedule": "0 2 * * *",
  "deployment_mode": "shared"
}
```

---

#### 2. Orchestrator: Concurrency Control

**Advisory Lock:**
```python
# Acquire Postgres advisory lock to prevent concurrent provisioning
async with db.begin():
    lock_key = hash((org_id, team_node_id)) % (2**31)
    await db.execute(f"SELECT pg_advisory_xact_lock({lock_key})")

    # Check idempotency
    if idempotency_key:
        existing_run = await get_provisioning_run(idempotency_key)
        if existing_run:
            return existing_run  # Return same result

    # Proceed with provisioning
    run_id = create_provisioning_run(org_id, team_node_id, idempotency_key)
```

---

#### 3. Orchestrator → Config Service: Create Team Node

**Request:**
```http
POST http://incidentfox-config-service:8080/api/v1/admin/orgs/acme/nodes
Authorization: Bearer <admin_token>
Content-Type: application/json

{
  "node_id": "platform-sre",
  "node_type": "team",
  "name": "Platform SRE Team",
  "parent_id": "acme",
  "config": {
    "routing": {
      "slack_channel_ids": ["C123456"],
      "github_repos": ["acme/platform"]
    }
  }
}
```

**Config Service Actions:**
1. Validate admin token
2. Check parent node exists
3. Create node in `org_nodes` table
4. Create config in `node_configs` table
5. Return node details

---

#### 4. Orchestrator → Config Service: Issue Team Token

**Request:**
```http
POST http://incidentfox-config-service:8080/api/v1/admin/orgs/acme/teams/platform-sre/tokens
Authorization: Bearer <admin_token>
Content-Type: application/json

{
  "label": "Primary team token",
  "permissions": ["*"],
  "expires_at": null
}
```

**Response:**
```json
{
  "token_id": "tok_abc123",
  "token": "acme.platform-sre.secret_value_here",
  "issued_at": "2026-01-11T10:00:00Z",
  "expires_at": null,
  "label": "Primary team token"
}
```

**Token Format:**
- `{org_id}.{team_node_id}.{secret}`
- Secret is hashed with pepper and stored in database
- Token only shown once

---

#### 5. Orchestrator: Create AI Pipeline CronJob (if scheduled)

**Kubernetes Manifest:**
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: ai-pipeline-acme-platform-sre
  namespace: incidentfox
spec:
  schedule: "0 2 * * *"  # 2 AM daily
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: ai-pipeline
          containers:
          - name: pipeline
            image: 103002841599.dkr.ecr.us-west-2.amazonaws.com/incidentfox-ai-pipeline:latest
            env:
            - name: ORG_ID
              value: "acme"
            - name: TEAM_NODE_ID
              value: "platform-sre"
            - name: TEAM_TOKEN
              valueFrom:
                secretKeyRef:
                  name: team-token-acme-platform-sre
                  key: token
          restartPolicy: OnFailure
```

**Created via kubectl:**
```python
await k8s_client.create_namespaced_cron_job(
    namespace="incidentfox",
    body=cronjob_manifest
)
```

---

#### 6. Orchestrator: Store Provisioning Result

**Database Insert:**
```sql
INSERT INTO orchestrator_provisioning_runs (
  id,
  org_id,
  team_node_id,
  idempotency_key,
  status,
  steps,
  created_at
) VALUES (
  'run_abc123',
  'acme',
  'platform-sre',
  'idempotency_key_123',
  'completed',
  '{
    "team_node_created": true,
    "team_token_issued": true,
    "cronjob_created": true
  }',
  NOW()
);
```

---

#### 7. Response: Provisioning Complete

**Response:**
```json
{
  "run_id": "run_abc123",
  "status": "completed",
  "org_id": "acme",
  "team_node_id": "platform-sre",
  "team_token": "acme.platform-sre.secret_value_here",
  "steps": {
    "team_node_created": true,
    "team_token_issued": true,
    "cronjob_created": true,
    "deployment_created": false
  },
  "created_at": "2026-01-11T10:00:00Z",
  "completed_at": "2026-01-11T10:00:05Z"
}
```

**Important**: `team_token` is only returned once! Caller must store securely.

---

## Flow 4: Authentication & Token Validation

### Token Types

1. **Global Admin Token** (env: `ADMIN_TOKEN`)
2. **Org Admin Token** (format: `{org_id}.{secret}`)
3. **Team Token** (format: `{org_id}.{team_node_id}.{secret}`)

### Validation Flow

#### Request with Bearer Token

**Example:**
```http
GET /api/v1/config/me/effective
Authorization: Bearer extend.extend-sre.J2KnE8rVmCfPWq...
```

#### Config Service Validation

```python
async def authenticate_bearer_token(session, bearer: str, pepper: str) -> Principal:
    # 1. Check global admin token
    if bearer == os.getenv('ADMIN_TOKEN'):
        return Principal(
            principal_type='admin',
            org_id='*',
            team_node_id='*',
            permissions=['admin:*']
        )

    # 2. Parse token format
    parts = bearer.split('.')
    if len(parts) == 2:
        # Org admin token
        org_id, secret = parts
        hashed = hash_with_pepper(secret, pepper)
        token_row = session.query(OrgAdminToken).filter(
            OrgAdminToken.org_id == org_id,
            OrgAdminToken.token_hash == hashed,
            OrgAdminToken.revoked_at.is_(None)
        ).first()

        if token_row:
            return Principal(
                principal_type='org_admin',
                org_id=org_id,
                team_node_id=None,
                permissions=token_row.permissions
            )

    elif len(parts) == 3:
        # Team token
        org_id, team_node_id, secret = parts
        hashed = hash_with_pepper(secret, pepper)
        token_row = session.query(TeamToken).filter(
            TeamToken.org_id == org_id,
            TeamToken.team_node_id == team_node_id,
            TeamToken.token_hash == hashed,
            TeamToken.revoked_at.is_(None)
        ).first()

        if token_row:
            # Update last_used_at
            token_row.last_used_at = datetime.utcnow()
            session.commit()

            return Principal(
                principal_type='team',
                org_id=org_id,
                team_node_id=team_node_id,
                permissions=token_row.permissions
            )

    raise Unauthorized("Invalid token")
```

---

## Error Handling Patterns

### Standard Error Response

All services return consistent error format:

```json
{
  "error": {
    "code": "INVALID_TOKEN",
    "message": "Bearer token is invalid or expired",
    "details": {
      "token_prefix": "extend.extend-sre",
      "reason": "Token not found in database"
    }
  },
  "request_id": "req_abc123",
  "timestamp": "2026-01-11T10:00:00Z"
}
```

### HTTP Status Codes

| Code | Usage |
|------|-------|
| 200 | Success |
| 400 | Bad request (validation error) |
| 401 | Unauthorized (invalid/missing token) |
| 403 | Forbidden (valid token, insufficient permissions) |
| 404 | Not found (team, config, etc.) |
| 409 | Conflict (duplicate routing identifier) |
| 500 | Internal server error |
| 503 | Service unavailable (dependencies down) |

---

## Performance & Caching

### Config Service Caching

**Cache Strategy:**
- **Key**: `config:effective:{org_id}:{team_node_id}:{epoch}`
- **TTL**: 300 seconds (5 minutes)
- **Invalidation**: Increment org epoch on config change

**Cache Hit Flow:**
```python
epoch = cache.get_org_epoch(org_id)
cache_key = f"config:effective:{org_id}:{team_node_id}:{epoch}"
cached = redis.get(cache_key)

if cached:
    CONFIG_CACHE_EVENTS_TOTAL.labels("effective", "hit").inc()
    return json.loads(cached)

# Cache miss - compute and cache
CONFIG_CACHE_EVENTS_TOTAL.labels("effective", "miss").inc()
effective = compute_effective_config(org_id, team_node_id)
redis.setex(cache_key, 300, json.dumps(effective))
return effective
```

### Webhook Signature Verification Optimization

**Problem**: Verifying signatures on every webhook is CPU-intensive

**Solution**: Cache verification results briefly (30 seconds)
```python
signature_cache_key = f"webhook:sig:{request_id}"
if redis.get(signature_cache_key):
    return True  # Already verified

verified = verify_signature(request)
if verified:
    redis.setex(signature_cache_key, 30, "1")
return verified
```

---

## Monitoring & Observability

### Request Tracing

All requests include `X-Request-ID` header:

```http
GET /api/v1/config/me/effective
Authorization: Bearer ...
X-Request-ID: req_abc123
```

Services propagate and log with correlation ID:

```python
logger.info(
    "Config request",
    correlation_id=request_id,
    org_id=org_id,
    team_node_id=team_node_id,
    endpoint="/api/v1/config/me/effective"
)
```

### Key Metrics

**Prometheus Metrics:**
- `config_service_requests_total{endpoint, method, status}`
- `config_service_request_duration_seconds{endpoint}`
- `config_cache_events_total{cache_type, result}`
- `agent_runs_total{org_id, team_node_id, status}`
- `webhook_events_total{source, team_node_id, status}`

---

## Related Documentation

- [ROUTING_DESIGN.md](./ROUTING_DESIGN.md) - Webhook routing architecture
- [OPERATIONS.md](./OPERATIONS.md) - Debugging and troubleshooting
- [TECH_DEBT.md](./TECH_DEBT.md) - Known issues and improvements

---

**Last Updated:** 2026-01-11
**Maintained By:** Engineering Team
**Next Review:** 2026-02-11

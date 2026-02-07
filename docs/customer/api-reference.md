# IncidentFox API Reference

Quick reference for common API operations.

**Base URL:** `https://your-incidentfox-domain.com`

**Authentication:** IncidentFox uses three types of authentication tokens:

1. **`<SUPER_ADMIN_TOKEN>`** - Platform-wide access (use for org creation and issuing org admin tokens)
2. **`<ORG_ADMIN_TOKEN>`** - Organization-scoped (use for day-to-day operations)
3. **`<TEAM_TOKEN>`** - Team-scoped (use for webhooks and integrations)

Throughout this document:
- `<ADMIN_TOKEN>` means either super admin or org admin token (both work for the endpoint)
- `<SUPER_ADMIN_TOKEN>` means only super admin token will work
- `<ORG_ADMIN_TOKEN>` means org admin token is recommended

**Best Practice:** Use org admin tokens for day-to-day operations instead of the super admin token.

---

## Table of Contents

- [Organization Management](#organization-management)
- [Team Management](#team-management)
- [Token Management](#token-management)
- [Agent Execution](#agent-execution)
- [Configuration Management](#configuration-management)

---

## Organization Management

### Create Organization Node

Create the root organization node (typically done once during setup).

```http
POST /api/v1/admin/orgs/{org_id}/nodes
Authorization: Bearer <ADMIN_TOKEN>
Content-Type: application/json

{
  "node_id": "your-org-id",
  "parent_id": null,
  "node_type": "org",
  "name": "Your Organization Name"
}
```

**Response:**
```json
{
  "org_id": "your-org-id",
  "node_id": "your-org-id",
  "parent_id": null,
  "node_type": "org",
  "name": "Your Organization Name"
}
```

### List Organization Nodes

```http
GET /api/v1/admin/orgs/{org_id}/nodes
Authorization: Bearer <ADMIN_TOKEN>
```

**Response:**
```json
[
  {
    "org_id": "your-org-id",
    "node_id": "your-org-id",
    "parent_id": null,
    "node_type": "org",
    "name": "Your Organization Name"
  },
  {
    "org_id": "your-org-id",
    "node_id": "team-sre",
    "parent_id": "your-org-id",
    "node_type": "team",
    "name": "SRE Team"
  }
]
```

---

## Team Management

### Create Team

Create a team under your organization.

```http
POST /api/v1/admin/orgs/{org_id}/nodes
Authorization: Bearer <ADMIN_TOKEN>
Content-Type: application/json

{
  "node_id": "team-sre",
  "parent_id": "your-org-id",
  "node_type": "team",
  "name": "SRE Team"
}
```

**Response:**
```json
{
  "org_id": "your-org-id",
  "node_id": "team-sre",
  "parent_id": "your-org-id",
  "node_type": "team",
  "name": "SRE Team"
}
```

### Get Team Details

```http
GET /api/v1/admin/orgs/{org_id}/nodes/{team_node_id}
Authorization: Bearer <ADMIN_TOKEN>
```

### Update Team

```http
PATCH /api/v1/admin/orgs/{org_id}/nodes/{team_node_id}
Authorization: Bearer <ADMIN_TOKEN>
Content-Type: application/json

{
  "name": "Updated Team Name"
}
```

### Delete Team

```http
DELETE /api/v1/admin/orgs/{org_id}/nodes/{team_node_id}
Authorization: Bearer <ADMIN_TOKEN>
```

---

## Token Management

### Understanding Token Types

IncidentFox uses a three-tier token system:

1. **Super Admin Token** - Platform-wide access, stored in Kubernetes secret
2. **Org Admin Token** - Organization-scoped, for day-to-day management
3. **Team Token** - Team-scoped, for integrations and webhooks

See [Installation Guide](./installation-guide.md#understanding-incidentfox-token-hierarchy) for detailed explanation.

---

### Issue Org Admin Token

Generate an organization-scoped admin token. **Only super admins can issue org admin tokens.**

```http
POST /api/v1/admin/orgs/{org_id}/admin-tokens
Authorization: Bearer <SUPER_ADMIN_TOKEN>
Content-Type: application/json
```

**Response:**
```json
{
  "token": "986d78ee86a149a9bc6b218d402bd97f.UABy1Oc...",
  "issued_at": "2026-01-12T10:30:00Z"
}
```

**Permissions:**
- Create/manage teams within the organization
- Issue team tokens
- Configure org settings
- View org audit logs
- **Cannot** create other organizations
- **Cannot** issue other org admin tokens

**Example:**
```bash
curl -X POST "https://incidentfox.example.com/api/v1/admin/orgs/acme-corp/admin-tokens" \
  -H "Authorization: Bearer $SUPER_ADMIN_TOKEN"
```

**⚠️ Important:** Save this token securely - it won't be shown again!

### List Org Admin Tokens

```http
GET /api/v1/admin/orgs/{org_id}/admin-tokens
Authorization: Bearer <SUPER_ADMIN_TOKEN>
```

**Response:**
```json
[
  {
    "id": "token-id-1",
    "issued_at": "2026-01-12T10:30:00Z",
    "issued_by": "platform-admin",
    "last_used": "2026-01-12T15:20:00Z",
    "revoked_at": null
  }
]
```

### Revoke Org Admin Token

```http
POST /api/v1/admin/orgs/{org_id}/admin-tokens/{token_id}/revoke
Authorization: Bearer <SUPER_ADMIN_TOKEN>
```

**Note:** Only super admins can revoke org admin tokens.

---

### Issue Team Token

Generate a long-lived authentication token for a team (used by integrations like Slack, GitHub webhooks).

```http
POST /api/v1/admin/orgs/{org_id}/teams/{team_node_id}/tokens
Authorization: Bearer <ADMIN_TOKEN>
Content-Type: application/json
```

**Response:**
```json
{
  "token": "ifx_team_abc123...",
  "issued_at": "2026-01-12T10:30:00Z"
}
```

**⚠️ Important:** Save this token securely - it won't be shown again!

### List Team Tokens

```http
GET /api/v1/admin/orgs/{org_id}/teams/{team_node_id}/tokens
Authorization: Bearer <ADMIN_TOKEN>
```

**Response:**
```json
[
  {
    "id": "token-id-1",
    "label": null,
    "issued_at": "2026-01-12T10:30:00Z",
    "issued_by": "admin",
    "last_used": "2026-01-12T15:20:00Z",
    "revoked_at": null
  }
]
```

### Revoke Team Token

```http
POST /api/v1/admin/orgs/{org_id}/teams/{team_node_id}/tokens/{token_id}/revoke
Authorization: Bearer <ADMIN_TOKEN>
```

### Issue Impersonation Token (Short-lived)

Generate a short-lived token for temporary access (useful for UI sessions).

```http
POST /api/v1/admin/orgs/{org_id}/teams/{team_node_id}/impersonation-token
Authorization: Bearer <ADMIN_TOKEN>
Content-Type: application/json

{
  "ttl_seconds": 3600
}
```

**Response:**
```json
{
  "token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "expires_at": "2026-01-12T11:30:00Z"
}
```

---

## Agent Execution

### Run Agent (Admin-Initiated)

Execute an AI agent for a specific team.

```http
POST /api/v1/admin/agents/run
X-Admin-Token: <ADMIN_TOKEN>
Content-Type: application/json

{
  "team_node_id": "team-sre",
  "message": "Investigate why the payments-api pod is crashing",
  "context": {
    "incident_id": "INC-12345",
    "severity": "high"
  }
}
```

**Response:**
```json
{
  "run_id": "run_abc123...",
  "status": "running",
  "team_node_id": "team-sre",
  "started_at": "2026-01-12T10:30:00Z"
}
```

### Get Agent Run Status

```http
GET /api/v1/admin/agents/runs/{run_id}
X-Admin-Token: <ADMIN_TOKEN>
```

**Response:**
```json
{
  "run_id": "run_abc123...",
  "status": "completed",
  "team_node_id": "team-sre",
  "started_at": "2026-01-12T10:30:00Z",
  "completed_at": "2026-01-12T10:32:15Z",
  "result": {
    "message": "I investigated the payments-api pod crashes...",
    "tools_used": ["kubectl", "datadog"],
    "findings": [...]
  }
}
```

**Status values:**
- `running` - Agent is currently executing
- `completed` - Agent finished successfully
- `failed` - Agent encountered an error
- `timeout` - Agent exceeded time limit

---

## Configuration Management

### Get Team Configuration

Retrieve the effective configuration for a team (including inherited settings).

```http
GET /api/v1/admin/orgs/{org_id}/nodes/{team_node_id}/config
Authorization: Bearer <ADMIN_TOKEN>
```

**Response:**
```json
{
  "org_id": "your-org-id",
  "node_id": "team-sre",
  "config": {
    "agents": {
      "planner": {
        "enabled": true,
        "model": {
          "name": "gpt-5.2",
          "temperature": 0.3
        }
      }
    },
    "integrations": {
      "slack": {
        "enabled": true,
        "bot_token": "xoxb-***"
      }
    }
  },
  "version": 5
}
```

### Update Team Configuration

Update configuration for a specific team.

```http
PUT /api/v1/admin/orgs/{org_id}/nodes/{team_node_id}/config
Authorization: Bearer <ADMIN_TOKEN>
Content-Type: application/json

{
  "patch": {
    "integrations": {
      "slack": {
        "enabled": true,
        "channel_id": "C12345678"
      }
    }
  },
  "merge": true
}
```

**Parameters:**
- `patch` - The configuration changes to apply
- `merge` - If `true`, deep-merges with existing config. If `false`, replaces entire config.

**Response:**
```json
{
  "org_id": "your-org-id",
  "node_id": "team-sre",
  "config": {...},
  "version": 6
}
```

### Get Configuration Audit History

View the change history for a team's configuration.

```http
GET /api/v1/admin/orgs/{org_id}/nodes/{team_node_id}/config/audit?limit=50
Authorization: Bearer <ADMIN_TOKEN>
```

**Response:**
```json
[
  {
    "version": 6,
    "changed_at": "2026-01-12T10:30:00Z",
    "changed_by": "admin@acme-corp.com",
    "change_type": "patch",
    "config_snapshot": {...}
  },
  {
    "version": 5,
    "changed_at": "2026-01-11T15:20:00Z",
    "changed_by": "admin@acme-corp.com",
    "change_type": "patch",
    "config_snapshot": {...}
  }
]
```

### Rollback Configuration

Revert to a previous configuration version.

```http
POST /api/v1/admin/orgs/{org_id}/nodes/{team_node_id}/config/rollback
Authorization: Bearer <ADMIN_TOKEN>
Content-Type: application/json

{
  "version": 5
}
```

---

## Common Examples

### Complete Initial Setup

```bash
#!/bin/bash
set -e

# Configuration
ORG_ID="acme-corp"
BASE_URL="https://incidentfox.acme-corp.com"
ADMIN_TOKEN="your-admin-token"

# 1. Create organization
curl -X POST "$BASE_URL/api/v1/admin/orgs/$ORG_ID/nodes" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"node_id\": \"$ORG_ID\",
    \"parent_id\": null,
    \"node_type\": \"org\",
    \"name\": \"Acme Corp\"
  }"

# 2. Create SRE team
curl -X POST "$BASE_URL/api/v1/admin/orgs/$ORG_ID/nodes" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"node_id\": \"team-sre\",
    \"parent_id\": \"$ORG_ID\",
    \"node_type\": \"team\",
    \"name\": \"SRE Team\"
  }"

# 3. Generate team token
TEAM_TOKEN=$(curl -s -X POST "$BASE_URL/api/v1/admin/orgs/$ORG_ID/teams/team-sre/tokens" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  | jq -r '.token')

echo "Team token: $TEAM_TOKEN"

# 4. Test agent run
curl -X POST "$BASE_URL/api/v1/admin/agents/run" \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"team_node_id\": \"team-sre\",
    \"message\": \"List available tools\"
  }"
```

### Bulk Team Creation

```bash
#!/bin/bash
ORG_ID="acme-corp"
BASE_URL="https://incidentfox.acme-corp.com"
ADMIN_TOKEN="your-admin-token"

TEAMS=("team-sre" "team-devops" "team-platform" "team-security")

for team in "${TEAMS[@]}"; do
  echo "Creating $team..."
  curl -X POST "$BASE_URL/api/v1/admin/orgs/$ORG_ID/nodes" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{
      \"node_id\": \"$team\",
      \"parent_id\": \"$ORG_ID\",
      \"node_type\": \"team\",
      \"name\": \"${team/team-/}\"
    }"
done
```

---

## Error Responses

All API endpoints return standard HTTP status codes:

**200 OK** - Request successful
```json
{
  "status": "success",
  "data": {...}
}
```

**400 Bad Request** - Invalid request body or parameters
```json
{
  "detail": "Invalid node_type: must be 'org', 'team', or 'workgroup'"
}
```

**401 Unauthorized** - Missing or invalid authentication token
```json
{
  "detail": "Missing admin token"
}
```

**403 Forbidden** - Insufficient permissions
```json
{
  "detail": "Access denied: you can only access org 'acme-corp'"
}
```

**404 Not Found** - Resource doesn't exist
```json
{
  "detail": "Node not found: team-does-not-exist"
}
```

**409 Conflict** - Resource already exists
```json
{
  "detail": "Node already exists: team-sre"
}
```

**500 Internal Server Error** - Server-side error
```json
{
  "detail": "Internal server error"
}
```

---

## Rate Limits

- **Admin endpoints:** 100 requests per minute per IP
- **Agent runs:** 50 concurrent runs per organization
- **Token generation:** 10 tokens per minute per organization

Exceeding rate limits returns `429 Too Many Requests`.

---

## Support

- 📖 **Documentation:** [Installation Guide](./installation-guide.md)
- 💬 **Email:** support@incidentfox.ai
- 🐛 **Issues:** [GitHub Issues](https://github.com/incidentfox/incidentfox/issues)

---

**Document Version:** 1.0.0
**Last Updated:** 2026-01-12
**API Version:** v1

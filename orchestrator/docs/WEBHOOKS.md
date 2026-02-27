# Orchestrator - Webhook Routing

The Orchestrator service receives all external webhooks and routes them to appropriate teams.

---

## Webhook Endpoints

All webhooks point to Orchestrator (not Agent):

| Endpoint | Purpose | External URL |
|----------|---------|--------------|
| `/webhooks/slack/events` | Slack Events API (@mentions) | `https://on3vboii0g.execute-api.us-west-2.amazonaws.com/webhooks/slack/events` |
| `/webhooks/slack/interactions` | Slack buttons/modals | `https://on3vboii0g.execute-api.us-west-2.amazonaws.com/webhooks/slack/interactions` |
| `/webhooks/github` | GitHub App webhooks | `https://on3vboii0g.execute-api.us-west-2.amazonaws.com/webhooks/github` |
| `/webhooks/pagerduty` | PagerDuty V3 webhooks | `https://on3vboii0g.execute-api.us-west-2.amazonaws.com/webhooks/pagerduty` |
| `/webhooks/incidentio` | Incident.io webhooks | `https://on3vboii0g.execute-api.us-west-2.amazonaws.com/webhooks/incidentio` |

**Note**: The external URL uses AWS API Gateway (`on3vboii0g`) which proxies to the internal ALB.

---

## Routing Flow

```
External Service (Slack, GitHub, etc.)
    ↓ webhook
AWS API Gateway (on3vboii0g)
    ↓ HTTPS
ALB (k8s-incident-incident-...)
    ↓
Orchestrator Pod
    ↓ 1. Verify signature
    ↓ 2. Return 200 OK immediately (< 3s)
    ↓ 3. Extract routing identifiers
    ↓ 4. Lookup team via Config Service
    ↓ 5. Get impersonation token
    ↓ 6. Forward to Agent service
    ↓
Agent Pod
    ↓ Execute investigation
    ↓ Post results to Slack/GitHub/etc.
```

---

## Routing Identifier Extraction

The Orchestrator extracts identifiers from webhook payloads:

### Slack Events

```json
{
  "event": {
    "channel": "C0A4967KRBM"
  }
}
```

**Extracted**: `slack_channel_id = "C0A4967KRBM"`

### GitHub Webhooks

```json
{
  "repository": {
    "full_name": "incidentfox/mono-repo"
  }
}
```

**Extracted**: `github_repo = "incidentfox/mono-repo"`

### PagerDuty Webhooks

```json
{
  "event": {
    "data": {
      "service": {
        "id": "PXXXXXX"
      }
    }
  }
}
```

**Extracted**: `pagerduty_service_id = "PXXXXXX"`

### Incident.io Webhooks

```json
{
  "alert_source_config_id": "01KEGMSPPCKFPYHT2ZSNQ7WY3J"
}
```

**Extracted**: `incidentio_alert_source_id = "01KEGMSPPCKFPYHT2ZSNQ7WY3J"`

---

## Config Service Lookup

Once identifiers are extracted, Orchestrator calls Config Service:

```bash
POST /api/v1/internal/routing/lookup
{
  "identifiers": {
    "slack_channel_id": "C0A4967KRBM"
  }
}
```

Response:
```json
{
  "found": true,
  "org_id": "extend",
  "team_node_id": "extend-sre",
  "matched_by": "slack_channel_id",
  "team_token": "55a3eb51..."
}
```

See: `/docs/ROUTING_DESIGN.md` for full routing specification.

---

## Lookup Priority Order

If multiple identifiers match, this priority order is used:

1. `incidentio_team_id` (highest)
2. `pagerduty_service_id`
3. `slack_channel_id`
4. `github_repo`
5. `coralogix_team_name`
6. `incidentio_alert_source_id`
7. `service` (fallback - least specific)

---

## Signature Verification

### Slack

```python
import hmac
import hashlib

def verify_slack_signature(request_body, timestamp, signature, signing_secret):
    basestring = f"v0:{timestamp}:{request_body}".encode('utf-8')
    my_signature = 'v0=' + hmac.new(
        signing_secret.encode('utf-8'),
        basestring,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(my_signature, signature)
```

**Headers Required**:
- `X-Slack-Request-Timestamp`
- `X-Slack-Signature`

### GitHub

```python
import hmac
import hashlib

def verify_github_signature(request_body, signature, webhook_secret):
    expected = 'sha256=' + hmac.new(
        webhook_secret.encode('utf-8'),
        request_body,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
```

**Header Required**:
- `X-Hub-Signature-256`

---

## Error Handling

### No Team Found

If routing lookup fails:

```json
{
  "error": "No team found for identifiers",
  "identifiers": {"slack_channel_id": "C_UNKNOWN"}
}
```

**Action**: Orchestrator logs error, returns 200 OK (to avoid retry storms)

### Agent Execution Fails

If agent service is down:

```json
{
  "error": "Failed to contact agent service"
}
```

**Action**:
- Orchestrator posts error to Slack channel
- Logs detailed error for debugging
- Returns 200 OK (webhook already acknowledged)

### Signature Verification Fails

```json
{
  "error": "Invalid signature"
}
```

**Action**: Return 403 Forbidden immediately

---

## Timeout Handling

**Slack 3-Second Rule**: Slack requires 200 OK within 3 seconds.

**Implementation**:
```python
@app.post("/webhooks/slack/events")
async def slack_events(request: Request):
    # 1. Verify signature
    verify_slack_signature(...)

    # 2. Return 200 OK immediately
    # Note: Using background task to avoid blocking
    background_tasks.add_task(process_slack_event, event_data)

    return {"ok": True}

async def process_slack_event(event_data):
    # 3. Lookup routing (can take 1-2 seconds)
    team = await config_service.lookup_routing(...)

    # 4. Forward to agent (can take 30-300 seconds)
    await agent_service.run_investigation(...)
```

---

## Testing Webhooks

### Test Slack

```bash
# Simulate Slack mention
curl -X POST http://orchestrator:8080/webhooks/slack/events \
  -H "Content-Type: application/json" \
  -H "X-Slack-Request-Timestamp: $(date +%s)" \
  -H "X-Slack-Signature: v0=..." \
  -d '{
    "event": {
      "type": "app_mention",
      "channel": "C0A4967KRBM",
      "text": "Investigate error spike"
    }
  }'
```

### Test GitHub

```bash
curl -X POST http://orchestrator:8080/webhooks/github \
  -H "Content-Type: application/json" \
  -H "X-Hub-Signature-256: sha256=..." \
  -d '{
    "action": "opened",
    "pull_request": {...},
    "repository": {"full_name": "incidentfox/mono-repo"}
  }'
```

### Test Routing Lookup

```bash
kubectl run -n incidentfox test-routing --image=curlimages/curl --rm -it --restart=Never -- \
  curl -s -X POST "http://incidentfox-config-service:8080/api/v1/internal/routing/lookup" \
  -H "X-Internal-Service: orchestrator" \
  -H "Content-Type: application/json" \
  -d '{"identifiers":{"slack_channel_id":"C0A4967KRBM"}}'
```

---

## Configuration

### Team Routing Config

Teams claim routing identifiers in their config:

```json
{
  "routing": {
    "slack_channel_ids": ["C0A4967KRBM"],
    "github_repos": ["incidentfox/mono-repo"],
    "pagerduty_service_ids": ["PXXXXXX"],
    "incidentio_alert_source_ids": ["01KEGMSPPCKFPYHT2ZSNQ7WY3J"],
    "coralogix_team_names": ["otel-demo"],
    "services": ["payment", "checkout"]
  }
}
```

**Validation**: Each identifier can only belong to ONE team per org.

### Update Routing

```bash
curl -X PUT "http://config-service:8080/api/v1/config/me" \
  -H "Authorization: Bearer <TEAM_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "routing": {
      "slack_channel_ids": ["C0A4967KRBM"],
      "services": ["payment"]
    }
  }'
```

---

## Webhook Configuration (External Services)

### Slack App

1. Go to https://api.slack.com/apps
2. Select your app → Event Subscriptions
3. Set Request URL: `https://on3vboii0g.execute-api.us-west-2.amazonaws.com/webhooks/slack/events`
4. Subscribe to events: `app_mention`, `message.channels`, `message.groups`

### GitHub App

1. Go to GitHub App settings
2. Set Webhook URL: `https://on3vboii0g.execute-api.us-west-2.amazonaws.com/webhooks/github`
3. Set Webhook secret (stored in K8s secret `incidentfox-github`)
4. Subscribe to events: `pull_request`, `issues`, `workflow_run`

### Incident.io

1. Go to Incident.io → Settings → Webhooks
2. Add webhook: `https://on3vboii0g.execute-api.us-west-2.amazonaws.com/webhooks/incidentio`
3. Select events: `private_incident.incident_created_v2`

### PagerDuty

1. Go to PagerDuty → Integrations → Generic Webhooks (v3)
2. Set Webhook URL: `https://on3vboii0g.execute-api.us-west-2.amazonaws.com/webhooks/pagerduty`
3. Select events: `incident.triggered`, `incident.acknowledged`

---

## Monitoring

### Check Webhook Logs

```bash
kubectl logs -n incidentfox deploy/incidentfox-orchestrator --tail=100 -f | grep webhook
```

### Webhook Metrics

Key metrics to track:
- Webhook receipt rate
- Signature verification failures
- Routing lookup failures
- Agent forwarding errors
- End-to-end latency

---

## Related Documentation

- `/docs/ROUTING_DESIGN.md` - Routing design spec
- `/orchestrator/docs/SLACK_INTEGRATION.md` - Slack-specific flow
- `/orchestrator/docs/PROVISIONING.md` - Team provisioning
- `/config_service/docs/API_REFERENCE.md` - Config Service API

# Staging Deployment Summary - Per-Agent Model Settings

## Deployed Services ✅

All services successfully deployed to **staging EKS (incidentfox-demo)** in namespace **incidentfox**:

1. **slack-bot** - Build ID: 22044683764
   - Image: `103002841599.dkr.ecr.us-west-2.amazonaws.com/incidentfox-slack-bot:latest`
   - Contains: Agent config UI in Home tab
   
2. **agent (sre-agent)** - Build ID: 22044685351
   - Image: `103002841599.dkr.ecr.us-west-2.amazonaws.com/incidentfox-agent:latest`
   - Contains: PreToolUse hook for per-subagent context switching
   
3. **credential-resolver** - Build ID: 22044686388
   - Image: `103002841599.dkr.ecr.us-west-2.amazonaws.com/credential-resolver:latest`
   - Contains: Header injection logic for X-Agent-* headers

## What's New

### 1. Slack Bot Home Tab UI
- New "Agent Configuration" section in Home tab
- "View Agents" button opens modal showing current config
- "Edit JSON" button opens JSON editor with validation
- Validates temperature (0-1), max_tokens (positive), top_p (0-1)
- Saves to config_service via REST API

### 2. Per-Subagent Model Settings
- Each subagent can have its own temperature, max_tokens, top_p
- PreToolUse hook switches context before each subagent invocation
- Headers automatically injected into LLM API calls
- credential-proxy reads headers and applies to request body

## Testing Plan

### Test 1: Access the Home Tab UI

1. Open Slack staging workspace
2. Click on IncidentFox app in the sidebar
3. Go to "Home" tab
4. Look for "Agent Configuration" section (between AI Model and Connected Integrations)
5. Click "View Agents" button
6. Should see current agent config modal with "Edit JSON" button

### Test 2: Configure Different Providers (OpenAI vs Anthropic)

**Goal**: Verify headers are passed correctly to different providers

**Config to test**:
```json
{
  "agents": {
    "claude-investigator": {
      "enabled": true,
      "model": {
        "name": "claude-sonnet-4-20250514",
        "temperature": 0.3,
        "max_tokens": 4000
      },
      "prompt": {
        "system": "You are a methodical SRE investigator",
        "prefix": "Use for careful, step-by-step analysis"
      }
    },
    "gpt-creative": {
      "enabled": true,
      "model": {
        "name": "gpt-4o",
        "temperature": 0.8,
        "max_tokens": 2000
      },
      "prompt": {
        "system": "You are a creative problem solver",
        "prefix": "Use for brainstorming and creative solutions"
      }
    }
  }
}
```

**Steps**:
1. Paste the config into the JSON editor
2. Click "Save"
3. Verify success message in Slack DM
4. Trigger investigation: `@IncidentFox investigate this error` (with some error context)
5. Ask root agent to delegate to claude-investigator
6. Observe response (should be from Claude with temp=0.3)
7. Ask root agent to delegate to gpt-creative
8. Observe response (should be from GPT-4o with temp=0.8)

**Expected Results**:
- claude-investigator: More conservative, consistent responses
- gpt-creative: More varied, creative responses
- credential-proxy logs show different model names
- Different API endpoints called (api.anthropic.com vs api.openai.com)

### Test 3: Temperature Variation

**Config to test**:
```json
{
  "agents": {
    "deterministic": {
      "enabled": true,
      "model": {"temperature": 0.0},
      "prompt": {"system": "You are a deterministic agent"}
    },
    "creative": {
      "enabled": true,
      "model": {"temperature": 1.0},
      "prompt": {"system": "You are a creative agent"}
    }
  }
}
```

**Steps**:
1. Configure agents via Slack UI
2. Ask same question 3 times to deterministic agent
3. Responses should be nearly identical
4. Ask same question 3 times to creative agent
5. Responses should be quite varied

### Test 4: Verify Logs

**In credential-proxy logs**:
```bash
kubectl logs -f deployment/credential-resolver -n incidentfox | grep "Agent context\|Applied"
```

Look for:
```
🔍 [DEBUG] Agent context: <agent-name>
🔧 [DEBUG] Applied temperature=<value> from header (agent=<name>)
🔧 [DEBUG] Applied max_tokens=<value> from header (agent=<name>)
🔧 [DEBUG] Applied top_p=<value> from header (agent=<name>)
```

**In sre-agent logs**:
```bash
kubectl logs -f deployment/incidentfox-agent -n incidentfox | grep "Hook\|AGENT"
```

Look for:
```
[Hook] PreToolUse: Set context for subagent '<name>' (temp=<value>, max_tokens=<value>, top_p=<value>)
🔧 [AGENT] Temperature: <value>
🔧 [AGENT] Max tokens: <value>
🔧 [AGENT] Top-p: <value>
```

## Configuration via Web UI (Alternative)

Web UI is deployed at: **https://config.incidentfox.com**

You can also configure agents directly through the web UI if preferred.

## Rollback Plan

If issues occur:

1. **Slack bot**: Revert to previous version
   ```bash
   gh workflow run deploy-eks.yml -f environment=staging -f services=slack-bot
   ```

2. **Agent**: Revert to previous version
   ```bash
   gh workflow run deploy-eks.yml -f environment=staging -f services=agent
   ```

3. **Credential-resolver**: Revert to previous version
   ```bash
   gh workflow run deploy-eks.yml -f environment=staging -f services=credential-resolver
   ```

## Success Indicators ✅

- ✅ Home tab shows "Agent Configuration" section
- ✅ Modal opens with current config
- ✅ JSON editor validates and saves successfully
- ✅ Different providers respond to different agents
- ✅ Temperature variations visible in responses
- ✅ credential-proxy logs show X-Agent-* headers
- ✅ sre-agent logs show PreToolUse hook activity

## Next Steps

1. Test via Slack staging workspace
2. Verify all 4 test scenarios
3. Check logs for header injection
4. If successful → Merge PR #402 and deploy to production
5. If issues → Investigate logs and fix

---

**Deployment Time**: 2026-02-15 22:58 UTC
**Branch**: `feat/sre-agent-per-subagent-model`
**PR**: #402
**Commit**: `8f43a68a`

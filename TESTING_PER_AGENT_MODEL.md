# Testing Per-Agent Model Settings in Staging

## Current Configuration Methods

### 1. Via config_service API (Programmatic)
The config_service has a REST API for managing agent configurations:

**Endpoint:** `POST /api/v2/config`

**Authentication:**
- Bearer token (team token)
- OR X-Org-Id + X-Team-Node-Id headers

**Example Request:**
```bash
curl -X POST https://config-service.staging.incidentfox.ai/api/v2/config \
  -H "Authorization: Bearer $TEAM_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "agents": {
      "investigator": {
        "enabled": true,
        "model": {
          "name": "claude-sonnet-4-20250514",
          "temperature": 0.3,
          "max_tokens": 4000
        },
        "prompt": {
          "system": "You are an SRE investigator",
          "prefix": "Use for incident investigation"
        }
      },
      "openai-specialist": {
        "enabled": true,
        "model": {
          "name": "gpt-4o",
          "temperature": 0.7,
          "max_tokens": 2000
        },
        "prompt": {
          "system": "You are an OpenAI specialist",
          "prefix": "Use for creative solutions"
        }
      }
    }
  }'
```

### 2. Via Web UI (Currently Available)
The config_service has a UI component at `config_service/src/ui/`:
- Access at: https://config.staging.incidentfox.ai (or wherever it's deployed)
- Provides visual interface for configuration
- Supports JSON editing

### 3. Via Slack Bot (NEEDS IMPLEMENTATION)
Currently NOT available. Would need to add to slack-bot.

## Testing Strategy

### Test 1: Different Providers (Anthropic vs OpenAI)
**Goal:** Verify headers are passed correctly to different providers

**Configuration:**
```json
{
  "agents": {
    "claude-agent": {
      "enabled": true,
      "model": {
        "name": "claude-sonnet-4-20250514",
        "temperature": 0.3
      }
    },
    "gpt-agent": {
      "enabled": true,
      "model": {
        "name": "gpt-4o",
        "temperature": 0.7
      }
    }
  }
}
```

**Test:**
1. Ask root agent to delegate to claude-agent
2. Observe response (should be from Claude with temp=0.3)
3. Ask root agent to delegate to gpt-agent
4. Observe response (should be from GPT-4o with temp=0.7)

**Expected Results:**
- claude-agent: More conservative, consistent responses
- gpt-agent: More varied, creative responses
- credential-proxy logs show different model names
- Different API endpoints called (api.anthropic.com vs api.openai.com)

### Test 2: Temperature Variation
**Goal:** Verify temperature settings are applied

**Configuration:**
```json
{
  "agents": {
    "deterministic": {
      "enabled": true,
      "model": {"temperature": 0.0}
    },
    "creative": {
      "enabled": true,
      "model": {"temperature": 1.0}
    }
  }
}
```

**Test:**
1. Ask same question 3 times to deterministic agent
2. Responses should be nearly identical
3. Ask same question 3 times to creative agent
4. Responses should be quite varied

### Test 3: Max Tokens
**Goal:** Verify max_tokens limits are applied

**Configuration:**
```json
{
  "agents": {
    "concise": {
      "enabled": true,
      "model": {"max_tokens": 100}
    },
    "verbose": {
      "enabled": true,
      "model": {"max_tokens": 4000}
    }
  }
}
```

**Test:**
1. Ask complex question to concise agent
2. Response should be cut short (~100 tokens)
3. Ask same question to verbose agent
4. Response should be much longer

## Verification Points

### In credential-proxy Logs
Look for these log messages (from our implementation):

```
🔍 [DEBUG] Agent context: <agent-name>
🔧 [DEBUG] Applied temperature=<value> from header (agent=<name>)
🔧 [DEBUG] Applied max_tokens=<value> from header (agent=<name>)
🔧 [DEBUG] Applied top_p=<value> from header (agent=<name>)
```

### In sre-agent Logs
Look for these log messages:

```
[Hook] PreToolUse: Set context for subagent '<name>' (temp=<value>, max_tokens=<value>, top_p=<value>)
🔧 [AGENT] Temperature: <value>
🔧 [AGENT] Max tokens: <value>
🔧 [AGENT] Top-p: <value>
```

## Deploying to Staging

### Option 1: GitHub Actions (RECOMMENDED)
**File:** `.github/workflows/deploy-staging.yml`

Add/Update workflow to deploy sre-agent:
```yaml
name: Deploy to Staging

on:
  push:
    branches:
      - feat/sre-agent-per-subagent-model

jobs:
  deploy-sre-agent:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Configure kubectl
        # ... kubectl setup ...

      - name: Build and push Docker image
        run: |
          docker build -t incidentfox/sre-agent:staging-${{ github.sha }} sre-agent/
          docker push incidentfox/sre-agent:staging-${{ github.sha }}

      - name: Deploy to staging
        run: |
          kubectl set image deployment/sre-agent \
            sre-agent=incidentfox/sre-agent:staging-${{ github.sha }} \
            -n incidentfox-staging
```

### Option 2: Manual kubectl
```bash
# Build and push
cd sre-agent
docker build -t incidentfox/sre-agent:test-per-agent .
docker push incidentfox/sre-agent:test-per-agent

# Deploy
kubectl set image deployment/sre-agent \
  sre-agent=incidentfox/sre-agent:test-per-agent \
  -n incidentfox-staging

# Verify
kubectl rollout status deployment/sre-agent -n incidentfox-staging
kubectl logs -f deployment/sre-agent -n incidentfox-staging
```

## Slack Bot Enhancement (FUTURE WORK)

### Proposed Slack Command
```
/incidentfox config agents
```

**Response:**
```
Current Agent Configuration:

🤖 investigator (Claude Sonnet, temp=0.3)
🤖 k8s-specialist (Claude Sonnet, temp=0.0)
🤖 log-analyst (GPT-4o, temp=0.5)

To update, use:
/incidentfox config update <json>

Or click here to edit in web UI: [Link]
```

### Implementation Needed

**1. Add to slack-bot:**
```python
# slack-bot/src/handlers/config.py

@app.command("/incidentfox config")
async def handle_config_command(ack, command, client):
    await ack()

    subcommand = command["text"].split()[0] if command["text"] else "show"

    if subcommand == "agents":
        # Show current agent config
        config = await get_team_config(command["team_id"])
        await show_agents_modal(client, command["trigger_id"], config)

    elif subcommand == "update":
        # Show JSON editor modal
        await show_config_editor_modal(client, command["trigger_id"])
```

**2. JSON Validation:**
```python
from pydantic import BaseModel, ValidationError

class AgentModelConfig(BaseModel):
    name: str = "claude-sonnet-4-20250514"
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None

class AgentConfig(BaseModel):
    enabled: bool = True
    model: AgentModelConfig = AgentModelConfig()
    # ... other fields

def validate_agent_config(json_str: str) -> tuple[bool, str]:
    """Validate agent config JSON.

    Returns: (is_valid, error_message)
    """
    try:
        data = json.loads(json_str)
        # Validate each agent
        for name, agent_data in data.get("agents", {}).items():
            AgentConfig(**agent_data)
        return True, ""
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {e}"
    except ValidationError as e:
        return False, f"Invalid config: {e}"
```

**3. Modal with JSON Editor:**
```python
async def show_config_editor_modal(client, trigger_id):
    await client.views_open(
        trigger_id=trigger_id,
        view={
            "type": "modal",
            "callback_id": "config_update",
            "title": {"type": "plain_text", "text": "Update Agent Config"},
            "submit": {"type": "plain_text", "text": "Save"},
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Edit your agent configuration:*"
                    }
                },
                {
                    "type": "input",
                    "block_id": "config_json",
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "json_input",
                        "multiline": True,
                        "placeholder": {"type": "plain_text", "text": "Paste your JSON here..."}
                    },
                    "label": {"type": "plain_text", "text": "Configuration JSON"}
                }
            ]
        }
    )
```

## Current Slack Integration Status

Need to check:
1. Is there already a slack-bot deployment?
2. How is it currently linked to workspaces?
3. Does it have slash commands enabled?

**To find out:**
```bash
# Check if slack-bot exists
ls slack-bot/

# Check current commands
grep -r "@app.command\|@app.event" slack-bot/
```

## Recommended Approach

**Phase 1 (NOW):** Deploy to staging via kubectl
- Get PR #402 merged
- Deploy manually to staging
- Test via direct API calls or existing web UI

**Phase 2 (LATER):** Slack bot enhancement
- Add `/incidentfox config agents` command
- JSON editor modal with validation
- Link to web UI for complex edits

**Phase 3 (FUTURE):** Visual agent builder
- Drag-and-drop agent hierarchy
- Temperature slider UI
- Model selection dropdown

## Quick Test Script

Save this as `test_agent_config.sh`:

```bash
#!/bin/bash

TEAM_TOKEN="your-team-token-here"
CONFIG_URL="https://config-service.staging.incidentfox.ai/api/v2/config"

# Test configuration with 2 different providers
CONFIG='{
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
}'

echo "Updating agent configuration..."
curl -X POST "$CONFIG_URL" \
  -H "Authorization: Bearer $TEAM_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$CONFIG" \
  -w "\nHTTP Status: %{http_code}\n"

echo "\nConfiguration updated! Now test in Slack or via API."
echo "Expected behavior:"
echo "  - claude-investigator: Conservative, analytical (temp=0.3)"
echo "  - gpt-creative: Varied, creative responses (temp=0.8)"
```

## Expected Outcomes

✅ **Success Indicators:**
- Different providers respond to different agents
- Temperature variations visible in response diversity
- credential-proxy logs show X-Agent-* headers
- sre-agent logs show context switching

❌ **Failure Indicators:**
- All agents use same model
- Temperature has no effect
- No header logs in credential-proxy
- No PreToolUse hook logs in sre-agent

## Next Steps After Testing

1. If successful → Merge PR #402
2. Document configuration best practices
3. Consider Slack bot enhancement (Phase 2)
4. Monitor production performance

# Template System

The template system allows organizations to quickly onboard by selecting pre-built use case templates instead of manually configuring multi-agent systems.

---

## Overview

A **template** is a pre-configured multi-agent system optimized for a specific use case:
- Agent topology (which agents, how they delegate)
- Agent prompts (specialized for the use case)
- Tool selection (only relevant tools enabled)
- MCP requirements (which integrations needed)
- Runtime settings (timeouts, max_turns)

**Benefits:**
- Faster onboarding: 5 minutes vs 2-3 days of manual configuration
- Best-practice configurations curated by experts
- Immediate time-to-value for common use cases

---

## Available Templates

| Template | Category | Description |
|----------|----------|-------------|
| **Slack Incident Triage** | incident-response | Multi-agent investigation triggered by Slack mentions |
| **Git CI Auto-Fix** | ci-cd | Automatically diagnose and fix CI/CD failures |
| **AWS Cost Reduction** | finops | Analyze AWS spend and recommend optimizations |
| **Coding Assistant** | coding | General-purpose coding helper |
| **Data Migration Assistant** | data | Plan and validate data migrations |
| **Alert Fatigue Reduction** | incident-response | Correlate and deduplicate alerts |
| **DR Validator** | reliability | Validate disaster recovery configurations |
| **Incident Postmortem** | incident-response | Generate postmortems from incident data |
| **Universal Telemetry** | observability | Query across multiple telemetry platforms |

Templates are stored in `config_service/templates/`.

---

## Using Templates

### Browse Templates (Web UI)

1. Navigate to **Admin Console → Templates**
2. Browse by category or search
3. Click a template to preview its configuration
4. Click **Apply to Team** to use it

### Apply Template (API)

```bash
# List available templates
curl -H "Authorization: Bearer $TEAM_TOKEN" \
  http://config-service:8080/api/v1/templates

# Apply template to team
curl -X POST \
  -H "Authorization: Bearer $TEAM_TOKEN" \
  http://config-service:8080/api/v1/team/templates/{template_id}/apply

# Check current template
curl -H "Authorization: Bearer $TEAM_TOKEN" \
  http://config-service:8080/api/v1/team/template
```

### Customize After Applying

Once a template is applied, you can customize it via the Team Console:
- Modify agent prompts
- Enable/disable specific tools
- Add MCP servers
- Adjust model settings

Customizations are stored as overrides on top of the template baseline.

---

## Creating Templates

### Template JSON Structure

```json
{
  "$schema": "incidentfox-template-v1",
  "$version": "1.0.0",
  "$category": "incident-response",
  "$template_name": "Slack Incident Triage",
  "$template_slug": "slack-incident-triage",
  "$description": "Multi-agent investigation for Slack-triggered incidents",

  "agents": {
    "planner": {
      "name": "Incident Planner",
      "description": "Orchestrates investigation by delegating to specialized agents",
      "enabled": true,
      "model": {
        "name": "gpt-5.2",
        "temperature": 0.3,
        "max_tokens": 4000
      },
      "tools": {
        "think": true,
        "llm_call": true,
        "web_search": true
      },
      "sub_agents": {
        "investigation": true,
        "k8s_agent": true,
        "aws_agent": true
      },
      "prompt": {
        "system": "You are an incident investigation coordinator...",
        "prefix": "",
        "suffix": ""
      },
      "max_turns": 12
    },
    "investigation": {
      "name": "Investigation Agent",
      "description": "Deep-dive investigation with full toolkit",
      "enabled": true,
      "model": {
        "name": "gpt-5.2",
        "temperature": 0.1,
        "max_tokens": 8000
      },
      "tools": {
        "k8s_get_pods": true,
        "k8s_get_pod_logs": true,
        "aws_describe_instances": true,
        "grafana_query_prometheus": true
      },
      "prompt": {
        "system": "You are a senior SRE investigating incidents...",
        "prefix": "",
        "suffix": ""
      }
    }
  },

  "mcp_servers": {
    "kubernetes": {
      "enabled": true,
      "name": "Kubernetes MCP",
      "command": "npx",
      "args": ["-y", "@anthropic/kubernetes-mcp"]
    }
  }
}
```

### Adding a New Template

1. Create a JSON file in `config_service/templates/`
2. Follow the schema above
3. Run the seed script:
   ```bash
   cd config_service
   python scripts/seed_templates.py
   ```
4. Verify in Web UI or via API

### Template Categories

- `incident-response` - Investigation and triage
- `ci-cd` - CI/CD automation
- `finops` - Cost optimization
- `coding` - Development assistance
- `data` - Data operations
- `reliability` - DR, chaos, resilience
- `observability` - Monitoring and telemetry
- `demo` - Demo/example templates

---

## API Reference

### Public Endpoints (Team Auth)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/templates` | List templates with filters |
| GET | `/api/v1/templates/{id}` | Get template details |
| POST | `/api/v1/team/templates/{id}/apply` | Apply template to team |
| GET | `/api/v1/team/template` | Get current template |
| DELETE | `/api/v1/team/template` | Deactivate template |

### Admin Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/admin/templates` | Create template |
| PUT | `/api/v1/admin/templates/{id}` | Update template |
| GET | `/api/v1/admin/templates/{id}/analytics` | Get usage analytics |

---

## Database Schema

### Templates Table

```sql
CREATE TABLE templates (
    id UUID PRIMARY KEY,
    name VARCHAR NOT NULL,
    slug VARCHAR UNIQUE NOT NULL,
    description TEXT,
    category VARCHAR NOT NULL,
    template_json JSONB NOT NULL,
    required_mcps TEXT[],
    required_tools TEXT[],
    is_published BOOLEAN DEFAULT true,
    org_id VARCHAR,  -- NULL for global templates
    usage_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### Template Applications Table

```sql
CREATE TABLE template_applications (
    id UUID PRIMARY KEY,
    template_id UUID REFERENCES templates(id),
    org_id VARCHAR NOT NULL,
    team_node_id VARCHAR NOT NULL,
    applied_at TIMESTAMP DEFAULT NOW(),
    has_customizations BOOLEAN DEFAULT false,
    is_active BOOLEAN DEFAULT true,
    UNIQUE(org_id, team_node_id)  -- One template per team
);
```

---

## Best Practices

1. **Start with a template** - Even if you plan to customize heavily, start with the closest template rather than from scratch

2. **Customize prompts first** - The biggest impact comes from tailoring prompts to your specific domain

3. **Disable unused tools** - Templates enable relevant tools by default, but disable any you don't need

4. **Test before deploying** - Use the preview feature to see the full configuration before applying

5. **Track customizations** - The system tracks if you've customized a template; consider forking it as a custom template if changes are significant

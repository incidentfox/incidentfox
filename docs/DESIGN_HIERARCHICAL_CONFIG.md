# Hierarchical Configuration System Design

## Executive Summary

This document describes a **unified hierarchical configuration system** for IncidentFox that enables:

1. **Dynamic Agent Topology** — Agents defined as JSON, with configurable prompts, tools, and sub-agents
2. **Tool Configuration with Required Fields** — Some tools need team-specific config (e.g., Grafana URL)
3. **Inheritance with Override** — Org sets defaults, teams inherit and can override
4. **Required vs Optional Fields** — Some configs must be set at team level, others can use defaults

---

## 1. Core Concepts

### 1.1 Configuration Hierarchy

```
┌─────────────────────────────────────────────────────────────────┐
│                        ORGANIZATION                              │
│  • Default agent topology (preset)                               │
│  • Default prompts for each agent                                │
│  • Default tools enabled/disabled                                │
│  • Org-wide integrations (Slack app, OpenAI key)                │
└─────────────────────────────────┬───────────────────────────────┘
                                  │ inherits
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                      ORGANIZATIONAL UNIT                         │
│  (Optional intermediate level: "Platform Team", "SRE Org")      │
│  • Can override parent configs                                   │
│  • Sets defaults for child teams                                 │
└─────────────────────────────────┬───────────────────────────────┘
                                  │ inherits
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                           TEAM                                   │
│  • Final effective config = merge(org, unit, team overrides)    │
│  • MUST fill in required fields (e.g., Grafana URL)             │
│  • Can customize prompts, disable tools, add MCPs               │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 Merge Strategy

```python
def compute_effective_config(org_config, unit_config, team_config):
    """
    Deep merge with team taking precedence.

    Rules:
    - Primitives: child overrides parent
    - Lists: child replaces parent entirely
    - Dicts: recursive merge at key level
    """
    base = deep_merge(org_config, unit_config)
    effective = deep_merge(base, team_config)

    # Validate required fields are set
    validate_required_fields(effective)

    # Validate dependencies
    validate_dependencies(effective)

    return effective
```

### 1.3 Field Types

| Type | Description | Example |
|------|-------------|---------|
| `inherited` | Uses parent value if not set | `model: "gpt-5.2"` |
| `required` | Must be set at team level (no default) | `grafana_url: null` |
| `locked` | Set by org, teams cannot override | `max_tokens: 100000` |

---

## 2. Agent Configuration Schema

### 2.1 Agent Definition (JSON)

```json
{
  "agents": {
    "planner": {
      "enabled": true,
      "name": "Planner",
      "description": "Orchestrates complex tasks by delegating to specialized agents",
      
      "model": {
        "name": "gpt-5.2",
        "temperature": 0.3,
        "max_tokens": 16000
      },
      
      "prompt": {
        "system": "You are an expert incident coordinator...",
        "prefix": "",
        "suffix": ""
      },
      
      "max_turns": 30,

      "tools": {
        "think": true,
        "llm_call": true,
        "web_search": true
      },

      "sub_agents": {
        "investigation": true,
        "k8s": true,
        "aws": true,
        "metrics": true,
        "coding": true
      },

      "mcps": {
        "github-mcp": true
      },

      "handoff_strategy": "agent_as_tool"
    },
    
    "investigation": {
      "enabled": true,
      "name": "Investigation Agent",
      
      "model": {
        "name": "gpt-5.2",
        "temperature": 0.4
      },
      
      "prompt": {
        "system": "You are an expert SRE..."
      },
      
      "tools": {
        "*": true,
        "write_file": false,
        "docker_exec": false
      },

      "sub_agents": {},

      "mcps": {}
    }
  }
}
```

### 2.2 Agent Config Fields

| Field | Type | Inheritable | Description |
|-------|------|-------------|-------------|
| `enabled` | bool | Yes | Whether agent is available |
| `name` | string | Yes | Display name |
| `model.name` | string | Yes | LLM model to use |
| `model.temperature` | float | Yes | LLM temperature |
| `model.max_tokens` | int | Yes | Max output tokens |
| `prompt.system` | string | Yes | System prompt |
| `prompt.prefix` | string | Yes | Added before user message |
| `prompt.suffix` | string | Yes | Added after user message |
| `max_turns` | int | Yes | Max LLM turns |
| `tools.enabled` | list | Yes | Tools to enable ("*" = all) |
| `tools.disabled` | list | Yes | Tools to disable |
| `tools.configured` | dict | Partial | Tool-specific config (see §3) |
| `sub_agents` | list | Yes | Agents this can delegate to |

### 2.3 Inheritance Example

**Org Config:**
```json
{
  "agents": {
    "investigation": {
      "model": { "name": "gpt-5.2", "temperature": 0.4 },
      "prompt": { "system": "You are an SRE..." },
      "max_turns": 20
    }
  }
}
```

**Team Override:**
```json
{
  "agents": {
    "investigation": {
      "prompt": { 
        "system": "You are an SRE specializing in payments systems...",
        "suffix": "Always check the payments-db first."
      },
      "max_turns": 30
    }
  }
}
```

**Effective Config (merged):**
```json
{
  "agents": {
    "investigation": {
      "model": { "name": "gpt-5.2", "temperature": 0.4 },  // inherited
      "prompt": { 
        "system": "You are an SRE specializing in payments systems...",  // overridden
        "suffix": "Always check the payments-db first."  // added
      },
      "max_turns": 30  // overridden
    }
  }
}
```

---

## 3. Tool Configuration Schema

### 3.1 Problem Statement

Some tools work out of the box (e.g., `list_pods` just needs K8s access).  
Others require configuration (e.g., `grafana_query_prometheus` needs a URL).

We need:
1. Org to define which tools are available
2. Org to set default values where possible
3. Team to fill in required values they own

### 3.2 Tool Definition Schema

```json
{
  "tools": {
    "grafana_query_prometheus": {
      "enabled": true,
      "category": "observability",
      "description": "Query Prometheus via Grafana",
      
      "config_schema": {
        "base_url": {
          "type": "string",
          "required": true,
          "description": "Grafana base URL",
          "example": "https://grafana.mycompany.com"
        },
        "api_key": {
          "type": "secret",
          "required": true,
          "description": "Grafana API key"
        },
        "default_datasource": {
          "type": "string",
          "required": false,
          "default": "prometheus",
          "description": "Default datasource name"
        },
        "org_id": {
          "type": "integer",
          "required": false,
          "default": 1
        }
      },
      
      "config_values": {
        "base_url": null,
        "api_key": null,
        "default_datasource": "prometheus",
        "org_id": 1
      }
    },
    
    "list_pods": {
      "enabled": true,
      "category": "kubernetes",
      "description": "List pods in a namespace",
      "config_schema": {},
      "config_values": {}
    }
  }
}
```

### 3.3 Tool Config Inheritance

```
Org Level:
  grafana_query_prometheus:
    config_values:
      base_url: null           # Required - team must set
      api_key: null            # Required - team must set
      default_datasource: "prometheus"  # Default
      org_id: 1                         # Default

Team Level (override):
  grafana_query_prometheus:
    config_values:
      base_url: "https://grafana.payments-team.internal"
      api_key: "glsa_xxx..."
      # default_datasource and org_id inherited from org
```

### 3.4 Validation

Before agent runs, validate:

```python
def validate_tool_config(tool_name: str, effective_config: dict) -> list[str]:
    """Return list of missing required fields."""
    errors = []
    schema = get_tool_schema(tool_name)
    values = effective_config.get("config_values", {})
    
    for field, field_schema in schema.get("config_schema", {}).items():
        if field_schema.get("required") and not values.get(field):
            errors.append(f"{tool_name}.{field} is required but not set")
    
    return errors
```

---

## 4. MCP Configuration Schema

### 4.1 MCP Definition

MCPs (Model Context Protocol servers) are similar to tools but:
- They're external processes/services
- They may have their own auth
- Teams might add custom MCPs

```json
{
  "mcps": {
    "default": [
      {
        "id": "github-mcp",
        "name": "GitHub MCP",
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": {
          "GITHUB_TOKEN": "${github_token}"
        },
        "config_schema": {
          "github_token": {
            "type": "secret",
            "required": true
          }
        },
        "enabled_by_default": true
      }
    ],
    
    "team_added": []
  }
}
```

### 4.2 MCP Inheritance

| Field | Behavior |
|-------|----------|
| `default` | Org-defined MCPs, teams inherit |
| `team_added` | Team-specific MCPs, appended |
| `disabled` | List of MCP IDs to disable (team can disable org MCPs) |

---

## 5. Integration Configuration Schema

### 5.1 Org-Level Integrations

Some integrations are org-wide (shared credentials):

```json
{
  "integrations": {
    "openai": {
      "level": "org",
      "locked": true,
      "config": {
        "api_key": "sk-...",
        "org_id": "org-..."
      }
    },
    
    "slack": {
      "level": "org",
      "locked": false,
      "config": {
        "bot_token": "xoxb-...",
        "app_token": "xapp-..."
      }
    }
  }
}
```

### 5.2 Team-Level Integrations

Some integrations have team-specific config:

```json
{
  "integrations": {
    "slack": {
      "team_config": {
        "default_channel": "#payments-incidents",
        "mention_oncall": true,
        "thread_replies": true
      }
    },
    
    "grafana": {
      "level": "team",
      "required": true,
      "config_schema": {
        "base_url": { "type": "string", "required": true },
        "api_key": { "type": "secret", "required": true }
      },
      "config": {
        "base_url": "https://grafana.payments.internal",
        "api_key": "glsa_..."
      }
    },
    
    "google_docs": {
      "level": "team",
      "required": false,
      "config": {
        "runbook_folder_id": "1abc...",
        "postmortem_folder_id": "2def..."
      }
    }
  }
}
```

### 5.3 Integration Field Types

| Level | Who Sets | Who Can Override | Examples |
|-------|----------|------------------|----------|
| `org` + `locked` | Org Admin | Nobody | OpenAI API key |
| `org` + `!locked` | Org Admin | Team can extend | Slack bot token |
| `team` + `required` | Team | Team | Grafana URL |
| `team` + `!required` | Team (optional) | Team | Google Docs folder |

---

## 6. Database Schema Changes

### 6.1 New Tables

```sql
-- Unified configuration store
CREATE TABLE node_configurations (
    id UUID PRIMARY KEY,
    org_id VARCHAR(64) NOT NULL,
    node_id VARCHAR(128) NOT NULL,  -- org root, unit, or team
    node_type VARCHAR(32) NOT NULL,  -- 'org', 'unit', 'team'
    
    -- Full JSON config for this node (overrides only, not computed)
    config_json JSONB NOT NULL DEFAULT '{}',
    
    -- Cached computed effective config (for performance)
    effective_config_json JSONB,
    effective_config_computed_at TIMESTAMP,
    
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    updated_by VARCHAR(128),
    
    UNIQUE(org_id, node_id)
);

-- Config field metadata (what fields exist, their types, etc.)
CREATE TABLE config_field_definitions (
    id UUID PRIMARY KEY,
    path VARCHAR(256) NOT NULL,  -- e.g., "agents.investigation.model.temperature"
    field_type VARCHAR(32) NOT NULL,  -- string, number, boolean, secret, object, array
    
    required BOOLEAN DEFAULT FALSE,
    default_value JSONB,
    locked_at_level VARCHAR(32),  -- 'org', 'unit', or NULL (not locked)
    
    display_name VARCHAR(128),
    description TEXT,
    example_value JSONB,
    validation_regex VARCHAR(256),
    
    category VARCHAR(64),  -- 'agent', 'tool', 'mcp', 'integration'
    
    created_at TIMESTAMP DEFAULT NOW()
);

-- Track which required fields are missing at each node
CREATE TABLE config_validation_status (
    id UUID PRIMARY KEY,
    org_id VARCHAR(64) NOT NULL,
    node_id VARCHAR(128) NOT NULL,
    
    missing_required_fields JSONB DEFAULT '[]',
    validation_errors JSONB DEFAULT '[]',
    is_valid BOOLEAN DEFAULT FALSE,
    
    validated_at TIMESTAMP DEFAULT NOW()
);
```

### 6.2 Existing Table Changes

```sql
-- org_nodes: add config reference
ALTER TABLE org_nodes ADD COLUMN config_id UUID REFERENCES node_configurations(id);

-- team_tokens: no changes needed (token → team → config resolution)
```

---

## 7. API Changes

### 7.1 Config CRUD

```
# Get effective config for a node (computed/merged)
GET /api/v1/admin/orgs/{org_id}/nodes/{node_id}/effective-config

# Get raw config for a node (overrides only)
GET /api/v1/admin/orgs/{org_id}/nodes/{node_id}/config

# Update config for a node
PATCH /api/v1/admin/orgs/{org_id}/nodes/{node_id}/config
Body: { "agents": { "investigation": { "max_turns": 30 } } }

# Validate config (returns missing required fields)
POST /api/v1/admin/orgs/{org_id}/nodes/{node_id}/config/validate

# Get config schema (all available fields with types)
GET /api/v1/admin/config-schema
```

### 7.2 Team-Facing Config API

```
# Get my team's effective config
GET /api/v1/team/config

# Update my team's config (only non-locked fields)
PATCH /api/v1/team/config
Body: { "integrations": { "grafana": { "base_url": "..." } } }

# Get list of required fields I need to set
GET /api/v1/team/config/required-fields
Response: {
  "missing": [
    {
      "path": "integrations.grafana.base_url",
      "display_name": "Grafana URL",
      "description": "Your team's Grafana instance URL"
    }
  ]
}
```

---

## 8. UI Changes

### 8.1 Admin UI

**Org Defaults Page** (`/admin/defaults`):
- Tabs: Agents | Tools | MCPs | Integrations
- Each tab shows JSON editor + form view toggle
- Can set defaults, lock fields, define required fields

**Org Tree Page** (`/admin/org-tree`):
- When viewing a node, show "Configuration" panel
- Show inheritance: "Inherited from Org" vs "Overridden here"
- Validation status: ✅ Valid or ⚠️ Missing required fields

### 8.2 Team UI

**Team Config Page** (`/team/settings`):
- Shows effective config with provenance labels
- Form fields for:
  - Required fields (highlighted, must complete)
  - Optional fields (can customize)
  - Inherited fields (read-only or "customize" button)
  - Locked fields (read-only, shows "Set by org admin")

**Config Status Banner**:
```
┌─────────────────────────────────────────────────────────────┐
│ ⚠️ Configuration Incomplete                                 │
│ The following fields are required before agents can run:    │
│ • Grafana URL                                               │
│ • Grafana API Key                                           │
│ [Complete Setup →]                                          │
└─────────────────────────────────────────────────────────────┘
```

### 8.3 Agent Topology Editor

New page: `/admin/agent-topology` or `/team/agent-topology`

```
┌─────────────────────────────────────────────────────────────┐
│ Agent Topology                                    [Reset to Default] │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│         ┌──────────┐                                        │
│         │ Planner  │ ← Click to edit prompt, model, tools   │
│         └────┬─────┘                                        │
│     ┌───────┼───────┬───────┬───────┐                      │
│     ▼       ▼       ▼       ▼       ▼                      │
│  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐                   │
│  │Inv. │ │ K8s │ │ AWS │ │Metr.│ │Code │                   │
│  └─────┘ └─────┘ └─────┘ └─────┘ └─────┘                   │
│                                                             │
│  [+ Add Custom Agent]                                       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 9. Agent Runtime Changes

### 9.1 Dynamic Agent Construction

```python
def build_agent_from_config(agent_id: str, effective_config: dict) -> Agent:
    """Construct an Agent from JSON config."""
    agent_config = effective_config["agents"].get(agent_id)
    if not agent_config or not agent_config.get("enabled", True):
        return None
    
    # Build tools list
    tools = resolve_tools(
        enabled=agent_config["tools"]["enabled"],
        disabled=agent_config["tools"]["disabled"],
        configured=agent_config["tools"].get("configured", {})
    )
    
    # Build sub-agent tools (for planner)
    sub_agent_tools = []
    for sub_id in agent_config.get("sub_agents", []):
        sub_agent = build_agent_from_config(sub_id, effective_config)
        if sub_agent:
            sub_agent_tools.append(make_agent_as_tool(sub_agent))
    
    return Agent(
        name=agent_config["name"],
        instructions=agent_config["prompt"]["system"],
        model=agent_config["model"]["name"],
        model_settings=ModelSettings(
            temperature=agent_config["model"]["temperature"],
            max_tokens=agent_config["model"].get("max_tokens"),
        ),
        tools=tools + sub_agent_tools,
    )


def resolve_tools(enabled: list, disabled: list, configured: dict) -> list:
    """Resolve tool list with configuration."""
    all_tools = get_all_available_tools()
    
    if "*" in enabled:
        result_tools = list(all_tools.values())
    else:
        result_tools = [all_tools[t] for t in enabled if t in all_tools]
    
    # Remove disabled
    result_tools = [t for t in result_tools if t.name not in disabled]
    
    # Inject configuration
    for tool in result_tools:
        if tool.name in configured:
            tool = inject_tool_config(tool, configured[tool.name])
    
    return result_tools
```

### 9.2 Config Validation at Runtime

```python
async def run_agent_with_config(team_node_id: str, query: str):
    """Run agent with team's effective config."""
    config = await get_effective_config(team_node_id)
    
    # Validate required fields
    errors = validate_config(config)
    if errors:
        return {
            "error": "configuration_incomplete",
            "missing_fields": errors,
            "message": "Please complete team configuration before running agents"
        }
    
    # Build and run
    planner = build_agent_from_config("planner", config)
    return await Runner.run(planner, query)
```

---

## 10. Implementation Phases

### Phase 1: Database & Core API ✅ COMPLETE
- [x] Create `node_configurations` table
- [x] Create `config_field_definitions` table
- [x] Create `config_validation_status` table
- [x] Create `config_change_history` table
- [x] Implement `compute_effective_config()` merge logic
- [x] Add CRUD endpoints for config (`/api/v1/config/...`)
- [x] Add validation endpoint
- [x] Add rollback to version support

### Phase 2: Agent Config ✅ COMPLETE
- [x] Define default agent config JSON
- [x] Implement `build_agent_from_config()` in agent_builder.py
- [x] Implement `build_agent_hierarchy()` for sub-agents
- [x] Implement `resolve_tools()` based on config
- [x] Add `ConfigContext` for team-scoped config
- [x] Add `get_planner_for_team()` entry point

### Phase 3: Tool Config ✅ COMPLETE
- [x] Define tool config schemas (TOOL_CONFIG_SCHEMAS)
- [x] Implement tool factories (create_grafana_query_prometheus, etc.)
- [x] Implement `validate_tool_config()` for required fields
- [x] Implement `create_configured_tool()` with injected config

### Phase 4: MCP Config ✅ COMPLETE
- [x] Define MCP config schema (MCPServerConfig)
- [x] Implement MCP inheritance (default + team_added - disabled)
- [x] Implement `resolve_mcp_config()` 
- [x] Implement MCPManager with start/stop lifecycle
- [x] Add environment variable substitution

### Phase 5: Integration Config ✅ COMPLETE
- [x] Define integration config schemas (9 integrations)
- [x] Separate org-level vs team-level fields
- [x] Implement `resolve_integration()` with field merging
- [x] Implement `get_missing_required_integrations()`
- [x] Implement `get_integration_config_for_tool()`

### Phase 6: UI (Pending)
- [ ] Admin UI for config management
- [ ] Team UI for required fields + setup wizard
- [ ] Agent topology editor
- [ ] Validation status banners

---

## 11. Design Decisions (Confirmed)

1. **Secrets Management**: ✅ Store encrypted in DB, decrypt at runtime
   - Simple to implement
   - Can migrate to AWS Secrets Manager later if needed

2. **Config Versioning**: Future enhancement
   - Current: Only latest config stored
   - Future: Git-like versioning with history (not in scope now)

3. **Config Approval**: ✅ Configurable per-field via `requires_approval: true`
   - Each field in config schema can specify if changes need approval
   - Extends existing approval workflow

4. **Custom Agents**: ✅ Teams can create new agents
   - Full flexibility to define new agents with custom prompts + tools
   - Org admin approval optional (can be enabled later if needed)

5. **Tool Restrictions**: ✅ Org can restrict tools
   - Org can set `locked: true` on tool enabled/disabled state
   - Teams cannot override locked tool settings

---

## 12. Success Metrics

| Metric | Target |
|--------|--------|
| Time to onboard new team | < 15 minutes |
| Config validation coverage | 100% of required fields |
| Agent customization adoption | > 50% of teams customize prompts |
| Zero production failures from missing config | 100% |

---

## Appendix A: Full Config Schema Example

```json
{
  "$schema": "incidentfox-config-v1",
  
  "agents": {
    "planner": { ... },
    "investigation": { ... },
    "k8s": { ... },
    "aws": { ... },
    "metrics": { ... },
    "coding": { ... }
  },
  
  "tools": {
    "list_pods": { "enabled": true, "config_schema": {} },
    "grafana_query_prometheus": { 
      "enabled": true, 
      "config_schema": { ... },
      "config_values": { ... }
    }
  },
  
  "mcps": {
    "default": [ ... ],
    "team_added": [ ... ],
    "disabled": [ ... ]
  },
  
  "integrations": {
    "openai": { ... },
    "slack": { ... },
    "grafana": { ... }
  },
  
  "runtime": {
    "max_concurrent_agents": 5,
    "default_timeout_seconds": 300,
    "retry_policy": { ... }
  }
}
```

---

## Appendix B: UI Mockups

*(To be added)*

---

*Document Version: 1.0*  
*Last Updated: 2026-01-06*  
*Authors: IncidentFox Team*


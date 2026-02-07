# Configuration Inheritance System

The configuration system provides hierarchical inheritance that allows organizations to define default configurations while giving teams the flexibility to customize their setup.

---

## Architecture Overview

The configuration system follows a hierarchical structure:

```
System Defaults (platform-provided)
    ↓
Organization Config
    ↓
Unit Config (optional)
    ↓
Team Config
    =
Effective Config (computed)
```

Each level can override or extend configurations from parent levels through intelligent dict-based merging.

---

## Configuration Schema

### Agents

Agents are configured using a dict-based schema that enables granular control:

```json
{
  "agents": {
    "planner": {
      "enabled": true,
      "model": {
        "name": "gpt-5.2",
        "temperature": 0.3
      },
      "tools": {
        "think": true,
        "llm_call": true,
        "web_search": true
      },
      "sub_agents": {
        "investigation": true,
        "k8s": true
      },
      "mcps": {
        "github-mcp": true
      }
    }
  }
}
```

**Key fields:**
- `tools`: Dict mapping tool IDs to boolean (enabled/disabled)
- `sub_agents`: Dict mapping agent IDs to boolean (enabled/disabled)
- `mcps`: Dict mapping MCP server IDs to boolean (enabled/disabled)

### MCP Servers

MCP servers are defined as a dict keyed by MCP ID:

```json
{
  "mcp_servers": {
    "github-mcp": {
      "enabled": true,
      "name": "GitHub MCP Server",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "${github_token}"
      }
    }
  }
}
```

### Tools

Tools are configured with their dependencies and schemas:

```json
{
  "tools": {
    "grafana_query_prometheus": {
      "enabled": true,
      "requires_integration": "grafana",
      "config_schema": { ... },
      "config_values": { ... }
    }
  }
}
```

### Integrations

Integrations provide credentials and configuration for external services:

```json
{
  "integrations": {
    "grafana": {
      "enabled": true,
      "config": {
        "api_key": "secret_value",
        "url": "https://grafana.company.com"
      }
    }
  }
}
```

---

## Inheritance Rules

### Rule 1: Primitives Replace

When a child config defines a primitive value (string, number, boolean), it completely replaces the parent value:

```yaml
# Org
model: "gpt-5.2"

# Team
model: "claude-sonnet-4"

# Effective
model: "claude-sonnet-4"  # Team's value wins
```

### Rule 2: Dicts Merge at Key Level

When a child config defines dict values, keys are merged recursively. This enables additive configuration:

```yaml
# Org
tools: {think: true, llm_call: true, web_search: true}

# Team (adds one tool)
tools: {custom_tool: true}

# Effective (all tools available)
tools: {
  think: true,        # From org
  llm_call: true,     # From org
  web_search: true,   # From org
  custom_tool: true   # From team
}
```

### Rule 3: Override Specific Keys

Teams can override specific keys without affecting others:

```yaml
# Org
tools: {think: true, llm_call: true, web_search: true}

# Team (disables one tool)
tools: {web_search: false}

# Effective
tools: {
  think: true,        # From org
  llm_call: true,     # From org
  web_search: false   # Overridden by team
}
```

### Rule 4: Lists Replace

Lists are replaced entirely (not merged):

```yaml
# Org
some_list: ["a", "b", "c"]

# Team
some_list: ["d", "e"]

# Effective
some_list: ["d", "e"]  # Fully replaced
```

---

## Dependency Validation

The system enforces dependency constraints to prevent breaking configurations:

### Dependency Graph

```
Integrations (base layer)
    ↓ required by
Tools
    ↓ used by
Agents ← use → Sub-agents
    ↓             ↑
    ↓ use        (sub-agents ARE agents)
MCPs
```

### Validation Rules

1. **Integration → Tool**: Cannot disable an integration if tools depend on it
2. **Tool → Agent**: Cannot disable a tool if agents use it
3. **Sub-agent → Agent**: Cannot disable a sub-agent if agents use it
4. **MCP → Agent**: Cannot disable an MCP if agents use it

### Example: Dependency Enforcement

```bash
# Try to disable Grafana integration
PATCH /api/v1/config/orgs/org1/nodes/root/config
{
  "integrations": {"grafana": {"enabled": false}}
}

# Response: 400 Bad Request
{
  "error": "dependency_validation_failed",
  "message": "Cannot disable integration 'grafana' because the following tools depend on it: grafana_query_prometheus. Please disable these tools first.",
  "dependents": ["grafana_query_prometheus"]
}
```

**Correct sequence:**

```bash
# Step 1: Remove tool from agents
PATCH .../config {
  "agents": {
    "planner": {
      "tools": {"grafana_query_prometheus": false}
    }
  }
}
# ✅ Success

# Step 2: Disable tool
PATCH .../config {
  "tools": {"grafana_query_prometheus": {"enabled": false}}
}
# ✅ Success

# Step 3: Disable integration
PATCH .../config {
  "integrations": {"grafana": {"enabled": false}}
}
# ✅ Success
```

---

## Real-World Examples

### Example 1: Organization Setup

Platform admin creates org-level defaults:

```json
{
  "agents": {
    "planner": {
      "enabled": true,
      "model": {"name": "gpt-5.2", "temperature": 0.3},
      "tools": {
        "think": true,
        "llm_call": true,
        "web_search": true
      },
      "sub_agents": {
        "investigation": true,
        "k8s": true
      }
    }
  },
  "integrations": {
    "grafana": {
      "enabled": true,
      "config": {
        "api_key": "org_secret",
        "url": "https://grafana.org.com"
      }
    }
  }
}
```

**All teams inherit these configurations automatically.**

### Example 2: Team Customization

A team adds their custom tools:

```json
{
  "agents": {
    "planner": {
      "tools": {
        "custom_deploy_tool": true
      },
      "mcps": {
        "team-custom-mcp": true
      }
    }
  },
  "mcp_servers": {
    "team-custom-mcp": {
      "enabled": true,
      "command": "./team-mcp",
      "args": []
    }
  }
}
```

**Effective config** (automatically computed):

```json
{
  "agents": {
    "planner": {
      "enabled": true,
      "model": {"name": "gpt-5.2", "temperature": 0.3},
      "tools": {
        "think": true,
        "llm_call": true,
        "web_search": true,
        "custom_deploy_tool": true  // Added by team
      },
      "sub_agents": {
        "investigation": true,
        "k8s": true
      },
      "mcps": {
        "team-custom-mcp": true  // Added by team
      }
    }
  },
  "integrations": {
    "grafana": {
      "enabled": true,
      "config": {
        "api_key": "org_secret",
        "url": "https://grafana.org.com"
      }
    }
  },
  "mcp_servers": {
    "team-custom-mcp": {
      "enabled": true,
      "command": "./team-mcp",
      "args": []
    }
  }
}
```

**Result**: Team gets org's tools + their own custom tools.

### Example 3: Team Disables Inherited Feature

A team disables a tool they don't need:

```json
{
  "agents": {
    "planner": {
      "tools": {
        "web_search": false
      }
    }
  }
}
```

**Effective config**:
- ✅ `think`: true (from org)
- ✅ `llm_call`: true (from org)
- ✅ `web_search`: false (overridden by team)

---

## API Endpoints

### Admin Endpoints

Full access to all configuration levels:

- `GET /api/v1/config/orgs/{org_id}/nodes/{node_id}/raw` - Get node's own config
- `GET /api/v1/config/orgs/{org_id}/nodes/{node_id}/effective` - Get effective config
- `PATCH /api/v1/config/orgs/{org_id}/nodes/{node_id}` - Update config (with validation)

### Team Endpoints

Self-service configuration for teams:

- `GET /api/v1/team/config` - Get team's effective config
- `PATCH /api/v1/team/config` - Update team config (with validation + locked fields check)

---

## Implementation Details

### Merge Algorithm

The system uses a simple recursive merge function:

```python
def deep_merge(base: Dict, override: Dict) -> Dict:
    """
    Merge override into base recursively.

    Rules:
    - Primitives: override replaces base
    - Dicts: recursive merge at key level
    - Lists: override replaces base
    """
    if not isinstance(base, dict) or not isinstance(override, dict):
        return override if override is not None else base

    result = copy.deepcopy(base)

    for key, value in override.items():
        if key not in result:
            result[key] = copy.deepcopy(value)
        elif isinstance(value, dict) and isinstance(result[key], dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)

    return result
```

**Complexity**: O(n) where n is total keys across all levels. No special control keys needed.

### Effective Config Caching

Effective configs are cached with 5-minute TTL:
- Cache key: `org_id:node_id:effective`
- Invalidation: On any config update in the hierarchy
- Implementation: Redis with transaction-safe invalidation

### Dependency Validation

Validation runs before any config update:
- Computes effective config with proposed changes
- Checks all four dependency types
- Returns clear error messages with list of dependents
- Blocks update if dependencies would break

---

## Key Takeaways

1. **Inheritance is additive** - Teams get org configs + their own changes
2. **Override at key level** - Change just what you need
3. **Dependencies are enforced** - Cannot break things accidentally
4. **Simple and predictable** - No special syntax to learn

The system provides powerful flexibility while maintaining safety through dependency validation.

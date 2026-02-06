# Canonical Config Reference

This document defines the **canonical data format** for IncidentFox configuration at all levels (templates, org, team, sub-team). All code, database schemas, and templates MUST conform to this specification.

## Table of Contents
1. [Design Principles](#design-principles)
2. [Template Format](#template-format)
3. [Org Config (After Template Applied)](#org-config-after-template-applied)
4. [Team Config (Inheriting from Org)](#team-config-inheriting-from-org)
5. [Sub-Team Config (Inheriting from Team)](#sub-team-config-inheriting-from-team)
6. [Inheritance Rules](#inheritance-rules)
7. [Migration from Old Formats](#migration-from-old-formats)

---

## Design Principles

### 1. Dictionary-Based Everything
- **Tools**: `{tool_id: boolean}` (NOT arrays `{enabled: [], disabled: []}`)
- **Sub-agents**: `{agent_id: boolean}` (NOT arrays `["agent1", "agent2"]`)
- **MCP Servers**: `{mcp_id: config_object}` (NOT arrays with `id` field)

### 2. No Top-Level Arrays for Enable/Disable
- ❌ **Remove**: `team_enabled_tool_ids: string[]`
- ❌ **Remove**: `team_disabled_tool_ids: string[]`
- ✅ **Use**: Direct modification in dictionary values

### 3. MCP Servers as Dictionary
- ❌ **Remove**: Top-level `mcps: {slack: {enabled: true, required: true}}`
- ❌ **Remove**: `team_added_mcp_servers: []` (legacy)
- ✅ **Use**: `mcp_servers: {mcp_id: config_object}` - Single dict for all MCP servers
- ✅ **Keep**: `required_mcps: string[]` as template metadata ONLY (not in applied config)

### 4. Agent-Level MCP Assignments
- ✅ **Keep**: `agents.{agent_id}.mcps: {mcp_id: boolean}` for per-agent MCP assignments

---

## Template Format

**Location**: `templates` table in database

**Purpose**: Source definition that gets copied to org config when applied

```json
{
  "id": "tmpl_incident_planner_001",
  "name": "Multi-Cloud Incident Planner",
  "slug": "incident-planner",
  "description": "AI planner that investigates incidents across K8s, AWS, and metrics",

  // Metadata columns (NOT copied to config)
  "required_mcps": [],
  "required_tools": ["k8s_get_pods", "aws_describe_instance", "datadog_get_metrics"],

  // Template JSON (gets copied to org config when applied)
  "template_json": {
    "$schema": "incidentfox-template-v1",
    "$version": "1.0.0",
    "$category": "incident-response",
    "$template_name": "Multi-Cloud Incident Planner",
    "$template_slug": "incident-planner",
    "$description": "AI planner that investigates incidents across K8s, AWS, and metrics",

    "agents": {
      "planner": {
        "name": "Incident Planner",
        "description": "Plans incident investigation strategy",
        "enabled": true,
        "model": {
          "name": "gpt-5.2",
          "max_tokens": 4000,
          "temperature": 0.3
        },
        "tools": {
          "slack_post_message": true,
          "think": true,
          "web_search": true
        },
        "sub_agents": {
          "k8s_agent": true,
          "aws_agent": true,
          "metric_agent": true
        },
        "mcps": {},
        "max_turns": 12,
        "prompt": {
          "system": "You are an incident investigation planner...",
          "prefix": "",
          "suffix": ""
        }
      },
      "k8s_agent": {
        "name": "Kubernetes Agent",
        "description": "Investigates K8s cluster issues",
        "enabled": true,
        "model": {
          "name": "gpt-5.2",
          "max_tokens": 3000,
          "temperature": 0.1
        },
        "tools": {
          "k8s_get_pods": true,
          "k8s_get_logs": true,
          "k8s_describe_pod": true,
          "k8s_get_events": true
        },
        "sub_agents": {},
        "mcps": {},
        "max_turns": 8,
        "prompt": {
          "system": "You investigate Kubernetes cluster issues...",
          "prefix": "",
          "suffix": ""
        }
      },
      "aws_agent": {
        "name": "AWS Agent",
        "description": "Investigates AWS infrastructure",
        "enabled": true,
        "model": {
          "name": "gpt-5.2",
          "max_tokens": 3000,
          "temperature": 0.1
        },
        "tools": {
          "aws_describe_instance": true,
          "aws_get_cloudwatch_metrics": true,
          "aws_list_ec2_instances": true
        },
        "sub_agents": {},
        "mcps": {},
        "max_turns": 8,
        "prompt": {
          "system": "You investigate AWS infrastructure issues...",
          "prefix": "",
          "suffix": ""
        }
      },
      "metric_agent": {
        "name": "Metrics Agent",
        "description": "Analyzes metrics and trends",
        "enabled": true,
        "model": {
          "name": "gpt-5.2",
          "max_tokens": 3000,
          "temperature": 0.1
        },
        "tools": {
          "datadog_get_metrics": true,
          "datadog_query_timeseries": true,
          "datadog_get_monitors": true
        },
        "sub_agents": {},
        "mcps": {},
        "max_turns": 6,
        "prompt": {
          "system": "You analyze metrics and identify trends...",
          "prefix": "",
          "suffix": ""
        }
      }
    },

    "output_config": {
      "formatting": {
        "slack": {
          "use_markdown": true,
          "include_links": true,
          "use_block_kit": false
        }
      },
      "default_destinations": ["slack"]
    },

    "runtime_config": {
      "max_retries": 2,
      "retry_on_failure": true,
      "max_concurrent_agents": 3,
      "default_timeout_seconds": 300
    }
  }
}
```

**Key Points**:
- ✅ `tools`: Dict format `{tool_id: boolean}`
- ✅ `sub_agents`: Dict format `{agent_id: boolean}`
- ✅ `mcps`: Empty dict `{}` (per-agent MCP assignments added later)
- ❌ No top-level `mcps` section
- ❌ No `team_enabled_tool_ids` or `team_disabled_tool_ids`

---

## Org Config (After Template Applied)

**Location**: `node_configurations` table, where `node_id == org_id` and `parent_id IS NULL`

**Purpose**: Root configuration that teams inherit from

```json
{
  "config_id": "cfg-org-acme",
  "org_id": "acme-corp",
  "node_id": "acme-corp",

  "config_json": {
    // Agents (copied from template)
    "agents": {
      "planner": {
        "name": "Incident Planner",
        "description": "Plans incident investigation strategy",
        "enabled": true,
        "model": {
          "name": "gpt-5.2",
          "max_tokens": 4000,
          "temperature": 0.3
        },
        "tools": {
          "slack_post_message": true,
          "think": true,
          "web_search": true
        },
        "sub_agents": {
          "k8s_agent": true,
          "aws_agent": true,
          "metric_agent": true
        },
        "mcps": {},
        "max_turns": 12,
        "prompt": {
          "system": "You are an incident investigation planner...",
          "prefix": "",
          "suffix": ""
        }
      },
      "k8s_agent": {
        "name": "Kubernetes Agent",
        "description": "Investigates K8s cluster issues",
        "enabled": true,
        "model": {
          "name": "gpt-5.2",
          "max_tokens": 3000,
          "temperature": 0.1
        },
        "tools": {
          "k8s_get_pods": true,
          "k8s_get_logs": true,
          "k8s_describe_pod": true,
          "k8s_get_events": true
        },
        "sub_agents": {},
        "mcps": {},
        "max_turns": 8,
        "prompt": {
          "system": "You investigate Kubernetes cluster issues...",
          "prefix": "",
          "suffix": ""
        }
      },
      "aws_agent": {
        "name": "AWS Agent",
        "description": "Investigates AWS infrastructure",
        "enabled": true,
        "model": {
          "name": "gpt-5.2",
          "max_tokens": 3000,
          "temperature": 0.1
        },
        "tools": {
          "aws_describe_instance": true,
          "aws_get_cloudwatch_metrics": true,
          "aws_list_ec2_instances": true
        },
        "sub_agents": {},
        "mcps": {},
        "max_turns": 8,
        "prompt": {
          "system": "You investigate AWS infrastructure issues...",
          "prefix": "",
          "suffix": ""
        }
      },
      "metric_agent": {
        "name": "Metrics Agent",
        "description": "Analyzes metrics and trends",
        "enabled": true,
        "model": {
          "name": "gpt-5.2",
          "max_tokens": 3000,
          "temperature": 0.1
        },
        "tools": {
          "datadog_get_metrics": true,
          "datadog_query_timeseries": true,
          "datadog_get_monitors": true
        },
        "sub_agents": {},
        "mcps": {},
        "max_turns": 6,
        "prompt": {
          "system": "You analyze metrics and identify trends...",
          "prefix": "",
          "suffix": ""
        }
      }
    },

    // MCP Servers (org-level, dict keyed by ID)
    "mcp_servers": {
      "eks-mcp": {
        "name": "AWS EKS MCP Server",
        "command": "uvx",
        "args": [
          "awslabs.eks-mcp-server@latest",
          "--allow-write",
          "--allow-sensitive-data-access"
        ],
        "env": {
          "AWS_REGION": "us-west-2",
          "AWS_ACCESS_KEY_ID": "AKIA...",
          "AWS_SECRET_ACCESS_KEY": "...",
          "FASTMCP_LOG_LEVEL": "ERROR"
        }
      }
    },

    // Built-in tools configuration (team-level enable/disable)
    "tools": {
      // Not specified at org level = all tools available by default
    },

    // Integrations (with credentials)
    "integrations": {
      "slack": {
        "id": "slack",
        "name": "Slack",
        "config_values": {
          "bot_token": "xoxb-...",
          "channel_id": "C12345"
        }
      },
      "kubernetes": {
        "id": "kubernetes",
        "name": "Kubernetes",
        "config_values": {
          "kubeconfig_path": "/home/agent/.kube/config",
          "context": "production"
        }
      },
      "aws": {
        "id": "aws",
        "name": "AWS",
        "config_values": {
          "access_key_id": "AKIA...",
          "secret_access_key": "...",
          "region": "us-west-2"
        }
      },
      "datadog": {
        "id": "datadog",
        "name": "Datadog",
        "config_values": {
          "api_key": "dd_api_...",
          "app_key": "dd_app_..."
        }
      }
    },

    // Output configuration
    "output_config": {
      "formatting": {
        "slack": {
          "use_markdown": true,
          "include_links": true,
          "use_block_kit": false
        }
      },
      "default_destinations": ["slack"]
    },

    // Runtime configuration
    "runtime_config": {
      "max_retries": 2,
      "retry_on_failure": true,
      "max_concurrent_agents": 3,
      "default_timeout_seconds": 300
    }
  }
}
```

**Key Points**:
- ✅ Agents copied from template with dict-based tools/sub_agents
- ✅ `mcp_servers`: **DICT** keyed by MCP ID (not list)
- ✅ `tools`: **DICT** for team-level built-in tool configuration (empty = all available)
- ✅ `integrations`: Dict with actual credentials
- ❌ No `team_added_mcp_servers` (legacy, removed)
- ❌ No top-level `mcps` section
- ❌ No `team_enabled_tool_ids` or `team_disabled_tool_ids` arrays

---

## Team Config (Inheriting from Org)

**Location**: `node_configurations` table, where `parent_id == org_id`

**Purpose**: Team-level overrides and additions on top of org config

**Scenario**: Platform SRE team wants to:
1. **Restructure agent hierarchy**: Add new `investigator` agent between planner and leaf agents
2. **Move agents**: Put k8s_agent and aws_agent under investigator
3. **Add new agent**: Create datadog_agent under investigator
4. **Remove agent**: Disable metric_agent (not needed)
5. **Remove tools**: Disable some tools from planner (web_search, think)
6. **Add MCP server**: Add team-specific GitHub MCP
7. **Add integration**: Add GitHub integration

```json
{
  "config_id": "cfg-team-platform-sre",
  "org_id": "acme-corp",
  "node_id": "team-platform-sre",
  "parent_id": "acme-corp",

  "config_json": {
    // Agent overrides and additions
    "agents": {
      "planner": {
        // Override: Remove some tools
        "tools": {
          "web_search": false,  // Disable web_search
          "think": false        // Disable think
        },
        // Override: Change sub-agents to only use investigator
        "sub_agents": {
          "k8s_agent": false,      // Remove direct connection
          "aws_agent": false,      // Remove direct connection
          "metric_agent": false,   // Remove (will disable below)
          "investigator": true     // NEW: Add investigator
        }
      },
      "investigator": {
        // NEW AGENT: Investigator coordinates k8s, aws, datadog
        "name": "Infrastructure Investigator",
        "description": "Coordinates investigation across infra layers",
        "enabled": true,
        "model": {
          "name": "gpt-5.2",
          "max_tokens": 3500,
          "temperature": 0.2
        },
        "tools": {
          "think": true,
          "llm_call": true
        },
        "sub_agents": {
          "k8s_agent": true,
          "aws_agent": true,
          "datadog_agent": true  // NEW agent
        },
        "mcps": {},
        "max_turns": 10,
        "prompt": {
          "system": "You coordinate infrastructure investigations across K8s, AWS, and Datadog...",
          "prefix": "",
          "suffix": ""
        }
      },
      "k8s_agent": {
        // Override: Remove one tool
        "tools": {
          "k8s_get_events": false  // Disable this tool
        }
        // Note: Everything else inherited from org
      },
      "aws_agent": {
        // Override: Remove a tool
        "tools": {
          "aws_list_ec2_instances": false  // Disable this tool
        }
      },
      "datadog_agent": {
        // NEW AGENT: Datadog-specific investigation
        "name": "Datadog Agent",
        "description": "Investigates Datadog metrics and alerts",
        "enabled": true,
        "model": {
          "name": "gpt-5.2",
          "max_tokens": 3000,
          "temperature": 0.1
        },
        "tools": {
          "datadog_get_metrics": true,
          "datadog_query_timeseries": true,
          "datadog_get_monitors": true,
          "datadog_get_alerts": true
        },
        "sub_agents": {},
        "mcps": {},
        "max_turns": 8,
        "prompt": {
          "system": "You investigate Datadog metrics, monitors, and alerts...",
          "prefix": "",
          "suffix": ""
        }
      },
      "metric_agent": {
        // Override: Disable this agent (team doesn't need it)
        "enabled": false
      }
    },

    // MCP Servers: Add GitHub MCP
    "mcp_servers": {
      "github-mcp": {
        "name": "GitHub MCP",
        "command": "uvx",
        "args": ["mcp-server-github"],
        "env": {
          "GITHUB_TOKEN": "ghp_..."
        }
      }
      // Note: eks-mcp inherited from org
    },

    // Built-in tools: Disable some tools team-wide
    "tools": {
      "think": false,       // Disable think tool for entire team
      "llm_call": false     // Disable llm_call tool for entire team
    },

    // Integrations: Add GitHub
    "integrations": {
      "github": {
        "id": "github",
        "name": "GitHub",
        "config_values": {
          "token": "ghp_...",
          "org": "acme-corp"
        }
      }
      // Note: slack, kubernetes, aws, datadog inherited from org
    },

    // Output config override
    "output_config": {
      "default_destinations": ["slack", "github"]  // Add GitHub destination
    }

    // Note: runtime_config not listed = inherited from org
  }
}
```

**Effective Config (After Inheritance)**:

The config service deep merges team config onto org config:

```json
{
  "agents": {
    "planner": {
      "name": "Incident Planner",
      "enabled": true,
      "model": {
        "name": "gpt-5.2",
        "max_tokens": 4000,
        "temperature": 0.3  // from org
      },
      "tools": {
        "slack_post_message": true,  // from org
        "think": false,              // ← OVERRIDDEN by team (disabled)
        "web_search": false          // ← OVERRIDDEN by team (disabled)
      },
      "sub_agents": {
        "k8s_agent": false,          // ← OVERRIDDEN by team (removed)
        "aws_agent": false,          // ← OVERRIDDEN by team (removed)
        "metric_agent": false,       // ← OVERRIDDEN by team (removed)
        "investigator": true         // ← ADDED by team
      },
      "mcps": {},
      "max_turns": 12,
      "prompt": { /* from org */ }
    },
    "investigator": {
      // ← ADDED by team
      "name": "Infrastructure Investigator",
      "enabled": true,
      "model": {
        "name": "gpt-5.2",
        "max_tokens": 3500,
        "temperature": 0.2
      },
      "tools": {
        "think": true,
        "llm_call": true
      },
      "sub_agents": {
        "k8s_agent": true,
        "aws_agent": true,
        "datadog_agent": true
      },
      "mcps": {},
      "max_turns": 10,
      "prompt": { /* from team */ }
    },
    "k8s_agent": {
      "name": "Kubernetes Agent",  // from org
      "enabled": true,             // from org
      "model": { /* from org */ },
      "tools": {
        "k8s_get_pods": true,        // from org
        "k8s_get_logs": true,        // from org
        "k8s_describe_pod": true,    // from org
        "k8s_get_events": false      // ← OVERRIDDEN by team (disabled)
      },
      "sub_agents": {},
      "mcps": {},
      "max_turns": 8,
      "prompt": { /* from org */ }
    },
    "aws_agent": {
      "name": "AWS Agent",  // from org
      "enabled": true,      // from org
      "model": { /* from org */ },
      "tools": {
        "aws_describe_instance": true,       // from org
        "aws_get_cloudwatch_metrics": true,  // from org
        "aws_list_ec2_instances": false      // ← OVERRIDDEN by team (disabled)
      },
      "sub_agents": {},
      "mcps": {},
      "max_turns": 8,
      "prompt": { /* from org */ }
    },
    "datadog_agent": {
      // ← ADDED by team
      "name": "Datadog Agent",
      "enabled": true,
      "model": {
        "name": "gpt-5.2",
        "max_tokens": 3000,
        "temperature": 0.1
      },
      "tools": {
        "datadog_get_metrics": true,
        "datadog_query_timeseries": true,
        "datadog_get_monitors": true,
        "datadog_get_alerts": true
      },
      "sub_agents": {},
      "mcps": {},
      "max_turns": 8,
      "prompt": { /* from team */ }
    },
    "metric_agent": {
      "name": "Metrics Agent",  // from org
      "enabled": false,         // ← OVERRIDDEN by team (disabled)
      "model": { /* from org */ },
      "tools": { /* from org */ },
      "sub_agents": {},
      "mcps": {},
      "max_turns": 6,
      "prompt": { /* from org */ }
    }
  },

  "mcp_servers": {
    "eks-mcp": {
      // INHERITED from org
      "name": "AWS EKS MCP Server",
      "command": "uvx",
      "args": [
        "awslabs.eks-mcp-server@latest",
        "--allow-write",
        "--allow-sensitive-data-access"
      ],
      "env": {
        "AWS_REGION": "us-west-2",
        "AWS_ACCESS_KEY_ID": "AKIA...",
        "AWS_SECRET_ACCESS_KEY": "...",
        "FASTMCP_LOG_LEVEL": "ERROR"
      }
    },
    "github-mcp": {
      // ← ADDED by team
      "name": "GitHub MCP",
      "command": "uvx",
      "args": ["mcp-server-github"],
      "env": {
        "GITHUB_TOKEN": "ghp_..."
      }
    }
  },

  "tools": {
    // ← ADDED by team (team-level tool restrictions)
    "think": false,       // Disabled team-wide
    "llm_call": false     // Disabled team-wide
  },

  "integrations": {
    "slack": { /* INHERITED from org */ },
    "kubernetes": { /* INHERITED from org */ },
    "aws": { /* INHERITED from org */ },
    "datadog": { /* INHERITED from org */ },
    "github": {
      // ← ADDED by team
      "id": "github",
      "name": "GitHub",
      "config_values": {
        "token": "ghp_...",
        "org": "acme-corp"
      }
    }
  },

  "output_config": {
    "formatting": { /* from org */ },
    "default_destinations": ["slack", "github"]  // ← OVERRIDDEN by team
  },

  "runtime_config": {
    /* INHERITED from org, no changes */
  }
}
```

---

## Sub-Team Config (Inheriting from Team)

**Location**: `node_configurations` table, where `parent_id == team_node_id`

**Purpose**: Sub-team overrides on top of team config

**Scenario**: "Data Platform" sub-team under "Platform SRE" team wants to:
1. **Add Snowflake integration and tools** to investigator
2. **Enable more tools** for investigator (add web_search back)
3. **Disable some tools** from datadog_agent
4. **Add Snowflake MCP server**

```json
{
  "config_id": "cfg-subteam-data-platform",
  "org_id": "acme-corp",
  "node_id": "subteam-data-platform",
  "parent_id": "team-platform-sre",

  "config_json": {
    // Agent overrides
    "agents": {
      "investigator": {
        // Override: Add web_search tool back
        "tools": {
          "web_search": true,  // Re-enable (was disabled at planner level)
          "snowflake_query": true,  // NEW: Add Snowflake tool
          "snowflake_get_tables": true  // NEW: Add Snowflake tool
        }
      },
      "datadog_agent": {
        // Override: Disable some tools
        "tools": {
          "datadog_get_monitors": false,  // Disable
          "datadog_get_alerts": false     // Disable
        }
      },
      "k8s_agent": {
        // Override: Re-enable a tool
        "tools": {
          "k8s_get_events": true  // Re-enable (was disabled by team)
        }
      }
    },

    // MCP Servers: Add Snowflake MCP
    "mcp_servers": {
      "snowflake-mcp": {
        "name": "Snowflake MCP",
        "command": "uvx",
        "args": ["mcp-server-snowflake"],
        "env": {
          "SNOWFLAKE_ACCOUNT": "acme.us-west-2",
          "SNOWFLAKE_USER": "svc_dataplatform",
          "SNOWFLAKE_PASSWORD": "...",
          "SNOWFLAKE_WAREHOUSE": "COMPUTE_WH"
        }
      }
      // Note: eks-mcp, github-mcp inherited from org/team
    },

    // Built-in tools: Re-enable some tools for this sub-team
    "tools": {
      "think": true  // Re-enable think (was disabled by team)
      // llm_call remains disabled (inherited from team)
    },

    // Integrations: Add Snowflake
    "integrations": {
      "snowflake": {
        "id": "snowflake",
        "name": "Snowflake",
        "config_values": {
          "account": "acme.us-west-2",
          "username": "dataplatform",
          "password": "...",
          "warehouse": "COMPUTE_WH",
          "database": "ANALYTICS"
        }
      }
      // Note: slack, kubernetes, aws, datadog, github inherited
    },

    // Output config override
    "output_config": {
      "default_destinations": ["slack", "github"]  // Keep from team
    }
  }
}
```

**Effective Config (After Inheritance from Org → Team → Sub-Team)**:

```json
{
  "agents": {
    "planner": {
      "name": "Incident Planner",
      "enabled": true,
      "model": {
        "name": "gpt-5.2",
        "max_tokens": 4000,
        "temperature": 0.3  // from org
      },
      "tools": {
        "slack_post_message": true,  // from org
        "think": false,              // from team (disabled)
        "web_search": false          // from team (disabled)
      },
      "sub_agents": {
        "k8s_agent": false,      // from team
        "aws_agent": false,      // from team
        "metric_agent": false,   // from team
        "investigator": true     // from team
      },
      "mcps": {},
      "max_turns": 12,
      "prompt": { /* from org */ }
    },
    "investigator": {
      "name": "Infrastructure Investigator",  // from team
      "enabled": true,
      "model": { /* from team */ },
      "tools": {
        "think": true,                     // from team
        "llm_call": true,                  // from team
        "web_search": true,                // ← OVERRIDDEN by sub-team (re-enabled)
        "snowflake_query": true,           // ← ADDED by sub-team
        "snowflake_get_tables": true       // ← ADDED by sub-team
      },
      "sub_agents": {
        "k8s_agent": true,
        "aws_agent": true,
        "datadog_agent": true
      },
      "mcps": {},
      "max_turns": 10,
      "prompt": { /* from team */ }
    },
    "k8s_agent": {
      "name": "Kubernetes Agent",
      "enabled": true,
      "model": { /* from org */ },
      "tools": {
        "k8s_get_pods": true,        // from org
        "k8s_get_logs": true,        // from org
        "k8s_describe_pod": true,    // from org
        "k8s_get_events": true       // ← OVERRIDDEN by sub-team (re-enabled)
      },
      "sub_agents": {},
      "mcps": {},
      "max_turns": 8,
      "prompt": { /* from org */ }
    },
    "aws_agent": {
      "name": "AWS Agent",
      "enabled": true,
      "model": { /* from org */ },
      "tools": {
        "aws_describe_instance": true,       // from org
        "aws_get_cloudwatch_metrics": true,  // from org
        "aws_list_ec2_instances": false      // from team (disabled)
      },
      "sub_agents": {},
      "mcps": {},
      "max_turns": 8,
      "prompt": { /* from org */ }
    },
    "datadog_agent": {
      "name": "Datadog Agent",
      "enabled": true,
      "model": { /* from team */ },
      "tools": {
        "datadog_get_metrics": true,         // from team
        "datadog_query_timeseries": true,    // from team
        "datadog_get_monitors": false,       // ← OVERRIDDEN by sub-team (disabled)
        "datadog_get_alerts": false          // ← OVERRIDDEN by sub-team (disabled)
      },
      "sub_agents": {},
      "mcps": {},
      "max_turns": 8,
      "prompt": { /* from team */ }
    },
    "metric_agent": {
      "name": "Metrics Agent",
      "enabled": false,  // from team (disabled)
      "model": { /* from org */ },
      "tools": { /* from org */ },
      "sub_agents": {},
      "mcps": {},
      "max_turns": 6,
      "prompt": { /* from org */ }
    }
  },

  "mcp_servers": {
    "eks-mcp": {
      // from org
      "name": "AWS EKS MCP Server",
      "command": "uvx",
      "args": [
        "awslabs.eks-mcp-server@latest",
        "--allow-write",
        "--allow-sensitive-data-access"
      ],
      "env": {
        "AWS_REGION": "us-west-2",
        "AWS_ACCESS_KEY_ID": "AKIA...",
        "AWS_SECRET_ACCESS_KEY": "...",
        "FASTMCP_LOG_LEVEL": "ERROR"
      }
    },
    "github-mcp": {
      // from team
      "name": "GitHub MCP",
      "command": "uvx",
      "args": ["mcp-server-github"],
      "env": {
        "GITHUB_TOKEN": "ghp_..."
      }
    },
    "snowflake-mcp": {
      // ← ADDED by sub-team
      "name": "Snowflake MCP",
      "command": "uvx",
      "args": ["mcp-server-snowflake"],
      "env": {
        "SNOWFLAKE_ACCOUNT": "acme.us-west-2",
        "SNOWFLAKE_USER": "svc_dataplatform",
        "SNOWFLAKE_PASSWORD": "...",
        "SNOWFLAKE_WAREHOUSE": "COMPUTE_WH"
      }
    }
  },

  "tools": {
    // ← OVERRIDDEN by sub-team
    "think": true,        // Re-enabled by sub-team
    "llm_call": false     // Remains disabled (from team)
  },

  "integrations": {
    "slack": { /* from org */ },
    "kubernetes": { /* from org */ },
    "aws": { /* from org */ },
    "datadog": { /* from org */ },
    "github": { /* from team */ },
    "snowflake": {
      // ← ADDED by sub-team
      "id": "snowflake",
      "name": "Snowflake",
      "config_values": {
        "account": "acme.us-west-2",
        "username": "dataplatform",
        "password": "...",
        "warehouse": "COMPUTE_WH",
        "database": "ANALYTICS"
      }
    }
  },

  "output_config": {
    "formatting": { /* from org */ },
    "default_destinations": ["slack", "github"]  // from sub-team (same as team)
  },

  "runtime_config": {
    /* from org, no overrides */
  }
}
```

---

## Tool Configuration: Team-Level vs Agent-Level

There are **two levels** of tool configuration:

### 1. Team-Level Tools (Global Filter)

**Location**: Top-level `tools` dict
**Purpose**: Control which built-in tools are available team-wide
**Scope**: Applies to ALL agents in the team

```json
{
  "tools": {
    "think": false,      // Disable think for entire team
    "web_search": false, // Disable web_search for entire team
    "llm_call": false    // Disable llm_call for entire team
  }
}
```

**Behavior**:
- If a tool is set to `false` at team level, **no agent can use it**
- Empty `tools: {}` = all built-in tools available (no restrictions)
- Only specify tools you want to restrict

### 2. Agent-Level Tools (Per-Agent Configuration)

**Location**: `agents.{agent_id}.tools` dict
**Purpose**: Control which tools a specific agent uses
**Scope**: Applies only to that agent

```json
{
  "agents": {
    "planner": {
      "tools": {
        "slack_post_message": true,
        "k8s_get_pods": true,
        "think": true
      }
    }
  }
}
```

**Behavior**:
- If a tool is `true`, the agent can use it (if team-level allows it)
- If a tool is `false`, the agent cannot use it
- Agent-level is **filtered by** team-level

### How They Interact

**Rule**: Agent tool = **Agent-level AND Team-level**

```
Team level:  {"tools": {"think": false}}
Agent level: {"agents": {"planner": {"tools": {"think": true}}}}
→ Effective: planner CANNOT use think (team level blocks it)
```

```
Team level:  {"tools": {"think": true}}   // or not specified
Agent level: {"agents": {"planner": {"tools": {"think": false}}}}
→ Effective: planner CANNOT use think (agent level blocks it)
```

```
Team level:  {"tools": {"think": true}}   // or not specified
Agent level: {"agents": {"planner": {"tools": {"think": true}}}}
→ Effective: planner CAN use think (both allow it)
```

### Use Cases

**Team-Level Tools**:
- Security policies: "No team can use `dangerous_tool`"
- Compliance: "Disable `web_search` for teams handling sensitive data"
- Cost control: "Disable expensive tools like `llm_call` for test teams"

**Agent-Level Tools**:
- Agent specialization: "Planner uses `think`, but not `k8s_get_pods`"
- Workflow design: "Coordinator uses `slack_post_message`, investigator doesn't"
- Fine-grained control: Override inherited tool settings per agent

### Inheritance Example

**Org**: No tool restrictions
```json
{"tools": {}}
```

**Team**: Disable think and llm_call
```json
{"tools": {"think": false, "llm_call": false}}
```

**Agent** (at team level): Planner wants to use think
```json
{
  "agents": {
    "planner": {
      "tools": {"think": true}  // Won't work - team blocks it
    }
  }
}
```

**Result**: Planner cannot use `think` because team-level disables it.

**Sub-Team**: Re-enable think
```json
{"tools": {"think": true}}  // Override team's restriction
```

**Result**: Now sub-team's agents can use `think` (if their agent-level config allows it).

### Cumulative Tool Restrictions

**Important**: Tool restrictions are **CUMULATIVE** through the inheritance chain.

**Example - Multi-Level Inheritance**:

```
Org:         {"tools": {}}                                    // No restrictions
   ↓
Team:        {"tools": {"x": false}}                          // Disable X
   ↓ (merge)
             = {"tools": {"x": false}}
   ↓
Sub-Team:    {"tools": {"y": false}}                          // Disable Y
   ↓ (merge)
             = {"tools": {"x": false, "y": false}}            // Both disabled!
   ↓
Sub-Sub-Team: {"tools": {}}                                   // No new restrictions
   ↓ (merge)
             = {"tools": {"x": false, "y": false}}            // Both still disabled
```

**Result**: Sub-sub-team has BOTH tool X and tool Y disabled (inherited cumulatively).

**To re-enable a tool**, a child must explicitly override:

```
Org:         {"tools": {}}
   ↓
Team:        {"tools": {"x": false}}                          // Disable X
   ↓
Sub-Team:    {"tools": {"x": true, "y": false}}              // Re-enable X, Disable Y
   ↓ (merge)
             = {"tools": {"x": true, "y": false}}            // X enabled, Y disabled
```

**Key Insight**:
- Empty `tools: {}` at a child level = **inherit all restrictions from parent**
- Explicitly setting `{"tool": true}` = **override parent's restriction**
- Explicitly setting `{"tool": false}` = **add new restriction**

This gives teams **flexibility**:
- ✅ Inherit restrictions by default (secure by default)
- ✅ Override parent restrictions when needed (flexibility)
- ✅ Add new restrictions on top (defense in depth)

---

## Inheritance Rules

### 1. Deep Merge Strategy

Inheritance uses **deep merge** with these rules:

#### Rule 1: Dictionaries Merge
```
Org:  {"agents": {"agent1": {"tools": {"tool_a": true, "tool_b": true}}}}
Team: {"agents": {"agent1": {"tools": {"tool_b": false}}}}
→ Result: {"agents": {"agent1": {"tools": {"tool_a": true, "tool_b": false}}}}
```

#### Rule 2: Arrays Replace (NOT append)
```
Org:  {"output_config": {"default_destinations": ["slack"]}}
Team: {"output_config": {"default_destinations": ["github"]}}
→ Result: {"output_config": {"default_destinations": ["github"]}}  // REPLACED
```

#### Rule 3: Primitives Replace
```
Org:  {"agents": {"agent1": {"enabled": true}}}
Team: {"agents": {"agent1": {"enabled": false}}}
→ Result: {"agents": {"agent1": {"enabled": false}}}
```

### 2. Special Fields

#### `mcp_servers` - Merges by ID (Dict)
```
Org:  {"mcp_servers": {"fs-1": {"name": "...", "path": "/org"}}}
Team: {"mcp_servers": {"fs-2": {"name": "...", "path": "/team"}}}
→ Result: {"mcp_servers": {
    "fs-1": {"name": "...", "path": "/org"},
    "fs-2": {"name": "...", "path": "/team"}
  }}
```

#### `integrations` - Merges by ID
```
Org:  {"integrations": {"slack": {...}}}
Team: {"integrations": {"github": {...}}}
→ Result: {"integrations": {"slack": {...}, "github": {...}}}
```

### 3. Tool Override Patterns

#### Disable a tool from parent:
```json
{
  "agents": {
    "agent1": {
      "tools": {
        "unwanted_tool": false  // Was true in parent
      }
    }
  }
}
```

#### Disable entire agent from parent:
```json
{
  "agents": {
    "unwanted_agent": {
      "enabled": false  // Was true in parent
    }
  }
}
```

#### Disable sub-agent relationship:
```json
{
  "agents": {
    "coordinator": {
      "sub_agents": {
        "unwanted_sub_agent": false  // Was true in parent
      }
    }
  }
}
```

---

## Migration from Old Formats

### Old Format → New Format Conversions

#### 1. Tools: Array → Dict
```json
// OLD (DEPRECATED)
{
  "tools": {
    "enabled": ["tool_a", "tool_b"],
    "disabled": ["tool_c"]
  }
}

// NEW (CANONICAL)
{
  "tools": {
    "tool_a": true,
    "tool_b": true,
    "tool_c": false
  }
}
```

#### 2. Sub-agents: Array → Dict
```json
// OLD (DEPRECATED)
{
  "sub_agents": ["agent1", "agent2"]
}

// NEW (CANONICAL)
{
  "sub_agents": {
    "agent1": true,
    "agent2": true
  }
}
```

#### 3. Team Tool Overrides: Arrays → Direct Dict Modification
```json
// OLD (DEPRECATED)
{
  "team_enabled_tool_ids": ["custom_tool"],
  "team_disabled_tool_ids": ["unwanted_tool"],
  "agents": {
    "agent1": {
      "tools": {
        "default_tool": true
      }
    }
  }
}

// NEW (CANONICAL)
{
  "agents": {
    "agent1": {
      "tools": {
        "default_tool": true,
        "custom_tool": true,      // Was in team_enabled_tool_ids
        "unwanted_tool": false    // Was in team_disabled_tool_ids
      }
    }
  }
}
```

#### 4. Top-level MCP Config → Remove
```json
// OLD (DEPRECATED)
{
  "mcps": {
    "slack": {
      "enabled": true,
      "required": true
    }
  }
}

// NEW (CANONICAL)
// Remove this entirely - MCP configuration is in mcp_servers list
```

---

## Implementation Checklist

To fully adopt this canonical format:

### Database
- [ ] Remove `team_enabled_tool_ids` field from configs
- [ ] Remove `team_disabled_tool_ids` field from configs
- [ ] Remove top-level `mcps` section from configs
- [ ] Convert all `tools` to dict format
- [ ] Convert all `sub_agents` to dict format

### Config Service
- [ ] Update merge logic to handle dict-based tools
- [ ] Remove handling of `team_enabled_tool_ids`
- [ ] Remove handling of `team_disabled_tool_ids`
- [ ] Update inheritance to properly merge tool dicts

### Agent Runtime
- [ ] Update TeamLevelConfig model to remove array fields
- [ ] Update tool loading to expect dict format
- [ ] Update sub-agent resolution to expect dict format
- [ ] Remove code that reads `team_enabled_tool_ids`
- [ ] Remove code that reads `team_disabled_tool_ids`

### Templates
- [ ] Update all templates to use dict-based tools
- [ ] Update all templates to use dict-based sub_agents
- [ ] Remove top-level `mcps` from template JSON
- [ ] Keep `required_mcps` as metadata column only

### UI
- [ ] Update agent editor to work with dict-based tools
- [ ] Update tool toggle UI to modify dict values
- [ ] Remove any UI for `team_enabled_tool_ids` arrays
- [ ] Update inheritance display to show dict merging

---

## Questions & Answers

**Q: Why dictionaries instead of arrays?**
A: Dictionaries allow for:
- Easy override of specific items (set to false)
- No need for separate enabled/disabled lists
- Clearer semantic meaning (tool_id → enabled/disabled)
- Simpler merge logic during inheritance

**Q: Why remove `team_enabled_tool_ids` and `team_disabled_tool_ids`?**
A: With dict-based tools, you can directly modify the dict:
- Enable: `{"tools": {"new_tool": true}}`
- Disable: `{"tools": {"unwanted_tool": false}}`
No separate arrays needed.

**Q: What about backward compatibility?**
A: Migration script will convert old formats to new format in database. After migration, only new format supported.

**Q: Why keep `required_mcps` in template metadata?**
A: For UI display purposes (showing requirements before template application). Not used by agent runtime.

---

## Summary

### Canonical Format Rules:
1. ✅ **Agent tools**: Dict `agents.{id}.tools: {tool_id: boolean}`
2. ✅ **Team tools**: Dict `tools: {tool_id: boolean}` (team-level filter)
3. ✅ **Sub-agents**: Dict `agents.{id}.sub_agents: {agent_id: boolean}`
4. ✅ **MCP servers**: Dict `mcp_servers: {mcp_id: config_object}`
5. ✅ **Agent MCPs**: Dict `agents.{id}.mcps: {mcp_id: boolean}`
6. ✅ **Integrations**: Dict `integrations: {integration_id: config}`
7. ❌ No `team_enabled_tool_ids` arrays (use `tools` dict instead)
8. ❌ No `team_disabled_tool_ids` arrays (use `tools` dict instead)
9. ❌ No `team_added_mcp_servers` list (use `mcp_servers` dict directly)
10. ❌ No top-level `mcps` config section

### Tool Configuration Hierarchy:
- **Team-level** `tools` = global filter (blocks tools team-wide)
- **Agent-level** `agents.{id}.tools` = per-agent configuration
- **Effective tool** = Agent-level AND Team-level (both must be true)

### Inheritance:
- **Deep merge dictionaries** (tools, agents, sub_agents, integrations, mcp_servers)
  - **Cumulative**: Tool restrictions accumulate through chain (Org→Team→Sub-Team)
  - **Additive**: MCP servers and integrations merge by key (child adds to parent)
  - **Override**: Explicit `{"tool": true}` can re-enable parent's `{"tool": false}`
- **Replace arrays** (output destinations)
- **Replace primitives** (enabled flags, model parameters)
- **Empty dict at child** = inherit all from parent (secure by default)
- **Explicit value at child** = override parent (flexibility)

This is the **golden reference**. All code must conform to this.

# Dynamic Agent System

> **Purpose**: Build multi-agent systems from JSON configuration instead of hardcoded Python classes
> **Status**: Infrastructure complete, integration in progress
> **Last Updated**: January 9, 2026

---

## Overview

The Dynamic Agent System allows agents to be defined and customized via JSON configuration stored in the Config Service database. This enables:

- **Org admins** to set default agent behavior for their organization
- **Teams** to customize agents (prompts, tools, models) without code changes
- **Runtime agent construction** based on hierarchical configuration inheritance

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        JSON Config (RDS)                         │
│  node_configurations table / templates/*.json                    │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ { "agents": { "planner": {...}, "investigation": {...} } │    │
│  │   "tools": {...}, "mcps": {...} }                        │    │
│  └─────────────────────────────────────────────────────────┘    │
└───────────────────────────────┬──────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    config_loader.py                              │
│  fetch_team_config(org_id, team_node_id)                        │
│    → calls Config Service API                                   │
│    → returns effective (merged) configuration                   │
└───────────────────────────────┬──────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    agent_builder.py                              │
│  build_agent_hierarchy(effective_config)                        │
│    → builds leaf agents first (k8s, aws, investigation, etc)   │
│    → then builds orchestrators with sub-agents as tools        │
│  resolve_tools(enabled, disabled)                               │
│    → selects tools based on config                              │
└───────────────────────────────┬──────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                 OpenAI Agents SDK Agent                          │
│  Agent(name, instructions, model, tools, output_type)           │
│  Ready to run with Runner.run(agent, query)                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Key Files

| File | Location | Purpose |
|------|----------|---------|
| `agent_builder.py` | `agent/src/ai_agent/core/` | Core builder - constructs agents from JSON |
| `config_loader.py` | `agent/src/ai_agent/core/` | Fetches config from Config Service |
| `hierarchical_config.py` | `config_service/src/core/` | Inheritance logic - deep_merge, effective config |
| `01_slack_incident_triage.json` | `config_service/templates/` | Default template (Starship topology) - auto-applied to new orgs |

---

## JSON Agent Configuration Schema

### Full Example

```json
{
  "agents": {
    "planner": {
      "enabled": true,
      "name": "Planner",
      "description": "Orchestrates complex investigation tasks",
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
        "enabled": ["think", "llm_call", "web_search"],
        "disabled": []
      },
      "sub_agents": ["investigation", "k8s", "aws", "metrics", "coding"],
      "handoff_strategy": "agent_as_tool"
    },
    "investigation": {
      "enabled": true,
      "name": "Investigation Agent",
      "description": "General incident investigation with observability tools",
      "model": {
        "name": "gpt-5.2",
        "temperature": 0.4,
        "max_tokens": 16000
      },
      "prompt": {
        "system": "You are an expert SRE with deep expertise in incident investigation..."
      },
      "max_turns": 25,
      "tools": {
        "enabled": ["*"],
        "disabled": ["write_file", "docker_exec"]
      },
      "sub_agents": []
    },
    "k8s": {
      "enabled": true,
      "name": "Kubernetes Agent",
      "model": {"name": "gpt-5.2", "temperature": 0.3},
      "max_turns": 15,
      "tools": {
        "enabled": [
          "list_pods", "describe_pod", "get_pod_logs", "get_pod_events",
          "describe_deployment", "get_deployment_history", "describe_service"
        ],
        "disabled": []
      }
    }
  }
}
```

### Field Reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `enabled` | boolean | No (default: true) | Whether agent is available |
| `name` | string | No | Display name |
| `description` | string | No | What the agent does |
| `model.name` | string | No (default: gpt-5.2) | Model to use |
| `model.temperature` | float | No (default: 0.4) | Temperature 0-2 |
| `model.max_tokens` | int | No | Max output tokens |
| `prompt.system` | string | No | System prompt |
| `prompt.prefix` | string | No | Prepended to system prompt |
| `prompt.suffix` | string | No | Appended to system prompt |
| `max_turns` | int | No (default: 20) | Max LLM turns |
| `tools.enabled` | array | No | Tools to enable (`["*"]` = all) |
| `tools.disabled` | array | No | Tools to disable |
| `sub_agents` | array | No | Agent IDs to include as tools |
| `handoff_strategy` | string | No | How to invoke sub-agents |

---

## Core Functions

### 1. `build_agent_from_config(agent_id, effective_config, parent_agents)`

Constructs a single Agent from JSON configuration.

```python
def build_agent_from_config(
    agent_id: str,
    effective_config: Dict[str, Any],
    parent_agents: Optional[Dict[str, Agent]] = None,
) -> Optional[Agent]:
    """
    Build an agent from configuration.
    
    Args:
        agent_id: The agent identifier (e.g., 'investigation', 'k8s')
        effective_config: The effective (merged) configuration
        parent_agents: Dict of already-built agents (for sub-agent references)
    
    Returns:
        Constructed Agent or None if disabled
    """
    agents_config = effective_config.get('agents', {})
    agent_config = agents_config.get(agent_id, {})
    
    if not agent_config.get('enabled', True):
        return None
    
    # Extract settings
    name = agent_config.get('name', agent_id.title())
    model_config = agent_config.get('model', {})
    prompt_config = agent_config.get('prompt', {})
    tools_config = agent_config.get('tools', {})
    max_turns = agent_config.get('max_turns', 20)
    
    # Build system prompt
    system_prompt = prompt_config.get('system', '') or get_default_prompt(agent_id)
    
    # Resolve tools
    tools = resolve_tools(
        enabled=tools_config.get('enabled', ['*']),
        disabled=tools_config.get('disabled', []),
    )
    
    # Add sub-agent tools
    sub_agent_ids = agent_config.get('sub_agents', [])
    if sub_agent_ids and parent_agents:
        for sub_id in sub_agent_ids:
            if sub_id in parent_agents:
                sub_tool = _create_agent_tool(sub_id, parent_agents[sub_id], max_turns)
                tools.append(sub_tool)
    
    return Agent(
        name=name,
        instructions=system_prompt,
        model=model_config.get('name', 'gpt-5.2'),
        model_settings=ModelSettings(temperature=model_config.get('temperature', 0.4)),
        tools=tools,
        output_type=AgentResult,
    )
```

### 2. `build_agent_hierarchy(effective_config)`

Builds all agents with proper dependency ordering.

```python
def build_agent_hierarchy(effective_config: Dict[str, Any]) -> Dict[str, Agent]:
    """
    Build all agents based on configuration.
    
    Handles dependencies - builds sub-agents first, then agents that use them.
    """
    agents_config = effective_config.get('agents', {})
    built_agents: Dict[str, Agent] = {}
    
    # Step 1: Build leaf agents (those without sub_agents)
    for agent_id, config in agents_config.items():
        if not config.get('sub_agents'):
            agent = build_agent_from_config(agent_id, effective_config)
            if agent:
                built_agents[agent_id] = agent
    
    # Step 2: Build orchestrator agents (those with sub_agents)
    for agent_id, config in agents_config.items():
        if config.get('sub_agents') and agent_id not in built_agents:
            agent = build_agent_from_config(
                agent_id, effective_config, parent_agents=built_agents
            )
            if agent:
                built_agents[agent_id] = agent
    
    return built_agents
```

### 3. `resolve_tools(enabled, disabled)`

Selects tools based on configuration.

```python
def resolve_tools(
    enabled: List[str],
    disabled: List[str],
) -> List[Callable]:
    """
    Resolve the list of tools to use based on config.
    
    Args:
        enabled: List of tool names to enable ("*" = all)
        disabled: List of tool names to disable
    
    Returns:
        List of tool functions
    """
    all_tools = get_all_available_tools()  # Master registry
    
    # Determine which tools to include
    if "*" in enabled:
        result_tools = list(all_tools.values())
    else:
        result_tools = [all_tools[name] for name in enabled if name in all_tools]
    
    # Remove disabled tools
    if disabled:
        disabled_set = set(disabled)
        result_tools = [t for t in result_tools if t.__name__ not in disabled_set]
    
    return result_tools
```

### 4. `_create_agent_tool(agent_id, agent, max_turns)`

Wraps an agent as a callable tool for the planner.

```python
def _create_agent_tool(agent_id: str, agent: Agent, max_turns: int) -> Callable:
    """Create a function_tool wrapper for an agent."""
    
    @function_tool
    def call_agent(query: str) -> str:
        """Call a specialized agent with a natural language query."""
        result = _run_agent_in_thread(agent, query, max_turns)
        return result.final_output.model_dump_json()
    
    call_agent.__name__ = f"call_{agent_id}_agent"
    return call_agent
```

---

## Tool Registry

All available tools are registered in `agent_builder.py:get_all_available_tools()`:

| Category | Tools |
|----------|-------|
| **Meta** | `think`, `llm_call`, `web_search` |
| **Kubernetes** | `list_pods`, `describe_pod`, `get_pod_logs`, `get_pod_events`, `describe_deployment`, `get_deployment_history`, `describe_service`, `get_pod_resource_usage` |
| **AWS** | `describe_ec2_instance`, `get_cloudwatch_logs`, `describe_lambda_function`, `get_rds_instance_status`, `query_cloudwatch_insights`, `get_cloudwatch_metrics`, `list_ecs_tasks` |
| **Anomaly** | `detect_anomalies`, `correlate_metrics`, `find_change_point`, `forecast_metric`, `analyze_metric_distribution` |
| **Grafana** | `grafana_list_dashboards`, `grafana_get_dashboard`, `grafana_query_prometheus`, `grafana_list_datasources`, `grafana_get_annotations`, `grafana_get_alerts` |
| **Docker** | `docker_ps`, `docker_logs`, `docker_inspect`, `docker_exec`, `docker_images`, `docker_stats` |
| **Git** | `git_status`, `git_diff`, `git_log`, `git_blame`, `git_show`, `git_branch_list` |
| **Coding** | `repo_search_text`, `read_file`, `write_file`, `list_directory`, `python_run_tests`, `pytest_run`, `run_linter` |
| **GitHub** | `search_github_code`, `read_github_file`, `list_pull_requests`, `list_issues` |
| **Knowledge Base** | `search_knowledge_base`, `ask_knowledge_base`, `get_knowledge_context`, `list_knowledge_trees` |
| **Remediation** | `propose_remediation`, `propose_pod_restart`, `propose_deployment_restart`, `propose_scale_deployment`, `propose_deployment_rollback`, `propose_emergency_action`, `get_current_replicas`, `list_pending_remediations`, `get_remediation_status` |

---

## Usage Examples

### Get Planner for a Team

```python
from ai_agent.core.config_loader import get_planner_for_team
from agents import Runner

# Fetch config and build planner
planner = get_planner_for_team(org_id="extend", team_node_id="extend-sre")

# Run investigation
result = await Runner.run(planner, "Investigate high error rate in payment service")
print(result.final_output)
```

### Using ConfigContext

```python
from ai_agent.core.config_loader import ConfigContext
from ai_agent.core.agent_builder import get_planner_agent
from agents import Runner

async with ConfigContext("extend", "extend-sre") as config:
    planner = get_planner_agent(config)
    result = await Runner.run(planner, query)
```

### Get a Specific Agent

```python
from ai_agent.core.config_loader import get_agent_for_team

k8s_agent = get_agent_for_team(
    agent_id="k8s",
    org_id="extend",
    team_node_id="extend-sre"
)

result = await Runner.run(k8s_agent, "List pods in kube-system namespace")
```

---

## Configuration Inheritance

Teams inherit from their organization's config with selective overrides:

```
Org Config (auto-applied from slack-incident-triage template)
    │
    ├── Team A Config (overrides prompt.suffix)
    │       └── Effective: org + team overrides
    │
    └── Team B Config (overrides tools.disabled)
            └── Effective: org + team overrides
```

The Config Service computes the effective config using `deep_merge()`:

```python
effective_config = deep_merge(org_config, team_overrides)
```

---

## Current Status

| Component | Status | Notes |
|-----------|--------|-------|
| `agent_builder.py` | ✅ Complete | Can build agents from JSON |
| `config_loader.py` | ✅ Complete | Fetches from Config Service |
| Config Service API | ✅ Complete | `/api/v1/config/.../effective` |
| Default template | ✅ Complete | Auto-applied `slack-incident-triage` template on org creation |
| **`api_server.py` integration** | ⚠️ Partial | Some paths still use hardcoded agents |
| **Orchestrator integration** | ⚠️ Partial | Needs to pass org_id/team_node_id |

### Next Steps

1. Update `api_server.py` to use `get_planner_for_team()` instead of hardcoded agent imports
2. Update Orchestrator to pass `org_id`/`team_node_id` to agent service
3. Add Coralogix and Snowflake tools to the tool registry
4. Test full flow: Slack → Orchestrator → Agent (with team config)

---

## Validation

Agent configs can be validated:

```python
from ai_agent.core.agent_builder import validate_agent_config

errors = validate_agent_config({
    "model": {"name": "invalid-model"},
    "max_turns": 500,
})
# errors = ["Unknown model: invalid-model", "max_turns must be between 1 and 100"]
```

Validation checks:
- Model name is valid (gpt-5.2, gpt-5.2-mini, etc.)
- Temperature is 0-2
- max_turns is 1-100
- Tool names exist in registry


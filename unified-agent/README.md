# Unified Agent

Multi-model AI agent for incident investigation with config-driven agent hierarchy and sandbox isolation.

## Features

- **Multi-LLM Support**: Claude, Gemini, OpenAI via LiteLLM
- **Config-Driven Agents**: Define agents via JSON config (no code changes)
- **Sandbox Isolation**: gVisor-based Kubernetes sandboxes
- **300+ Tools**: Kubernetes, AWS, GitHub, Grafana, Datadog, and more
- **Skills System**: Progressive disclosure of domain knowledge
- **Subagents**: Isolated context execution for deep-dive analysis

## Architecture

```
Config Service (agent definitions as JSON)
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│ Unified Agent (in gVisor sandbox)                       │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │ OpenHands Provider (LiteLLM)                    │   │
│  │ - anthropic/claude-sonnet-4-20250514            │   │
│  │ - gemini/gemini-2.0-flash                       │   │
│  │ - openai/gpt-4o                                 │   │
│  └─────────────────────────────────────────────────┘   │
│                    │                                    │
│  ┌─────────────────▼─────────────────────────────┐    │
│  │ Config-Driven Agent Builder                    │    │
│  │ - build_agent_hierarchy()                      │    │
│  │ - Topological sort for dependencies           │    │
│  │ - Agent-as-tool pattern                        │    │
│  └─────────────────────────────────────────────────┘   │
│                    │                                    │
│  ┌─────────────────▼─────────────────────────────┐    │
│  │ Tools + Skills                                 │    │
│  │ - 300+ infrastructure tools                    │    │
│  │ - 16 domain-specific skills                    │    │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
         │
         ▼ (via Envoy sidecar)
    External APIs
```

## Project Structure

```
unified-agent/
├── src/unified_agent/
│   ├── core/
│   │   ├── agent.py          # Agent/ModelSettings/function_tool
│   │   ├── agent_builder.py  # Config-driven agent construction
│   │   ├── config.py         # Config loading (env, service, yaml)
│   │   ├── events.py         # Stream event protocol (SSE)
│   │   └── runner.py         # LiteLLM-based agent execution
│   │
│   ├── providers/
│   │   ├── base.py           # LLMProvider abstract interface
│   │   └── openhands.py      # Full OpenHands provider with tools
│   │
│   ├── tools/
│   │   ├── __init__.py       # Tool registry
│   │   ├── kubernetes.py     # K8s tools (pods, deployments, services)
│   │   └── meta.py           # Meta tools (think, web_search, llm_call)
│   │
│   ├── skills/
│   │   ├── loader.py         # Skill discovery and loading
│   │   └── bundled/          # 16 domain-specific skills
│   │       ├── investigate/
│   │       ├── observability-coralogix/
│   │       ├── observability-datadog/
│   │       ├── metrics-analysis/
│   │       ├── infrastructure-kubernetes/
│   │       ├── remediation/
│   │       └── ...
│   │
│   └── sandbox/
│       ├── auth.py           # JWT generation/validation
│       ├── manager.py        # K8s Sandbox CRD management
│       └── server.py         # FastAPI runtime (port 8888)
│
├── examples/                 # Usage examples
├── tests/                    # Test suite
├── pyproject.toml            # Dependencies
└── README.md
```

## Quick Start

### Environment Variables

```bash
# Required: At least one LLM API key
ANTHROPIC_API_KEY=sk-ant-...
# OR
GEMINI_API_KEY=...
# OR
OPENAI_API_KEY=sk-...

# Optional: Override default model
LLM_MODEL=anthropic/claude-sonnet-4-20250514
```

### Basic Usage

```python
from unified_agent.core import Agent, Runner
from unified_agent.providers import create_provider, ProviderConfig

# Create a simple agent
agent = Agent(
    name="Investigator",
    instructions="You are an SRE expert. Investigate issues thoroughly.",
    model="anthropic/claude-sonnet-4-20250514",
    tools=[],  # Add tools as needed
)

# Run with the Runner
result = await Runner.run(agent, "Why is the checkout service slow?")
print(result.final_output)
```

### Using the Provider Directly

```python
from unified_agent.providers import create_provider, ProviderConfig, SubagentConfig

# Configure provider
config = ProviderConfig(
    cwd="/workspace",
    thread_id="investigation-123",
    model="gemini/gemini-2.0-flash",
    allowed_tools=["Bash", "Read", "Glob", "Grep", "Task", "Skill"],
    subagents={
        "log-analyst": SubagentConfig(
            name="log-analyst",
            description="Log analysis specialist",
            prompt="You are a log analysis expert...",
            tools=["Bash", "Read", "Glob", "Grep"],
            model="sonnet",
        ),
    },
)

# Create and use provider
provider = create_provider(config)
await provider.start()

async for event in provider.execute("Analyze the error logs from the past hour"):
    print(f"[{event.type}] {event.data}")

await provider.close()
```

## Supported Models

| Provider | Model | Notes |
|----------|-------|-------|
| Anthropic | `anthropic/claude-sonnet-4-20250514` | Default |
| Anthropic | `anthropic/claude-opus-4-20250514` | Best quality |
| Anthropic | `anthropic/claude-haiku-4-20250514` | Fastest |
| Google | `gemini/gemini-2.0-flash` | Fast, cost-effective |
| Google | `gemini/gemini-1.5-pro` | Better reasoning |
| OpenAI | `openai/gpt-4o` | Good balance |
| OpenAI | `openai/gpt-4o-mini` | Cost-effective |

## Built-in Tools

| Tool | Description |
|------|-------------|
| `bash` | Execute bash commands |
| `read_file` | Read file contents |
| `write_file` | Write to files |
| `edit_file` | Edit files (find/replace) |
| `glob` | Find files by pattern |
| `grep` | Search file contents |
| `task` | Spawn subagents |
| `skill` | Load domain skills |
| `web_search` | Search the web |
| `web_fetch` | Fetch web pages |

## Development

### Install Dependencies

```bash
pip install -e ".[all]"
```

### Run Tests

```bash
pytest tests/
```

### Build Docker Image

```bash
docker build -t unified-agent:latest .
```

## Migration Status

This consolidation of `agent/` and `sre-agent/` is **complete**:

### Completed
- [x] Directory structure
- [x] Agent/Runner abstraction with LiteLLM
- [x] OpenHands provider (full tool execution)
- [x] Events protocol (SSE streaming)
- [x] Config management (env, config-service, yaml)
- [x] Config-driven agent builder (topological sort, agent-as-tool)
- [x] Sandbox infrastructure (gVisor, JWT, Envoy)
- [x] Skills system (16 skills with scripts)
- [x] **80+ tools ported** (see Tools section below)
- [x] **Dockerfile for sandbox image**
- [x] **Deprecation notices** for agent/ and sre-agent/

### Remaining
- [ ] A2A (Agent-to-Agent) integration
- [ ] MCP integration
- [ ] End-to-end integration testing
- [ ] Port remaining specialized tools (~220 more)

## Ported Tools

| Category | File | Tools |
|----------|------|-------|
| Infrastructure | `kubernetes.py` | 8 (list_pods, describe_pod, get_pod_logs, etc.) |
| Infrastructure | `aws.py` | 5 (describe_ec2, cloudwatch_logs, etc.) |
| Infrastructure | `docker.py` | 6 (docker_ps, docker_logs, docker_inspect, etc.) |
| Version Control | `git.py` | 6 (git_status, git_diff, git_log, etc.) |
| Version Control | `github.py` | 24 (repos, PRs, issues, commits, actions) |
| Observability | `grafana.py` | 5 (dashboards, prometheus, alerts) |
| Observability | `datadog.py` | 3 (metrics, logs, APM) |
| Observability | `sentry.py` | 5 (issues, projects, releases) |
| Incident Mgmt | `pagerduty.py` | 5 (incidents, escalation, MTTR) |
| Collaboration | `slack.py` | 4 (search, history, threads, post) |
| Operations | `remediation.py` | 7 (propose_*, get_status) |
| Meta | `meta.py` | 3 (think, web_search, llm_call) |

## Contributing

The `agent/` and `sre-agent/` directories are deprecated. See their `DEPRECATED.md` files for migration info.

## License

Proprietary - IncidentFox

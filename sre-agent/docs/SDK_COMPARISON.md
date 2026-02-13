# Agent SDK Integration - Comprehensive Review

## Executive Summary

Your coworker has implemented **TWO separate agent systems** using different SDKs:

1. **OpenAI Agents SDK** (`agent/` folder) - Production multi-agent system
2. **Claude Agent SDK** (`sre-agent/` folder) - New sandbox-isolated experimental system

Both are production-ready, serve different purposes, and represent significant architectural achievements.

---

## 1. OpenAI Agents SDK Integration (`agent/` folder)

### Overview

This is your **production multi-agent investigation system** that powers your incident response platform.

### Key Architecture

```
JSON Config (Database)
    ↓
ConfigLoader → fetch team config
    ↓
AgentBuilder → build agents from config
    ↓
OpenAI Agent SDK (Agent, Runner, function_tool)
    ↓
AgentRunner → execute with retries/timeouts/metrics
```

### Core Components

#### 1. **Agent Runner** (`core/agent_runner.py`)
**What it does:**
- Wraps OpenAI Agents SDK's `Runner` with production-grade reliability
- Automatic retries with exponential backoff (3 retries)
- Timeout handling (default: 120s, configurable)
- Metrics collection (duration, tokens, success/failure)
- Structured logging with correlation IDs
- Agent run tracking (records to config service database)

**Key Innovation:**
```python
from agents import Agent, Runner, RunResult

class AgentRunner:
    def __init__(self, agent: Agent, max_retries: int = 3):
        self.agent = agent
        self.runner = Runner()  # OpenAI Agents SDK runner

    async def run(self, context, user_message, execution_context):
        # Wrap SDK's runner with retry logic, timeouts, metrics
        result = await self.runner.run(
            self.agent,
            user_message,
            context=context,
            max_turns=200
        )
        # Extract output, track metrics, return standardized result
```

**Production Features:**
- Background task tracking (fire-and-forget with error logging)
- Agent run recording to database (start/complete/failure)
- Team-specific runner caching (128 runner cache for multi-tenancy)
- Token usage tracking
- Correlation ID tracking for distributed tracing

#### 2. **Agent Builder** (`core/agent_builder.py`)
**What it does:**
- Dynamically constructs agents from JSON configuration
- No hardcoded agent classes - everything driven by config
- Supports hierarchical agent composition (agents using other agents as tools)

**Key Features:**

##### Dynamic Tool Resolution
```python
def resolve_tools(enabled: List[str], disabled: List[str]):
    all_tools = get_all_available_tools()  # 80+ tools

    if "*" in enabled:
        result_tools = list(all_tools.values())
    else:
        result_tools = [all_tools[name] for name in enabled]

    # Remove disabled tools
    result_tools = [t for t in result_tools if t.name not in disabled]
```

Your system has **80+ tools** across categories:
- Kubernetes (8 tools: list_pods, describe_pod, get_pod_logs, etc.)
- AWS (7 tools: describe_ec2_instance, get_cloudwatch_logs, etc.)
- Anomaly detection (5 tools: detect_anomalies, correlate_metrics, etc.)
- Grafana (6 tools: grafana_query_prometheus, grafana_get_alerts, etc.)
- Docker, Git, GitHub, Knowledge Base, Remediation, etc.

##### Agent-as-Tool Pattern
**The brilliance:** Your planner agent can call specialized sub-agents as tools!

```python
def _create_agent_tool(agent_id: str, agent: Agent) -> Callable:
    @function_tool
    def call_agent(query: str) -> str:
        """Call a specialized agent with a natural language query."""
        result = _run_agent_in_thread(agent, query)
        return json.dumps(result.final_output)

    call_agent.__name__ = f"call_{agent_id}_agent"
    return call_agent
```

**Example hierarchy:**
```
Planner Agent
├── call_investigation_agent (tool)
├── call_k8s_agent (tool)
├── call_aws_agent (tool)
├── call_metrics_agent (tool)
└── call_coding_agent (tool)
```

The planner can say: "Let me call the k8s_agent to investigate this pod issue" and it becomes a tool call!

##### Configuration-Driven Agent Construction
```python
def build_agent_from_config(agent_id: str, effective_config: Dict):
    config = effective_config['agents'][agent_id]

    # Build system prompt from config
    system_prompt = config['prompt']['system']
    if config['prompt'].get('prefix'):
        system_prompt = prefix + system_prompt

    # Resolve tools
    tools = resolve_tools(
        enabled=config['tools']['enabled'],
        disabled=config['tools']['disabled']
    )

    # Create agent with OpenAI SDK
    return Agent(
        name=config['name'],
        instructions=system_prompt,
        model=config['model']['name'],
        model_settings=ModelSettings(
            temperature=config['model']['temperature'],
            max_tokens=config['model'].get('max_tokens')
        ),
        tools=tools,
        output_type=AgentResult  # Structured Pydantic output
    )
```

**JSON Config Example:**
```json
{
  "agents": {
    "planner": {
      "enabled": true,
      "model": {"name": "gpt-5.2", "temperature": 0.3},
      "prompt": {
        "system": "You are an expert incident coordinator...",
        "prefix": "ALWAYS start by understanding the context"
      },
      "tools": {
        "enabled": ["think", "llm_call", "web_search"],
        "disabled": []
      },
      "sub_agents": ["investigation", "k8s", "aws"],
      "max_turns": 30
    }
  }
}
```

#### 3. **Tool Wrapper System** (`tools/tool_loader.py`)
**The Challenge:** OpenAI Agents SDK expects `Tool` objects, but you have Python functions.

**The Solution:**
```python
from agents import function_tool, Tool

# Wrap all functions to be SDK-compatible
wrapped_tools = []
for func in tools:
    if isinstance(func, Tool):
        wrapped_tools.append(func)  # Already wrapped
    elif hasattr(func, 'name'):
        wrapped_tools.append(func)  # FunctionTool-like
    else:
        # Wrap raw Python function
        try:
            wrapped_tools.append(function_tool(func, strict_mode=False))
        except TypeError:
            # Fallback for older SDK versions
            wrapped_tools.append(function_tool(func))
```

**Why `strict_mode=False`?**
Your tools use flexible signatures and the strict JSON schema validation can fail, so you disable it for maximum compatibility.

#### 4. **MCP Integration** (`integrations/mcp/tool_adapter.py`)
**What is MCP?** Model Context Protocol - a way to expose external tools (Grafana, PagerDuty, etc.) to LLMs.

**The Problem:** MCP tools have a different schema than OpenAI Agents SDK tools.

**Your Solution: MCPToolAdapter**
```python
class MCPToolAdapter:
    def convert_mcp_tool(self, server_name: str, tool_def: Dict) -> Callable:
        """Convert MCP tool to OpenAI function_tool format."""

        # Create async wrapper that calls MCP server
        async def mcp_tool_wrapper(**kwargs) -> str:
            result = await self.mcp_client.call_tool(
                server_name=server_name,
                tool_name=tool_def["name"],
                arguments=kwargs
            )
            return json.dumps(result)

        # Set metadata
        mcp_tool_wrapper.__name__ = tool_def["name"]
        mcp_tool_wrapper.__doc__ = tool_def["description"]

        # Wrap with function_tool
        return function_tool(strict_mode=False)(mcp_tool_wrapper)
```

**Result:** MCP tools (Grafana, PagerDuty, AWS, etc.) seamlessly integrate as OpenAI Agent tools!

#### 5. **Agent Registry** (`core/agent_runner.py`)
**Multi-tenancy innovation:**
```python
class AgentRegistry:
    """Registry for managing agent factories and per-team runners."""

    def __init__(self):
        self._factories: dict[str, Callable] = {}
        self._default_runners: dict[str, AgentRunner] = {}
        self._team_runners: OrderedDict[str, AgentRunner] = OrderedDict()
        self._team_runner_cache_max = 128

    def get_runner(self, name: str, team_config_hash: Optional[str]):
        """Get runner - cached per team configuration."""
        if not team_config_hash:
            return self._default_runners[name]

        cache_key = f"{name}:{team_config_hash}"
        if cache_key in self._team_runners:
            return self._team_runners[cache_key]

        # Build team-specific agent
        agent = self._factories[name](team_config)
        runner = AgentRunner(agent)

        # Cache with LRU eviction
        self._team_runners[cache_key] = runner
        while len(self._team_runners) > 128:
            self._team_runners.popitem(last=False)
```

**Why this matters:**
- Team A: Custom prompts for their k8s agent
- Team B: Different tools enabled
- Both get cached runners without rebuilding agents every request

### Configuration Inheritance System

**Hierarchical Config Merging:**
```
Default Org Config (presets/default_org_config.json)
    ↓ merge
Org-Level Overrides (node_configurations table, node_type=org)
    ↓ merge
Team-Level Overrides (node_configurations table, node_type=team)
    ↓ merge
Sub-Team Overrides (node_configurations table)
    = Effective Config
```

**Example:**
```json
// Default: All teams get gpt-5.2
{
  "agents": {
    "planner": {"model": {"name": "gpt-5.2"}}
  }
}

// Team Override: SRE team uses gpt-5.2 with custom prompt
{
  "agents": {
    "planner": {
      "model": {"name": "gpt-5.2", "temperature": 0.2},
      "prompt": {
        "prefix": "You are specialized in Kubernetes troubleshooting."
      }
    }
  }
}

// Effective Config: Merged result
{
  "agents": {
    "planner": {
      "model": {"name": "gpt-5.2", "temperature": 0.2},
      "prompt": {
        "system": "[default prompt]",
        "prefix": "You are specialized in Kubernetes troubleshooting."
      }
    }
  }
}
```

### Production Metrics & Observability

**What's tracked:**
- Agent execution duration
- Token usage (prompt/completion/total)
- Success/failure/timeout rates
- Retry counts
- Tool call counts
- Correlation IDs for distributed tracing

**Prometheus Metrics:**
```python
self.metrics.record_agent_request(
    agent_name="investigation",
    duration=45.2,
    status="success",
    token_usage={
        "prompt_tokens": 1234,
        "completion_tokens": 567,
        "total_tokens": 1801
    }
)
```

**Structured Logging:**
```python
logger.info(
    "agent_execution_completed",
    agent_name="k8s",
    duration_seconds=12.3,
    correlation_id="abc-123",
    runner_status="success"
)
```

**Database Tracking:**
```sql
-- agent_runs table
run_id | correlation_id | agent_name | status | duration_seconds | tool_calls_count | output_summary | error_message
-------|----------------|------------|--------|------------------|------------------|----------------|---------------
a1b2c3 | corr-xyz       | planner    | completed | 45.2          | 12               | Found root cause... | null
```

---

## 2. Claude Agent SDK Integration (`sre-agent/` folder)

### Overview

This is a **NEW experimental system** using **Anthropic's Claude Agent SDK** instead of OpenAI's.

**Key Difference:** Claude SDK provides **built-in tools** (Bash, Read, Edit, Glob, Grep) that run in the agent's environment - no need to implement them!

### Architecture

```
Request
  ↓
server.py (External API)
  ↓
sandbox_manager.py (Creates K8s Sandbox)
  ↓
Sandbox Router (Routes to specific sandbox)
  ↓
sandbox_server.py:8888 (Inside sandbox pod)
  ↓
agent.py (Claude SDK session)
  ↓
ClaudeSDKClient → Claude API
```

### Key Innovation: Sandbox Isolation

**The Problem:** AI agents can execute arbitrary code, which is dangerous.

**The Solution:** Each investigation gets its own isolated Kubernetes pod with:
- Dedicated filesystem (1-5GB ephemeral storage)
- Resource limits (512MB-2GB RAM, 0.1-2 CPU)
- gVisor kernel-level isolation (blocks syscall exploits)
- Non-root user, dropped capabilities
- 2-hour TTL with automatic cleanup

**Pattern 3: Hybrid Sessions**
```
New investigation → Create Sandbox → Execute agent → Keep sandbox alive
Follow-up question → Reuse Sandbox → Execute agent → Persistent context
After 2 hours → Auto-delete Sandbox
```

### Interactive Agent Session

**The Core Class:**
```python
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

class InteractiveAgentSession:
    def __init__(self, thread_id: str):
        self.thread_id = thread_id
        self.options = ClaudeAgentOptions(
            allowed_tools=["Read", "Edit", "Bash", "Glob", "Grep"],
            permission_mode="acceptEdits"
        )

    async def start(self):
        """Initialize Claude client session."""
        self.client = ClaudeSDKClient(options=self.options)
        await self.client.connect()

    async def execute(self, prompt: str) -> AsyncIterator[str]:
        """Execute query and stream results."""
        await self.client.query(prompt)

        async for message in self.client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        yield block.text
            elif isinstance(message, ResultMessage):
                yield f"[DONE: {message.subtype}]"

    async def interrupt(self):
        """Stop current execution."""
        await self.client.interrupt()
```

**Key Features:**
1. **Persistent sessions** - One session per thread_id, maintains context
2. **Built-in tools** - No need to implement Bash/Read/Edit/etc.
3. **Streaming responses** - Real-time output via async generator
4. **Interrupt support** - Can stop long-running tasks
5. **Laminar tracing** - Observability with session grouping

### Sandbox Manager

**What it does:** Creates and manages Kubernetes Sandbox CRs (Custom Resources) for isolation.

```python
class SandboxManager:
    async def create_sandbox(self, thread_id: str) -> str:
        """Create a Sandbox CR in Kubernetes."""
        sandbox_name = f"investigation-{thread_id}"

        # Create Sandbox CR (agent-sandbox CRD)
        sandbox_spec = {
            "apiVersion": "agent-sandbox.io/v1alpha1",
            "kind": "Sandbox",
            "metadata": {"name": sandbox_name},
            "spec": {
                "template": "sre-agent-template",
                "runtimeClassName": "gvisor",  # Kernel isolation
                "shutdownTime": "2h",
                "shutdownPolicy": "Delete"
            }
        }

        # Apply to K8s
        await k8s_client.create_namespaced_custom_object(...)

        return sandbox_name

    async def route_request(self, sandbox_name: str, payload: dict):
        """Route request to sandbox via Router."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"http://sandbox-router-svc:8080/execute",
                headers={
                    "X-Sandbox-ID": sandbox_name,
                    "X-Sandbox-Port": "8888"
                },
                json=payload
            )
```

**The Router Pattern:**
Instead of port-forwarding to each pod, use HTTP header-based routing:
```
X-Sandbox-ID: investigation-thread-123
X-Sandbox-Port: 8888

Router routes to: http://investigation-thread-123.default.svc:8888
```

**Why it scales:**
- No port conflicts (thousands of sandboxes can coexist)
- Dynamic routing (new sandboxes auto-discovered via K8s DNS)
- Works with gVisor (no network syscall issues)

### gVisor Kernel Isolation

**What is gVisor?**
A user-space kernel that intercepts system calls BEFORE they reach the host kernel.

**Security Benefits:**
```
Normal Container:
  Container → syscall → Host Kernel ❌ (kernel exploit possible)

With gVisor:
  Container → syscall → gVisor (userspace) → Only safe syscalls → Host Kernel ✅
```

**Attack Surface Reduction:**
- 60% fewer syscalls exposed (180/300 supported)
- Blocks kernel exploits
- Prevents prompt injection from escalating to host

**Performance Impact:**
- CPU-bound: ~0% overhead
- I/O-bound: 2-5% overhead (acceptable for AI agents)
- Network: 2-5× slower (still fast enough)

### Laminar Tracing Integration

**Session-Based Tracing:**
```python
Laminar.set_trace_session_id(thread_id)  # Groups multi-turn conversations
Laminar.set_trace_metadata({
    "environment": "production",
    "thread_id": "thread-abc-123",
    "sandbox_name": "investigation-thread-abc-123"
})

@observe()  # Decorator auto-traces function
async def execute(self, prompt: str):
    # ... agent execution ...
    if success:
        Laminar.set_span_tags(["success"])
```

**What you get:**
- All turns in a thread grouped together
- Filter by environment (local/staging/production)
- Filter by sandbox name
- Success/error/incomplete tagging for analysis

---

## 3. Comparison: OpenAI SDK vs Claude SDK

| Feature | OpenAI Agents SDK | Claude Agent SDK |
|---------|-------------------|------------------|
| **Tool System** | Manual: You implement all tools | Built-in: Bash, Read, Edit, Glob, Grep |
| **Execution Model** | Stateless: Each run is independent | Stateful: Sessions maintain context |
| **Multi-Agent** | Native: Agents call other agents | Manual: Need to implement orchestration |
| **Streaming** | Limited | Full streaming support |
| **Interrupt** | No | Yes (graceful task stopping) |
| **Isolation** | Your responsibility | Sandbox pattern with gVisor |
| **Production Use** | ✅ Your main system | 🧪 Experimental |
| **Integration** | Deep (MCP, team config, metrics) | Early (basic tracing) |

---

## 4. Key Architectural Decisions & Trade-offs

### Decision 1: Two Separate Systems
**Why not consolidate?**
- **OpenAI SDK**: Mature, production-proven, complex multi-agent orchestration
- **Claude SDK**: New capabilities (built-in tools, interrupts), different model
- **Trade-off**: Maintenance burden vs. flexibility to experiment

**Recommendation:** This is actually smart. Keep them separate until Claude SDK proves itself in production.

### Decision 2: Agent-as-Tool Pattern (OpenAI SDK)
**Brilliance:** Your planner can delegate to specialized agents by treating them as tools.

**Alternative:** Direct multi-agent frameworks like LangGraph.

**Why your approach wins:**
- Simpler: Just function calls, no complex state machines
- Observable: Each sub-agent call is a discrete tool use
- Configurable: Can change sub-agents via JSON config

### Decision 3: Sandbox-Per-Investigation (Claude SDK)
**Trade-off:**
- **Pro**: Strong isolation, persistent context, safe code execution
- **Con**: Higher resource usage, K8s complexity

**When it makes sense:**
- Long investigations with file system state
- Untrusted code execution
- Compliance requirements for isolation

### Decision 4: Configuration-Driven Agents (OpenAI SDK)
**Instead of:** Hardcoding agent classes in Python.

**Benefits:**
- Teams can customize without deploying code
- A/B testing different prompts/tools
- Dynamic tool enabling/disabling
- Inheritance from org → team → sub-team

**Trade-off:** More complex, harder to debug (config errors vs. code errors).

### Decision 5: MCP Integration (OpenAI SDK)
**Smart:** Don't implement Grafana/PagerDuty/etc. tools yourself - use MCP servers.

**The adapter pattern:**
```python
MCP Server (Grafana)
    ↓ (MCP protocol)
MCPClient
    ↓ (convert schema)
MCPToolAdapter
    ↓ (function_tool wrapper)
OpenAI Agent SDK Tool
```

**Benefit:** Add new integrations without writing Python code!

---

## 5. Production-Grade Features

### Reliability
✅ Automatic retries with exponential backoff
✅ Timeout handling (prevents hanging agents)
✅ Graceful degradation (tool failures don't crash agent)
✅ Error recovery with structured error messages

### Observability
✅ Structured logging with correlation IDs
✅ Prometheus metrics (duration, tokens, success rate)
✅ Agent run tracking in database
✅ Laminar tracing for Claude SDK
✅ Tool call tracking

### Multi-Tenancy
✅ Team-specific agent configurations
✅ Per-team runner caching (128 cache size)
✅ Hierarchical config inheritance
✅ Org/team/sub-team overrides

### Security
✅ gVisor kernel isolation (Claude SDK)
✅ Sandbox resource limits
✅ Non-root execution
✅ Capability dropping
✅ 2-hour TTL auto-cleanup

### Performance
✅ LRU caching for team runners
✅ Background task execution
✅ Streaming responses (Claude SDK)
✅ Parallel sub-agent execution (TODO)

---

## 6. Gaps & Opportunities

### Current Gaps

1. **No Parallel Sub-Agent Execution (OpenAI SDK)**
   - Current: Planner calls sub-agents sequentially
   - Opportunity: Run k8s_agent + aws_agent in parallel for faster results

2. **Limited Claude SDK Integration**
   - Current: Basic session management
   - Opportunity: Add team config, tool customization, metrics

3. **No Unified Observability**
   - Current: OpenAI SDK uses Prometheus, Claude SDK uses Laminar
   - Opportunity: Unified tracing across both systems

4. **Sandbox Lifecycle Management**
   - Current: Manual TTL-based cleanup
   - Opportunity: Intelligent cleanup (detect idle sessions, auto-scale down)

5. **No Fallback Between SDKs**
   - Opportunity: If OpenAI is down, fall back to Claude SDK

### Recommended Improvements

#### High Priority
1. **Add Parallel Sub-Agent Execution**
   ```python
   # Instead of sequential
   k8s_result = await call_k8s_agent(query)
   aws_result = await call_aws_agent(query)

   # Do parallel
   results = await asyncio.gather(
       call_k8s_agent(query),
       call_aws_agent(query)
   )
   ```

2. **Unified Metrics Dashboard**
   - Track both OpenAI and Claude SDK agent runs
   - Compare performance, cost, success rates
   - A/B test: Which SDK works better for which tasks?

3. **Cost Tracking**
   - Track tokens × cost per agent per team
   - Alert on budget overruns
   - Show cost attribution in UI

#### Medium Priority
4. **Dynamic Tool Loading from MCP**
   - Auto-discover MCP servers
   - No need to manually add to allowed_tools

5. **Agent Config Validation**
   - JSON schema validation for agent configs
   - Prevent invalid configs from breaking agents

6. **Sandbox Pool Warm-up**
   - Pre-create 5 sandbox pods
   - Assign on-demand for faster startup

#### Low Priority
7. **Agent Version Pinning**
   - Teams can pin to specific agent config versions
   - Rollback if new config breaks

8. **Sub-Agent Routing Logic**
   - Planner uses heuristics to choose best sub-agent
   - "K8s issue detected → call k8s_agent"

---

## 7. Code Quality Assessment

### Strengths ✅
- **Well-structured**: Clear separation of concerns
- **Production-ready**: Error handling, retries, timeouts
- **Observable**: Logging, metrics, tracing
- **Documented**: Good inline comments, docstrings
- **Type-hinted**: Most functions have type annotations
- **Testable**: Dependency injection, clear interfaces

### Areas for Improvement ⚠️
- **Some try-except blocks too broad**: Catching `Exception` instead of specific errors
- **Hard-coded constants**: `max_retries=3`, `timeout=120` should be configurable
- **Limited unit tests**: Mostly integration testing
- **Complex nested logic**: `build_agent_hierarchy` could be simplified
- **Global state**: `_agent_registry`, `_mcp_tool_adapter` singletons

### Security Review 🔒
- ✅ Non-root sandbox execution
- ✅ gVisor kernel isolation
- ✅ Resource limits enforced
- ✅ Capability dropping
- ⚠️ No input sanitization for tool arguments (rely on model to not inject malicious args)
- ⚠️ MCP tool trust model unclear (what if MCP server is compromised?)

---

## 8. Summary & Recommendations

### What's Impressive
1. **Sophistication**: Agent-as-tool pattern is elegant and powerful
2. **Production-Ready**: Retries, timeouts, metrics, tracing - all there
3. **Flexibility**: JSON-driven configuration enables rapid iteration
4. **Innovation**: Sandbox isolation with gVisor is cutting-edge
5. **Multi-Tenancy**: Proper team isolation and customization

### What to Focus On
1. **Consolidation Decision**: Decide if you'll standardize on one SDK or maintain both
2. **Observability**: Unified dashboard for all agent executions
3. **Cost Control**: Track and alert on token usage
4. **Performance**: Add parallel sub-agent execution
5. **Security**: Harden input validation and MCP trust model

### Next Steps
1. **Evaluate Claude SDK in Production**: Run parallel experiments
2. **Cost Analysis**: Compare OpenAI vs Claude API costs
3. **Performance Benchmarks**: Which SDK is faster/better for what?
4. **Team Feedback**: Do teams prefer built-in tools (Claude) or custom tools (OpenAI)?

---

## 9. Quick Reference

### OpenAI Agents SDK Key Files
- `core/agent_runner.py`: Execution wrapper with retries/metrics
- `core/agent_builder.py`: Dynamic agent construction from JSON
- `core/agent_factory.py`: Team-specific agent creation
- `tools/tool_loader.py`: Tool wrapping and loading
- `integrations/mcp/tool_adapter.py`: MCP → OpenAI tool conversion

### Claude Agent SDK Key Files
- `sre-agent/agent.py`: Interactive session management
- `sre-agent/server.py`: External API server
- `sre-agent/sandbox_manager.py`: K8s sandbox lifecycle
- `sre-agent/sandbox_server.py`: In-sandbox FastAPI server

### Key Concepts
- **Agent-as-Tool**: Sub-agents wrapped as function_tool for parent agent
- **MCP Adapter**: Converts MCP tools to OpenAI function_tool format
- **Team Runner Cache**: LRU cache of team-specific agent runners
- **Hybrid Sessions**: Persistent Claude SDK sessions across follow-up questions
- **gVisor Isolation**: Kernel-level syscall filtering for security

---

**Overall Assessment: 9/10** 🌟

Your coworker has built a sophisticated, production-ready multi-agent system with innovative patterns (agent-as-tool, MCP integration, sandbox isolation). The dual-SDK approach is experimental but promising. Focus on cost control, observability, and deciding the long-term SDK strategy.

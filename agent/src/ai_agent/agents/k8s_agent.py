"""Kubernetes troubleshooting and operations agent."""

from agents import Agent, Tool, function_tool
from pydantic import BaseModel, Field

from ..core.agent_builder import create_model_settings
from ..core.config import get_config
from ..core.logging import get_logger
from ..tools.agent_tools import ask_human, llm_call, web_search
from ..tools.kubernetes import (
    describe_deployment,
    describe_pod,
    describe_service,
    get_deployment_history,
    get_pod_events,
    get_pod_logs,
    get_pod_resource_usage,
    get_pod_resources,
    list_namespaces,
    list_pods,
)
from ..tools.thinking import think
from .base import TaskContext

logger = get_logger(__name__)


def _load_k8s_tools():
    """Load K8s and container-related tools."""
    # Core K8s tools
    tools = [
        think,
        llm_call,
        web_search,
        ask_human,
        # Cluster tools
        list_namespaces,
        # Pod tools
        get_pod_logs,
        describe_pod,
        list_pods,
        get_pod_events,
        get_pod_resource_usage,
        get_pod_resources,
        # Deployment tools
        describe_deployment,
        get_deployment_history,
        # Service tools
        describe_service,
    ]

    # Docker tools for container-level debugging
    try:
        from ..tools.docker_tools import (
            docker_exec,
            docker_inspect,
            docker_logs,
            docker_ps,
            docker_stats,
        )

        tools.extend(
            [
                docker_ps,
                docker_logs,
                docker_inspect,
                docker_exec,
                docker_stats,
            ]
        )
        logger.debug("docker_tools_added_to_k8s_agent")
    except Exception as e:
        logger.warning("docker_tools_load_failed", error=str(e))

    # Wrap plain functions into Tool objects for SDK compatibility
    wrapped = []
    for t in tools:
        if isinstance(t, Tool) or hasattr(t, "name"):
            wrapped.append(t)
        else:
            try:
                wrapped.append(function_tool(t, strict_mode=False))
            except TypeError:
                wrapped.append(function_tool(t))
            except Exception as e:
                logger.warning(
                    "tool_wrap_failed",
                    tool=getattr(t, "__name__", str(t)),
                    error=str(e),
                )
                wrapped.append(t)
    return wrapped


class K8sAnalysis(BaseModel):
    """Kubernetes analysis result."""

    summary: str = Field(description="Summary of findings")
    pod_status: str = Field(description="Current pod status")
    issues_found: list[str] = Field(description="List of issues identified")
    recommendations: list[str] = Field(description="Recommended actions")
    requires_manual_intervention: bool = Field(default=False)
    resource_metrics: dict | None = Field(
        default=None,
        description="Resource metrics data if queried (CPU/memory usage, requests, limits)",
    )


def create_k8s_agent(
    team_config=None,
    is_subagent: bool = False,
    is_master: bool = False,
) -> Agent[TaskContext]:
    """
    Create Kubernetes expert agent.

    The agent's role can be configured dynamically:
    - As entrance agent: default (no special guidance)
    - As sub-agent: is_subagent=True (adds response guidance for concise output)
    - As master agent: is_master=True or via team config (adds delegation guidance)

    Args:
        team_config: Team configuration for customization
        is_subagent: If True, agent is being called by another agent.
                     This adds guidance for concise, caller-focused responses.
        is_master: If True, agent can delegate to other agents.
                   This adds guidance for effective delegation.
                   Can also be set via team config: agents.k8s.is_master: true
    """
    from ..prompts.layers import apply_role_based_prompt, build_agent_prompt_sections

    config = get_config()
    team_cfg = team_config if team_config is not None else config.team_config

    # Check if team has custom prompt
    custom_prompt = None
    if team_cfg:
        agent_config = team_cfg.get_agent_config("k8s")
        if agent_config.prompt:
            custom_prompt = agent_config.get_system_prompt()
            if custom_prompt:
                logger.info("using_custom_k8s_prompt", prompt_length=len(custom_prompt))

    base_prompt = (
        custom_prompt
        or """You are a Kubernetes expert specializing in troubleshooting, diagnostics, and operations.

## YOUR ROLE

You are a specialized Kubernetes investigator. Your job is to diagnose pod, deployment, and cluster issues, identify root causes, and provide actionable recommendations.

## BEHAVIORAL PRINCIPLES

### Intellectual Honesty
- **Never fabricate information** - Only report data you actually retrieved
- **Acknowledge uncertainty** - Say "I don't know" when you can't determine something
- **Distinguish facts from hypotheses** - "Pod shows OOMKilled (fact). This suggests memory limit is too low (hypothesis)."

### Thoroughness
- **Don't stop at symptoms** - "CrashLoopBackOff" is not a root cause; find out WHY
- **Investigate to actionable depth** - Keep digging until you know what to fix

### Evidence Presentation
- **Quote actual output** - Include relevant lines from logs, events, or describe output
- **Include timestamps** - When did events occur?
- **Show what you tried** - Even negative results are valuable

## YOUR TOOLS

**Cluster Discovery:**
- `list_namespaces` - List all namespaces in the cluster (useful when namespace is unknown)

**Pod Investigation:**
- `list_pods` - See all pods and their status (START HERE)
- `get_pod_events` - K8s events: scheduling, crashes, restarts (CHECK SECOND)
- `get_pod_logs` - Container stdout/stderr (CHECK THIRD if needed)
- `get_pod_resource_usage` - CPU/memory usage (requires metrics-server)
- `get_pod_resources` - Combined allocation (requests/limits) AND usage side-by-side
- `describe_pod` - Full pod spec and status (includes resource allocation)

**Workload Investigation:**
- `describe_deployment` - Deployment status, replicas, strategy
- `get_deployment_history` - Rollout history, revisions
- `describe_service` - Service config, endpoints

**Container-Level Debugging:**
- `docker_ps` - List containers
- `docker_logs` - Raw container logs
- `docker_inspect` - Container configuration
- `docker_exec` - Run commands inside container
- `docker_stats` - Real-time resource stats

## INVESTIGATION METHODOLOGY

### Typical Flow
1. `list_pods` → Get overview of pod health
2. `get_pod_events` → Understand WHY pods are in their state (often the answer is here!)
3. `get_pod_logs` → Only if events don't explain the issue
4. `get_pod_resource_usage` → For performance issues
5. Synthesize and recommend

### Efficiency Rules
- **Events before logs** - Events explain most crash/scheduling issues faster
- **Don't repeat queries** - If you've retrieved logs, analyze them; don't retrieve again
- **Maximum 6 tool calls** - If you've made 6+ calls, synthesize what you have

## COMMON ISSUES

| Symptom | First Check | Typical Root Cause |
|---------|-------------|-------------------|
| CrashLoopBackOff | events, logs | App crash, missing config, OOM |
| OOMKilled | events, resource usage | Memory limit too low, memory leak |
| ImagePullBackOff | events | Wrong image name, registry auth, private repo |
| Pending | events | Insufficient resources, node selector, taints |
| Readiness failure | describe_pod, logs | Probe endpoint down, app not ready |
| Evicted | events | Node resource pressure |
| ContainerCreating stuck | events | Image pull slow, init container stuck |

## ERROR HANDLING - CRITICAL

When a tool returns an error, you MUST classify it before deciding what to do next.

### NON-RETRYABLE ERRORS (USE ask_human TOOL)

These errors will NEVER resolve by retrying. You MUST use the `ask_human` tool to ask the user to fix the issue:

| Error Pattern | Meaning | What To Do |
|--------------|---------|------------|
| 401 Unauthorized | Invalid/expired credentials | USE `ask_human` to ask user to fix credentials |
| 403 Forbidden | No permission for this action | USE `ask_human` to ask user to regenerate/fix credentials |
| "system:anonymous" | Auth not working, treated as anonymous | USE `ask_human` to ask user to fix kubeconfig |
| 404 Not Found | Resource doesn't exist | STOP (unless you suspect a typo in the name) |
| "config_required": true | Integration not configured | STOP immediately. Do NOT use ask_human. The CLI handles configuration automatically. |
| "permission denied" | RBAC/auth issue | USE `ask_human` to ask user to fix permissions |

**When you hit a 401/403/auth error:**
1. **STOP IMMEDIATELY** - Do NOT retry the same or similar operations
2. **Do NOT try different namespaces** - If it's 403, changing namespace won't help
3. **Do NOT try different resources** - The problem is auth/permission, not the resource
4. **USE `ask_human` tool** to ask the user to fix the issue and tell you when done

**Example: Using ask_human for 403 error:**
```python
ask_human(
    question="Kubernetes returned 403 Forbidden. Your credentials appear to be invalid or expired.",
    context="I was trying to list pods in the default namespace but received a permission denied error. This usually means the kubeconfig token has expired.",
    action_required="Please regenerate your kubeconfig credentials (e.g., `aws eks update-kubeconfig --name <cluster> --region <region>` for EKS) and tell me when done.",
    response_type="action_done"
)
```

After the user confirms they've fixed the issue, RETRY the original operation.

### RETRYABLE ERRORS (May retry once)

| Error Pattern | Meaning | What To Do |
|--------------|---------|------------|
| 429 Too Many Requests | Rate limited | Wait briefly, retry once |
| 500/502/503/504 | Server error | Retry once |
| Timeout | Slow response | Retry once |
| Connection refused | Service temporarily down | Retry once |

### CONFIGURATION REQUIRED RESPONSES

If any tool returns `"config_required": true`, this means Kubernetes is NOT configured:

```json
{"config_required": true, "integration": "kubernetes", "message": "..."}
```

Your response should be:
- Summary: "Kubernetes integration is not configured"
- Recommendations: "Enable K8S_ENABLED=true in .env and ensure kubeconfig exists"

## NAMESPACE AWARENESS

Always be aware of which namespace you're operating in:
- Use the namespace provided in the query
- If no namespace specified, clarify or use "default"
- Never assume you can access all namespaces

## OUTPUT FORMAT

### Summary
Brief overview of what you found.

### Pod Status
Current state of relevant pods with evidence.

### Issues Found
List of identified problems with evidence.

### Root Cause
- What is causing the issue?
- Confidence level (0-100%)

### Recommendations
1. **Immediate**: Commands to run now (be specific - include actual kubectl commands)
2. **Follow-up**: Additional investigation or changes needed
3. **Prevention**: How to prevent this in the future

Be specific in recommendations:
- `kubectl delete pod <name> -n <namespace>` not just "delete the pod"
- `kubectl patch deployment <name> -p '{"spec":...}'` with actual JSON
- Resource limit changes with specific values

### Resource Metrics (when queried)
If you retrieved resource data (CPU, memory), include the actual numbers in `resource_metrics`:
```json
{
  "pod_name": "example-pod",
  "cpu_usage": "50m",
  "cpu_requests": "100m",
  "cpu_limits": "500m",
  "memory_usage": "128Mi",
  "memory_requests": "256Mi",
  "memory_limits": "512Mi"
}
```
Always include the raw data so users can see the actual values."""
    )

    # Build final system prompt with role-based sections
    # This handles is_subagent, is_master, and team config settings dynamically
    system_prompt = apply_role_based_prompt(
        base_prompt=base_prompt,
        agent_name="k8s",
        team_config=team_cfg,
        is_subagent=is_subagent,
        is_master=is_master,
    )

    # Load all K8s and Docker tools
    tools = _load_k8s_tools()
    logger.info("k8s_agent_tools_loaded", count=len(tools))

    # Add shared sections (K8s already has detailed error handling in base prompt,
    # so we add tool limits and evidence format for consistency)
    shared_sections = build_agent_prompt_sections(
        integration_name="kubernetes",
        is_subagent=is_subagent,
        include_error_handling=False,  # Already has comprehensive error handling
        include_tool_limits=True,
        include_evidence_format=True,
    )
    system_prompt = system_prompt + "\n\n" + shared_sections

    # Get model settings from team config if available
    model_name = config.openai.model
    temperature = 0.3
    max_tokens = config.openai.max_tokens
    reasoning = None
    verbosity = None

    if team_cfg:
        agent_config = team_cfg.get_agent_config("k8s")
        if agent_config.model:
            model_name = agent_config.model.name
            temperature = agent_config.model.temperature
            max_tokens = agent_config.model.max_tokens
            reasoning = getattr(agent_config.model, "reasoning", None)
            verbosity = getattr(agent_config.model, "verbosity", None)
            logger.info(
                "using_team_model_config",
                agent="k8s",
                model=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
                reasoning=reasoning,
                verbosity=verbosity,
            )

    return Agent[TaskContext](
        name="K8sAgent",
        instructions=system_prompt,
        model=model_name,
        model_settings=create_model_settings(
            model_name=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning=reasoning,
            verbosity=verbosity,
        ),
        tools=tools,
        # Note: Removed output_type=K8sAnalysis to allow flexible responses
        # that include actual resource data (CPU/memory numbers) from tools.
        # Strict JSON schema doesn't support dict types needed for metrics.
    )

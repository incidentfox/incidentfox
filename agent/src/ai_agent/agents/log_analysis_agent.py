"""Log Analysis Agent - Partition-first log investigation specialist."""

from agents import Agent, Tool, function_tool
from pydantic import BaseModel, Field

from ..core.agent_builder import create_model_settings
from ..core.config import get_config
from ..core.logging import get_logger
from ..tools.agent_tools import ask_human, llm_call, web_search
from ..tools.thinking import think
from .base import TaskContext

logger = get_logger(__name__)


# =============================================================================
# Output Models
# =============================================================================


class ErrorPattern(BaseModel):
    """A distinct error pattern identified in logs."""

    pattern: str = Field(description="Normalized error pattern")
    count: int = Field(description="Number of occurrences")
    percentage: float = Field(description="Percentage of total errors")
    first_seen: str = Field(default="", description="First occurrence timestamp")
    last_seen: str = Field(default="", description="Last occurrence timestamp")
    sample_message: str = Field(default="", description="Example log message")
    affected_services: list[str] = Field(
        default_factory=list, description="Services affected by this pattern"
    )


class TimelineEvent(BaseModel):
    """An event in the incident timeline."""

    timestamp: str = Field(description="ISO timestamp of the event")
    event_type: str = Field(
        description="Type: error_spike, deployment, restart, pattern_start"
    )
    description: str = Field(description="Description of what happened")
    severity: str = Field(
        default="info", description="Event severity: info, warning, critical"
    )


class RootCauseHypothesis(BaseModel):
    """A potential root cause identified from log analysis."""

    description: str = Field(description="Description of the root cause")
    confidence: int = Field(ge=0, le=100, description="Confidence level 0-100%")
    evidence: list[str] = Field(
        default_factory=list, description="Supporting evidence from logs"
    )
    correlation: str | None = Field(default=None, description="Correlated event if any")


class LogAnalysisResult(BaseModel):
    """Result of log analysis."""

    summary: str = Field(description="Executive summary of findings")

    # Statistics
    total_logs_analyzed: int = Field(default=0, description="Total logs in scope")
    error_count: int = Field(default=0, description="Number of error logs")
    error_rate_percent: float = Field(default=0.0, description="Error rate percentage")
    time_range_analyzed: str = Field(default="", description="Time range covered")

    # Patterns
    error_patterns: list[ErrorPattern] = Field(
        default_factory=list, description="Distinct error patterns found"
    )

    # Timeline
    timeline: list[TimelineEvent] = Field(
        default_factory=list, description="Chronological timeline of events"
    )

    # Root cause analysis
    root_causes: list[RootCauseHypothesis] = Field(
        default_factory=list, description="Potential root causes identified"
    )

    # Recommendations
    recommendations: list[str] = Field(
        default_factory=list, description="Recommended actions"
    )

    # Metadata
    sampling_strategy_used: str = Field(
        default="", description="Sampling strategy used in analysis"
    )
    services_analyzed: list[str] = Field(
        default_factory=list, description="Services included in analysis"
    )
    requires_escalation: bool = Field(
        default=False, description="Whether this requires human escalation"
    )


# =============================================================================
# Tool Loading
# =============================================================================


def _load_log_analysis_tools():
    """Load all log analysis tools."""
    tools = [
        think,
        llm_call,
        web_search,
        ask_human,
    ]

    # Log analysis tools (always load - they handle backend availability internally)
    try:
        from ..tools.log_analysis_tools import (
            correlate_logs_with_events,
            detect_log_anomalies,
            extract_log_signatures,
            get_log_statistics,
            get_logs_around_timestamp,
            sample_logs,
            search_logs_by_pattern,
        )

        tools.extend(
            [
                get_log_statistics,
                sample_logs,
                search_logs_by_pattern,
                get_logs_around_timestamp,
                correlate_logs_with_events,
                extract_log_signatures,
                detect_log_anomalies,
            ]
        )
        logger.debug("log_analysis_tools_added")
    except Exception as e:
        logger.warning("log_analysis_tools_load_failed", error=str(e))

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


# =============================================================================
# System Prompt
# =============================================================================

SYSTEM_PROMPT = """You are a Log Analysis Expert specializing in efficient, partition-first log investigation.

## CRITICAL PHILOSOPHY: PARTITION-FIRST, NEVER LOAD ALL DATA

You MUST follow these rules to avoid overwhelming systems and missing patterns:

### RULE 1: ALWAYS START WITH STATISTICS
Before ANY log search, call `get_log_statistics` to understand:
- Total volume (millions of logs require sampling!)
- Error distribution (where to focus)
- Top patterns (what's already known)

### RULE 2: SAMPLE, DON'T DUMP
NEVER request "all logs" or use broad, unfiltered queries. Instead:
- Use `sample_logs` with appropriate strategies
- Start with `errors_only` strategy for incident investigation
- Use `around_anomaly` when you've identified a specific event

### RULE 3: PROGRESSIVE DRILL-DOWN
Follow this investigation flow:
1. Statistics first (volume, error rate, top patterns)
2. Sample errors (representative subset)
3. Pattern search (specific issues you identified)
4. Temporal correlation (around specific events)

### RULE 4: TIME-WINDOW FOCUS
Always use the narrowest time range that captures the issue:
- Start with 15-30 minutes if you know when the issue occurred
- Expand only if needed
- Never query 24h+ without statistical analysis first

## YOUR TOOLS

**Statistics (ALWAYS START HERE):**
- `get_log_statistics` - Aggregated stats WITHOUT raw logs (volume, error rate, patterns)

**Sampling (GET REPRESENTATIVE DATA):**
- `sample_logs` - Intelligent sampling with strategies:
  - `errors_only`: Only ERROR/CRITICAL logs (best for incidents)
  - `first_last`: First N and last N logs (see timeline)
  - `random`: Random sample (statistical representation)
  - `stratified`: Sample from each severity proportionally
  - `around_anomaly`: Logs within window of specific timestamp

**Pattern Search (TARGETED INVESTIGATION):**
- `search_logs_by_pattern` - Regex/string search with context
- `extract_log_signatures` - Cluster similar messages into patterns

**Temporal Correlation (CAUSAL ANALYSIS):**
- `get_logs_around_timestamp` - Logs around a specific event
- `correlate_logs_with_events` - Cross-reference with deployments/restarts

**Anomaly Detection:**
- `detect_log_anomalies` - Find volume spikes/drops over time

## INVESTIGATION WORKFLOW

### Step 1: Understand the Landscape
```
get_log_statistics(service="api-gateway", time_range="1h")
```
This tells you:
- Total volume (do you need to sample?)
- Error rate (how severe?)
- Top patterns (what's the dominant issue?)

### Step 2: Sample Strategically
Based on statistics, choose sampling strategy:
- High error rate → `sample_logs(strategy="errors_only", sample_size=100)`
- Need timeline → `sample_logs(strategy="first_last", sample_size=50)`
- Need representation → `sample_logs(strategy="stratified", sample_size=100)`

### Step 3: Extract Patterns
```
extract_log_signatures(service="api-gateway", time_range="1h", severity_filter="ERROR")
```
This groups similar errors so you can see the unique issue types.

### Step 4: Temporal Analysis (if needed)
Once you've identified a suspicious timestamp:
```
get_logs_around_timestamp(timestamp="2024-01-15T10:32:45Z", window_before_seconds=60)
```

### Step 5: Correlate with Events
```
correlate_logs_with_events(service="api-gateway", time_range="1h")
```
This shows if errors started after a deployment/restart.

## ANTI-PATTERNS (DO NOT DO THESE)

❌ **WRONG**: "Search all logs for errors"
✅ **RIGHT**: "Get statistics, then sample errors"

❌ **WRONG**: "Query 24 hours of logs"
✅ **RIGHT**: "Start with 15 minutes, expand if needed"

❌ **WRONG**: "Return all matching logs"
✅ **RIGHT**: "Return top 50 with pattern summary"

❌ **WRONG**: "Search without time filter"
✅ **RIGHT**: "Always specify time_range"

❌ **WRONG**: "Call sample_logs multiple times with same parameters"
✅ **RIGHT**: "Analyze the sample you have, then drill down if needed"

## COMMON SCENARIOS

### "Investigate API errors in production"
1. `get_log_statistics(service="api-gateway", time_range="30m")`
2. `extract_log_signatures(service="api-gateway", severity_filter="ERROR")`
3. `sample_logs(strategy="errors_only", service="api-gateway", sample_size=50)`
4. If you find a pattern, drill down with `search_logs_by_pattern`

### "Errors started at 10:30am"
1. `get_log_statistics(time_range="15m")` (around 10:30)
2. `get_logs_around_timestamp(timestamp="2024-01-15T10:30:00Z")`
3. `correlate_logs_with_events()` to check for deployments

### "What changed after the deployment?"
1. `correlate_logs_with_events(service="api-gateway")`
2. Compare error patterns before/after deployment timestamp
3. `search_logs_by_pattern(pattern="new_error_pattern")`

## OUTPUT EXPECTATIONS

Provide structured findings with:
- **Log Statistics**: Volume, error rate, top patterns
- **Error Patterns**: Distinct error types and their frequency
- **Timeline**: When issues started, any correlations with events
- **Root Cause Hypothesis**: Based on patterns and correlations
- **Recommendations**: Specific actions to resolve

Never say "I searched all logs" - always describe your sampling strategy and coverage.

## TOOL CALL LIMITS

- Maximum 8 tool calls per investigation
- After 5 calls, you MUST start forming conclusions
- If you've called `get_log_statistics` and `sample_logs`, you have enough for initial findings
"""


# =============================================================================
# Agent Factory
# =============================================================================


def create_log_analysis_agent(
    team_config=None,
    is_subagent: bool = False,
    is_master: bool = False,
) -> Agent[TaskContext]:
    """
    Create Log Analysis Agent with partition-first philosophy.

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
                   Can also be set via team config: agents.log_analysis.is_master: true
    """
    from ..prompts.layers import (
        apply_role_based_prompt,
        build_agent_prompt_sections,
        build_tool_guidance,
    )

    config = get_config()
    team_cfg = team_config if team_config is not None else config.team_config

    # Check for custom prompt override
    custom_prompt = None
    if team_cfg:
        try:
            agent_config = team_cfg.get_agent_config("log_analysis_agent")
            if agent_config and agent_config.prompt:
                custom_prompt = agent_config.prompt
                logger.info(
                    "using_custom_log_analysis_prompt", prompt_length=len(custom_prompt)
                )
        except Exception:
            pass

    base_prompt = custom_prompt or SYSTEM_PROMPT

    # Build final system prompt with role-based sections
    system_prompt = apply_role_based_prompt(
        base_prompt=base_prompt,
        agent_name="log_analysis",
        team_config=team_cfg,
        is_subagent=is_subagent,
        is_master=is_master,
    )

    # Load tools
    tools = _load_log_analysis_tools()
    logger.info("log_analysis_agent_tools_loaded", count=len(tools))

    # Add tool-specific guidance to the system prompt
    tool_guidance = build_tool_guidance(tools)
    if tool_guidance:
        system_prompt = system_prompt + "\n\n" + tool_guidance

    # Add shared sections (error handling, evidence format)
    # Note: Log analysis already has tool limits in SYSTEM_PROMPT
    # Uses predefined LOGS_ERRORS from registry
    shared_sections = build_agent_prompt_sections(
        integration_name="logs",
        is_subagent=is_subagent,
        include_tool_limits=False,  # Already has limits in SYSTEM_PROMPT
    )
    system_prompt = system_prompt + "\n\n" + shared_sections

    # Get model settings from team config if available
    model_name = config.openai.model
    temperature = 0.2  # Lower temp for analytical tasks
    max_tokens = config.openai.max_tokens
    reasoning = None
    verbosity = None

    if team_cfg:
        agent_config = team_cfg.get_agent_config("log_analysis")
        if agent_config.model:
            model_name = agent_config.model.name
            temperature = agent_config.model.temperature
            max_tokens = agent_config.model.max_tokens
            reasoning = getattr(agent_config.model, "reasoning", None)
            verbosity = getattr(agent_config.model, "verbosity", None)
            logger.info(
                "using_team_model_config",
                agent="log_analysis",
                model=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
                reasoning=reasoning,
                verbosity=verbosity,
            )

    return Agent[TaskContext](
        name="LogAnalysisAgent",
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
        output_type=LogAnalysisResult,
    )

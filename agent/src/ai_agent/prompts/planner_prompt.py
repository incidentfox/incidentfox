"""
Planner Agent System Prompt Builder.

This module builds the planner system prompt following the standard agent pattern:

    base_prompt = custom_prompt or PLANNER_SYSTEM_PROMPT
    system_prompt = base_prompt
    system_prompt += build_capabilities_section(...)  # Dynamic capabilities
    system_prompt = apply_role_based_prompt(...)      # Role sections
    system_prompt += build_agent_prompt_sections(...) # Shared sections

Context (runtime metadata, team config) is now passed in the user message,
not the system prompt. This allows context to flow naturally to sub-agents.
"""

from typing import Any

from .agent_capabilities import AGENT_CAPABILITIES, get_enabled_agent_keys
from .layers import (
    apply_role_based_prompt,
    build_agent_prompt_sections,
    build_capabilities_section,
)

# =============================================================================
# Planner System Prompt (Inline)
# =============================================================================
# This merges the static parts of the old 7-layer system:
# - Layer 1: Core Identity
# - Layer 3: Behavioral Foundation
# - Layer 7: Output Format and Rules

PLANNER_SYSTEM_PROMPT = """You are an expert AI SRE (Site Reliability Engineer) responsible for investigating incidents, diagnosing issues, and providing actionable recommendations.

## QUICK REFERENCE

**Core Principles:**
- Never fabricate data - report tool failures honestly
- Find ROOT CAUSE, not just symptoms (keep asking "why?")
- Delegate with context, not commands
- Stop at 12+ tool calls - synthesize findings

**Error Handling:**
- 401/403/permission denied → STOP, use ask_human
- 429/5xx/timeout → Retry ONCE, then stop
- config_required → STOP, report limitation (CLI handles it)

**Output:** Use XML format defined in TRANSPARENCY & AUDITABILITY section

---

## YOUR ROLE

You are the primary orchestrator for incident investigation. Your responsibilities:

1. **Understand the problem** - Analyze the issue, clarify scope, identify affected systems
2. **Investigate systematically** - Delegate to specialized agents, gather evidence, correlate findings
3. **Synthesize insights** - Combine findings from multiple sources into a coherent diagnosis
4. **Provide actionable recommendations** - Give specific, prioritized next steps

You are NOT a simple router. You are an expert who thinks before acting, asks clarifying questions when needed, and provides confident conclusions backed by evidence.

## REASONING FRAMEWORK

For every investigation, follow this mental model:

### Phase 1: UNDERSTAND
- What is the reported problem?
- What systems are likely involved?
- What is the blast radius / business impact?
- What time did this start? (critical for correlation)

### Phase 2: HYPOTHESIZE
- Based on symptoms, what are the top 3 most likely causes?
- What evidence would confirm or rule out each hypothesis?

### Phase 3: INVESTIGATE
- Delegate to appropriate agents to gather evidence
- Start with the most likely hypothesis
- Pivot if evidence points elsewhere

### Phase 4: SYNTHESIZE
- Combine findings from all agents
- Build a timeline of events
- Identify the root cause (or most likely candidates)

### Phase 5: RECOMMEND
- What should be done immediately?
- What should be done to prevent recurrence?
- Who should be notified?

## BEHAVIORAL PRINCIPLES

### Intellectual Honesty

**Never fabricate information.** If a tool fails, report "I couldn't retrieve the logs" - this is infinitely more valuable than fabricating data.

**Acknowledge uncertainty.** Say "I don't know" rather than guessing. Present what you DO know, clearly labeled.

**Distinguish facts from hypotheses:**
- Facts: Directly observed from tool outputs (quote them)
- Hypotheses: Your interpretations (label them)
- Example: "Logs show 'connection refused' (fact). Database may be down (hypothesis)."

### Thoroughness Over Speed

**Find root cause, not just symptoms.** Keep asking "why?":
- ❌ "Pod is crashing" (symptom)
- ❌ "Pods in CrashLoopBackOff" (still symptom)
- ✅ "OOMKilled, memory spikes to 512Mi during peak (256Mi limit)"
- ✅ "Memory leak in cart serialization, introduced in commit abc123"

**When to stop:**
- You've identified a specific, actionable cause
- You've exhausted available diagnostic tools
- Further investigation requires access you don't have (and you've said so)
- The user has asked you to stop

### Human-Centric Communication

**Respect human input.** If they say "I already checked X", don't recheck X. If they correct you, acknowledge and adjust.

**Ask clarifying questions when needed** (but don't over-ask):
- "Which environment are you seeing this in?"
- "When did this start happening?"
- "Has anything changed recently?"

### Evidence & Efficiency

**Show your work.** Quote log lines, include timestamps, explain reasoning.

**Report negative results.** "CloudWatch logs had no relevant entries" is valuable - it tells what's been ruled out.

**Be efficient:**
- Don't call the same tool twice with same parameters
- Prefer targeted queries over broad data dumps
- Respect production systems - prefer read-only operations

## INVESTIGATION RULES

### Delegation Rules
- **Delegate with goals, not commands** - Tell agents WHAT you want to know, not HOW to find it
- **Provide context** - Include symptoms, timing, and any relevant findings from other agents
- **Don't repeat** - Never call the same agent twice for the same question
- **Trust specialists** - Agents are experts in their domain; don't second-guess their approach

### Efficiency Rules
- **Start with the most likely cause** - Don't boil the ocean; investigate hypotheses in order of likelihood
- **Stop when you have enough** - If evidence clearly points to a root cause, conclude
- **Parallelize when independent** - If you need K8s and AWS info and they're unrelated, call both agents

### Quality Rules
- **Evidence over speculation** - Every conclusion must cite specific evidence
- **Confidence calibration** - Be honest about uncertainty; don't overstate confidence
- **Actionable recommendations** - Vague advice ("investigate further") is not helpful

### Safety Rules
- **Check approval requirements** - Some actions require human approval
- **Production awareness** - Be extra cautious with production systems
- **Escalate when appropriate** - If the issue is severe or beyond your capability, recommend escalation

---

Remember: You are an expert SRE. Think systematically, investigate thoroughly, and provide actionable insights.
"""


def build_planner_system_prompt(
    # Capabilities
    enabled_agents: list[str] | None = None,
    agent_capabilities: dict[str, dict[str, Any]] | None = None,
    remote_agents: dict[str, dict[str, Any]] | None = None,
    # Team config (for custom prompt override)
    team_config: dict[str, Any] | None = None,
    # Custom prompt override
    custom_prompt: str | None = None,
) -> str:
    """
    Build the planner system prompt following the standard agent pattern.

    Pattern:
        base_prompt = custom_prompt or PLANNER_SYSTEM_PROMPT
        system_prompt = base_prompt + capabilities
        system_prompt = apply_role_based_prompt(...)  # Add delegation guidance
        system_prompt += shared_sections

    NOTE: Runtime metadata and contextual info are now passed in the user message,
    not the system prompt. Use build_user_context() to build the user message context.

    Args:
        enabled_agents: List of agent keys to include in capabilities
        agent_capabilities: Custom capability descriptors (uses defaults if not provided)
        remote_agents: Dict of remote A2A agent configs
        team_config: Team configuration dict (used for custom prompt override)
        custom_prompt: Custom base prompt to use instead of PLANNER_SYSTEM_PROMPT

    Returns:
        Complete system prompt string
    """
    # Get enabled agents from team config if not provided
    if enabled_agents is None:
        enabled_agents = get_enabled_agent_keys(team_config)

    if agent_capabilities is None:
        agent_capabilities = AGENT_CAPABILITIES

    # 1. Base prompt (can be overridden from config or parameter)
    if custom_prompt:
        base_prompt = custom_prompt
    elif team_config:
        # Check for custom prompt in team config
        # Config structure: agents.planner.prompt.system (string) or agents.planner.prompt (string)
        planner_config = team_config.get("agents", {}).get("planner", {})
        config_prompt = None
        prompt_cfg = planner_config.get("prompt")
        if isinstance(prompt_cfg, str) and prompt_cfg:
            config_prompt = prompt_cfg
        elif isinstance(prompt_cfg, dict):
            config_prompt = prompt_cfg.get("system")
        base_prompt = config_prompt if config_prompt else PLANNER_SYSTEM_PROMPT
    else:
        base_prompt = PLANNER_SYSTEM_PROMPT

    # 2. Capabilities section (dynamic based on enabled agents)
    capabilities = build_capabilities_section(
        enabled_agents=enabled_agents,
        agent_capabilities=agent_capabilities,
        remote_agents=remote_agents,
    )
    system_prompt = base_prompt + "\n\n" + capabilities

    # 3. Role-based sections (planner is always a master, never a subagent)
    system_prompt = apply_role_based_prompt(
        base_prompt=system_prompt,
        agent_name="planner",
        team_config=team_config,
        is_subagent=False,
        is_master=True,
    )

    # 4. Shared sections (error handling, tool limits, evidence format)
    shared_sections = build_agent_prompt_sections(
        integration_name="planner",
        is_subagent=False,
        include_error_handling=True,
        include_tool_limits=True,
        include_evidence_format=True,
    )
    system_prompt = system_prompt + "\n\n" + shared_sections

    return system_prompt


def build_planner_system_prompt_from_team_config(
    team_config: Any,
    remote_agents: dict[str, dict[str, Any]] | None = None,
) -> str:
    """
    Build planner system prompt from a TeamLevelConfig object.

    This is a convenience wrapper that extracts the relevant fields from
    a TeamLevelConfig object and passes them to build_planner_system_prompt.

    NOTE: Runtime metadata and contextual info are now passed in the user message.
    Use build_user_context() to build the user message context.

    Args:
        team_config: TeamLevelConfig object from config service
        remote_agents: Dict of remote A2A agent configs

    Returns:
        Complete system prompt string
    """
    # Convert team config to dict if needed
    config_dict = {}

    if team_config:
        if isinstance(team_config, dict):
            config_dict = team_config
        elif hasattr(team_config, "__dict__"):
            # Extract relevant fields from config object
            config_dict = {}

            # Check for agents config
            if hasattr(team_config, "agents"):
                agents = team_config.agents
                if isinstance(agents, dict):
                    config_dict["agents"] = agents
                elif hasattr(agents, "__dict__"):
                    config_dict["agents"] = {
                        k: v
                        for k, v in agents.__dict__.items()
                        if not k.startswith("_")
                    }

            # Check for planner-specific config
            if hasattr(team_config, "get_agent_config"):
                planner_config = team_config.get_agent_config("planner")
                if planner_config:
                    if "agents" not in config_dict:
                        config_dict["agents"] = {}
                    if hasattr(planner_config, "__dict__"):
                        config_dict["agents"]["planner"] = {
                            k: v
                            for k, v in planner_config.__dict__.items()
                            if not k.startswith("_")
                        }
                    elif isinstance(planner_config, dict):
                        config_dict["agents"]["planner"] = planner_config

    return build_planner_system_prompt(
        remote_agents=remote_agents,
        team_config=config_dict,
    )

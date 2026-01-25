"""Incident writeup and postmortem generation agent."""

from agents import Agent, ModelSettings
from pydantic import BaseModel, Field

from ..core.config import get_config
from ..core.logging import get_logger
from ..tools.agent_tools import ask_human, llm_call, web_search
from ..tools.thinking import think
from .base import TaskContext

logger = get_logger(__name__)


# =============================================================================
# Output Models
# =============================================================================


class ActionItem(BaseModel):
    """An action item from the postmortem."""

    description: str = Field(description="What needs to be done")
    owner: str = Field(default="TBD", description="Who is responsible")
    priority: str = Field(
        default="medium", description="Priority: critical, high, medium, low"
    )
    due_date: str = Field(default="TBD", description="When it should be completed")
    status: str = Field(
        default="open", description="Status: open, in_progress, completed"
    )


class PostmortemDocument(BaseModel):
    """Postmortem document structure."""

    title: str = Field(description="Incident title")
    severity: str = Field(
        default="", description="Incident severity (SEV1, SEV2, etc.)"
    )
    duration: str = Field(default="", description="How long the incident lasted")

    summary: str = Field(description="Executive summary (2-3 sentences)")

    impact: str = Field(description="Impact description - users, business, technical")

    timeline: list[str] = Field(
        default_factory=list,
        description="Timeline of events with timestamps",
    )

    root_cause: str = Field(description="Root cause analysis")
    contributing_factors: list[str] = Field(
        default_factory=list, description="Contributing factors"
    )

    detection: str = Field(default="", description="How was the incident detected?")
    resolution: str = Field(default="", description="How was the incident resolved?")

    action_items: list[ActionItem] = Field(
        default_factory=list, description="Action items with owners"
    )

    lessons_learned: list[str] = Field(
        default_factory=list, description="Lessons learned"
    )

    what_went_well: list[str] = Field(
        default_factory=list, description="What went well during the incident"
    )


# =============================================================================
# System Prompt
# =============================================================================


SYSTEM_PROMPT = """You are an expert technical writer specializing in incident postmortems and documentation.

## YOUR ROLE

You generate clear, actionable incident documentation based on investigation findings. Your postmortems follow industry best practices and help teams learn from incidents.

## BEHAVIORAL PRINCIPLES

### Blameless Culture
- **Focus on systems, not people** - Identify systemic issues, not individual mistakes
- **Assume good intentions** - Everyone was trying to do their best
- **Learn, don't blame** - The goal is improvement, not punishment

### Clarity
- **Write for your audience** - Technical details for engineers, summary for leadership
- **Be specific** - Include timestamps, metrics, and concrete details
- **Be actionable** - Every action item should have a clear owner and deadline

### Thoroughness
- **Complete timeline** - Capture all relevant events
- **Multiple root causes** - Most incidents have contributing factors
- **Systemic fixes** - Focus on preventing recurrence, not just fixing symptoms

## POSTMORTEM STRUCTURE

### 1. Title and Metadata
- Clear, descriptive title (e.g., "Payment Service Outage - Database Connection Pool Exhaustion")
- Severity level (SEV1, SEV2, SEV3)
- Duration (start to full resolution)
- Services affected

### 2. Executive Summary (2-3 sentences)
- What happened?
- What was the impact?
- How was it resolved?

Example: "On January 15, the payment service experienced a 45-minute outage due to database connection pool exhaustion. Approximately 15,000 transactions failed, impacting $2.3M in potential revenue. The issue was resolved by scaling up the connection pool and restarting affected pods."

### 3. Impact
- **User impact**: Number of users affected, duration of impact
- **Business impact**: Revenue, SLAs, customer satisfaction
- **Technical impact**: Data integrity, service degradation, cascading failures

### 4. Timeline
Format: `HH:MM UTC - Event description`

Include:
- Detection time
- Key investigation milestones
- Mitigation steps taken
- Resolution time

### 5. Root Cause Analysis
- **Primary root cause**: The main technical reason
- **Contributing factors**: What made the issue possible or worse
- **Why safeguards failed**: Why existing monitoring/alerting didn't catch it

### 6. Action Items
Each item needs:
- Description (specific and actionable)
- Owner (team or individual)
- Priority (critical, high, medium, low)
- Due date

Categories:
- **Immediate** (already done): What was done to resolve
- **Short-term** (1-2 weeks): Quick improvements
- **Long-term** (this quarter): Systemic changes

### 7. Lessons Learned
- What went well? (Good practices to reinforce)
- What could be improved? (Process gaps)
- Where did we get lucky? (Hidden risks to address)

## WRITING GUIDELINES

- Use **past tense** for events that happened
- Be **precise with times** (always use UTC)
- **Include metrics and data** - "500 errors spiked to 15%" not "errors increased"
- **Link to evidence** - Reference dashboards, logs, or tickets
- Keep action items **SMART**: Specific, Measurable, Achievable, Relevant, Time-bound

## YOUR TOOLS

- `think` - Organize your thoughts and structure the document
- `llm_call` - Get help with phrasing or clarifying technical details
- `web_search` - Look up best practices or industry examples if needed

## WHAT YOU NEED FROM THE CALLER

To write a good postmortem, you need:
1. **Investigation findings** - Root cause, timeline, affected systems
2. **Impact data** - How many users, how long, business metrics
3. **Resolution details** - What fixed it, who was involved

If information is missing, note it clearly: "[NEEDS INPUT: Number of affected users]"

## ANTI-PATTERNS (DON'T DO THESE)

❌ Blame individuals: "John deployed bad code"
✅ Focus on systems: "The deployment process lacked adequate testing gates"

❌ Vague action items: "Improve monitoring"
✅ Specific action items: "Add alert for connection pool utilization >80% - Platform team - High - Jan 30"

❌ Skip lessons learned: Just listing what happened
✅ Extract learnings: "Our runbook was outdated, leading to 10 minutes of confusion"

❌ Ignore contributing factors: Only listing the trigger
✅ Full analysis: "While the deployment triggered the issue, the lack of connection pool limits allowed it to cascade\""""


# =============================================================================
# Agent Factory
# =============================================================================


def create_writeup_agent(
    team_config=None,
    is_subagent: bool = False,
    is_master: bool = False,
) -> Agent[TaskContext]:
    """
    Create incident writeup and postmortem generation agent.

    This agent specializes in generating well-structured incident documentation
    based on investigation findings.

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
                   Can also be set via team config: agents.writeup.is_master: true
    """
    from ..prompts.layers import (
        apply_role_based_prompt,
        build_agent_prompt_sections,
        build_tool_guidance,
    )

    config = get_config()
    team_cfg = team_config if team_config is not None else config.team_config

    # Check if team has custom prompt
    custom_prompt = None
    if team_cfg:
        try:
            agent_config = None
            if hasattr(team_cfg, "get_agent_config"):
                agent_config = team_cfg.get_agent_config("writeup_agent")
                if not agent_config:
                    agent_config = team_cfg.get_agent_config("writeup")
            elif isinstance(team_cfg, dict):
                agents = team_cfg.get("agents", {})
                agent_config = agents.get("writeup_agent") or agents.get("writeup")

            if agent_config:
                if hasattr(agent_config, "get_system_prompt"):
                    custom_prompt = agent_config.get_system_prompt()
                elif hasattr(agent_config, "prompt") and agent_config.prompt:
                    custom_prompt = agent_config.prompt
                elif isinstance(agent_config, dict) and agent_config.get("prompt"):
                    prompt_cfg = agent_config["prompt"]
                    if isinstance(prompt_cfg, str):
                        custom_prompt = prompt_cfg
                    elif isinstance(prompt_cfg, dict):
                        custom_prompt = prompt_cfg.get("system")

                if custom_prompt:
                    logger.info(
                        "using_custom_writeup_prompt", prompt_length=len(custom_prompt)
                    )
        except Exception:
            pass

    base_prompt = custom_prompt or SYSTEM_PROMPT

    # Build final system prompt with role-based sections
    system_prompt = apply_role_based_prompt(
        base_prompt=base_prompt,
        agent_name="writeup",
        team_config=team_cfg,
        is_subagent=is_subagent,
        is_master=is_master,
    )

    # Writeup agent has minimal tools - mostly synthesis
    tools = [think, llm_call, web_search, ask_human]
    logger.info("writeup_agent_tools_loaded", count=len(tools))

    # Add tool-specific guidance to the system prompt
    tool_guidance = build_tool_guidance(tools)
    if tool_guidance:
        system_prompt = system_prompt + "\n\n" + tool_guidance

    # Add shared sections (error handling, tool limits, evidence format)
    shared_sections = build_agent_prompt_sections(
        integration_name="coding",  # Writeup is similar to coding - no specific integration
        is_subagent=is_subagent,
        include_error_handling=True,
        include_tool_limits=True,
        include_evidence_format=False,  # Writeup doesn't need evidence format
    )
    system_prompt = system_prompt + "\n\n" + shared_sections

    # Get model settings from team config if available
    model_name = config.openai.model
    temperature = 0.5  # Slightly higher for creative writing
    max_tokens = config.openai.max_tokens

    if team_cfg:
        try:
            agent_config = None
            if hasattr(team_cfg, "get_agent_config"):
                agent_config = team_cfg.get_agent_config("writeup")
            elif isinstance(team_cfg, dict):
                agents = team_cfg.get("agents", {})
                agent_config = agents.get("writeup")

            if agent_config:
                model_cfg = None
                if hasattr(agent_config, "model"):
                    model_cfg = agent_config.model
                elif isinstance(agent_config, dict):
                    model_cfg = agent_config.get("model")

                if model_cfg:
                    if hasattr(model_cfg, "name"):
                        model_name = model_cfg.name
                        temperature = model_cfg.temperature
                        max_tokens = model_cfg.max_tokens
                    elif isinstance(model_cfg, dict):
                        model_name = model_cfg.get("name", model_name)
                        temperature = model_cfg.get("temperature", temperature)
                        max_tokens = model_cfg.get("max_tokens", max_tokens)
                    logger.info(
                        "using_team_model_config",
                        agent="writeup",
                        model=model_name,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
        except Exception:
            pass

    return Agent[TaskContext](
        name="WriteupAgent",
        instructions=system_prompt,
        model=model_name,
        model_settings=ModelSettings(
            temperature=temperature,
            max_tokens=max_tokens,
        ),
        tools=tools,
        output_type=PostmortemDocument,
    )

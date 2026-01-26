"""AWS resource management and debugging agent."""

from agents import Agent
from pydantic import BaseModel, Field

from ..core.agent_builder import create_model_settings
from ..core.config import get_config
from ..core.logging import get_logger
from ..tools.agent_tools import ask_human, llm_call, web_search
from ..tools.aws_tools import (
    describe_ec2_instance,
    describe_lambda_function,
    get_cloudwatch_logs,
    get_cloudwatch_metrics,
    get_rds_instance_status,
    list_ecs_tasks,
    query_cloudwatch_insights,
)
from ..tools.thinking import think
from .base import TaskContext

logger = get_logger(__name__)


class AWSAnalysis(BaseModel):
    """AWS analysis result."""

    summary: str = Field(description="Summary of findings")
    resource_status: str = Field(description="Current resource status")
    issues_found: list[str] = Field(description="Issues identified")
    recommendations: list[str] = Field(description="Recommended actions")
    estimated_cost_impact: str | None = Field(default=None)


def create_aws_agent(
    team_config=None,
    is_subagent: bool = False,
    is_master: bool = False,
) -> Agent[TaskContext]:
    """
    Create AWS expert agent.

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
                   Can also be set via team config: agents.aws.is_master: true
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
        agent_config = team_cfg.get_agent_config("aws")
        if agent_config.prompt:
            custom_prompt = agent_config.get_system_prompt()
            if custom_prompt:
                logger.info("using_custom_aws_prompt", prompt_length=len(custom_prompt))

    base_prompt = (
        custom_prompt
        or """You are an AWS expert specializing in infrastructure troubleshooting, resource management, and debugging.

## YOUR ROLE

You are a specialized AWS investigator. Your job is to diagnose EC2, Lambda, RDS, ECS, and other AWS service issues, identify root causes, and provide actionable recommendations.

## BEHAVIORAL PRINCIPLES

### Intellectual Honesty
- **Never fabricate information** - Only report data you actually retrieved from AWS
- **Acknowledge uncertainty** - Say "I don't know" when you can't determine something
- **Distinguish facts from hypotheses** - "Lambda returned error code 500 (fact). This suggests a permission issue (hypothesis)."

### Thoroughness
- **Don't stop at symptoms** - "Lambda timed out" is not a root cause; find out WHY
- **Investigate to actionable depth** - Keep digging until you know what to fix

### Evidence Presentation
- **Quote actual output** - Include relevant CloudWatch logs, metrics, or describe output
- **Include timestamps** - When did events occur?
- **Show what you tried** - Even negative results are valuable

## YOUR TOOLS

**Resource Inspection:**
- `describe_ec2_instance` - EC2 instance details, status, metadata
- `describe_lambda_function` - Lambda configuration, runtime, memory, timeout
- `get_rds_instance_status` - RDS instance health, connections, storage
- `list_ecs_tasks` - ECS task status and details

**Logging & Monitoring:**
- `get_cloudwatch_logs` - Retrieve logs from log groups
- `query_cloudwatch_insights` - Query logs with CloudWatch Insights syntax
- `get_cloudwatch_metrics` - Get metric data (CPU, memory, etc.)

## INVESTIGATION METHODOLOGY

### Typical Flow
1. Identify the AWS resource/service involved
2. Check resource status using describe functions
3. Review CloudWatch logs for errors
4. Check CloudWatch metrics for anomalies
5. Analyze configuration for misconfigurations
6. Synthesize and recommend

### Efficiency Rules
- **Status before logs** - Check resource status first; logs may not be needed
- **Don't repeat queries** - If you've retrieved logs, analyze them; don't retrieve again
- **Maximum 6 tool calls** - If you've made 6+ calls, synthesize what you have

## COMMON ISSUES

| Service | Symptom | First Check | Typical Root Cause |
|---------|---------|-------------|-------------------|
| EC2 | Instance unreachable | describe_ec2_instance | Security group, stopped, status check failed |
| EC2 | Performance degradation | CloudWatch metrics | CPU/memory exhaustion, disk I/O, network |
| Lambda | Timeout | CloudWatch logs | External call slow, cold start, memory too low |
| Lambda | Permission denied | CloudWatch logs | IAM role missing permissions |
| Lambda | Memory error | CloudWatch metrics | Memory allocation too low |
| RDS | Connection refused | get_rds_instance_status | Security group, max connections, storage full |
| RDS | Slow queries | CloudWatch metrics | CPU, IOPS, parameter group settings |
| ECS | Task failed | list_ecs_tasks, logs | Container crash, resource limits, image pull failure |

## REGION AWARENESS

- Use the region provided in the query
- If no region specified, ask or assume us-east-1
- Be aware that resources exist in specific regions

## OUTPUT FORMAT

### Summary
Brief overview of what you found.

### Resource Status
Current state of AWS resources with evidence.

### Issues Found
List of identified problems with evidence.

### Root Cause
- What is causing the issue?
- Confidence level (0-100%)

### Recommendations
1. **Immediate**: Actions to take now
2. **Follow-up**: Additional investigation or changes needed
3. **Prevention**: How to prevent this in the future

Be specific in recommendations:
- `aws ec2 describe-instances --instance-ids i-xxx` not just "check the instance"
- IAM policy changes with actual JSON
- Security group rules with specific ports and CIDRs
- CloudWatch alarm configurations"""
    )

    # Build final system prompt with role-based sections
    system_prompt = apply_role_based_prompt(
        base_prompt=base_prompt,
        agent_name="aws",
        team_config=team_cfg,
        is_subagent=is_subagent,
        is_master=is_master,
    )

    tools = [
        think,
        llm_call,
        web_search,
        ask_human,
        # Resource inspection
        describe_ec2_instance,
        describe_lambda_function,
        get_rds_instance_status,
        list_ecs_tasks,
        # Logging and monitoring
        get_cloudwatch_logs,
        query_cloudwatch_insights,
        get_cloudwatch_metrics,
    ]

    logger.info("aws_agent_tools_loaded", count=len(tools))

    # Add tool-specific guidance to the system prompt
    tool_guidance = build_tool_guidance(tools)
    if tool_guidance:
        system_prompt = system_prompt + "\n\n" + tool_guidance

    # Add shared sections (error handling, tool limits, evidence format)
    # Uses predefined AWS_ERRORS from registry
    shared_sections = build_agent_prompt_sections(
        integration_name="aws",
        is_subagent=is_subagent,
    )
    system_prompt = system_prompt + "\n\n" + shared_sections

    # Get model settings from team config if available
    model_name = config.openai.model
    temperature = 0.3
    max_tokens = config.openai.max_tokens
    reasoning = None
    verbosity = None

    if team_cfg:
        agent_config = team_cfg.get_agent_config("aws")
        if agent_config.model:
            model_name = agent_config.model.name
            temperature = agent_config.model.temperature
            max_tokens = agent_config.model.max_tokens
            reasoning = getattr(agent_config.model, "reasoning", None)
            verbosity = getattr(agent_config.model, "verbosity", None)
            logger.info(
                "using_team_model_config",
                agent="aws",
                model=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
                reasoning=reasoning,
                verbosity=verbosity,
            )

    return Agent[TaskContext](
        name="AWSAgent",
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
        output_type=AWSAnalysis,
    )

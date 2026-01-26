"""Metrics Advisor agent for proposing metrics and alerts."""

import os

from agents import Agent, ModelSettings, Tool, function_tool
from pydantic import BaseModel, Field

from ..core.config import get_config
from ..core.logging import get_logger
from ..tools.agent_tools import ask_human, llm_call, web_search
from ..tools.thinking import think
from ..tools.tool_loader import is_integration_available
from .base import TaskContext

logger = get_logger(__name__)


def _load_metrics_advisor_tools():
    """Load all tools needed for metrics advising."""
    # Core meta-tools
    tools = [
        think,
        llm_call,
        web_search,
        ask_human,
    ]

    # Metrics advisor specific tools (always available - pure Python)
    try:
        from ..tools.metrics_advisor_tools import (
            analyze_metrics_gap,
            classify_service_type,
            format_proposal_document,
            generate_datadog_monitors,
            generate_prometheus_rules,
            get_metrics_framework_template,
        )

        tools.extend(
            [
                classify_service_type,
                get_metrics_framework_template,
                analyze_metrics_gap,
                generate_prometheus_rules,
                generate_datadog_monitors,
                format_proposal_document,
            ]
        )
        logger.debug("metrics_advisor_tools_loaded")
    except Exception as e:
        logger.warning("metrics_advisor_tools_load_failed", error=str(e))

    # K8s tools for service discovery (if available)
    if is_integration_available("kubernetes"):
        try:
            from ..tools.kubernetes import (
                describe_deployment,
                describe_pod,
                describe_service,
                list_namespaces,
                list_pods,
            )

            tools.extend(
                [
                    list_namespaces,
                    list_pods,
                    describe_pod,
                    describe_deployment,
                    describe_service,
                ]
            )
            logger.debug("k8s_tools_added_to_metrics_advisor")
        except Exception as e:
            logger.warning("k8s_tools_load_failed", error=str(e))

    # AWS tools for infrastructure discovery (always available - boto3)
    try:
        from ..tools.aws_tools import (
            describe_ec2_instance,
            get_cloudwatch_metrics,
            list_ecs_tasks,
        )

        tools.extend(
            [
                describe_ec2_instance,
                list_ecs_tasks,
                get_cloudwatch_metrics,
            ]
        )
        logger.debug("aws_tools_added_to_metrics_advisor")
    except Exception as e:
        logger.warning("aws_tools_load_failed", error=str(e))

    # Datadog tools for existing metrics analysis (if available)
    if is_integration_available("datadog_api_client"):
        try:
            from ..tools.datadog_tools import (
                query_datadog_metrics,
                search_datadog_logs,
            )

            tools.extend(
                [
                    query_datadog_metrics,
                    search_datadog_logs,
                ]
            )
            logger.debug("datadog_tools_added_to_metrics_advisor")
        except Exception as e:
            logger.warning("datadog_tools_load_failed", error=str(e))

    # Grafana tools for dashboard/alert discovery (if httpx available)
    if is_integration_available("httpx"):
        try:
            from ..tools.grafana_tools import (
                grafana_get_alerts,
                grafana_get_dashboard,
                grafana_list_dashboards,
            )

            tools.extend(
                [
                    grafana_list_dashboards,
                    grafana_get_dashboard,
                    grafana_get_alerts,
                ]
            )
            logger.debug("grafana_tools_added_to_metrics_advisor")
        except Exception as e:
            logger.warning("grafana_tools_load_failed", error=str(e))

    # Knowledge base tools for RAG (if enabled)
    if is_integration_available("httpx") and os.getenv("RAPTOR_ENABLED"):
        try:
            from ..tools.knowledge_base_tools import (
                ask_knowledge_base,
                search_knowledge_base,
            )

            tools.extend(
                [
                    search_knowledge_base,
                    ask_knowledge_base,
                ]
            )
            logger.debug("knowledge_base_tools_added_to_metrics_advisor")
        except Exception as e:
            logger.warning("knowledge_base_tools_load_failed", error=str(e))

    # Wrap plain functions into Tool objects for SDK compatibility
    wrapped = []
    for t in tools:
        if isinstance(t, Tool) or hasattr(t, "name"):
            wrapped.append(t)
        else:
            try:
                wrapped.append(function_tool(t, strict_mode=False))
            except TypeError:
                # Older SDK version without strict_mode
                wrapped.append(function_tool(t))
            except Exception as e:
                logger.warning(
                    "tool_wrap_failed",
                    tool=getattr(t, "__name__", str(t)),
                    error=str(e),
                )
                wrapped.append(t)
    return wrapped


class MetricRecommendation(BaseModel):
    """A recommended metric to add."""

    name: str = Field(description="Metric name")
    type: str = Field(description="Metric type (counter, gauge, histogram)")
    description: str = Field(description="What this metric measures")
    priority: str = Field(description="Priority level (high, medium, low)")


class AlertRecommendation(BaseModel):
    """A recommended alert rule."""

    name: str = Field(description="Alert name")
    severity: str = Field(description="Severity (critical, warning, info)")
    description: str = Field(description="What this alert detects")


class MetricsProposal(BaseModel):
    """Complete metrics and alerts proposal."""

    service_name: str = Field(description="Service being analyzed")
    service_type: str = Field(description="Classified service type")
    framework: str = Field(description="Recommended framework (RED, USE, etc.)")
    coverage_score: float = Field(default=0, description="Current coverage percentage")
    missing_metrics: list[MetricRecommendation] = Field(
        default_factory=list, description="Metrics to add"
    )
    alert_recommendations: list[AlertRecommendation] = Field(
        default_factory=list, description="Alerts to create"
    )
    proposal_document: str = Field(default="", description="Full proposal in requested format")


METRICS_ADVISOR_PROMPT = """You are a Metrics & Observability Advisor - an expert in SRE best practices for
monitoring, alerting, and SLI/SLO design. Your job is to help teams set up
proper observability for their services.

## YOUR ROLE

You help teams that have systems but lack proper metrics and alerts. You:
1. Discover and understand their services
2. Classify service types to apply the right framework
3. Analyze existing metrics to find gaps
4. Propose metrics and alerts based on industry best practices
5. Output code (YAML/JSON) or documentation based on what users need

## CAPABILITIES

1. **Service Discovery**: Autonomously navigate K8s and AWS to find services
2. **Classification**: Identify service types (HTTP API, worker, database, cache, etc.)
3. **Gap Analysis**: Compare existing metrics against best practices
4. **Proposal Generation**: Output metrics/alerts as code OR documentation

## APPROACH

Follow this systematic workflow:

### 1. DISCOVER
Use K8s/AWS tools to understand the service landscape:
- `list_namespaces` and `list_pods` to find services
- `describe_pod` and `describe_deployment` to get service details
- `list_ecs_tasks` for AWS ECS services

### 2. CLASSIFY
Use `classify_service_type` with the discovered metadata:
- Pass pod_spec, deployment_spec from describe outputs
- The tool analyzes ports, images, labels to determine type
- Returns service_type and recommended_framework

### 3. ANALYZE
Query existing metrics to find gaps:
- Use `query_datadog_metrics` or Grafana tools to see what exists
- Use `analyze_metrics_gap` to compare against recommendations
- Use `grafana_list_dashboards` to see existing dashboards

### 4. CONSULT
Query knowledge base for team-specific patterns:
- Use `search_knowledge_base` or `ask_knowledge_base` if available
- Look for team standards, existing runbooks, naming conventions

### 5. PROPOSE
Generate recommendations based on frameworks:
- Use `get_metrics_framework_template` for metric recommendations
- Use `generate_prometheus_rules` for Prometheus alert YAML
- Use `generate_datadog_monitors` for Datadog monitor JSON
- Use `format_proposal_document` for complete documentation

## METRICS FRAMEWORKS

Apply the appropriate framework based on service type:

### HTTP APIs (RED Method)
- **R**ate: Request throughput (`http_requests_total`)
- **E**rrors: Error rate by status code (`http_requests_total{status=~"5.."}`)
- **D**uration: Latency percentiles P50, P95, P99 (`http_request_duration_seconds`)

### Infrastructure/Databases (USE Method)
- **U**tilization: Resource usage percentage (connections, CPU, memory)
- **S**aturation: Queue depths, pending work
- **E**rrors: Failed operations, deadlocks, timeouts

### All Services (Golden Signals)
- **Latency**: How long requests take
- **Traffic**: How much demand is on the system
- **Errors**: Rate of failed requests
- **Saturation**: How "full" the system is

## SERVICE TIER TARGETS

| Tier | Availability | P99 Latency | Error Rate |
|------|-------------|-------------|------------|
| Critical | 99.9% | 500ms | 0.1% |
| Standard | 99.5% | 1s | 0.5% |
| Best Effort | 99% | 2s | 1% |

## OUTPUT FORMATS

Respond based on what the user asks for:

### If user wants CODE:
- **Prometheus**: Output valid PrometheusRule YAML using `generate_prometheus_rules`
- **Datadog**: Output monitor definitions as JSON using `generate_datadog_monitors`
- Include comments explaining each rule

### If user wants DOCUMENTATION:
- Use `format_proposal_document` for structured markdown
- Include classification rationale
- Include gap analysis
- Include implementation notes

### If user doesn't specify:
- Ask them: "Would you like the output as deployable code (Prometheus YAML or Datadog JSON) or as a proposal document?"

## ALERT DESIGN PRINCIPLES

1. **Alert on symptoms, not causes** - Alert on "high error rate", not "database slow"
2. **Use multi-window burn rates** - 5m for fast burn, 1h for slow burn
3. **Set realistic thresholds** - Based on baselines, not arbitrary numbers
4. **Include runbook links** - Every alert should have documentation
5. **Severity levels**:
   - `critical`: Page immediately (production down)
   - `warning`: Create ticket (degraded but functional)
   - `info`: Dashboard only (FYI)

## EXAMPLE WORKFLOW

**User: "Set up monitoring for the payment-api service in production namespace"**

1. Discover:
   ```
   describe_pod(pod_name="payment-api-xxx", namespace="production")
   describe_deployment(deployment_name="payment-api", namespace="production")
   ```

2. Classify:
   ```
   classify_service_type(
       service_name="payment-api",
       namespace="production",
       pod_spec=<pod JSON>,
       deployment_spec=<deployment JSON>
   )
   → Returns: service_type="http_api", framework="RED"
   ```

3. Check existing metrics:
   ```
   query_datadog_metrics(query='avg:http.server.request.count{service:payment-api}')
   ```

4. Analyze gaps:
   ```
   analyze_metrics_gap(
       service_name="payment-api",
       existing_metrics='["http_requests_total"]',
       service_type="http_api"
   )
   → Returns coverage_score, missing metrics
   ```

5. Generate rules:
   ```
   generate_prometheus_rules(
       service_name="payment-api",
       namespace="production",
       service_type="http_api"
   )
   ```

6. Format output:
   ```
   format_proposal_document(
       service_name="payment-api",
       classification_result=<classification JSON>,
       gap_analysis_result=<gap JSON>,
       generated_rules=<YAML>
   )
   ```

## KEY POINTS

- **Be thorough**: Discover all relevant services before proposing
- **Be specific**: Include actual metric names, thresholds, durations
- **Be practical**: Consider the team's existing stack (Prometheus vs Datadog)
- **Be educational**: Explain WHY certain metrics matter
- **Ask clarifying questions**: Service tier? Notification channels? Custom thresholds?"""


def create_metrics_advisor_agent(
    team_config=None,
    is_subagent: bool = False,
    is_master: bool = False,
) -> Agent[TaskContext]:
    """
    Create Metrics Advisor agent for proposing metrics and alerts.

    This agent helps teams set up proper observability by:
    - Discovering services via K8s/AWS navigation
    - Classifying service types (HTTP API, worker, database, etc.)
    - Analyzing existing metrics coverage gaps
    - Proposing metrics and alert rules based on SRE best practices
    - Outputting as code (Prometheus YAML, Datadog JSON) or documentation

    Args:
        team_config: Team configuration for customization
        is_subagent: If True, agent is being called by another agent.
                     This adds guidance for concise, caller-focused responses.
        is_master: If True, agent can delegate to other agents.
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
        agent_config = team_cfg.get_agent_config("metrics_advisor_agent")
        if agent_config.prompt:
            custom_prompt = agent_config.get_system_prompt()
            if custom_prompt:
                logger.info(
                    "using_custom_metrics_advisor_prompt",
                    prompt_length=len(custom_prompt),
                )

    base_prompt = custom_prompt or METRICS_ADVISOR_PROMPT

    # Build final system prompt with role-based sections
    system_prompt = apply_role_based_prompt(
        base_prompt=base_prompt,
        agent_name="metrics_advisor",
        team_config=team_cfg,
        is_subagent=is_subagent,
        is_master=is_master,
    )

    # Load all available tools
    tools = _load_metrics_advisor_tools()
    logger.info("metrics_advisor_agent_tools_loaded", count=len(tools))

    # Add tool-specific guidance to the system prompt
    tool_guidance = build_tool_guidance(tools)
    if tool_guidance:
        system_prompt = system_prompt + "\n\n" + tool_guidance

    # Add shared sections (error handling, tool limits, evidence format)
    shared_sections = build_agent_prompt_sections(
        integration_name="metrics_advisor",
        is_subagent=is_subagent,
    )
    system_prompt = system_prompt + "\n\n" + shared_sections

    # Get model settings from team config if available
    model_name = config.openai.model
    temperature = 0.3  # Balanced for analytical + creative output
    max_tokens = config.openai.max_tokens

    if team_cfg:
        agent_config = team_cfg.get_agent_config("metrics_advisor_agent")
        if agent_config.model:
            model_name = agent_config.model.name
            temperature = agent_config.model.temperature
            max_tokens = agent_config.model.max_tokens
            logger.info(
                "using_team_model_config",
                agent="metrics_advisor",
                model=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
            )

    return Agent[TaskContext](
        name="MetricsAdvisorAgent",
        instructions=system_prompt,
        model=model_name,
        model_settings=ModelSettings(
            temperature=temperature,
            max_tokens=max_tokens,
        ),
        tools=tools,
        output_type=MetricsProposal,
    )

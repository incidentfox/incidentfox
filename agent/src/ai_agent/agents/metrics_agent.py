"""Metrics analysis and anomaly detection agent."""

from agents import Agent, Tool, function_tool
from pydantic import BaseModel, Field

from ..core.agent_builder import create_model_settings
from ..core.config import get_config
from ..core.logging import get_logger
from ..prompts.default_prompts import get_default_agent_prompt
from ..tools.agent_tools import ask_human, llm_call, web_search
from ..tools.aws_tools import get_cloudwatch_metrics, query_cloudwatch_insights
from ..tools.thinking import think
from ..tools.tool_loader import is_integration_available
from .base import TaskContext

logger = get_logger(__name__)


def _load_metrics_tools():
    """Load all available metrics and observability tools."""
    # Core tools
    tools = [
        think,
        llm_call,
        web_search,
        ask_human,
        # CloudWatch (always available)
        get_cloudwatch_metrics,
        query_cloudwatch_insights,
    ]

    # Anomaly detection tools (always available - pure Python)
    try:
        from ..tools.anomaly_tools import (
            analyze_metric_distribution,
            correlate_metrics,
            detect_anomalies,
            find_change_point,
            forecast_metric,
        )

        tools.extend(
            [
                detect_anomalies,
                correlate_metrics,
                find_change_point,
                forecast_metric,
                analyze_metric_distribution,
            ]
        )
        logger.debug("anomaly_tools_added_to_metrics_agent")
    except Exception as e:
        logger.warning("anomaly_tools_load_failed", error=str(e))

    # Prophet-based tools (if prophet installed)
    if is_integration_available("prophet"):
        try:
            from ..tools.anomaly_tools import (
                prophet_decompose,
                prophet_detect_anomalies,
                prophet_forecast,
            )

            tools.extend(
                [
                    prophet_detect_anomalies,
                    prophet_forecast,
                    prophet_decompose,
                ]
            )
            logger.debug("prophet_tools_added_to_metrics_agent")
        except Exception as e:
            logger.warning("prophet_tools_load_failed", error=str(e))

    # Grafana tools (if httpx available)
    if is_integration_available("httpx"):
        try:
            from ..tools.grafana_tools import (
                grafana_get_alerts,
                grafana_get_annotations,
                grafana_get_dashboard,
                grafana_list_dashboards,
                grafana_list_datasources,
                grafana_query_prometheus,
            )

            tools.extend(
                [
                    grafana_list_dashboards,
                    grafana_get_dashboard,
                    grafana_query_prometheus,
                    grafana_list_datasources,
                    grafana_get_annotations,
                    grafana_get_alerts,
                ]
            )
            logger.debug("grafana_tools_added_to_metrics_agent")
        except Exception as e:
            logger.warning("grafana_tools_load_failed", error=str(e))

    # Datadog tools (if available)
    if is_integration_available("datadog_api_client"):
        try:
            from ..tools.datadog_tools import (
                get_service_apm_metrics,
                query_datadog_metrics,
                search_datadog_logs,
            )

            tools.extend(
                [
                    query_datadog_metrics,
                    search_datadog_logs,
                    get_service_apm_metrics,
                ]
            )
            logger.debug("datadog_tools_added_to_metrics_agent")
        except Exception as e:
            logger.warning("datadog_tools_load_failed", error=str(e))

    # NewRelic tools (if available)
    if is_integration_available("httpx"):
        try:
            from ..tools.newrelic_tools import (
                get_apm_summary,
                query_newrelic_nrql,
            )

            tools.extend(
                [
                    query_newrelic_nrql,
                    get_apm_summary,
                ]
            )
            logger.debug("newrelic_tools_added_to_metrics_agent")
        except Exception as e:
            logger.warning("newrelic_tools_load_failed", error=str(e))

    # K8s resource metrics (if available)
    if is_integration_available("kubernetes"):
        try:
            from ..tools.kubernetes import get_pod_resource_usage

            tools.append(get_pod_resource_usage)
            logger.debug("k8s_resource_tool_added_to_metrics_agent")
        except Exception as e:
            logger.warning("k8s_resource_tool_load_failed", error=str(e))

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


class Anomaly(BaseModel):
    """An anomaly detected in metrics."""

    metric_name: str
    timestamp: str
    value: float
    expected_range: str
    severity: str  # low, medium, high, critical


class MetricsAnalysis(BaseModel):
    """Metrics analysis result."""

    summary: str = Field(description="Summary of metric analysis")
    anomalies_found: list[Anomaly] = Field(description="Anomalies detected")
    baseline_established: bool = Field(description="Whether baseline was established")
    recommendations: list[str] = Field(description="Recommendations based on analysis")
    requires_immediate_action: bool = Field(default=False)


def create_metrics_agent(
    team_config=None,
    is_subagent: bool = False,
    is_master: bool = False,
) -> Agent[TaskContext]:
    """
    Create metrics analysis expert agent.

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
                   Can also be set via team config: agents.metrics.is_master: true
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
        agent_config = team_cfg.get_agent_config("metrics")
        if agent_config.prompt:
            custom_prompt = agent_config.get_system_prompt()
            if custom_prompt:
                logger.info(
                    "using_custom_metrics_prompt", prompt_length=len(custom_prompt)
                )

    # Get base prompt from 01_slack template (single source of truth)
    base_prompt = custom_prompt or get_default_agent_prompt("metrics")

    # Build final system prompt with role-based sections
    system_prompt = apply_role_based_prompt(
        base_prompt=base_prompt,
        agent_name="metrics",
        team_config=team_cfg,
        is_subagent=is_subagent,
        is_master=is_master,
    )

    # Load all available metrics tools
    tools = _load_metrics_tools()
    logger.info("metrics_agent_tools_loaded", count=len(tools))

    # Add tool-specific guidance to the system prompt
    tool_guidance = build_tool_guidance(tools)
    if tool_guidance:
        system_prompt = system_prompt + "\n\n" + tool_guidance

    # Add shared sections (error handling, tool limits, evidence format)
    # Uses predefined METRICS_ERRORS from registry
    shared_sections = build_agent_prompt_sections(
        integration_name="metrics",
        is_subagent=is_subagent,
    )
    system_prompt = system_prompt + "\n\n" + shared_sections

    # Get model settings from team config if available
    model_name = config.openai.model
    temperature = 0.2  # Lower temp for analytical tasks
    max_tokens = config.openai.max_tokens
    reasoning = None
    verbosity = None

    if team_cfg:
        agent_config = team_cfg.get_agent_config("metrics")
        if agent_config.model:
            model_name = agent_config.model.name
            temperature = agent_config.model.temperature
            max_tokens = agent_config.model.max_tokens
            reasoning = getattr(agent_config.model, "reasoning", None)
            verbosity = getattr(agent_config.model, "verbosity", None)
            logger.info(
                "using_team_model_config",
                agent="metrics",
                model=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
                reasoning=reasoning,
                verbosity=verbosity,
            )

    return Agent[TaskContext](
        name="MetricsAgent",
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
        # Removed output_type=MetricsAnalysis to allow flexible XML-based output format
        # defined in system prompt. This enables hot-reloadable output schema via config.
    )

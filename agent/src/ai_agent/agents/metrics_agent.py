"""Metrics analysis and anomaly detection agent."""

from agents import Agent, ModelSettings, Tool, function_tool
from pydantic import BaseModel, Field

from ..core.config import get_config
from ..core.logging import get_logger
from ..tools.agent_tools import llm_call, web_search
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
    from ..prompts.layers import apply_role_based_prompt

    config = get_config()
    team_cfg = team_config if team_config is not None else config.team_config

    # Check if team has custom prompt
    custom_prompt = None
    if team_cfg:
        agent_config = team_cfg.get_agent_config("metrics_agent")
        if agent_config.prompt:
            custom_prompt = agent_config.get_system_prompt()
            if custom_prompt:
                logger.info(
                    "using_custom_metrics_prompt", prompt_length=len(custom_prompt)
                )

    base_prompt = (
        custom_prompt
        or """You are a metrics analysis expert specializing in anomaly detection, root cause correlation, and performance analysis.

## YOUR ROLE

You are a specialized metrics investigator. Your job is to analyze time-series data, detect anomalies, find correlations, and help identify root causes of performance issues.

## BEHAVIORAL PRINCIPLES

### Intellectual Honesty
- **Never fabricate data** - Only report metrics you actually retrieved
- **Acknowledge uncertainty** - Statistical methods have confidence intervals; communicate them
- **Distinguish facts from hypotheses** - "Error rate spiked at 10:30 (fact). This correlates with the deployment (observation). The deployment likely caused the spike (hypothesis)."

### Thoroughness
- **Don't stop at anomalies** - Finding a spike is not root cause; find WHY
- **Correlate across metrics** - Look for related metrics that explain the issue
- **Check for seasonality** - Is this actually unusual, or just a daily pattern?

### Evidence Presentation
- **Quote actual values** - Include specific numbers, timestamps, and ranges
- **Show correlations** - Include correlation coefficients and confidence
- **Visualize when helpful** - Describe patterns clearly

## YOUR TOOLS

### Statistical Anomaly Detection (Fast, Always Available)
- `detect_anomalies` - Find spikes/drops using Z-score (takes JSON array)
- `correlate_metrics` - Check if two metrics are related (root cause discovery)
- `find_change_point` - Identify when behavior changed (deployment impact)
- `forecast_metric` - Simple linear forecast (quick capacity check)
- `analyze_metric_distribution` - Understand percentiles and SLOs

### Prophet-based Analysis (Best for Seasonality)
- `prophet_detect_anomalies` - **PREFERRED** for metrics with daily/weekly patterns
  - Accounts for time-of-day and day-of-week seasonality
  - Returns anomalies with expected values and confidence bounds
- `prophet_forecast` - **PREFERRED** for accurate capacity planning
  - Seasonality-aware forecasting with uncertainty bounds
  - Better than linear for metrics with patterns
- `prophet_decompose` - Separate trend vs seasonality vs noise
  - Reveals if issues are trend-based or seasonal
  - Shows how predictable the metric is

### Grafana (Primary Dashboard Source)
- `grafana_list_dashboards` - Find relevant dashboards
- `grafana_get_dashboard` - Get panel queries from a dashboard
- `grafana_query_prometheus` - Query Prometheus metrics directly
- `grafana_list_datasources` - See what data sources are available
- `grafana_get_annotations` - Get deployment/incident markers
- `grafana_get_alerts` - Check which alerts are firing

### AWS CloudWatch
- `get_cloudwatch_metrics` - Query CloudWatch metrics
- `query_cloudwatch_insights` - Run log insights queries

### Datadog (if configured)
- `query_datadog_metrics` - Query Datadog metrics
- `search_datadog_logs` - Search Datadog logs
- `get_service_apm_metrics` - Get APM performance data

### New Relic (if configured)
- `query_newrelic_nrql` - Run NRQL queries
- `get_apm_summary` - Get APM summary

### Kubernetes
- `get_pod_resource_usage` - Get pod CPU/memory metrics

### Reasoning
- `think` - Internal analysis and reasoning
- `llm_call` - Get additional AI perspective
- `web_search` - Search for metric interpretation help

## ROOT CAUSE CORRELATION WORKFLOW

### Step 1: Get the Data
```
1. Use grafana_query_prometheus or get_cloudwatch_metrics to fetch metrics
2. Get multiple related metrics (latency, errors, CPU, memory)
```

### Step 2: Detect Anomalies
```
detect_anomalies(values="[1.2, 1.3, 5.8, 1.1]", metric_name="latency_p99")
→ Finds spikes at specific points
```

### Step 3: Find Correlations
```
correlate_metrics(
    metric_a_values="[cpu values]",
    metric_b_values="[latency values]",
    metric_a_name="cpu",
    metric_b_name="latency"
)
→ Tells you if CPU and latency move together (root cause hint!)
```

### Step 4: Check for Change Points
```
find_change_point(values="[metric values]", metric_name="error_rate")
→ Identifies when the metric behavior changed (deployment correlation)
```

### Step 5: Correlate with Events
```
grafana_get_annotations(time_range="24h", tags="deployment")
→ Find deployments that coincide with the change point
```

## EXAMPLE INVESTIGATION

**User asks: "Why is latency high?"**

### Option A: With Prophet (Recommended for Production)
1. `grafana_query_prometheus(query="histogram_quantile(0.99, rate(http_duration_seconds_bucket[5m]))", time_range="6h")`
2. `prophet_detect_anomalies(values=[values], timestamps=[timestamps], metric_name="p99_latency")`
   - Prophet accounts for daily patterns (e.g., traffic peaks at noon)
   - Returns: anomalies that are ACTUALLY unusual, not just "higher than average"
3. `prophet_decompose(values=[...], timestamps=[...])`
   - Shows: Is this trend-based or just seasonal noise?
4. `correlate_metrics(cpu_values, latency_values)`
5. `grafana_get_annotations(tags="deployment")` - check for recent deploys

### Option B: Statistical (Fast, No Dependencies)
1. `grafana_query_prometheus(query="...", time_range="2h")`
2. `detect_anomalies(values=[results], metric_name="p99_latency")`
3. If anomalies found, get related metrics (CPU, errors)
4. `correlate_metrics(cpu_values, latency_values)`
5. If correlated: "High latency correlates with CPU (r=0.87). Root cause: CPU saturation."
6. `grafana_get_annotations(tags="deployment")` to check if recent deploy caused it

## KEY INSIGHTS TO PROVIDE

1. **Anomalies**: When did they occur? How severe?
2. **Correlations**: Which metrics move together? (This identifies root cause!)
3. **Change Points**: When did behavior change? What happened then?
4. **Forecasts**: Will this get worse? When will limits be hit?
5. **Recommendations**: Specific actions to fix or prevent

## CORRELATION INTERPRETATION

| Correlation | Meaning |
|-------------|---------|
| r > 0.7 | Strong positive - metrics move together |
| r < -0.7 | Strong negative - inverse relationship |
| r ≈ 0 | No relationship - look elsewhere |

When you find strong correlation, you've likely found the root cause path!"""
    )

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

    # Get model settings from team config if available
    model_name = config.openai.model
    temperature = 0.2  # Lower temp for analytical tasks
    max_tokens = config.openai.max_tokens

    if team_cfg:
        agent_config = team_cfg.get_agent_config("metrics")
        if agent_config.model:
            model_name = agent_config.model.name
            temperature = agent_config.model.temperature
            max_tokens = agent_config.model.max_tokens
            logger.info(
                "using_team_model_config",
                agent="metrics",
                model=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
            )

    return Agent[TaskContext](
        name="MetricsAgent",
        instructions=system_prompt,
        model=model_name,
        model_settings=ModelSettings(
            temperature=temperature,
            max_tokens=max_tokens,
        ),
        tools=tools,
        output_type=MetricsAnalysis,
    )

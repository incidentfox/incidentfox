"""
Agent capability descriptors for dynamic prompt construction.

Each capability descriptor contains:
- name: Human-readable agent name
- tool_name: The function name to call this agent
- description: Brief description of what the agent does
- use_when: List of scenarios when this agent should be used
- do_not_use_when: List of scenarios when this agent should NOT be used
- delegation_examples: Example natural language queries to delegate to this agent
"""

from typing import Any

# =============================================================================
# Built-in Agent Capabilities
# =============================================================================

AGENT_CAPABILITIES: dict[str, dict[str, Any]] = {
    # =========================================================================
    # TOP-LEVEL AGENTS (available directly from Planner)
    # =========================================================================
    "investigation": {
        "name": "Investigation Agent",
        "tool_name": "call_investigation_agent",
        "description": "Sub-orchestrator for incident investigation. Coordinates specialized agents (GitHub, K8s, AWS, Metrics, Log Analysis) to perform comprehensive, end-to-end investigation across multiple systems.",
        "use_when": [
            "The issue spans multiple systems (K8s + AWS + databases + external services)",
            "Root cause is unclear and you need broad, autonomous investigation",
            "You want comprehensive end-to-end analysis without coordinating multiple agents",
            "Complex incidents requiring correlation across infrastructure, logs, and metrics",
            "You need to check GitHub for recent changes that might have caused the issue",
        ],
        "do_not_use_when": [
            "You just need to write code fixes (use coding agent)",
            "You just need to write a postmortem (use writeup agent)",
            "A quick, targeted check is sufficient",
        ],
        "delegation_examples": [
            '"Investigate the elevated error rate in checkout service. Check pods, dependencies, recent deployments, and any correlated events. Build a timeline and identify root cause."',
            '"Full investigation of database connection timeouts. Check application logs, DB metrics, network connectivity, and any recent changes."',
            '"Something is broken in production but we don\'t know what. Investigate all systems and find the root cause."',
        ],
        "subagents": ["github", "k8s", "aws", "metrics", "log_analysis"],
    },
    "coding": {
        "name": "Coding Agent",
        "tool_name": "call_coding_agent",
        "description": "Code analysis specialist for debugging, reviewing, and suggesting fixes. Can analyze application code to understand behavior and identify bugs.",
        "use_when": [
            "You need to analyze application code to understand runtime behavior",
            "Error messages or stack traces point to specific code paths",
            "You need to suggest code fixes or patches for identified issues",
            "Configuration file analysis (YAML, JSON, environment variables)",
            "Understanding how a feature or component works in the codebase",
            "Reviewing recent code changes that might have caused issues",
        ],
        "do_not_use_when": [
            "The issue is infrastructure, not code (use investigation agent)",
            "You need runtime metrics or logs (use investigation agent)",
            "The issue is clearly in deployed infrastructure configuration",
        ],
        "delegation_examples": [
            '"Analyze the checkout handler code for potential null pointer exceptions based on this stack trace: [trace]"',
            '"Review the database connection pool configuration for issues that could cause connection exhaustion."',
            '"Look at the recent changes to payment-service and identify any that might cause the errors we\'re seeing."',
            '"Analyze the retry logic in the API client to understand why requests might be timing out."',
        ],
    },
    "writeup": {
        "name": "Writeup Agent",
        "tool_name": "call_writeup_agent",
        "description": "Incident documentation specialist for generating postmortems, incident reports, and technical documentation. Follows blameless postmortem best practices.",
        "use_when": [
            "User explicitly asks for a postmortem or incident report",
            "Investigation is complete and findings need to be documented",
            "You need to generate action items and lessons learned",
            "Creating a blameless incident writeup for stakeholders",
        ],
        "do_not_use_when": [
            "Investigation is still ongoing (complete investigation first)",
            "You need to find the root cause (use investigation agent first)",
            "You need to fix code (use coding agent)",
        ],
        "delegation_examples": [
            '"Generate a postmortem for the payment service outage based on these investigation findings: [findings]"',
            '"Write up an incident report for the database connection exhaustion issue. Include timeline, root cause, and action items."',
            '"Create a blameless postmortem document with lessons learned and preventive actions."',
        ],
    },
    # =========================================================================
    # SUB-AGENTS (available via Investigation Agent)
    # =========================================================================
    "github": {
        "name": "GitHub Agent",
        "tool_name": "call_github_agent",
        "description": "GitHub repository specialist for investigating recent changes, PRs, issues, and code context. Expert in correlating code changes with incidents.",
        "use_when": [
            "You need to find recent commits or PRs that might have caused an issue",
            "Investigating what changed in the codebase recently",
            "Looking for related GitHub issues or known problems",
            "Need to read specific files from a GitHub repository",
            "Searching for code patterns across repositories",
        ],
        "do_not_use_when": [
            "You need to analyze local code files (use coding agent)",
            "You need runtime infrastructure data (use k8s/aws agents)",
            "The issue is unrelated to code changes",
        ],
        "delegation_examples": [
            '"Check recent commits and PRs to payment-service that might have caused the errors."',
            '"Find any GitHub issues related to database connection problems."',
            '"Search the codebase for error handling patterns in the checkout flow."',
        ],
        "parent_agent": "investigation",
    },
    "k8s": {
        "name": "Kubernetes Agent",
        "tool_name": "call_k8s_agent",
        "description": "Kubernetes specialist for pod, deployment, service, and cluster diagnostics. Expert in troubleshooting container orchestration issues.",
        "use_when": [
            "Pods are crashing, restarting, or in bad state (CrashLoopBackOff, OOMKilled, Pending, ImagePullBackOff)",
            "Deployment issues (rollout stuck, replicas not scaling, failed updates)",
            "Resource problems (CPU/memory pressure, evictions, resource quota exceeded)",
            "Service connectivity issues within the cluster (DNS, service discovery, endpoints)",
            "Node issues affecting pod scheduling or performance",
            "ConfigMap/Secret issues affecting application configuration",
        ],
        "do_not_use_when": [
            "The issue is clearly in application code logic (use coding agent)",
            "The issue is in AWS infrastructure outside K8s (use AWS agent)",
            "You need historical metrics analysis over time (use metrics agent)",
            "You need detailed log pattern analysis (use log analysis agent)",
        ],
        "delegation_examples": [
            '"Investigate pod health in the checkout namespace. Check for crashes, OOMKills, pending pods, resource pressure, and any recent events."',
            '"Analyze the deployment rollout status for payment-service. Check if replicas are healthy, any failed pods, and what the logs show."',
            '"Check why pods are stuck in Pending state in the api-gateway namespace. Look at events, node capacity, and resource requests."',
            '"Investigate service connectivity issues between frontend and backend services. Check endpoints, DNS, and network policies."',
        ],
        "parent_agent": "investigation",
    },
    "aws": {
        "name": "AWS Agent",
        "tool_name": "call_aws_agent",
        "description": "AWS infrastructure specialist for EC2, RDS, Lambda, ECS, and CloudWatch. Expert in AWS service diagnostics and troubleshooting.",
        "use_when": [
            "EC2 instance issues (status checks failed, connectivity problems, performance)",
            "RDS database problems (connections exhausted, high CPU, storage full, replication lag)",
            "Lambda function errors, timeouts, or cold start issues",
            "CloudWatch alarms triggered or metrics investigation needed",
            "ECS task failures or service instability",
            "Load balancer health check failures or target group issues",
            "S3 access issues or IAM permission problems",
        ],
        "do_not_use_when": [
            "The issue is in Kubernetes (use K8s agent)",
            "You need code-level analysis (use coding agent)",
            "The issue is application logic, not AWS infrastructure",
        ],
        "delegation_examples": [
            '"Check RDS database health for prod-mysql. Look at connection count, CPU, storage, and any recent alarms."',
            '"Investigate Lambda function checkout-processor for errors and timeouts in the last hour."',
            '"Check EC2 instance i-1234567890abcdef0 status and why it might be unreachable."',
            '"Analyze ECS service payment-worker for task failures and check CloudWatch logs."',
        ],
        "parent_agent": "investigation",
    },
    "metrics": {
        "name": "Metrics Agent",
        "tool_name": "call_metrics_agent",
        "description": "Performance analyst specializing in anomaly detection, trend analysis, and metric correlation. Uses statistical methods and Prophet for time-series analysis.",
        "use_when": [
            "You need to detect anomalies in time-series data (sudden spikes, drops, pattern changes)",
            "You want to correlate metrics across multiple services to find relationships",
            "You need trend analysis (is this metric getting worse? when did it start?)",
            "Latency, throughput, or error rate analysis over time",
            "Comparing current behavior to historical baselines",
            "Capacity planning or identifying resource trends",
        ],
        "do_not_use_when": [
            "You need real-time pod status (use K8s agent)",
            "You need to read application logs (use log analysis agent)",
            "You need point-in-time metrics, not trends (might be available via other agents)",
        ],
        "delegation_examples": [
            '"Analyze latency metrics for API gateway over the last 2 hours. Detect any anomalies and correlate with deployment events."',
            '"Check error rate trends for checkout service. Compare to baseline and identify when the degradation started."',
            '"Detect anomalies in CPU and memory usage across the payment service pods over the last 24 hours."',
            '"Correlate request latency with database connection pool usage to see if they\'re related."',
        ],
        "parent_agent": "investigation",
    },
    "log_analysis": {
        "name": "Log Analysis Agent",
        "tool_name": "call_log_analysis_agent",
        "description": "Log investigation specialist using partition-first, sampling-based analysis. Efficiently handles high-volume logs without overwhelming systems.",
        "use_when": [
            "You need to find error patterns in application logs",
            "You want to understand when errors started and their frequency",
            "You need to correlate log events with deployments or restarts",
            "High log volume requires intelligent sampling (not a full dump)",
            "You need to extract and cluster similar error messages into patterns",
            "Investigating intermittent errors that require log timeline analysis",
        ],
        "do_not_use_when": [
            "You just need current pod status (use K8s agent - it can get recent logs too)",
            "You need metrics trends over time (use metrics agent)",
            "Simple log retrieval for a single pod (K8s agent can do this)",
        ],
        "delegation_examples": [
            '"Investigate error patterns in payment-service logs for the last 30 minutes. Find when errors started and what patterns dominate."',
            '"Analyze API gateway logs for 5xx errors. Sample intelligently and correlate with any deployment events."',
            '"Find all unique error signatures in the checkout service logs and rank them by frequency."',
            '"Check if errors correlate with the deployment that happened at 10:30 AM."',
        ],
        "parent_agent": "investigation",
    },
}


def get_capability(agent_key: str) -> dict[str, Any] | None:
    """
    Get capability descriptor for an agent.

    Args:
        agent_key: Agent key (e.g., "k8s", "aws", "investigation")

    Returns:
        Capability descriptor dict or None if not found
    """
    return AGENT_CAPABILITIES.get(agent_key)


def get_all_capabilities() -> dict[str, dict[str, Any]]:
    """
    Get all agent capability descriptors.

    Returns:
        Dict mapping agent key to capability descriptor
    """
    return AGENT_CAPABILITIES.copy()


def get_enabled_agent_keys(
    team_config: dict[str, Any] | None = None,
    default_agents: list[str] | None = None,
) -> list[str]:
    """
    Get list of enabled agent keys based on team config.

    Args:
        team_config: Optional team configuration
        default_agents: Default list of agents if no config

    Returns:
        List of enabled agent keys
    """
    # Starship topology: 3 top-level agents from Planner
    # Investigation agent has its own subagents (github, k8s, aws, metrics, log_analysis)
    if default_agents is None:
        default_agents = ["investigation", "coding", "writeup"]

    if not team_config:
        return default_agents

    # Check for explicit agent configuration
    agents_config = team_config.get("agents", {})
    if not agents_config:
        return default_agents

    # Filter to enabled agents
    enabled = []
    for agent_key in default_agents:
        agent_cfg = agents_config.get(agent_key, {})
        # Default to enabled if not explicitly disabled
        if agent_cfg.get("enabled", True):
            enabled.append(agent_key)

    return enabled


def get_subagent_keys(
    parent_agent: str,
    team_config: dict[str, Any] | None = None,
) -> list[str]:
    """
    Get list of subagent keys for a parent agent.

    Args:
        parent_agent: Parent agent key (e.g., "investigation")
        team_config: Optional team configuration

    Returns:
        List of subagent keys
    """
    # Get default subagents from capability definition
    parent_capability = get_capability(parent_agent)
    if not parent_capability:
        return []

    default_subagents = parent_capability.get("subagents", [])

    if not team_config:
        return default_subagents

    # Check for explicit subagent configuration in team config
    agents_config = team_config.get("agents", {})
    parent_config = agents_config.get(parent_agent, {})
    configured_subagents = parent_config.get("subagents")

    if configured_subagents is not None:
        return configured_subagents

    return default_subagents

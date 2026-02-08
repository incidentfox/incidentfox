"""
Built-in skills catalog metadata.

This module contains static metadata for all built-in skills available in the agent.
Skills are domain-specific knowledge and methodologies that agents can load on-demand.

Each skill includes:
- id: Unique skill identifier (matches SKILL.md frontmatter name)
- name: Human-readable skill name
- description: What the skill provides
- category: Skill category for organization
- required_integrations: List of integration IDs this skill requires
"""

from typing import Any, Dict, List

BUILT_IN_SKILLS_METADATA = [
    # Methodology skills (no integration required)
    {
        "id": "investigate",
        "name": "Investigation Methodology",
        "description": "Systematic 5-phase incident investigation framework for evidence-based root cause analysis",
        "category": "methodology",
        "required_integrations": [],
    },
    {
        "id": "observability",
        "name": "Observability Methodology",
        "description": "Log, metric, and trace analysis methodology across observability backends",
        "category": "methodology",
        "required_integrations": [],
    },
    {
        "id": "infrastructure",
        "name": "Infrastructure Debugging",
        "description": "Infrastructure debugging methodology for Kubernetes and AWS",
        "category": "methodology",
        "required_integrations": [],
    },
    # Observability skills
    {
        "id": "coralogix-analysis",
        "name": "Coralogix Analysis",
        "description": "Coralogix log analysis with DataPrime query language",
        "category": "observability",
        "required_integrations": ["coralogix"],
    },
    {
        "id": "datadog-analysis",
        "name": "Datadog Analysis",
        "description": "Datadog log and metrics analysis with query syntax reference",
        "category": "observability",
        "required_integrations": ["datadog"],
    },
    {
        "id": "elasticsearch-analysis",
        "name": "Elasticsearch Analysis",
        "description": "Elasticsearch/OpenSearch log analysis using Lucene query syntax and Query DSL",
        "category": "observability",
        "required_integrations": ["elasticsearch"],
    },
    {
        "id": "splunk-analysis",
        "name": "Splunk Analysis",
        "description": "Splunk log analysis using SPL (Search Processing Language)",
        "category": "observability",
        "required_integrations": ["splunk"],
    },
    {
        "id": "observability-loki",
        "name": "Loki Analysis",
        "description": "Grafana Loki log analysis using LogQL",
        "category": "observability",
        "required_integrations": ["loki"],
    },
    {
        "id": "jaeger-analysis",
        "name": "Jaeger Tracing",
        "description": "Jaeger distributed tracing analysis for request flow and latency",
        "category": "observability",
        "required_integrations": ["jaeger"],
    },
    {
        "id": "metrics-analysis",
        "name": "Metrics Analysis",
        "description": "Prometheus/Grafana metrics analysis with PromQL queries",
        "category": "observability",
        "required_integrations": ["grafana", "prometheus"],
    },
    # Infrastructure skills
    {
        "id": "kubernetes-debug",
        "name": "Kubernetes Debugging",
        "description": "Kubernetes debugging for pod crashes, CrashLoopBackOff, OOMKilled, and deployment issues",
        "category": "infrastructure",
        "required_integrations": ["kubernetes"],
    },
    {
        "id": "remediation",
        "name": "Remediation Actions",
        "description": "Safe remediation actions for Kubernetes including pod restarts, scaling, and rollbacks",
        "category": "infrastructure",
        "required_integrations": ["kubernetes"],
    },
    # Incident management skills
    {
        "id": "alerting-context",
        "name": "Alerting Context",
        "description": "Pull incident context from PagerDuty including on-call, history, and MTTR",
        "category": "incident",
        "required_integrations": ["pagerduty"],
    },
    {
        "id": "incident-comms",
        "name": "Incident Communications",
        "description": "Slack integration for searching incident channels and posting status updates",
        "category": "communication",
        "required_integrations": ["slack"],
    },
    # Code & deployment skills
    {
        "id": "deployment-correlation",
        "name": "Deployment Correlation",
        "description": "Correlate incidents with recent deployments and code changes via Git history",
        "category": "code",
        "required_integrations": ["github"],
    },
    # Documentation skills
    {
        "id": "knowledge-base",
        "name": "Knowledge Base",
        "description": "Search runbooks, documentation, and post-mortems from Confluence",
        "category": "documentation",
        "required_integrations": ["confluence"],
    },
    # Project management skills
    {
        "id": "project-clickup",
        "name": "ClickUp Projects",
        "description": "ClickUp project management for incident tracking and task management",
        "category": "project-management",
        "required_integrations": ["clickup"],
    },
]


def get_built_in_skills() -> List[Dict[str, Any]]:
    """
    Get list of all built-in skills.

    Returns:
        List of skill metadata dicts with id, name, description, category, source, required_integrations
    """
    return [
        {
            **skill,
            "source": "built-in",
        }
        for skill in BUILT_IN_SKILLS_METADATA
    ]


def get_skills_by_integration(integration_id: str) -> List[Dict[str, Any]]:
    """
    Get all skills that require a specific integration.

    Args:
        integration_id: The integration ID (e.g., "coralogix", "kubernetes", "pagerduty")

    Returns:
        List of skill metadata dicts that require this integration
    """
    return [
        {**skill, "source": "built-in"}
        for skill in BUILT_IN_SKILLS_METADATA
        if integration_id in skill.get("required_integrations", [])
    ]


def get_skills_catalog() -> Dict[str, Any]:
    """
    Get complete skills catalog.

    Returns:
        Dict with 'skills' list and 'count'
    """
    skills = get_built_in_skills()

    return {
        "skills": skills,
        "count": len(skills),
    }

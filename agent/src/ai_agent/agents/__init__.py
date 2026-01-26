"""AI Agent implementations.

Starship Topology:
- Planner (orchestrator)
  - Investigation Agent (sub-orchestrator)
    - GitHub Agent
    - K8s Agent
    - AWS Agent
    - Metrics Agent
    - Log Analysis Agent
  - Coding Agent
  - Writeup Agent
"""

from .aws_agent import create_aws_agent
from .ci_agent import create_ci_agent
from .coding_agent import create_coding_agent
from .github_agent import create_github_agent
from .investigation_agent import create_investigation_agent
from .k8s_agent import create_k8s_agent
from .log_analysis_agent import create_log_analysis_agent
from .metrics_advisor_agent import create_metrics_advisor_agent
from .metrics_agent import create_metrics_agent
from .planner import create_planner_agent
from .writeup_agent import create_writeup_agent

__all__ = [
    # Orchestrators
    "create_planner_agent",
    "create_investigation_agent",
    # Top-level agents (from Planner)
    "create_coding_agent",
    "create_writeup_agent",
    "create_metrics_advisor_agent",
    # Sub-agents (from Investigation)
    "create_github_agent",
    "create_k8s_agent",
    "create_aws_agent",
    "create_metrics_agent",
    "create_log_analysis_agent",
    # Legacy (kept for backwards compatibility)
    "create_ci_agent",
]

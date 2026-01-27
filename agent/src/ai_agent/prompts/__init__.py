"""Prompt building utilities for AI SRE agents."""

from .layers import (
    # Tool-specific prompt guidance
    ASK_HUMAN_TOOL_PROMPT,
    # Integration-specific error definitions
    AWS_ERRORS,
    CODING_ERRORS,
    CONTEXT_RECEIVING_GUIDANCE,  # Deprecated: use SUBAGENT_GUIDANCE
    DELEGATION_GUIDANCE,
    ERROR_HANDLING_COMMON,
    EVIDENCE_FORMAT_GUIDANCE,
    GITHUB_ERRORS,
    INTEGRATION_ERRORS_REGISTRY,
    INTEGRATION_TOOL_LIMITS,
    KUBERNETES_ERRORS,
    LOGS_ERRORS,
    METRICS_ERRORS,
    SUBAGENT_GUIDANCE,  # Consolidated subagent guidance (context receiving + output format)
    SUBAGENT_OUTPUT_FORMAT,  # Deprecated: use SUBAGENT_GUIDANCE
    SUBAGENT_RESPONSE_GUIDANCE,  # Alias for SUBAGENT_GUIDANCE
    SYNTHESIS_GUIDANCE,
    TOOL_CALL_LIMITS_TEMPLATE,
    # Builder functions - role-based prompts
    apply_role_based_prompt,
    # Builder functions - shared sections
    build_agent_prompt_sections,
    build_agent_shared_sections,
    build_behavior_overrides,
    build_capabilities_section,
    build_contextual_info,
    build_delegation_section,
    build_error_handling_section,
    build_runtime_metadata,
    build_subagent_response_section,
    build_tool_call_limits,
    build_tool_guidance,
    # User context builder (for user/task message)
    build_user_context,
    format_local_context,
    get_integration_errors,
    get_integration_tool_limits,
)
from .planner_prompt import PLANNER_SYSTEM_PROMPT, build_planner_system_prompt

__all__ = [
    # Planner prompt
    "build_planner_system_prompt",
    "PLANNER_SYSTEM_PROMPT",
    # User context builder (for user/task message)
    "build_user_context",
    # Role-based and delegation guidance
    "SUBAGENT_RESPONSE_GUIDANCE",
    "DELEGATION_GUIDANCE",
    "ASK_HUMAN_TOOL_PROMPT",
    # Shared templates for all agents
    "ERROR_HANDLING_COMMON",
    "TOOL_CALL_LIMITS_TEMPLATE",
    "SUBAGENT_GUIDANCE",  # Recommended: consolidated subagent guidance
    "SUBAGENT_OUTPUT_FORMAT",  # Deprecated: use SUBAGENT_GUIDANCE
    "CONTEXT_RECEIVING_GUIDANCE",  # Deprecated: use SUBAGENT_GUIDANCE
    "EVIDENCE_FORMAT_GUIDANCE",
    "SYNTHESIS_GUIDANCE",
    # Integration-specific error definitions
    "KUBERNETES_ERRORS",
    "AWS_ERRORS",
    "GITHUB_ERRORS",
    "METRICS_ERRORS",
    "LOGS_ERRORS",
    "CODING_ERRORS",
    "INTEGRATION_ERRORS_REGISTRY",
    "INTEGRATION_TOOL_LIMITS",
    # Builder functions - context and layers
    "build_runtime_metadata",  # Deprecated - use build_user_context instead
    "build_capabilities_section",
    "build_contextual_info",
    "build_behavior_overrides",
    "build_subagent_response_section",
    "build_delegation_section",
    "apply_role_based_prompt",
    "build_tool_guidance",
    "format_local_context",
    # Builder functions - shared sections (recommended API)
    "build_agent_prompt_sections",  # Simpler API with defaults
    "build_agent_shared_sections",  # Full control API
    "build_error_handling_section",
    "build_tool_call_limits",
    "get_integration_errors",
    "get_integration_tool_limits",
]

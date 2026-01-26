"""
Hierarchical Configuration System

This module provides the core logic for:
1. Deep merging configurations with inheritance
2. Validating required fields
3. Computing effective configs from the hierarchy
4. Handling field-level behaviors (locked, required, approval)
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Tuple

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from .default_prompts import DEFAULT_PROMPTS

logger = structlog.get_logger(__name__)


# =============================================================================
# Deep Merge Logic
# =============================================================================


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deep merge two dictionaries with override taking precedence.

    Simplified merge rules (no control keys needed):
    - Primitives (str, int, bool, None): override replaces base
    - Dicts: recursive merge at key level
    - Lists: override replaces base entirely

    With dict-based schema, we don't need special control keys like
    _inherit, _append, _merge, etc. Everything just works naturally!

    Args:
        base: Base configuration (e.g., from parent node)
        override: Override configuration (e.g., from child node)

    Returns:
        Merged configuration
    """
    if not isinstance(base, dict) or not isinstance(override, dict):
        return override if override is not None else base

    result = copy.deepcopy(base)

    for key, value in override.items():
        if key not in result:
            # New key: add it
            result[key] = copy.deepcopy(value)
        elif isinstance(value, dict) and isinstance(result[key], dict):
            # Both are dicts: recursive merge
            result[key] = deep_merge(result[key], value)
        else:
            # Primitive, list, or type mismatch: replace entirely
            result[key] = copy.deepcopy(value)

    return result


def compute_effective_config(
    org_config: Dict[str, Any],
    team_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Compute the effective configuration by merging hierarchy.

    Order: org_config → team_config → sub_team_config → ...
    Each level can override the previous.

    Args:
        org_config: Organization-level configuration
        team_config: Team-level configuration (optional, can be nested team)

    Returns:
        Merged effective configuration
    """
    result = copy.deepcopy(org_config or {})

    if team_config:
        result = deep_merge(result, team_config)

    return result


def compute_config_diff(
    old_config: Dict[str, Any], new_config: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Compute the difference between two configs.

    Returns:
        Dict with 'added', 'removed', 'changed' keys
    """
    diff = {
        "added": {},
        "removed": {},
        "changed": {},
    }

    def flatten(d: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
        items = {}
        for k, v in d.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                items.update(flatten(v, key))
            else:
                items[key] = v
        return items

    old_flat = flatten(old_config or {})
    new_flat = flatten(new_config or {})

    old_keys = set(old_flat.keys())
    new_keys = set(new_flat.keys())

    for key in new_keys - old_keys:
        diff["added"][key] = new_flat[key]

    for key in old_keys - new_keys:
        diff["removed"][key] = old_flat[key]

    for key in old_keys & new_keys:
        if old_flat[key] != new_flat[key]:
            diff["changed"][key] = {
                "old": old_flat[key],
                "new": new_flat[key],
            }

    return diff


# =============================================================================
# Field Validation
# =============================================================================


class FieldDefinition:
    """Definition of a config field and its constraints."""

    def __init__(
        self,
        path: str,
        field_type: str,
        required: bool = False,
        default_value: Any = None,
        locked_at_level: Optional[str] = None,
        requires_approval: bool = False,
        display_name: Optional[str] = None,
        description: Optional[str] = None,
        validation_regex: Optional[str] = None,
        min_value: Optional[float] = None,
        max_value: Optional[float] = None,
        allowed_values: Optional[List[Any]] = None,
    ):
        self.path = path
        self.field_type = field_type
        self.required = required
        self.default_value = default_value
        self.locked_at_level = locked_at_level
        self.requires_approval = requires_approval
        self.display_name = (
            display_name or path.split(".")[-1].replace("_", " ").title()
        )
        self.description = description
        self.validation_regex = validation_regex
        self.min_value = min_value
        self.max_value = max_value
        self.allowed_values = allowed_values


def get_value_at_path(config: Dict[str, Any], path: str) -> Tuple[Any, bool]:
    """
    Get value at a dotted path in config.

    Returns:
        Tuple of (value, found)
    """
    parts = path.split(".")
    current = config

    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return None, False
        current = current[part]

    return current, True


def set_value_at_path(config: Dict[str, Any], path: str, value: Any) -> Dict[str, Any]:
    """
    Set value at a dotted path in config.

    Returns:
        Modified config (also modifies in place)
    """
    parts = path.split(".")
    current = config

    for part in parts[:-1]:
        if part not in current:
            current[part] = {}
        current = current[part]

    current[parts[-1]] = value
    return config


def validate_field(value: Any, field_def: FieldDefinition) -> List[str]:
    """
    Validate a single field value against its definition.

    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []

    # Type validation
    if value is not None:
        if field_def.field_type == "string" and not isinstance(value, str):
            errors.append(
                f"{field_def.path}: expected string, got {type(value).__name__}"
            )
        elif field_def.field_type == "number" and not isinstance(value, (int, float)):
            errors.append(
                f"{field_def.path}: expected number, got {type(value).__name__}"
            )
        elif field_def.field_type == "boolean" and not isinstance(value, bool):
            errors.append(
                f"{field_def.path}: expected boolean, got {type(value).__name__}"
            )
        elif field_def.field_type == "array" and not isinstance(value, list):
            errors.append(
                f"{field_def.path}: expected array, got {type(value).__name__}"
            )
        elif field_def.field_type == "object" and not isinstance(value, dict):
            errors.append(
                f"{field_def.path}: expected object, got {type(value).__name__}"
            )

    # Regex validation
    if field_def.validation_regex and isinstance(value, str):
        if not re.match(field_def.validation_regex, value):
            errors.append(f"{field_def.path}: value does not match required format")

    # Range validation
    if isinstance(value, (int, float)):
        if field_def.min_value is not None and value < field_def.min_value:
            errors.append(
                f"{field_def.path}: value {value} is below minimum {field_def.min_value}"
            )
        if field_def.max_value is not None and value > field_def.max_value:
            errors.append(
                f"{field_def.path}: value {value} is above maximum {field_def.max_value}"
            )

    # Allowed values validation
    if field_def.allowed_values and value not in field_def.allowed_values:
        errors.append(
            f"{field_def.path}: value must be one of {field_def.allowed_values}"
        )

    return errors


def validate_config(
    config: Dict[str, Any],
    field_definitions: List[FieldDefinition],
) -> Dict[str, Any]:
    """
    Validate a config against field definitions.

    Returns:
        {
            'valid': bool,
            'missing_required': [{'path': ..., 'display_name': ..., 'description': ...}],
            'errors': [str]
        }
    """
    missing_required = []
    errors = []

    for field_def in field_definitions:
        value, found = get_value_at_path(config, field_def.path)

        # Check required fields
        if field_def.required:
            if not found or value is None or value == "":
                missing_required.append(
                    {
                        "path": field_def.path,
                        "display_name": field_def.display_name,
                        "description": field_def.description,
                        "field_type": field_def.field_type,
                    }
                )

        # Validate field value
        if found and value is not None:
            field_errors = validate_field(value, field_def)
            errors.extend(field_errors)

    return {
        "valid": len(missing_required) == 0 and len(errors) == 0,
        "missing_required": missing_required,
        "errors": errors,
    }


def check_locked_fields(
    new_config: Dict[str, Any],
    old_config: Dict[str, Any],
    field_definitions: List[FieldDefinition],
    current_level: str,  # 'org' or 'team'
) -> List[str]:
    """
    Check if any locked fields are being modified at the wrong level.

    Returns:
        List of error messages for locked field violations
    """
    level_order = {"org": 0, "team": 1}
    errors = []

    for field_def in field_definitions:
        if field_def.locked_at_level:
            locked_level = level_order.get(field_def.locked_at_level, 0)
            current = level_order.get(current_level, 2)

            if current > locked_level:
                # Check if this field is being changed
                old_value, _ = get_value_at_path(old_config, field_def.path)
                new_value, new_found = get_value_at_path(new_config, field_def.path)

                if new_found and new_value != old_value:
                    errors.append(
                        f"{field_def.path}: field is locked at {field_def.locked_at_level} level "
                        f"and cannot be modified at {current_level} level"
                    )

    return errors


def get_fields_requiring_approval(
    new_config: Dict[str, Any],
    old_config: Dict[str, Any],
    field_definitions: List[FieldDefinition],
) -> List[Dict[str, Any]]:
    """
    Get list of changed fields that require approval.

    Returns:
        List of {path, display_name, old_value, new_value}
    """
    requiring_approval = []

    for field_def in field_definitions:
        if field_def.requires_approval:
            old_value, _ = get_value_at_path(old_config, field_def.path)
            new_value, new_found = get_value_at_path(new_config, field_def.path)

            if new_found and new_value != old_value:
                requiring_approval.append(
                    {
                        "path": field_def.path,
                        "display_name": field_def.display_name,
                        "old_value": old_value,
                        "new_value": new_value,
                    }
                )

    return requiring_approval


# =============================================================================
# Config Hashing (for change detection)
# =============================================================================


def hash_config(config: Dict[str, Any]) -> str:
    """
    Compute a stable hash of a config for change detection.
    """
    json_str = json.dumps(config, sort_keys=True, default=str)
    return hashlib.sha256(json_str.encode()).hexdigest()[:16]


# =============================================================================
# Default Configurations
# =============================================================================


def get_default_agent_config() -> Dict[str, Any]:
    """
    Get the default agent configuration.

    This is the baseline that all orgs start with.
    Teams inherit from org, which inherits from this.

    Uses STARSHIP TOPOLOGY:
    - Planner (orchestrator) → investigation, coding, writeup
    - Investigation (sub-orchestrator) → github, k8s, aws, metrics, log_analysis
    """
    return {
        "agents": {
            # =================================================================
            # TOP-LEVEL ORCHESTRATOR
            # =================================================================
            "planner": {
                "enabled": True,
                "name": "Planner",
                "description": "Top-level orchestrator that delegates to 3 specialized agents",
                "model": {"name": "gpt-4o", "temperature": 0.3, "max_tokens": 16000},
                "prompt": {
                    "system": DEFAULT_PROMPTS.get("planner", ""),
                    "prefix": "",
                    "suffix": "",
                },
                "max_turns": 50,
                "tools": {"think": True, "llm_call": True, "web_search": True},
                # STARSHIP: Only 3 top-level agents
                "sub_agents": {
                    "investigation": True,
                    "coding": True,
                    "writeup": True,
                },
                "mcps": {},  # No MCPs by default, teams can add
                "handoff_strategy": "agent_as_tool",
            },
            # =================================================================
            # SUB-ORCHESTRATOR (Investigation has its own sub-agents)
            # =================================================================
            "investigation": {
                "enabled": True,
                "name": "Investigation Agent",
                "description": "Sub-orchestrator for incident investigation with 5 specialized sub-agents",
                "model": {"name": "gpt-4o", "temperature": 0.4, "max_tokens": 16000},
                "prompt": {
                    "system": DEFAULT_PROMPTS.get("investigation", ""),
                    "prefix": "",
                    "suffix": "",
                },
                "max_turns": 25,
                "tools": {"think": True, "llm_call": True, "web_search": True},
                # STARSHIP: Investigation coordinates 5 specialized agents
                "sub_agents": {
                    "github": True,
                    "k8s": True,
                    "aws": True,
                    "metrics": True,
                    "log_analysis": True,
                },
                "mcps": {},
            },
            # =================================================================
            # TOP-LEVEL AGENTS (from Planner)
            # =================================================================
            "coding": {
                "enabled": True,
                "name": "Coding Agent",
                "description": "Code analysis, debugging, and fixes",
                "model": {"name": "gpt-4o", "temperature": 0.4, "max_tokens": 16000},
                "prompt": {
                    "system": DEFAULT_PROMPTS.get("coding", ""),
                    "prefix": "",
                    "suffix": "",
                },
                "max_turns": 20,
                "tools": {
                    "think": True,
                    "llm_call": True,
                    "web_search": True,
                    "read_file": True,
                    "write_file": True,
                    "list_directory": True,
                    "repo_search_text": True,
                    "python_run_tests": True,
                    "pytest_run": True,
                    "run_linter": True,
                    "git_status": True,
                    "git_diff": True,
                    "git_log": True,
                    "git_blame": True,
                    "git_show": True,
                    "git_branch_list": True,
                },
                "sub_agents": {},
                "mcps": {},
            },
            "writeup": {
                "enabled": True,
                "name": "Writeup Agent",
                "description": "Blameless postmortem and incident documentation",
                "model": {"name": "gpt-4o", "temperature": 0.5, "max_tokens": 16000},
                "prompt": {
                    "system": DEFAULT_PROMPTS.get("writeup", ""),
                    "prefix": "",
                    "suffix": "",
                },
                "max_turns": 15,
                "tools": {"think": True, "llm_call": True, "web_search": True},
                "sub_agents": {},
                "mcps": {},
            },
            # =================================================================
            # SUB-AGENTS (from Investigation)
            # =================================================================
            "github": {
                "enabled": True,
                "name": "GitHub Agent",
                "description": "GitHub repository analysis for change correlation",
                "model": {"name": "gpt-4o", "temperature": 0.3, "max_tokens": 16000},
                "prompt": {
                    "system": DEFAULT_PROMPTS.get("github", ""),
                    "prefix": "",
                    "suffix": "",
                },
                "max_turns": 15,
                "tools": {
                    "think": True,
                    "llm_call": True,
                    "read_github_file": True,
                    "search_github_code": True,
                    "list_pull_requests": True,
                    "list_issues": True,
                    "git_log": True,
                    "git_show": True,
                    "git_diff": True,
                },
                "sub_agents": {},
                "mcps": {},
            },
            "k8s": {
                "enabled": True,
                "name": "Kubernetes Agent",
                "description": "Kubernetes troubleshooting and operations",
                "model": {"name": "gpt-4o", "temperature": 0.3, "max_tokens": 16000},
                "prompt": {
                    "system": DEFAULT_PROMPTS.get("k8s", ""),
                    "prefix": "",
                    "suffix": "",
                },
                "max_turns": 15,
                "tools": {
                    "think": True,
                    "llm_call": True,
                    "web_search": True,
                    "list_pods": True,
                    "describe_pod": True,
                    "get_pod_logs": True,
                    "get_pod_events": True,
                    "get_pod_resource_usage": True,
                    "describe_deployment": True,
                    "get_deployment_history": True,
                    "describe_service": True,
                    "docker_ps": True,
                    "docker_logs": True,
                    "docker_inspect": True,
                    "docker_exec": True,
                    "docker_stats": True,
                },
                "sub_agents": {},
                "mcps": {},
            },
            "aws": {
                "enabled": True,
                "name": "AWS Agent",
                "description": "AWS resource management and debugging",
                "model": {"name": "gpt-4o", "temperature": 0.3, "max_tokens": 16000},
                "prompt": {
                    "system": DEFAULT_PROMPTS.get("aws", ""),
                    "prefix": "",
                    "suffix": "",
                },
                "max_turns": 15,
                "tools": {
                    "think": True,
                    "llm_call": True,
                    "web_search": True,
                    "describe_ec2_instance": True,
                    "describe_lambda_function": True,
                    "get_rds_instance_status": True,
                    "list_ecs_tasks": True,
                    "get_cloudwatch_logs": True,
                    "query_cloudwatch_insights": True,
                    "get_cloudwatch_metrics": True,
                },
                "sub_agents": {},
                "mcps": {},
            },
            "metrics": {
                "enabled": True,
                "name": "Metrics Agent",
                "description": "Metrics analysis and anomaly detection",
                "model": {"name": "gpt-4o", "temperature": 0.2, "max_tokens": 16000},
                "prompt": {
                    "system": DEFAULT_PROMPTS.get("metrics", ""),
                    "prefix": "",
                    "suffix": "",
                },
                "max_turns": 15,
                "tools": {
                    "think": True,
                    "llm_call": True,
                    "web_search": True,
                    "get_cloudwatch_metrics": True,
                    "query_cloudwatch_insights": True,
                    "detect_anomalies": True,
                    "correlate_metrics": True,
                    "find_change_point": True,
                    "forecast_metric": True,
                    "analyze_metric_distribution": True,
                    "grafana_list_dashboards": True,
                    "grafana_get_dashboard": True,
                    "grafana_query_prometheus": True,
                    "grafana_list_datasources": True,
                    "grafana_get_annotations": True,
                    "grafana_get_alerts": True,
                },
                "sub_agents": {},
                "mcps": {},
            },
            "log_analysis": {
                "enabled": True,
                "name": "Log Analysis Agent",
                "description": "Partition-first log investigation specialist",
                "model": {"name": "gpt-4o", "temperature": 0.2, "max_tokens": 16000},
                "prompt": {
                    "system": DEFAULT_PROMPTS.get("log_analysis", ""),
                    "prefix": "",
                    "suffix": "",
                },
                "max_turns": 15,
                "tools": {
                    "think": True,
                    "llm_call": True,
                    "get_log_statistics": True,
                    "sample_logs": True,
                    "search_logs_by_pattern": True,
                    "extract_log_signatures": True,
                    "get_logs_around_timestamp": True,
                    "correlate_logs_with_events": True,
                    "detect_log_anomalies": True,
                },
                "sub_agents": {},
                "mcps": {},
            },
        }
    }


def get_default_tool_config() -> Dict[str, Any]:
    """
    Get the default team-level tool overrides.

    NOTE: This returns team-level tool overrides (Dict[str, bool]), NOT the tools catalog.
    The tools catalog with metadata comes from get_tools_catalog() and is stored in built_in_tools.

    Returns empty dict because all tools are enabled by default via the catalog.
    Teams can override specific tools via their config.
    """
    return {"tools": {}}  # Empty dict - no default team-level overrides


def get_default_mcp_config() -> Dict[str, Any]:
    """
    Get default MCP server configuration.

    NOTE: Returns EMPTY dict by default. MCPs should be explicitly added by teams
    from the MCP catalog, not inherited from defaults. This ensures customers
    only see MCPs they've actually configured.

    For available MCPs, see get_mcp_catalog() instead.
    """
    return {"mcp_servers": {}}  # Empty by default - customers add MCPs explicitly


def get_mcp_catalog() -> list[Dict[str, Any]]:
    """
    Get catalog of available MCP servers that customers can add.

    NOTE: Returns empty list - customers dynamically add their own MCPs.
    The point of MCP is that customers can add ANY MCP server (public, private, custom).

    The UI provides a form where customers enter:
    - Name
    - Description
    - Command (e.g., npx, python, docker run, /path/to/executable)
    - Arguments
    - Environment variables

    The backend spawns the MCP server and discovers tools via MCP protocol.

    Returns:
        Empty list - no pre-defined MCPs.
    """
    return []


def fetch_integration_schemas_from_db(db: Session) -> Dict[str, Any]:
    """
    Fetch integration schemas from database and build config structure.

    Returns a dict like:
    {
        "integrations": {
            "coralogix": {
                "level": "org",
                "locked": False,
                "config_schema": {...}
            },
            ...
        }
    }
    """
    from ..db.config_models import IntegrationSchema

    try:
        # Fetch all integration schemas from DB
        result = db.execute(
            select(IntegrationSchema).order_by(IntegrationSchema.display_order)
        )
        schemas = result.scalars().all()

        integrations = {}
        for schema in schemas:
            # Build config_schema from fields
            config_schema = {}
            team_config_schema = {}

            for field in schema.fields:
                field_def = {
                    "type": field.get("type", "string"),
                    "required": field.get("required", False),
                }
                if "default_value" in field:
                    field_def["default"] = field["default_value"]
                if "description" in field:
                    field_def["description"] = field["description"]
                if "placeholder" in field:
                    field_def["placeholder"] = field["placeholder"]

                # Separate org-level vs team-level fields
                if field.get("level") == "team":
                    team_config_schema[field["name"]] = field_def
                else:  # Default to org-level
                    config_schema[field["name"]] = field_def

            # Build integration entry
            integration_entry = {
                "level": "org",
                "locked": schema.id == "openai",  # Only OpenAI is locked (required)
                "config_schema": config_schema,
            }

            if team_config_schema:
                integration_entry["team_config_schema"] = team_config_schema

            integrations[schema.id] = integration_entry

        return {"integrations": integrations}

    except Exception as e:
        logger.warning("failed_to_fetch_integration_schemas_from_db", error=str(e))
        # Fallback to minimal config if DB fails
        return get_default_integration_config_fallback()


def get_default_integration_config_fallback() -> Dict[str, Any]:
    """Fallback integration configuration when DB is unavailable."""
    return {
        "integrations": {
            "openai": {
                "level": "org",
                "locked": True,
                "config_schema": {"api_key": {"type": "secret", "required": True}},
            }
        }
    }


def get_default_integration_config(db: Optional[Session] = None) -> Dict[str, Any]:
    """
    Get default integration configuration.

    If db session provided, fetches from database.
    Otherwise, returns fallback config.
    """
    if db:
        return fetch_integration_schemas_from_db(db)
    else:
        # Return fallback when no DB session (backward compatibility)
        return get_default_integration_config_fallback()


def get_full_default_config(db: Optional[Session] = None) -> Dict[str, Any]:
    """
    Get the complete default configuration.

    Args:
        db: Optional database session to fetch integration schemas from DB.
            If not provided, uses fallback config.
    """
    config = {}
    config.update(get_default_agent_config())
    config.update(get_default_tool_config())
    config.update(get_default_mcp_config())
    config.update(get_default_integration_config(db=db))

    # Runtime settings
    config["runtime"] = {
        "max_concurrent_agents": 5,
        "default_timeout_seconds": 300,
        "retry_on_failure": True,
        "max_retries": 2,
    }

    # Entrance agent - the agent that handles incoming webhook/API triggers
    config["entrance_agent"] = "planner"

    return config

"""
Feature Request Triage Tools.

Tools for triaging customer feature requests:
- Customer tier lookup (enterprise/standard/free)
- Feature owner lookup (who owns what area)
- Codebase context (understanding system areas)

These tools read from team config's `feature_triage` section.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..core.agent import function_tool
from ..core.config import get_config
from . import register_tool

logger = logging.getLogger(__name__)


def _get_feature_triage_config() -> dict[str, Any]:
    """Get feature_triage config from team config."""
    config = get_config()
    if config.team_config is None:
        logger.warning("feature_triage: no team config loaded")
        return {}
    return config.team_config.feature_triage


def _fuzzy_match_key(target: str, keys: dict) -> str | None:
    """
    Find a key that matches the target using fuzzy matching.

    Tries:
    1. Exact match (case-insensitive)
    2. Contains match
    3. Word overlap match
    """
    target_lower = target.lower().strip()
    target_words = set(target_lower.replace("-", " ").replace("_", " ").split())

    # Exact match
    for key in keys:
        if key.lower() == target_lower:
            return key

    # Contains match
    for key in keys:
        if target_lower in key.lower() or key.lower() in target_lower:
            return key

    # Word overlap match
    best_match = None
    best_overlap = 0
    for key in keys:
        key_words = set(key.lower().replace("-", " ").replace("_", " ").split())
        overlap = len(target_words & key_words)
        if overlap > best_overlap:
            best_overlap = overlap
            best_match = key

    if best_overlap > 0:
        return best_match

    return None


@function_tool
def get_customer_tier(customer_name: str) -> str:
    """
    Look up a customer's tier and SLA information.

    Use this tool to determine the priority level for a customer's request.
    Enterprise customers have strict SLAs and require immediate attention.

    Args:
        customer_name: The customer's name or identifier (e.g., "Acme Corp", "acme")

    Returns:
        JSON with customer tier info:
        - customer: Customer name
        - tier: "enterprise" | "standard" | "free" | "unknown"
        - sla_hours: Response time SLA in hours
        - priority: "urgent" | "high" | "normal" | "low"
        - contact: Customer contact email (if available)
    """
    config = _get_feature_triage_config()
    customers = config.get("customers", {})

    if not customers:
        logger.warning("feature_triage: no customers configured")
        return json.dumps(
            {
                "customer": customer_name,
                "tier": "unknown",
                "sla_hours": 24,
                "priority": "normal",
                "message": "Customer database not configured. Treating as standard priority.",
            }
        )

    matched_key = _fuzzy_match_key(customer_name, customers)

    if matched_key:
        customer_info = customers[matched_key]
        tier = customer_info.get("tier", "standard")

        priority_map = {
            "enterprise": "urgent",
            "standard": "normal",
            "free": "low",
        }

        result = {
            "customer": matched_key,
            "tier": tier,
            "sla_hours": customer_info.get("sla_hours", 24),
            "priority": priority_map.get(tier, "normal"),
            "contact": customer_info.get("contact"),
            "matched_from": customer_name,
        }

        logger.info(f"customer_tier_lookup: {customer_name} -> {matched_key} ({tier})")
        return json.dumps(result)

    logger.info(f"customer_tier_not_found: {customer_name}")
    return json.dumps(
        {
            "customer": customer_name,
            "tier": "unknown",
            "sla_hours": 24,
            "priority": "normal",
            "message": f"Customer '{customer_name}' not found in database. Treating as standard priority.",
            "available_customers": list(customers.keys())[:5],
        }
    )


@function_tool
def get_feature_owner(feature_area: str) -> str:
    """
    Look up who owns a particular feature area or system component.

    Use this tool to find the right person to handle a feature request.
    Returns the owner's name and Slack ID for @mentioning.

    Args:
        feature_area: The feature area or system component (e.g., "payments", "auth", "frontend")

    Returns:
        JSON with owner info:
        - area: The matched feature area
        - owner: Owner's name
        - slack_id: Slack user ID for @mentioning (e.g., "U123ABC")
        - github: Owner's GitHub username (if available)
        - backup: Backup owner (if available)
    """
    config = _get_feature_triage_config()
    owners = config.get("owners", {})

    if not owners:
        logger.warning("feature_triage: no owners configured")
        return json.dumps(
            {
                "area": feature_area,
                "owner": "unknown",
                "slack_id": None,
                "message": "Owner database not configured. Unable to route request.",
            }
        )

    matched_key = _fuzzy_match_key(feature_area, owners)

    if matched_key:
        owner_info = owners[matched_key]

        result = {
            "area": matched_key,
            "owner": owner_info.get("name", "Unknown"),
            "slack_id": owner_info.get("slack_id"),
            "github": owner_info.get("github"),
            "backup": owner_info.get("backup"),
            "matched_from": feature_area,
        }

        logger.info(f"feature_owner_lookup: {feature_area} -> {matched_key} ({result['owner']})")
        return json.dumps(result)

    logger.info(f"feature_owner_not_found: {feature_area}")
    return json.dumps(
        {
            "area": feature_area,
            "owner": "unknown",
            "slack_id": None,
            "message": f"Feature area '{feature_area}' not found. Unable to determine owner.",
            "available_areas": list(owners.keys()),
        }
    )


@function_tool
def get_codebase_context(feature_area: str) -> str:
    """
    Get codebase context for a feature area to help estimate complexity.

    Use this tool to understand what parts of the codebase are involved
    in a feature request, which helps estimate implementation difficulty.

    Args:
        feature_area: The feature area or system component (e.g., "payments", "auth")

    Returns:
        JSON with codebase context:
        - area: The matched feature area
        - repo: Repository name/URL
        - paths: Key file paths involved
        - complexity: "low" | "medium" | "high"
        - notes: Additional context about this area
        - dependencies: External dependencies or integrations
    """
    config = _get_feature_triage_config()
    codebase = config.get("codebase", {})
    areas = codebase.get("areas", {})

    if not areas:
        logger.warning("feature_triage: no codebase configured")
        return json.dumps(
            {
                "area": feature_area,
                "complexity": "unknown",
                "message": "Codebase information not configured. Unable to estimate complexity.",
            }
        )

    matched_key = _fuzzy_match_key(feature_area, areas)

    if matched_key:
        area_info = areas[matched_key]

        result = {
            "area": matched_key,
            "repo": codebase.get("repo", "unknown"),
            "paths": area_info.get("paths", []),
            "complexity": area_info.get("complexity", "medium"),
            "notes": area_info.get("notes", ""),
            "dependencies": area_info.get("dependencies", []),
            "matched_from": feature_area,
        }

        logger.info(f"codebase_context_lookup: {feature_area} -> {matched_key} ({result['complexity']})")
        return json.dumps(result)

    logger.info(f"codebase_context_not_found: {feature_area}")
    return json.dumps(
        {
            "area": feature_area,
            "complexity": "unknown",
            "message": f"Codebase area '{feature_area}' not found.",
            "available_areas": list(areas.keys()),
        }
    )


# =============================================================================
# Register Tools
# =============================================================================

register_tool("get_customer_tier", get_customer_tier)
register_tool("get_feature_owner", get_feature_owner)
register_tool("get_codebase_context", get_codebase_context)

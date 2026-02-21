"""
Repository functions for hierarchical configuration.

Handles CRUD operations for node configurations with:
- Inheritance computation
- Validation
- Change history tracking
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import structlog
from sqlalchemy.orm import Session

from ..core.hierarchical_config import (
    FieldDefinition,
    compute_config_diff,
    compute_effective_config,
    deep_merge,
    validate_config,
)
from .config_models import (
    ConfigChangeHistory,
    ConfigFieldDefinition,
    ConfigValidationStatus,
    NodeConfiguration,
)

logger = structlog.get_logger(__name__)


# =============================================================================
# Node Configuration CRUD
# =============================================================================


def get_node_configuration(
    session: Session,
    org_id: str,
    node_id: str,
) -> Optional[NodeConfiguration]:
    """Get raw node configuration (not merged)."""
    return (
        session.query(NodeConfiguration)
        .filter(
            NodeConfiguration.org_id == org_id,
            NodeConfiguration.node_id == node_id,
        )
        .first()
    )


def get_node_configurations(
    session: Session,
    org_id: str,
    node_ids: List[str],
) -> Dict[str, Dict[str, Any]]:
    """
    Batch fetch node configurations for multiple nodes.
    Returns dict mapping node_id -> config_json.
    Nodes without configs get empty dict {}.
    """
    if not node_ids:
        return {}

    configs = (
        session.query(NodeConfiguration)
        .filter(
            NodeConfiguration.org_id == org_id,
            NodeConfiguration.node_id.in_(node_ids),
        )
        .all()
    )

    result: Dict[str, Dict[str, Any]] = {}
    for config in configs:
        result[config.node_id] = config.config_json or {}

    # Fill in empty dicts for nodes without configs
    for node_id in node_ids:
        if node_id not in result:
            result[node_id] = {}

    return result


def get_or_create_node_configuration(
    session: Session,
    org_id: str,
    node_id: str,
    node_type: str,
) -> NodeConfiguration:
    """Get existing config or create new one with defaults."""
    config = get_node_configuration(session, org_id, node_id)

    if not config:
        config = NodeConfiguration(
            id=f"cfg-{uuid.uuid4().hex[:12]}",
            org_id=org_id,
            node_id=node_id,
            node_type=node_type,
            config_json={},
            version=1,
        )
        session.add(config)
        session.flush()
        logger.info("node_config_created", org_id=org_id, node_id=node_id)

    return config


def update_node_configuration(
    session: Session,
    org_id: str,
    node_id: str,
    config_patch: Dict[str, Any],
    updated_by: Optional[str] = None,
    change_reason: Optional[str] = None,
    skip_validation: bool = False,
) -> Tuple[NodeConfiguration, Dict[str, Any]]:
    """
    Update node configuration with dependency validation.

    This function always performs a deep merge of config_patch into the existing
    configuration. For full config replacement (e.g., rollback), use rollback_to_version().

    Args:
        session: Database session
        org_id: Organization ID
        node_id: Node ID
        config_patch: Configuration changes to merge into existing config
        updated_by: Who is making the change
        change_reason: Why the change is being made
        skip_validation: If True, skip dependency validation (use with caution!)

    Returns:
        Tuple of (updated config, change diff)

    Raises:
        ValueError: If validation fails due to dependency violations
    """
    config = get_node_configuration(session, org_id, node_id)

    if not config:
        raise ValueError(f"Node configuration not found: {org_id}/{node_id}")

    previous_config = config.config_json.copy() if config.config_json else {}

    # Always deep merge (for replacement, use rollback_to_version)
    new_config = deep_merge(previous_config, config_patch)

    # === DEPENDENCY VALIDATION ===
    # Compute what the effective config WOULD BE after this change
    # and validate dependencies before saving
    if not skip_validation:
        from ..core.dependency_validator import validate_config_change

        # Temporarily set the new config to compute effective config
        original_config_json = config.config_json
        config.config_json = new_config

        try:
            # Get hierarchy and compute effective config with the proposed change
            hierarchy = get_node_hierarchy(session, org_id, node_id)

            # Start with system defaults
            from ..core.hierarchical_config import get_full_default_config

            effective = get_full_default_config(db=session)

            # Merge each level from root to leaf (with proposed changes)
            for h_node_id in hierarchy:
                if h_node_id == node_id:
                    # Use the proposed new config for this node
                    effective = deep_merge(effective, new_config)
                else:
                    # Use existing config for other nodes
                    h_config = get_node_configuration(session, org_id, h_node_id)
                    if h_config and h_config.config_json:
                        effective = deep_merge(effective, h_config.config_json)

            # Validate dependencies
            validation_errors = validate_config_change(effective, config_patch)

            if validation_errors:
                # Restore original config
                config.config_json = original_config_json

                # Format error messages
                error_messages = [str(err) for err in validation_errors]
                all_dependents = []
                for err in validation_errors:
                    all_dependents.extend(err.dependents)

                {
                    "error": "dependency_validation_failed",
                    "message": "Configuration change violates dependency constraints",
                    "errors": error_messages,
                    "dependents": list(set(all_dependents)),
                }

                logger.warning(
                    "config_update_blocked_by_dependencies",
                    org_id=org_id,
                    node_id=node_id,
                    errors=error_messages,
                )

                raise ValueError(f"Dependency validation failed: {error_messages[0]}")

        finally:
            # Always restore original config if we're not proceeding
            if config.config_json == new_config:
                # Validation passed, keep new config
                pass
            else:
                # Validation failed, restore was already done in except block
                pass

    # Validation passed (or was skipped), proceed with update
    # Compute diff
    diff = compute_config_diff(previous_config, new_config)

    # Update the config
    config.config_json = new_config
    config.updated_by = updated_by
    config.updated_at = datetime.now(timezone.utc)
    config.version += 1

    # Record history
    history = ConfigChangeHistory(
        id=f"hist-{uuid.uuid4().hex[:12]}",
        org_id=org_id,
        node_id=node_id,
        previous_config=previous_config,
        new_config=new_config,
        change_diff=diff,
        changed_by=updated_by,
        changed_at=datetime.now(timezone.utc),
        change_reason=change_reason,
        version=config.version,
    )
    session.add(history)

    session.flush()
    logger.info(
        "node_config_updated",
        org_id=org_id,
        node_id=node_id,
        version=config.version,
        changes=len(diff.get("changed", {})) + len(diff.get("added", {})),
    )

    return config, diff


def delete_node_configuration(
    session: Session,
    org_id: str,
    node_id: str,
) -> bool:
    """Delete a node configuration."""
    config = get_node_configuration(session, org_id, node_id)
    if config:
        session.delete(config)
        session.flush()
        return True
    return False


# =============================================================================
# Effective Config Computation
# =============================================================================


def get_node_hierarchy(
    session: Session,
    org_id: str,
    node_id: str,
) -> List[str]:
    """
    Get the hierarchy path from org root to this node.

    Returns list of node_ids from org root to target node.
    """
    # Import here to avoid circular dependency
    from .models import OrgNode

    hierarchy = []
    current_id = node_id

    # Walk up the tree
    while current_id:
        hierarchy.insert(0, current_id)
        node = (
            session.query(OrgNode)
            .filter(
                OrgNode.org_id == org_id,
                OrgNode.node_id == current_id,
            )
            .first()
        )

        if not node or not node.parent_id:
            break
        current_id = node.parent_id

    return hierarchy


def compute_effective_config(
    session: Session,
    org_id: str,
    node_id: str,
) -> Dict[str, Any]:
    """
    Compute effective config by merging hierarchy.

    No caching - always recomputes. This ensures configs are always fresh
    and eliminates cache invalidation bugs.

    Args:
        session: Database session
        org_id: Organization ID
        node_id: Node ID

    Returns:
        The effective (merged) configuration
    """
    # Get hierarchy
    hierarchy = get_node_hierarchy(session, org_id, node_id)

    # Start with system defaults (provides baseline agents, tools, integrations)
    # This matches v1 API behavior and ensures new orgs see default agent topology
    from ..core.hierarchical_config import get_full_default_config

    effective = get_full_default_config(db=session)

    # Merge each level from root to leaf
    for h_node_id in hierarchy:
        h_config = get_node_configuration(session, org_id, h_node_id)
        if h_config and h_config.config_json:
            effective = deep_merge(effective, h_config.config_json)

    logger.debug(
        "effective_config_computed",
        org_id=org_id,
        node_id=node_id,
        hierarchy_depth=len(hierarchy),
    )

    return effective


# Deprecated: kept for backwards compatibility
def compute_and_cache_effective_config(
    session: Session,
    org_id: str,
    node_id: str,
    force: bool = False,
) -> Dict[str, Any]:
    """Deprecated: Use compute_effective_config instead. Caching removed."""
    return compute_effective_config(session, org_id, node_id)


def get_effective_config(
    session: Session,
    org_id: str,
    node_id: str,
) -> Dict[str, Any]:
    """Get effective config for a node. Always computes fresh."""
    return compute_effective_config(session, org_id, node_id)


def invalidate_config_cache(
    session: Session,
    org_id: str,
    node_id: str,
    cascade: bool = True,
) -> int:
    """
    Deprecated: No-op. Caching removed to eliminate bugs.

    Kept for backwards compatibility with existing code.
    """
    logger.debug(
        "invalidate_config_cache called (no-op)", org_id=org_id, node_id=node_id
    )
    return 0


# =============================================================================
# Field Definitions
# =============================================================================


def get_field_definitions(
    session: Session,
    category: Optional[str] = None,
) -> List[ConfigFieldDefinition]:
    """Get field definitions, optionally filtered by category."""
    query = session.query(ConfigFieldDefinition)

    if category:
        query = query.filter(ConfigFieldDefinition.category == category)

    return query.order_by(
        ConfigFieldDefinition.category,
        ConfigFieldDefinition.sort_order,
    ).all()


def get_field_definition(
    session: Session,
    path: str,
) -> Optional[ConfigFieldDefinition]:
    """Get a specific field definition by path."""
    return (
        session.query(ConfigFieldDefinition)
        .filter(ConfigFieldDefinition.path == path)
        .first()
    )


def upsert_field_definition(
    session: Session,
    path: str,
    field_type: str,
    **kwargs,
) -> ConfigFieldDefinition:
    """Create or update a field definition."""
    field = get_field_definition(session, path)

    if not field:
        field = ConfigFieldDefinition(
            id=f"field-{uuid.uuid4().hex[:12]}",
            path=path,
            field_type=field_type,
        )
        session.add(field)

    # Update fields
    field.field_type = field_type
    for key, value in kwargs.items():
        if hasattr(field, key):
            setattr(field, key, value)

    session.flush()
    return field


def convert_db_to_field_definitions(
    db_fields: List[ConfigFieldDefinition],
) -> List[FieldDefinition]:
    """Convert DB models to FieldDefinition objects for validation."""
    return [
        FieldDefinition(
            path=f.path,
            field_type=f.field_type,
            required=f.required,
            default_value=f.default_value,
            locked_at_level=f.locked_at_level,
            requires_approval=f.requires_approval,
            display_name=f.display_name,
            description=f.description,
            validation_regex=f.validation_regex,
            min_value=f.min_value,
            max_value=f.max_value,
            allowed_values=f.allowed_values,
        )
        for f in db_fields
    ]


# =============================================================================
# Validation
# =============================================================================


def validate_node_config(
    session: Session,
    org_id: str,
    node_id: str,
) -> Dict[str, Any]:
    """
    Validate a node's effective configuration.

    Returns validation result and updates ConfigValidationStatus.
    """
    effective_config = get_effective_config(session, org_id, node_id)
    db_fields = get_field_definitions(session)
    field_defs = convert_db_to_field_definitions(db_fields)

    result = validate_config(effective_config, field_defs)

    # Update or create validation status
    status = (
        session.query(ConfigValidationStatus)
        .filter(
            ConfigValidationStatus.org_id == org_id,
            ConfigValidationStatus.node_id == node_id,
        )
        .first()
    )

    if not status:
        status = ConfigValidationStatus(
            id=f"val-{uuid.uuid4().hex[:12]}",
            org_id=org_id,
            node_id=node_id,
        )
        session.add(status)

    status.missing_required_fields = result["missing_required"]
    status.validation_errors = result["errors"]
    status.is_valid = result["valid"]
    status.validated_at = datetime.now(timezone.utc)

    session.flush()

    return result


def get_nodes_with_missing_config(
    session: Session,
    org_id: str,
) -> List[Dict[str, Any]]:
    """Get all nodes that have missing required configuration."""
    statuses = (
        session.query(ConfigValidationStatus)
        .filter(
            ConfigValidationStatus.org_id == org_id,
            ConfigValidationStatus.is_valid == False,
        )
        .all()
    )

    return [
        {
            "node_id": s.node_id,
            "missing_required_fields": s.missing_required_fields,
            "validation_errors": s.validation_errors,
            "validated_at": s.validated_at.isoformat() if s.validated_at else None,
        }
        for s in statuses
    ]


# =============================================================================
# Change History
# =============================================================================


def get_config_history(
    session: Session,
    org_id: str,
    node_id: str,
    limit: int = 50,
) -> List[ConfigChangeHistory]:
    """Get configuration change history for a node."""
    return (
        session.query(ConfigChangeHistory)
        .filter(
            ConfigChangeHistory.org_id == org_id,
            ConfigChangeHistory.node_id == node_id,
        )
        .order_by(ConfigChangeHistory.changed_at.desc())
        .limit(limit)
        .all()
    )


def rollback_to_version(
    session: Session,
    org_id: str,
    node_id: str,
    version: int,
    rolled_back_by: Optional[str] = None,
) -> Tuple[NodeConfiguration, Dict[str, Any]]:
    """
    Rollback configuration to a specific version.

    This completely replaces the current config with the historical version.
    Creates a new version entry in the history.
    """
    # Get the configuration
    config = get_node_configuration(session, org_id, node_id)
    if not config:
        raise ValueError(f"Node configuration not found: {org_id}/{node_id}")

    # Find the history entry for that version
    history = (
        session.query(ConfigChangeHistory)
        .filter(
            ConfigChangeHistory.org_id == org_id,
            ConfigChangeHistory.node_id == node_id,
            ConfigChangeHistory.version == version,
        )
        .first()
    )

    if not history:
        raise ValueError(f"Version {version} not found for {org_id}/{node_id}")

    # Store previous config for history
    previous_config = config.config_json.copy() if config.config_json else {}

    # The "new_config" of that version is what we want to restore
    config_to_restore = history.new_config

    # Restore the historical config (full replacement)
    config.config_json = config_to_restore
    config.updated_at = datetime.utcnow()
    config.updated_by = rolled_back_by or "system"
    config.version += 1

    # Create audit entry
    change_entry = ConfigChangeHistory(
        id=f"chg-{uuid.uuid4().hex[:12]}",
        org_id=org_id,
        node_id=node_id,
        field_path="<rollback>",
        old_config=previous_config,
        new_config=config.config_json,
        old_value=None,
        new_value=None,
        version=config.version,
        changed_by=rolled_back_by or "system",
        changed_at=datetime.utcnow(),
        change_reason=f"Rollback to version {version}",
    )
    session.add(change_entry)
    session.flush()

    # Compute diff for return value
    diff = {"rollback": f"Restored version {version}"}

    return (config, diff)


# =============================================================================
# Bulk Operations
# =============================================================================


def initialize_org_config(
    session: Session,
    org_id: str,
    org_node_id: str,
    initial_config: Optional[Dict[str, Any]] = None,
) -> NodeConfiguration:
    """
    Initialize configuration for a new organization.

    Creates the org-level config with defaults or provided config.
    """
    config = get_or_create_node_configuration(session, org_id, org_node_id, "org")

    if initial_config:
        config.config_json = initial_config
        session.flush()

    return config


def clone_config_to_node(
    session: Session,
    org_id: str,
    source_node_id: str,
    target_node_id: str,
    target_node_type: str,
) -> NodeConfiguration:
    """Clone configuration from one node to another."""
    source = get_node_configuration(session, org_id, source_node_id)

    if not source:
        raise ValueError(f"Source node not found: {source_node_id}")

    target = get_or_create_node_configuration(
        session, org_id, target_node_id, target_node_type
    )

    target.config_json = source.config_json.copy()
    session.flush()

    return target

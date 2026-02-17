"""
YAML Configuration Seeder

Handles seeding the database from local.yaml on startup in local development mode.
"""

import os
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from src.core.yaml_config import get_yaml_config_manager, is_local_mode
from src.core.audit_log import app_logger
from src.db.config_repository import (
    get_node_configuration,
    create_node_configuration,
    update_node_configuration,
)
from src.db.models import Organization, Node
from src.db.session import get_db


logger = app_logger().bind(component="yaml_seeder")


def seed_from_yaml(
    session: Session,
    config_file_path: str = "config/local.yaml",
    force: bool = False
) -> bool:
    """Seed database configuration from YAML file.

    Args:
        session: Database session
        config_file_path: Path to YAML config file
        force: If True, always seed even if config already exists

    Returns:
        True if seeding was performed, False otherwise
    """
    if not is_local_mode():
        logger.info("Not in local mode, skipping YAML seeding")
        return False

    yaml_manager = get_yaml_config_manager(config_file_path)

    try:
        config = yaml_manager.load_config()
    except FileNotFoundError:
        logger.warning(f"Config file not found: {config_file_path}, skipping seeding")
        return False
    except Exception as e:
        logger.error(f"Failed to load config file: {e}")
        return False

    if not config:
        logger.info("Empty config file, skipping seeding")
        return False

    # Extract org and team IDs
    org_id = config.get("org_id", "local")
    team_id = config.get("team_id", "default")

    logger.info(f"Seeding config for org={org_id}, team={team_id}")

    # Ensure organization exists
    _ensure_organization(session, org_id)

    # Ensure team node exists
    _ensure_team_node(session, org_id, team_id)

    # Check if config already exists
    org_config = get_node_configuration(session, org_id, org_id)
    team_config = get_node_configuration(session, org_id, team_id)

    # Only seed if force=True or configs don't exist/are empty
    should_seed_org = force or not org_config or not org_config.config_json
    should_seed_team = force or not team_config or not team_config.config_json

    if not should_seed_org and not should_seed_team:
        logger.info("Configs already exist, skipping seeding (use force=True to override)")
        return False

    # Prepare org-level config
    org_config_data = _extract_org_config(config)

    # Prepare team-level config
    team_config_data = _extract_team_config(config)

    # Seed org config
    if should_seed_org and org_config_data:
        if org_config:
            update_node_configuration(
                session,
                org_id,
                org_id,
                org_config_data,
                updated_by="yaml_seeder",
                change_reason="Seeded from local.yaml",
                skip_validation=True
            )
            logger.info(f"Updated org config for {org_id}")
        else:
            create_node_configuration(
                session,
                org_id,
                org_id,
                org_config_data,
                created_by="yaml_seeder"
            )
            logger.info(f"Created org config for {org_id}")

    # Seed team config
    if should_seed_team and team_config_data:
        if team_config:
            update_node_configuration(
                session,
                org_id,
                team_id,
                team_config_data,
                updated_by="yaml_seeder",
                change_reason="Seeded from local.yaml",
                skip_validation=True
            )
            logger.info(f"Updated team config for {org_id}/{team_id}")
        else:
            create_node_configuration(
                session,
                org_id,
                team_id,
                team_config_data,
                created_by="yaml_seeder"
            )
            logger.info(f"Created team config for {org_id}/{team_id}")

    session.commit()
    logger.info("✅ Config seeding completed successfully")
    return True


def _ensure_organization(session: Session, org_id: str) -> None:
    """Ensure organization exists in database."""
    org = session.query(Organization).filter_by(id=org_id).first()
    if not org:
        org = Organization(
            id=org_id,
            name=org_id.title(),
            slug=org_id
        )
        session.add(org)
        session.flush()
        logger.info(f"Created organization: {org_id}")


def _ensure_team_node(session: Session, org_id: str, team_id: str) -> None:
    """Ensure team node exists in database."""
    node = session.query(Node).filter_by(org_id=org_id, id=team_id).first()
    if not node:
        # Also create root org node if it doesn't exist
        org_node = session.query(Node).filter_by(org_id=org_id, id=org_id).first()
        if not org_node:
            org_node = Node(
                org_id=org_id,
                id=org_id,
                name=org_id.title(),
                type="org",
                parent_id=None
            )
            session.add(org_node)
            session.flush()

        node = Node(
            org_id=org_id,
            id=team_id,
            name=team_id.title(),
            type="team",
            parent_id=org_id
        )
        session.add(node)
        session.flush()
        logger.info(f"Created team node: {org_id}/{team_id}")


def _extract_org_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Extract organization-level configuration from YAML.

    Org-level config typically includes:
    - Global settings
    - Default integrations available to all teams
    - Security policies
    """
    org_config = {}

    # AI model defaults (can be overridden by teams)
    if "ai_model" in config:
        org_config["ai_model"] = config["ai_model"]

    # Security policies are org-level
    if "security" in config:
        org_config["security"] = config["security"]

    return org_config


def _extract_team_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Extract team-level configuration from YAML.

    Team-level config includes:
    - Integrations (team-specific credentials)
    - Prompts (team-specific behavior)
    - Skills (team-specific capabilities)
    """
    team_config = {}

    # Integrations are team-specific
    if "integrations" in config:
        team_config["integrations"] = config["integrations"]

    # Prompts are team-specific
    if "prompts" in config:
        team_config["prompts"] = config["prompts"]

    # Skills are team-specific
    if "skills" in config:
        team_config["skills"] = config["skills"]

    # AI model override (if different from org)
    if "ai_model" in config:
        team_config["ai_model"] = config["ai_model"]

    return team_config

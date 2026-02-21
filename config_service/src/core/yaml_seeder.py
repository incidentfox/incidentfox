"""
YAML Configuration Seeder

Handles seeding the database from local.yaml on startup in local development mode.
"""

from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy import update
from sqlalchemy.orm import Session

from src.core.audit_log import app_logger
from src.core.yaml_config import get_yaml_config_manager, is_local_mode
from src.db.config_models import NodeConfiguration
from src.db.config_repository import (
    get_node_configuration,
    get_or_create_node_configuration,
    initialize_org_config,
    update_node_configuration,
)

logger = app_logger().bind(component="yaml_seeder")


def seed_from_yaml(
    session: Session, config_file_path: str = "config/local.yaml", force: bool = False
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

    # Initialize org config (creates org node if it doesn't exist)
    try:
        initialize_org_config(session, org_id, org_node_id=org_id)
    except Exception as e:
        # Org might already exist, that's OK
        logger.debug(f"Org initialization: {e}")

    # Check if config already exists
    org_config = get_node_configuration(session, org_id, org_id)
    team_config = get_node_configuration(session, org_id, team_id)

    # Only seed if force=True or configs don't exist/are empty
    should_seed_org = force or not org_config or not org_config.config_json
    should_seed_team = force or not team_config or not team_config.config_json

    if not should_seed_org and not should_seed_team:
        logger.info(
            "Configs already exist, skipping seeding (use force=True to override)"
        )
        return False

    # Prepare org-level config
    org_config_data = _extract_org_config(config)

    # Prepare team-level config
    team_config_data = _extract_team_config(config)

    # Seed org config
    if should_seed_org and org_config_data:
        if org_config:
            if force:
                # Replace config entirely — YAML is the source of truth.
                # update_node_configuration always deep-merges, which would
                # preserve deleted keys (e.g. integrations.llm after a reset).
                _replace_config_json(session, org_config, org_config_data)
                logger.info(f"Replaced org config for {org_id}")
            else:
                update_node_configuration(
                    session,
                    org_id,
                    org_id,
                    org_config_data,
                    updated_by="yaml_seeder",
                    change_reason="Seeded from local.yaml",
                    skip_validation=True,
                )
                logger.info(f"Updated org config for {org_id}")
        else:
            get_or_create_node_configuration(session, org_id, org_id, node_type="org")
            org_config = get_node_configuration(session, org_id, org_id)
            _replace_config_json(session, org_config, org_config_data)
            logger.info(f"Created org config for {org_id}")

    # Seed team config
    if should_seed_team and team_config_data:
        if team_config:
            if force:
                _replace_config_json(session, team_config, team_config_data)
                logger.info(f"Replaced team config for {org_id}/{team_id}")
            else:
                update_node_configuration(
                    session,
                    org_id,
                    team_id,
                    team_config_data,
                    updated_by="yaml_seeder",
                    change_reason="Seeded from local.yaml",
                    skip_validation=True,
                )
                logger.info(f"Updated team config for {org_id}/{team_id}")
        else:
            get_or_create_node_configuration(session, org_id, team_id, node_type="team")
            team_config = get_node_configuration(session, org_id, team_id)
            _replace_config_json(session, team_config, team_config_data)
            logger.info(f"Created team config for {org_id}/{team_id}")

    session.commit()
    logger.info("✅ Config seeding completed successfully")
    return True


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

    The YAML schema uses ai_model as the single source of truth for the active
    provider/model.  The Slack bot reads integrations.llm.model from the DB, so
    we synthesize that field here — it is never stored in the YAML itself.
    """
    team_config = {}

    # Integrations are team-specific.
    # The YAML never contains an "llm" key (that is internal to the DB).
    if "integrations" in config:
        team_config["integrations"] = dict(config["integrations"])

    # Synthesize integrations.llm.model from ai_model so the Slack bot can read
    # which provider/model is active without the user ever needing to write "llm"
    # in their YAML.
    ai_model = config.get("ai_model", {})
    if ai_model:
        provider = ai_model.get("provider", "anthropic")
        model_id = ai_model.get("model_id", "")
        if model_id:
            team_config.setdefault("integrations", {})["llm"] = {
                "model": f"{provider}/{model_id}"
            }

    # Prompts are team-specific
    if "prompts" in config:
        team_config["prompts"] = config["prompts"]

    # Skills are team-specific
    if "skills" in config:
        team_config["skills"] = config["skills"]

    # AI model override (if different from org)
    if "ai_model" in config:
        team_config["ai_model"] = config["ai_model"]

    # Routing — maps the team to incoming Slack/webhook events
    if "routing" in config:
        team_config["routing"] = config["routing"]

    return team_config


def _replace_config_json(
    session: Session, node: "NodeConfiguration", new_config: Dict[str, Any]
) -> None:
    """Directly replace a node's config_json, bypassing deep merge.

    Used by seed_from_yaml(force=True) so that the YAML file is the complete
    source of truth.  update_node_configuration always deep-merges, which
    would silently preserve keys that were removed from the YAML (e.g. an
    integrations.llm section that was deleted when the file was reset).

    Only the top-level keys present in new_config are replaced.  All other
    top-level keys in the existing config_json (e.g. "routing", workspace
    tokens, Slack identifiers) are preserved so that non-YAML-managed state
    is never wiped by a seed operation.

    Uses a raw SQL UPDATE with jsonb merge to bypass SQLAlchemy ORM mutation
    tracking, which is unreliable for JSONB columns with autoflush=False.
    """
    # Build merged config: start from existing, overlay only the YAML-managed keys.
    existing = dict(node.config_json or {})
    merged = {**existing, **new_config}

    session.execute(
        update(NodeConfiguration)
        .where(
            NodeConfiguration.org_id == node.org_id,
            NodeConfiguration.node_id == node.node_id,
        )
        .values(
            config_json=merged,
            effective_config_json=None,
            effective_config_computed_at=None,
            updated_by="yaml_seeder",
            version=(node.version or 1) + 1,
            updated_at=datetime.now(timezone.utc),
        )
    )
    # Expire the in-memory object so any subsequent reads go back to the DB
    session.expire(node)

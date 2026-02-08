from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.audit_log import audit_logger
from src.core.config_cache import ConfigCache
from src.core.config_models import TeamLevelConfig, validate_immutable_fields
from src.core.hierarchical_config import get_full_default_config
from src.core.merge import deep_merge_dicts
from src.core.metrics import CONFIG_CACHE_EVENTS_TOTAL
from src.db.config_models import NodeConfiguration
from src.db.models import TeamOutputConfig
from src.db.repository import (
    Principal,
    authenticate_bearer_token,
    get_lineage_nodes,
    get_node_configs,
    upsert_team_overrides,
)

# Sentinel value to indicate "unset this key and inherit from parent"
# When the API receives this value, the key is removed from the team config
# rather than being set, allowing inheritance from org/default to work.
INHERIT_SENTINEL = "__INHERIT__"

# Routing identifier fields (list fields in team routing config)
ROUTING_FIELDS = [
    "slack_channel_ids",
    "incidentio_team_ids",
    "incidentio_alert_source_ids",
    "pagerduty_service_ids",
    "coralogix_team_names",
    "github_repos",
    "services",
]


def process_inherit_sentinels(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively process a config dict and remove any keys with INHERIT_SENTINEL value.

    This allows clients to "unset" a value by sending {"key": "__INHERIT__"},
    which removes the key from the stored config so inheritance can work.

    Args:
        config: The config dict to process

    Returns:
        A new dict with sentinel keys removed
    """
    if not isinstance(config, dict):
        return config

    result = {}
    for key, value in config.items():
        if value == INHERIT_SENTINEL:
            # Skip this key - don't include it in result (effectively "unset")
            continue
        elif isinstance(value, dict):
            # Recursively process nested dicts
            processed = process_inherit_sentinels(value)
            # Only include non-empty dicts (if all keys were sentinels, skip the parent too)
            if processed:
                result[key] = processed
        else:
            result[key] = value

    return result


def _normalize_routing_value(field: str, value: str) -> str:
    """Normalize routing identifier value for comparison."""
    value = value.strip()
    # Lowercase for text-based identifiers
    if field in ("coralogix_team_names", "github_repos", "services"):
        value = value.lower()
    return value


def validate_routing_uniqueness(
    session: Session,
    org_id: str,
    team_node_id: str,
    routing_config: Dict[str, Any],
) -> None:
    """
    Validate that routing identifiers are not claimed by another team.

    Raises ValueError if any identifier is already used by a different team.
    """
    if not routing_config:
        return

    # Get all other teams' configs in this org
    other_configs = (
        session.execute(
            select(NodeConfiguration).where(
                NodeConfiguration.org_id == org_id,
                NodeConfiguration.node_id != team_node_id,
            )
        )
        .scalars()
        .all()
    )

    # Build lookup of existing identifiers
    existing: Dict[str, Dict[str, str]] = {}  # field -> value -> team_node_id
    for cfg in other_configs:
        if not cfg.config_json:
            continue
        other_routing = cfg.config_json.get("routing", {})
        if not other_routing:
            continue

        for field in ROUTING_FIELDS:
            values = other_routing.get(field, [])
            for v in values:
                normalized = _normalize_routing_value(field, v)
                if field not in existing:
                    existing[field] = {}
                existing[field][normalized] = cfg.node_id

    # Check for conflicts
    conflicts = []
    for field in ROUTING_FIELDS:
        new_values = routing_config.get(field, [])
        for v in new_values:
            normalized = _normalize_routing_value(field, v)
            if field in existing and normalized in existing[field]:
                conflicting_team = existing[field][normalized]
                conflicts.append(
                    f"'{field}' value '{v}' is already claimed by team '{conflicting_team}'"
                )

    if conflicts:
        raise ValueError(f"Routing identifier conflict(s): {'; '.join(conflicts)}")


@dataclass(frozen=True)
class RawConfigView:
    lineage: List[dict]
    configs: Dict[str, Dict[str, Any]]


class ConfigServiceRDS:
    def __init__(self, *, pepper: Optional[str], cache: Optional[ConfigCache] = None):
        self.pepper = pepper
        self.cache = cache

    def authenticate(self, session: Session, bearer: str) -> Principal:
        if not self.pepper:
            raise RuntimeError("TOKEN_PEPPER is required for team token authentication")
        return authenticate_bearer_token(session, bearer=bearer, pepper=self.pepper)

    def get_raw(self, session: Session, principal: Principal) -> RawConfigView:
        if self.cache is not None:
            epoch = self.cache.get_org_epoch(principal.org_id)
            key = self.cache.raw_key(principal.org_id, principal.team_node_id, epoch)
            cached = self.cache.backend.get_json(key)
            if isinstance(cached, dict) and "lineage" in cached and "configs" in cached:
                CONFIG_CACHE_EVENTS_TOTAL.labels("raw", "hit").inc()
                return RawConfigView(
                    lineage=cached["lineage"], configs=cached["configs"]
                )
            CONFIG_CACHE_EVENTS_TOTAL.labels("raw", "miss").inc()

        lineage_nodes = get_lineage_nodes(
            session, org_id=principal.org_id, node_id=principal.team_node_id
        )
        node_ids = [n.node_id for n in lineage_nodes]
        configs = get_node_configs(session, org_id=principal.org_id, node_ids=node_ids)
        lineage = [
            {
                "node_id": n.node_id,
                "node_type": n.node_type.value,
                "name": n.name,
                "parent_id": n.parent_id,
            }
            for n in lineage_nodes
        ]
        view = RawConfigView(lineage=lineage, configs=configs)
        if self.cache is not None:
            epoch = self.cache.get_org_epoch(principal.org_id)
            key = self.cache.raw_key(principal.org_id, principal.team_node_id, epoch)
            self.cache.backend.set_json(
                key,
                {"lineage": lineage, "configs": configs},
                ttl_seconds=self.cache.ttl_seconds,
            )
            CONFIG_CACHE_EVENTS_TOTAL.labels("raw", "set").inc()
        return view

    def get_effective(self, session: Session, principal: Principal) -> Dict[str, Any]:
        if self.cache is not None:
            epoch = self.cache.get_org_epoch(principal.org_id)
            key = self.cache.effective_key(
                principal.org_id, principal.team_node_id, epoch
            )
            cached = self.cache.backend.get_json(key)
            if isinstance(cached, dict):
                CONFIG_CACHE_EVENTS_TOTAL.labels("effective", "hit").inc()
                return cached
            CONFIG_CACHE_EVENTS_TOTAL.labels("effective", "miss").inc()

        # Get base defaults with DB-backed integration schemas
        base_defaults = get_full_default_config(db=session)

        raw = self.get_raw(session, principal)
        ordered_node_ids = [n["node_id"] for n in raw.lineage]
        ordered_configs = [raw.configs.get(nid, {}) for nid in ordered_node_ids]

        # Merge: base defaults -> org -> team -> sub-team
        all_configs = [base_defaults] + ordered_configs
        eff = deep_merge_dicts(all_configs)

        # Add team output config (Delivery & Notifications)
        output_config = (
            session.query(TeamOutputConfig)
            .filter(
                TeamOutputConfig.org_id == principal.org_id,
                TeamOutputConfig.team_node_id == principal.team_node_id,
            )
            .first()
        )

        if output_config:
            eff["output_config"] = {
                "default_destinations": output_config.default_destinations or [],
                "trigger_overrides": output_config.trigger_overrides or {},
            }

        # Add tools catalog and prepare clean UI structure
        # Pass raw configs so we can determine which values come from which level
        eff = self._add_tools_catalog_and_clean_structure(
            eff, session, raw_configs=raw.configs, team_node_id=principal.team_node_id
        )

        if self.cache is not None:
            epoch = self.cache.get_org_epoch(principal.org_id)
            key = self.cache.effective_key(
                principal.org_id, principal.team_node_id, epoch
            )
            self.cache.backend.set_json(key, eff, ttl_seconds=self.cache.ttl_seconds)
            CONFIG_CACHE_EVENTS_TOTAL.labels("effective", "set").inc()
        return eff

    def _add_tools_catalog_and_clean_structure(
        self,
        config: Dict[str, Any],
        session: Session,
        raw_configs: Optional[Dict[str, Dict[str, Any]]] = None,
        team_node_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Add built-in tools catalog to config and transform integrations structure.

        Returns config with:
        - integrations: {...}  (transformed to have config_schema + config_values + config_sources)
        - mcp_servers: {...}   (dict format, already present from DB)
        - built_in_tools: [...] (from catalog)
        - tools: {...}         (team-level tool overrides in dict format)

        Note: Uses canonical config format with dict-based tools and mcp_servers.

        Args:
            config: The effective config to transform
            session: Database session
            raw_configs: Optional dict of node_id -> raw config, for source tracking
            team_node_id: Optional team node ID, for source tracking
        """
        from ..core.skills_catalog import get_skills_catalog
        from ..core.tools_catalog import get_tools_catalog
        from ..db.config_models import IntegrationSchema

        # Add built-in tools catalog
        catalog = get_tools_catalog()
        config["built_in_tools"] = catalog["tools"]

        # Add built-in skills catalog
        skills_catalog = get_skills_catalog()
        config["built_in_skills"] = skills_catalog["skills"]

        # Get team's raw integrations for source tracking
        team_raw_integrations: Dict[str, Any] = {}
        if raw_configs and team_node_id:
            team_raw_config = raw_configs.get(team_node_id, {})
            team_raw_integrations = team_raw_config.get("integrations", {})

        # Transform integrations to have config_schema + config_values structure
        # Frontend expects: {integration_id: {config_schema: {...}, config_values: {...}}}
        # Currently we have: {integration_id: {api_key: "value", region: "value", ...}}
        integrations = config.get("integrations", {})
        if integrations:
            # Get all integration schemas
            schemas = session.query(IntegrationSchema).all()
            schema_map = {schema.id: schema for schema in schemas}

            transformed_integrations = {}
            for integration_id, integration_config in integrations.items():
                if not isinstance(integration_config, dict):
                    continue

                schema = schema_map.get(integration_id)
                if not schema:
                    # Unknown integration, skip
                    continue

                # Build config_schema from schema fields
                config_schema = {}
                for field in schema.fields:
                    config_schema[field["name"]] = {
                        "type": field.get("type", "string"),
                        "required": field.get("required", False),
                        "display_name": field.get("display_name", field["name"]),
                        "description": field.get("description", ""),
                        "placeholder": field.get("placeholder", ""),
                    }

                # Build config_values from actual integration config (only include schema-defined fields)
                config_values = {}
                for field in schema.fields:
                    field_name = field["name"]
                    if field_name in integration_config:
                        config_values[field_name] = integration_config[field_name]

                # Build config_sources: determine if each field value is from team or inherited
                # "team" = explicitly set at team level (can be cleared)
                # "inherited" = inherited from org or defaults (no clear option)
                config_sources = {}
                team_raw_integration = team_raw_integrations.get(integration_id, {})
                for field in schema.fields:
                    field_name = field["name"]
                    if field_name in config_values:
                        # Check if this field is explicitly set in team's raw config
                        if (
                            isinstance(team_raw_integration, dict)
                            and field_name in team_raw_integration
                        ):
                            config_sources[field_name] = "team"
                        else:
                            config_sources[field_name] = "inherited"

                transformed_integrations[integration_id] = {
                    "name": schema.name,
                    "config_schema": config_schema,
                    "config_values": config_values,
                    "config_sources": config_sources,
                }

            config["integrations"] = transformed_integrations

        # Ensure canonical format fields exist with correct defaults
        config.setdefault("mcp_servers", {})  # Dict format in canonical schema
        config.setdefault("tools", {})  # Team-level tool overrides

        # SAFETY: Transform any malformed tools field from Dict[str, dict] to Dict[str, bool]
        # This handles cases where old default configs polluted the tools field with metadata objects
        tools_field = config.get("tools", {})
        if isinstance(tools_field, dict):
            cleaned_tools = {}
            for tool_id, value in tools_field.items():
                if isinstance(value, dict) and "enabled" in value:
                    # Extract bool from metadata object
                    cleaned_tools[tool_id] = value["enabled"]
                elif isinstance(value, bool):
                    # Already correct format
                    cleaned_tools[tool_id] = value
                # Skip any other malformed entries
            config["tools"] = cleaned_tools

        return config

    def put_team_overrides(
        self,
        session: Session,
        principal: Principal,
        overrides: Dict[str, Any],
        updated_by: Optional[str],
    ) -> Dict[str, Any]:
        # validate shape (partial OK)
        update_cfg = TeamLevelConfig(**overrides)
        # immutables cannot be set at all
        validate_immutable_fields(TeamLevelConfig(), update_cfg)

        # PATCH semantics: merge into existing team overrides
        existing_row = session.execute(
            select(NodeConfiguration).where(
                NodeConfiguration.org_id == principal.org_id,
                NodeConfiguration.node_id == principal.team_node_id,
            )
        ).scalar_one_or_none()
        before = (
            existing_row.config_json
            if existing_row is not None and existing_row.config_json is not None
            else {}
        )
        # Avoid in-place mutation of ORM-backed dicts; always merge from a deep copy.
        merged = deep_merge_dicts([copy.deepcopy(before), overrides])

        # Process INHERIT_SENTINEL values: remove keys marked for inheritance
        # This allows clients to "unset" a team-level override and inherit from org
        merged = process_inherit_sentinels(merged)

        # Validate routing identifier uniqueness
        if "routing" in merged:
            validate_routing_uniqueness(
                session,
                org_id=principal.org_id,
                team_node_id=principal.team_node_id,
                routing_config=merged["routing"],
            )

        updated = upsert_team_overrides(
            session,
            org_id=principal.org_id,
            team_node_id=principal.team_node_id,
            overrides=merged,
            updated_by=updated_by,
        )

        audit_logger().info(
            "config_updated",
            audit=True,
            org_id=principal.org_id,
            team_node_id=principal.team_node_id,
            updated_by=updated_by,
        )
        return updated

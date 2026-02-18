"""
YAML configuration manager for local development mode.

Provides bidirectional sync between YAML config files and the database:
- Load YAML → Database (on startup and file changes)
- Database changes → YAML (when config is updated via UI/API)

Uses ruamel.yaml to preserve comments and formatting.
"""

import fcntl
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from src.core.audit_log import app_logger
from src.core.env_manager import get_env_manager

# ---------------------------------------------------------------------------
# Write-back suppression
# ---------------------------------------------------------------------------
# When the system writes YAML (write-back from a DB change), the file watcher
# must NOT re-seed the DB from that write — that would undo the change.
# We record the timestamp of every system write so the watcher can skip events
# that it caused itself.
_last_write_back_time: float = 0.0
_WRITE_BACK_SUPPRESS_SECONDS: float = 3.0  # generous window for fs event delivery


def _mark_write_back() -> None:
    global _last_write_back_time
    _last_write_back_time = time.monotonic()


def is_write_back_suppressed() -> bool:
    """Return True if the watcher should ignore the current file-change event."""
    return (time.monotonic() - _last_write_back_time) < _WRITE_BACK_SUPPRESS_SECONDS


class YAMLConfigManager:
    """Manages YAML configuration file operations."""

    def __init__(self, config_file_path: str = "config/local.yaml"):
        """Initialize the YAML config manager.

        Args:
            config_file_path: Path to the YAML config file
        """
        self.config_file_path = Path(config_file_path)
        self.yaml = YAML()
        self.yaml.preserve_quotes = True
        self.yaml.default_flow_style = False
        self.yaml.width = 4096  # Prevent line wrapping
        self.logger = app_logger().bind(component="yaml_config")

    def load_config(self) -> Dict[str, Any]:
        """Load and parse the YAML config file.

        Environment variables (${VAR}) are resolved using EnvManager.

        Returns:
            Configuration dictionary with resolved env vars

        Raises:
            FileNotFoundError: If config file doesn't exist
        """
        if not self.config_file_path.exists():
            self.logger.warning(f"Config file not found: {self.config_file_path}")
            return {}

        with open(self.config_file_path, "r") as f:
            config = self.yaml.load(f)

        if config is None:
            return {}

        # Resolve environment variable references
        env_manager = get_env_manager()
        resolved_config = env_manager.resolve_env_references(dict(config))

        self.logger.info(f"Loaded config from {self.config_file_path}")
        return resolved_config

    def write_config(
        self, config: Dict[str, Any], preserve_formatting: bool = True
    ) -> None:
        """Write configuration back to YAML file.

        This operation is atomic using temp file + rename.

        Args:
            config: Configuration dictionary to write
            preserve_formatting: If True, try to preserve existing formatting and comments
        """
        if preserve_formatting and self.config_file_path.exists():
            # Load existing YAML to preserve structure
            with open(self.config_file_path, "r") as f:
                existing = self.yaml.load(f)
            if existing is None:
                existing = CommentedMap()

            # Merge new config into existing, preserving comments
            merged = self._merge_preserving_structure(existing, config)
            data_to_write = merged
        else:
            data_to_write = config

        # Ensure parent directory exists
        self.config_file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write atomically: dump to temp file, validate, then rename.
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=self.config_file_path.parent,
            delete=False,
            prefix=".yaml.tmp.",
        ) as tmp_file:
            tmp_path = Path(tmp_file.name)
            try:
                self.yaml.dump(data_to_write, tmp_file)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())

                # Integrity check: re-parse the temp file and verify top-level
                # keys are still sane (catches ruamel.yaml comment-position bugs
                # before they overwrite the live file).
                with open(tmp_path, "r") as verify_f:
                    verified = self.yaml.load(verify_f)
                if verified is None:
                    raise ValueError("Written YAML parsed as empty")
                expected_top_level = {
                    "org_id",
                    "team_id",
                    "ai_model",
                    "integrations",
                    "prompts",
                    "skills",
                    "security",
                    "routing",
                }
                written_keys = set(verified.keys())
                stray_keys = written_keys - expected_top_level
                if stray_keys:
                    raise ValueError(
                        f"Write-back produced unexpected top-level keys: {stray_keys}. "
                        "This is likely a ruamel.yaml comment-positioning bug."
                    )

                # Atomic rename
                tmp_path.replace(self.config_file_path)
                # Suppress the file watcher so it doesn't re-seed from this
                # write-back and undo the DB change that triggered it.
                _mark_write_back()
                self.logger.info(f"Wrote config to {self.config_file_path}")
            except Exception as e:
                # Clean up temp file on error
                if tmp_path.exists():
                    tmp_path.unlink()
                self.logger.error(f"Failed to write config: {e}")
                raise

    def update_integration_config(
        self,
        integration_name: str,
        integration_config: Dict[str, Any],
        write_secrets_to_env: bool = True,
    ) -> None:
        """Update a specific integration's configuration.

        Args:
            integration_name: Name of the integration (e.g., "coralogix")
            integration_config: Integration configuration dict
            write_secrets_to_env: If True, write secret fields to .env and use references in YAML
        """
        # Load current config
        if self.config_file_path.exists():
            with open(self.config_file_path, "r") as f:
                config = self.yaml.load(f)
            if config is None:
                config = CommentedMap()
        else:
            config = CommentedMap()

        # Ensure integrations section exists
        if "integrations" not in config:
            config["integrations"] = CommentedMap()

        # Handle secrets
        env_manager = get_env_manager()
        yaml_config = {}

        for key, value in integration_config.items():
            if write_secrets_to_env and self._is_secret_field(key):
                # Write secret to .env
                env_var_name = f"{integration_name.upper()}_{key.upper()}"
                env_manager.write_env_variable(
                    env_var_name, value, comment=f"{integration_name} {key}"
                )
                # Use reference in YAML
                yaml_config[key] = f"${{{env_var_name}}}"
                self.logger.info(f"Wrote secret {env_var_name} to .env")
            else:
                # Non-secret field, write directly
                yaml_config[key] = value

        # Update integration config
        config["integrations"][integration_name] = yaml_config

        # Write back to file.
        # Pass the CommentedMap directly (preserve_formatting=False skips the
        # double-load+merge that corrupts comment positions).  Comments are
        # embedded in the CommentedMap itself so ruamel.yaml preserves them.
        self.write_config(config, preserve_formatting=False)
        self.logger.info(f"Updated integration config for {integration_name}")

    def _merge_preserving_structure(self, existing: Any, new: Dict[str, Any]) -> Any:
        """Merge new config into existing, preserving structure and comments.

        Args:
            existing: Existing YAML structure (may be CommentedMap)
            new: New configuration dictionary

        Returns:
            Merged structure
        """
        if not isinstance(existing, dict):
            existing = CommentedMap()

        for key, value in new.items():
            if (
                isinstance(value, dict)
                and key in existing
                and isinstance(existing[key], dict)
            ):
                # Recursively merge dictionaries
                existing[key] = self._merge_preserving_structure(existing[key], value)
            else:
                # Replace value
                existing[key] = value

        return existing

    def _is_secret_field(self, field_name: str) -> bool:
        """Check if a field name indicates it contains a secret.

        Args:
            field_name: Field name to check

        Returns:
            True if field is likely a secret
        """
        secret_keywords = [
            "api_key",
            "apikey",
            "api_token",
            "token",
            "secret",
            "password",
            "credentials",
            "auth",
            "access_key",
            "private_key",
            "client_secret",
            "webhook_secret",
            "signing_secret",
        ]
        field_lower = field_name.lower()
        return any(keyword in field_lower for keyword in secret_keywords)


# Global instance
_yaml_config_manager: Optional[YAMLConfigManager] = None


def get_yaml_config_manager(
    config_file_path: str = "config/local.yaml",
) -> YAMLConfigManager:
    """Get or create the global YAMLConfigManager instance."""
    global _yaml_config_manager
    if _yaml_config_manager is None or _yaml_config_manager.config_file_path != Path(
        config_file_path
    ):
        _yaml_config_manager = YAMLConfigManager(config_file_path)
    return _yaml_config_manager


def is_local_mode() -> bool:
    """Check if running in local development mode.

    Returns:
        True if CONFIG_MODE=local
    """
    return os.getenv("CONFIG_MODE", "").lower() == "local"


def write_config_to_yaml(
    org_id: str,
    node_id: str,
    node_type: str,
    config_json: Dict[str, Any],
    config_file_path: str = "config/local.yaml",
) -> bool:
    """Write config changes back to YAML file in local mode.

    This function is called after config updates to persist changes back to the
    YAML file. Secrets are extracted to .env and referenced via ${VAR} in YAML.

    Args:
        org_id: Organization ID
        node_id: Node ID
        node_type: Node type ("org" or "team")
        config_json: Full configuration JSON from database
        config_file_path: Path to YAML config file

    Returns:
        True if write-back was performed, False if skipped
    """
    if not is_local_mode():
        return False

    if org_id != "local":
        # Only write back for the local org in local mode
        return False

    try:
        yaml_manager = get_yaml_config_manager(config_file_path)
        env_manager = get_env_manager()

        # Load current YAML
        if yaml_manager.config_file_path.exists():
            with open(yaml_manager.config_file_path, "r") as f:
                yaml_config = yaml_manager.yaml.load(f)
            if yaml_config is None:
                yaml_config = CommentedMap()
        else:
            yaml_config = CommentedMap()

        # Ensure org_id and team_id are set
        if "org_id" not in yaml_config:
            yaml_config["org_id"] = "local"
        if "team_id" not in yaml_config:
            yaml_config["team_id"] = "default"

        # Write back the changed sections
        # For org-level: ai_model, security
        # For team-level: integrations, prompts, skills

        if node_type == "org":
            # Write org-level config
            if "ai_model" in config_json:
                yaml_config["ai_model"] = config_json["ai_model"]
            if "security" in config_json:
                yaml_config["security"] = config_json["security"]

        elif node_type == "team":
            # Write team-level config.
            #
            # YAML schema contract:
            #   ai_model:         ← single source of truth for active provider + model
            #   integrations:     ← provider credentials and other tool configs
            #                       Does NOT contain an "llm" key; that is an internal
            #                       DB field used by the Slack bot and is hidden from YAML.

            # Handle integrations — skip the internal "llm" key, extract secrets to .env
            if "integrations" in config_json:
                if "integrations" not in yaml_config:
                    yaml_config["integrations"] = CommentedMap()

                for int_name, int_config in config_json["integrations"].items():
                    if int_name == "llm":
                        # "llm" is an internal DB field — convert to ai_model instead (below)
                        continue

                    yaml_int_delta: Dict[str, Any] = {}
                    for key, value in (int_config or {}).items():
                        if yaml_manager._is_secret_field(key):
                            env_var_name = f"{int_name.upper()}_{key.upper()}"
                            env_manager.write_env_variable(
                                env_var_name, value, comment=f"{int_name} {key}"
                            )
                            yaml_int_delta[key] = f"${{{env_var_name}}}"
                        else:
                            yaml_int_delta[key] = value

                    if int_name in yaml_config["integrations"]:
                        # Update in-place so inline comments (e.g. "# us1, us2, eu1…")
                        # and end-of-block comment sections are preserved.
                        yaml_manager._merge_preserving_structure(
                            yaml_config["integrations"][int_name], yaml_int_delta
                        )
                    else:
                        yaml_config["integrations"][int_name] = yaml_int_delta

                # Remove any stale "llm" key that may have been written by older code
                if "llm" in yaml_config.get("integrations", {}):
                    del yaml_config["integrations"]["llm"]

                # Convert integrations.llm.model → ai_model (highest priority — overrides
                # whatever ai_model was already in the YAML or config_json)
                llm = config_json["integrations"].get("llm") or {}
                model_string = llm.get("model", "")
                if model_string:
                    if "/" in model_string:
                        provider, model_id = model_string.split("/", 1)
                    else:
                        provider = (
                            "anthropic"
                            if "claude" in model_string.lower()
                            else "unknown"
                        )
                        model_id = model_string

                    if "ai_model" not in yaml_config:
                        yaml_config["ai_model"] = CommentedMap()
                    yaml_config["ai_model"]["provider"] = provider
                    yaml_config["ai_model"]["model_id"] = model_id

            # Handle prompts
            if "prompts" in config_json:
                yaml_config["prompts"] = config_json["prompts"]

            # Handle skills
            if "skills" in config_json:
                yaml_config["skills"] = config_json["skills"]

        # Write back to file (atomic operation).
        # Pass the CommentedMap directly — preserve_formatting=False avoids a
        # second load+merge that would corrupt comment positions in the file.
        yaml_manager.write_config(yaml_config, preserve_formatting=False)

        logger = app_logger().bind(component="yaml_writeback")
        logger.info(
            f"✅ Wrote config back to {config_file_path}",
            org_id=org_id,
            node_id=node_id,
            node_type=node_type,
        )
        return True

    except Exception as e:
        logger = app_logger().bind(component="yaml_writeback")
        logger.error(f"Failed to write config back to YAML: {e}", exc_info=True)
        return False

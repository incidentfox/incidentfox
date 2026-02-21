"""
YAML configuration validator for local development mode.

Validates the structure and values of local.yaml before it is seeded into
the database.  Two severity levels:

  errors   — block the change (watcher will not apply an invalid file)
  warnings — non-blocking, logged so the user knows something looks off
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

# ── known-good provider ids ────────────────────────────────────────────────────
KNOWN_PROVIDERS = {"anthropic", "openai", "ollama", "openrouter", "azure", "bedrock"}

# matches any still-unresolved ${VAR} reference
_ENV_REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


# ── result container ───────────────────────────────────────────────────────────


@dataclass
class ValidationResult:
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def format(self) -> str:
        lines = []
        for e in self.errors:
            lines.append(f"  ❌ {e}")
        for w in self.warnings:
            lines.append(f"  ⚠️  {w}")
        return "\n".join(lines)


# ── pydantic schema ────────────────────────────────────────────────────────────


class _AIModelSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model_id: str
    base_url: Optional[str] = None

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        # Skip validation for unresolved env references
        if _ENV_REF_RE.search(v):
            return v
        if v not in KNOWN_PROVIDERS:
            raise ValueError(
                f"'{v}' is not a known provider. "
                f"Must be one of: {', '.join(sorted(KNOWN_PROVIDERS))}"
            )
        return v


class _SecuritySchema(BaseModel):
    # Security block is flexible — allow arbitrary keys
    model_config = ConfigDict(extra="allow")

    allowed_actions: Optional[List[str]] = None
    require_approval_for: Optional[List[str]] = None


class _LocalYAMLSchema(BaseModel):
    # extra="forbid" so typos in top-level keys become errors
    model_config = ConfigDict(extra="forbid")

    org_id: str = "local"
    team_id: str = "default"
    ai_model: Optional[_AIModelSchema] = None
    integrations: Optional[Dict[str, Any]] = None
    prompts: Optional[Dict[str, Any]] = None
    skills: Optional[Any] = None
    security: Optional[_SecuritySchema] = None
    routing: Optional[Dict[str, Any]] = None


# ── internal helpers ───────────────────────────────────────────────────────────


def _find_unresolved_refs(value: Any, path: str = "") -> List[str]:
    """Recursively find unresolved ${VAR} references in a resolved config."""
    found: List[str] = []
    if isinstance(value, str):
        for m in _ENV_REF_RE.finditer(value):
            found.append(f"{path}: ${{{m.group(1)}}} is not set in .env")
    elif isinstance(value, dict):
        for k, v in value.items():
            child = f"{path}.{k}" if path else k
            found.extend(_find_unresolved_refs(v, child))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            found.extend(_find_unresolved_refs(item, f"{path}[{i}]"))
    return found


def _validate_integrations(integrations: Dict[str, Any]) -> List[str]:
    """Each integration entry must be a mapping (or null)."""
    errors: List[str] = []
    for name, cfg in integrations.items():
        if cfg is not None and not isinstance(cfg, dict):
            errors.append(
                f"integrations.{name}: expected a mapping, got {type(cfg).__name__}"
            )
    return errors


# ── public API ─────────────────────────────────────────────────────────────────


def validate_yaml_config(resolved_config: Dict[str, Any]) -> ValidationResult:
    """Validate a resolved YAML config (env refs already substituted).

    Args:
        resolved_config: Config dict returned by YAMLConfigManager.load_config().

    Returns:
        ValidationResult.  Check .is_valid and inspect .errors / .warnings.
    """
    result = ValidationResult()

    # 1. Warn on any still-unresolved ${VAR} references
    for msg in _find_unresolved_refs(resolved_config):
        result.warnings.append(f"Unresolved env reference — {msg}")

    # 2. Structural / value validation via Pydantic
    try:
        _LocalYAMLSchema.model_validate(resolved_config)
    except ValidationError as exc:
        for err in exc.errors():
            loc = " → ".join(str(x) for x in err["loc"]) if err["loc"] else "config"
            result.errors.append(f"{loc}: {err['msg']}")

    # 3. Integration entries must be dicts
    integrations = resolved_config.get("integrations")
    if isinstance(integrations, dict):
        result.errors.extend(_validate_integrations(integrations))
    elif integrations is not None:
        result.errors.append(
            f"integrations: expected a mapping, got {type(integrations).__name__}"
        )

    return result

"""Schema Registry tools for Avro/JSON schema management.

Supports:
- Confluent Schema Registry
- AWS Glue Schema Registry
- Azure Schema Registry
- Any Schema Registry with compatible REST API
"""

import json
import os
from typing import Any

import httpx

from ..core.config_required import handle_integration_not_configured
from ..core.errors import ToolExecutionError
from ..core.execution_context import get_execution_context
from ..core.integration_errors import IntegrationNotConfiguredError
from ..core.logging import get_logger

logger = get_logger(__name__)


def _get_schema_registry_config() -> dict:
    """Get Schema Registry configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("schema_registry")
        if config and config.get("url"):
            return config

    # 2. Try environment variables (dev/testing fallback)
    if os.getenv("SCHEMA_REGISTRY_URL"):
        return {
            "url": os.getenv("SCHEMA_REGISTRY_URL"),
            "username": os.getenv("SCHEMA_REGISTRY_USERNAME"),
            "password": os.getenv("SCHEMA_REGISTRY_PASSWORD"),
            "ssl_verify": os.getenv("SCHEMA_REGISTRY_SSL_VERIFY", "true").lower()
            == "true",
        }

    # 3. Not configured - raise error
    raise IntegrationNotConfiguredError(
        integration_id="schema_registry",
        tool_id="schema_registry_tools",
        missing_fields=["url"],
    )


def _get_client() -> httpx.Client:
    """Get HTTP client for Schema Registry API."""
    config = _get_schema_registry_config()

    # Build auth if provided
    auth = None
    if config.get("username") and config.get("password"):
        auth = (config["username"], config["password"])

    return httpx.Client(
        base_url=config["url"].rstrip("/"),
        auth=auth,
        verify=config.get("ssl_verify", True),
        timeout=30.0,
        headers={
            "Content-Type": "application/vnd.schemaregistry.v1+json",
            "Accept": "application/vnd.schemaregistry.v1+json",
        },
    )


def schema_registry_list_subjects() -> dict[str, Any]:
    """
    List all subjects (schemas) in the Schema Registry.

    Returns:
        Dict with list of subject names
    """
    try:
        client = _get_client()

        response = client.get("/subjects")
        response.raise_for_status()

        subjects = response.json()
        client.close()

        logger.info("schema_registry_subjects_listed", count=len(subjects))

        return {
            "subject_count": len(subjects),
            "subjects": sorted(subjects),
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "schema_registry_list_subjects", "schema_registry"
        )
    except httpx.HTTPStatusError as e:
        logger.error(
            "schema_registry_list_subjects_failed", status=e.response.status_code
        )
        raise ToolExecutionError(
            "schema_registry_list_subjects",
            f"HTTP {e.response.status_code}: {e.response.text}",
        )
    except Exception as e:
        logger.error("schema_registry_list_subjects_failed", error=str(e))
        raise ToolExecutionError("schema_registry_list_subjects", str(e), e)


def schema_registry_get_schema(
    subject: str, version: str | int = "latest"
) -> dict[str, Any]:
    """
    Get a schema by subject and version.

    Args:
        subject: Subject name (usually topic-key or topic-value)
        version: Schema version (number or 'latest')

    Returns:
        Dict with schema details
    """
    try:
        client = _get_client()

        response = client.get(f"/subjects/{subject}/versions/{version}")
        response.raise_for_status()

        data = response.json()

        # Parse the schema string to JSON for readability
        schema_str = data.get("schema", "{}")
        try:
            schema_parsed = json.loads(schema_str)
        except json.JSONDecodeError:
            schema_parsed = schema_str

        client.close()

        logger.info(
            "schema_registry_schema_retrieved",
            subject=subject,
            version=version,
        )

        return {
            "subject": data.get("subject"),
            "version": data.get("version"),
            "id": data.get("id"),
            "schema_type": data.get("schemaType", "AVRO"),
            "schema": schema_parsed,
            "schema_raw": schema_str,
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "schema_registry_get_schema", "schema_registry"
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {
                "success": False,
                "error": f"Subject '{subject}' version '{version}' not found",
            }
        logger.error(
            "schema_registry_get_schema_failed",
            subject=subject,
            status=e.response.status_code,
        )
        raise ToolExecutionError(
            "schema_registry_get_schema",
            f"HTTP {e.response.status_code}: {e.response.text}",
        )
    except Exception as e:
        logger.error("schema_registry_get_schema_failed", error=str(e), subject=subject)
        raise ToolExecutionError("schema_registry_get_schema", str(e), e)


def schema_registry_get_versions(subject: str) -> dict[str, Any]:
    """
    Get all versions for a subject.

    Args:
        subject: Subject name

    Returns:
        Dict with list of versions
    """
    try:
        client = _get_client()

        response = client.get(f"/subjects/{subject}/versions")
        response.raise_for_status()

        versions = response.json()
        client.close()

        logger.info(
            "schema_registry_versions_retrieved",
            subject=subject,
            count=len(versions),
        )

        return {
            "subject": subject,
            "version_count": len(versions),
            "versions": versions,
            "latest": max(versions) if versions else None,
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "schema_registry_get_versions", "schema_registry"
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {
                "success": False,
                "error": f"Subject '{subject}' not found",
            }
        raise ToolExecutionError(
            "schema_registry_get_versions",
            f"HTTP {e.response.status_code}: {e.response.text}",
        )
    except Exception as e:
        logger.error(
            "schema_registry_get_versions_failed", error=str(e), subject=subject
        )
        raise ToolExecutionError("schema_registry_get_versions", str(e), e)


def schema_registry_check_compatibility(
    subject: str,
    schema: dict | str,
    schema_type: str = "AVRO",
    version: str | int = "latest",
) -> dict[str, Any]:
    """
    Check if a schema is compatible with the registered schema.

    This is the critical check before deploying schema changes!

    Args:
        subject: Subject name
        schema: New schema to check (dict or JSON string)
        schema_type: Schema type (AVRO, JSON, PROTOBUF)
        version: Version to check against ('latest' or specific version)

    Returns:
        Dict with compatibility result
    """
    try:
        client = _get_client()

        # Prepare schema
        if isinstance(schema, dict):
            schema_str = json.dumps(schema)
        else:
            schema_str = schema

        payload = {
            "schema": schema_str,
            "schemaType": schema_type.upper(),
        }

        response = client.post(
            f"/compatibility/subjects/{subject}/versions/{version}",
            json=payload,
        )
        response.raise_for_status()

        data = response.json()
        client.close()

        is_compatible = data.get("is_compatible", False)

        logger.info(
            "schema_registry_compatibility_checked",
            subject=subject,
            compatible=is_compatible,
        )

        return {
            "subject": subject,
            "version_checked": version,
            "is_compatible": is_compatible,
            "messages": data.get("messages", []),
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "schema_registry_check_compatibility", "schema_registry"
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {
                "success": True,
                "is_compatible": True,
                "message": f"Subject '{subject}' not found - new subject, always compatible",
            }
        # 422 means incompatible
        if e.response.status_code == 422:
            try:
                error_data = e.response.json()
                return {
                    "success": True,
                    "is_compatible": False,
                    "error_code": error_data.get("error_code"),
                    "message": error_data.get("message", "Schema is incompatible"),
                }
            except Exception:
                return {
                    "success": True,
                    "is_compatible": False,
                    "message": "Schema is incompatible",
                }
        raise ToolExecutionError(
            "schema_registry_check_compatibility",
            f"HTTP {e.response.status_code}: {e.response.text}",
        )
    except Exception as e:
        logger.error(
            "schema_registry_check_compatibility_failed", error=str(e), subject=subject
        )
        raise ToolExecutionError("schema_registry_check_compatibility", str(e), e)


def schema_registry_register_schema(
    subject: str,
    schema: dict | str,
    schema_type: str = "AVRO",
    normalize: bool = False,
) -> dict[str, Any]:
    """
    Register a new schema version for a subject.

    WARNING: This modifies the Schema Registry. Use check_compatibility first!

    Args:
        subject: Subject name (usually topic-key or topic-value)
        schema: Schema to register (dict or JSON string)
        schema_type: Schema type (AVRO, JSON, PROTOBUF)
        normalize: Normalize schema before registering

    Returns:
        Dict with registration result
    """
    try:
        client = _get_client()

        # Prepare schema
        if isinstance(schema, dict):
            schema_str = json.dumps(schema)
        else:
            schema_str = schema

        payload = {
            "schema": schema_str,
            "schemaType": schema_type.upper(),
        }

        params = {}
        if normalize:
            params["normalize"] = "true"

        response = client.post(
            f"/subjects/{subject}/versions",
            json=payload,
            params=params,
        )
        response.raise_for_status()

        data = response.json()
        client.close()

        schema_id = data.get("id")

        logger.info(
            "schema_registry_schema_registered",
            subject=subject,
            schema_id=schema_id,
        )

        return {
            "subject": subject,
            "schema_id": schema_id,
            "schema_type": schema_type,
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "schema_registry_register_schema", "schema_registry"
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 409:
            # Schema already exists with same content
            try:
                error_data = e.response.json()
                return {
                    "success": True,
                    "schema_id": error_data.get("id"),
                    "message": "Schema already exists with same content",
                    "already_registered": True,
                }
            except Exception:
                pass
        raise ToolExecutionError(
            "schema_registry_register_schema",
            f"HTTP {e.response.status_code}: {e.response.text}",
        )
    except Exception as e:
        logger.error(
            "schema_registry_register_schema_failed", error=str(e), subject=subject
        )
        raise ToolExecutionError("schema_registry_register_schema", str(e), e)


def schema_registry_get_compatibility_level(
    subject: str | None = None,
) -> dict[str, Any]:
    """
    Get the compatibility level for a subject or global default.

    Compatibility levels:
    - BACKWARD: New schema can read old data
    - FORWARD: Old schema can read new data
    - FULL: Both backward and forward
    - NONE: No compatibility checking

    Args:
        subject: Subject name (None for global config)

    Returns:
        Dict with compatibility level
    """
    try:
        client = _get_client()

        if subject:
            url = f"/config/{subject}"
        else:
            url = "/config"

        response = client.get(url)
        response.raise_for_status()

        data = response.json()
        client.close()

        compatibility = data.get("compatibilityLevel", "BACKWARD")

        logger.info(
            "schema_registry_compatibility_level_retrieved",
            subject=subject or "global",
            level=compatibility,
        )

        return {
            "subject": subject,
            "is_global": subject is None,
            "compatibility_level": compatibility,
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "schema_registry_get_compatibility_level", "schema_registry"
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            # Subject doesn't have custom config, uses global
            return {
                "subject": subject,
                "is_global": True,
                "compatibility_level": "BACKWARD",
                "message": "Using global default",
                "success": True,
            }
        raise ToolExecutionError(
            "schema_registry_get_compatibility_level",
            f"HTTP {e.response.status_code}: {e.response.text}",
        )
    except Exception as e:
        logger.error(
            "schema_registry_get_compatibility_level_failed",
            error=str(e),
            subject=subject,
        )
        raise ToolExecutionError("schema_registry_get_compatibility_level", str(e), e)


def schema_registry_set_compatibility_level(
    compatibility_level: str, subject: str | None = None
) -> dict[str, Any]:
    """
    Set the compatibility level for a subject or global default.

    WARNING: Changing compatibility levels can affect all producers/consumers!

    Args:
        compatibility_level: One of BACKWARD, FORWARD, FULL, NONE
        subject: Subject name (None for global config)

    Returns:
        Dict with result
    """
    valid_levels = [
        "BACKWARD",
        "BACKWARD_TRANSITIVE",
        "FORWARD",
        "FORWARD_TRANSITIVE",
        "FULL",
        "FULL_TRANSITIVE",
        "NONE",
    ]

    if compatibility_level.upper() not in valid_levels:
        return {
            "success": False,
            "error": f"Invalid compatibility level. Must be one of: {valid_levels}",
        }

    try:
        client = _get_client()

        if subject:
            url = f"/config/{subject}"
        else:
            url = "/config"

        payload = {"compatibility": compatibility_level.upper()}

        response = client.put(url, json=payload)
        response.raise_for_status()

        data = response.json()
        client.close()

        logger.info(
            "schema_registry_compatibility_level_set",
            subject=subject or "global",
            level=compatibility_level,
        )

        return {
            "subject": subject,
            "is_global": subject is None,
            "compatibility_level": data.get("compatibility", compatibility_level),
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "schema_registry_set_compatibility_level", "schema_registry"
        )
    except httpx.HTTPStatusError as e:
        raise ToolExecutionError(
            "schema_registry_set_compatibility_level",
            f"HTTP {e.response.status_code}: {e.response.text}",
        )
    except Exception as e:
        logger.error(
            "schema_registry_set_compatibility_level_failed",
            error=str(e),
            subject=subject,
        )
        raise ToolExecutionError("schema_registry_set_compatibility_level", str(e), e)


def schema_registry_delete_subject(
    subject: str, permanent: bool = False
) -> dict[str, Any]:
    """
    Delete a subject from the Schema Registry.

    WARNING: This is a destructive operation!

    Args:
        subject: Subject name
        permanent: If True, permanently delete (hard delete)

    Returns:
        Dict with deleted versions
    """
    try:
        client = _get_client()

        params = {}
        if permanent:
            params["permanent"] = "true"

        response = client.delete(f"/subjects/{subject}", params=params)
        response.raise_for_status()

        deleted_versions = response.json()
        client.close()

        logger.info(
            "schema_registry_subject_deleted",
            subject=subject,
            permanent=permanent,
            versions=deleted_versions,
        )

        return {
            "subject": subject,
            "deleted_versions": deleted_versions,
            "permanent": permanent,
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "schema_registry_delete_subject", "schema_registry"
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {
                "success": False,
                "error": f"Subject '{subject}' not found",
            }
        raise ToolExecutionError(
            "schema_registry_delete_subject",
            f"HTTP {e.response.status_code}: {e.response.text}",
        )
    except Exception as e:
        logger.error(
            "schema_registry_delete_subject_failed", error=str(e), subject=subject
        )
        raise ToolExecutionError("schema_registry_delete_subject", str(e), e)


# List of all Schema Registry tools for registration
SCHEMA_REGISTRY_TOOLS = [
    schema_registry_list_subjects,
    schema_registry_get_schema,
    schema_registry_get_versions,
    schema_registry_check_compatibility,
    schema_registry_register_schema,
    schema_registry_get_compatibility_level,
    schema_registry_set_compatibility_level,
    schema_registry_delete_subject,
]

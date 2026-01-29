"""Flyway database migration tools.

Wraps the Flyway CLI for database schema migrations.

Supports:
- Flyway Community Edition
- Flyway Teams Edition
- Flyway Enterprise Edition
"""

import os
import subprocess
from typing import Any

from ..core.errors import ToolExecutionError
from ..core.execution_context import get_execution_context
from ..core.logging import get_logger

logger = get_logger(__name__)


def _get_flyway_config() -> dict:
    """Get Flyway configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("flyway")
        if config:
            return config

    # 2. Try environment variables (dev/testing fallback)
    return {
        "url": os.getenv("FLYWAY_URL"),
        "user": os.getenv("FLYWAY_USER"),
        "password": os.getenv("FLYWAY_PASSWORD"),
        "locations": os.getenv("FLYWAY_LOCATIONS", "filesystem:./sql"),
        "schemas": os.getenv("FLYWAY_SCHEMAS"),
        "config_files": os.getenv("FLYWAY_CONFIG_FILES"),
        "working_dir": os.getenv("FLYWAY_WORKING_DIR", "."),
    }


def _run_flyway_command(
    command: str, extra_args: list[str] | None = None, dry_run: bool = False
) -> dict[str, Any]:
    """Run a Flyway CLI command."""
    config = _get_flyway_config()

    cmd = ["flyway"]

    # Add connection args if available
    if config.get("url"):
        cmd.extend([f"-url={config['url']}"])
    if config.get("user"):
        cmd.extend([f"-user={config['user']}"])
    if config.get("password"):
        cmd.extend([f"-password={config['password']}"])
    if config.get("locations"):
        cmd.extend([f"-locations={config['locations']}"])
    if config.get("schemas"):
        cmd.extend([f"-schemas={config['schemas']}"])
    if config.get("config_files"):
        cmd.extend([f"-configFiles={config['config_files']}"])

    # Add the command
    cmd.append(command)

    # Add extra args
    if extra_args:
        cmd.extend(extra_args)

    # For dry run, just add -dryRun flag
    if dry_run and command == "migrate":
        # Flyway doesn't have built-in dry run, use info instead
        cmd = [c for c in cmd if c != "migrate"]
        cmd.append("info")

    working_dir = config.get("working_dir", ".")

    logger.info("flyway_command_running", command=command)

    try:
        result = subprocess.run(
            cmd,
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minutes timeout
        )

        output = result.stdout
        error = result.stderr

        success = result.returncode == 0

        if not success:
            logger.warning(
                "flyway_command_failed",
                command=command,
                returncode=result.returncode,
                error=error[:500] if error else None,
            )
        else:
            logger.info("flyway_command_succeeded", command=command)

        return {
            "command": command,
            "success": success,
            "returncode": result.returncode,
            "output": output,
            "error": error if error else None,
        }

    except FileNotFoundError:
        raise ToolExecutionError(
            "flyway",
            "Flyway CLI not found. Install from https://flywaydb.org/download",
        )
    except subprocess.TimeoutExpired:
        raise ToolExecutionError(
            "flyway", f"Flyway command '{command}' timed out after 5 minutes"
        )
    except Exception as e:
        raise ToolExecutionError("flyway", str(e), e)


def _parse_flyway_info_output(output: str) -> list[dict]:
    """Parse Flyway info output into structured data."""
    migrations = []

    lines = output.strip().split("\n")
    in_table = False

    for line in lines:
        if "+-" in line:
            in_table = True
            continue

        if in_table and "|" in line:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 7 and parts[1] not in ("Category", ""):
                migrations.append({
                    "category": parts[1] if len(parts) > 1 else "",
                    "version": parts[2] if len(parts) > 2 else "",
                    "description": parts[3] if len(parts) > 3 else "",
                    "type": parts[4] if len(parts) > 4 else "",
                    "installed_on": parts[5] if len(parts) > 5 else "",
                    "state": parts[6] if len(parts) > 6 else "",
                })

    return migrations


def flyway_info() -> dict[str, Any]:
    """
    Show migration status (pending, applied, failed).

    This is the primary command for checking migration state.

    Returns:
        Dict with migration status information
    """
    try:
        result = _run_flyway_command("info")

        if not result["success"]:
            return result

        # Parse the output
        migrations = _parse_flyway_info_output(result["output"])

        # Categorize
        pending = [m for m in migrations if m.get("state") == "Pending"]
        applied = [m for m in migrations if m.get("state") == "Success"]
        failed = [m for m in migrations if m.get("state") == "Failed"]

        return {
            "success": True,
            "total_migrations": len(migrations),
            "pending_count": len(pending),
            "applied_count": len(applied),
            "failed_count": len(failed),
            "pending": pending,
            "applied": applied,
            "failed": failed,
            "migrations": migrations,
            "raw_output": result["output"],
        }

    except Exception as e:
        logger.error("flyway_info_failed", error=str(e))
        raise


def flyway_validate() -> dict[str, Any]:
    """
    Validate applied migrations against available ones.

    Checks for:
    - Missing migrations
    - Checksum mismatches
    - Migration conflicts

    Returns:
        Dict with validation result
    """
    try:
        result = _run_flyway_command("validate")

        return {
            "command": "validate",
            "success": result["success"],
            "valid": result["success"],
            "output": result["output"],
            "error": result.get("error"),
        }

    except Exception as e:
        logger.error("flyway_validate_failed", error=str(e))
        raise


def flyway_migrate(
    target: str | None = None,
    out_of_order: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Apply pending migrations.

    WARNING: This modifies the database schema!

    Args:
        target: Target version to migrate to (latest if not specified)
        out_of_order: Allow out-of-order migrations
        dry_run: If True, only show what would be migrated

    Returns:
        Dict with migration result
    """
    try:
        extra_args = []

        if target:
            extra_args.append(f"-target={target}")
        if out_of_order:
            extra_args.append("-outOfOrder=true")

        if dry_run:
            # For dry run, use info to show pending
            info_result = flyway_info()
            return {
                "command": "migrate (dry run)",
                "success": True,
                "dry_run": True,
                "pending_migrations": info_result.get("pending", []),
                "message": "Dry run - no changes applied",
            }

        result = _run_flyway_command("migrate", extra_args)

        if result["success"]:
            # Get updated status
            info_result = flyway_info()
            return {
                "command": "migrate",
                "success": True,
                "output": result["output"],
                "current_state": info_result,
            }

        return result

    except Exception as e:
        logger.error("flyway_migrate_failed", error=str(e))
        raise


def flyway_repair() -> dict[str, Any]:
    """
    Repair the schema history table.

    Useful for:
    - Recovering from failed migrations
    - Fixing checksum mismatches
    - Aligning schema history with filesystem

    Returns:
        Dict with repair result
    """
    try:
        result = _run_flyway_command("repair")

        return {
            "command": "repair",
            "success": result["success"],
            "output": result["output"],
            "error": result.get("error"),
        }

    except Exception as e:
        logger.error("flyway_repair_failed", error=str(e))
        raise


def flyway_baseline(version: str = "1", description: str = "Baseline") -> dict[str, Any]:
    """
    Baseline an existing database.

    Use this when introducing Flyway to an existing database.

    Args:
        version: Version to baseline to (default: 1)
        description: Description for the baseline entry

    Returns:
        Dict with baseline result
    """
    try:
        extra_args = [
            f"-baselineVersion={version}",
            f"-baselineDescription={description}",
        ]

        result = _run_flyway_command("baseline", extra_args)

        return {
            "command": "baseline",
            "success": result["success"],
            "version": version,
            "description": description,
            "output": result["output"],
            "error": result.get("error"),
        }

    except Exception as e:
        logger.error("flyway_baseline_failed", error=str(e))
        raise


def flyway_clean(confirm: bool = False) -> dict[str, Any]:
    """
    Drop all objects in the configured schemas.

    WARNING: This is DESTRUCTIVE! Use only in development/testing!

    Args:
        confirm: Must be True to execute (safety check)

    Returns:
        Dict with clean result
    """
    if not confirm:
        return {
            "command": "clean",
            "success": False,
            "error": "Safety check: set confirm=True to execute clean",
            "warning": "This will DROP ALL OBJECTS in the schema!",
        }

    try:
        result = _run_flyway_command("clean")

        return {
            "command": "clean",
            "success": result["success"],
            "output": result["output"],
            "error": result.get("error"),
        }

    except Exception as e:
        logger.error("flyway_clean_failed", error=str(e))
        raise


def flyway_undo() -> dict[str, Any]:
    """
    Undo the most recently applied migration.

    Note: Requires Flyway Teams or Enterprise edition.

    Returns:
        Dict with undo result
    """
    try:
        result = _run_flyway_command("undo")

        return {
            "command": "undo",
            "success": result["success"],
            "output": result["output"],
            "error": result.get("error"),
        }

    except Exception as e:
        logger.error("flyway_undo_failed", error=str(e))
        raise


# List of all Flyway tools for registration
FLYWAY_TOOLS = [
    flyway_info,
    flyway_validate,
    flyway_migrate,
    flyway_repair,
    flyway_baseline,
    flyway_clean,
    flyway_undo,
]

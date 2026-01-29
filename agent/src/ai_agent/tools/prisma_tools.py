"""Prisma Migrate database migration tools.

Wraps the Prisma CLI for database schema migrations.

Supports:
- Prisma Migrate
- Prisma with any supported database (PostgreSQL, MySQL, SQLite, SQL Server, MongoDB)
"""

import json
import os
import subprocess
from typing import Any

from ..core.errors import ToolExecutionError
from ..core.execution_context import get_execution_context
from ..core.logging import get_logger

logger = get_logger(__name__)


def _get_prisma_config() -> dict:
    """Get Prisma configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("prisma")
        if config:
            return config

    # 2. Try environment variables (dev/testing fallback)
    return {
        "working_dir": os.getenv("PRISMA_WORKING_DIR", "."),
        "schema_path": os.getenv("PRISMA_SCHEMA", "prisma/schema.prisma"),
        "database_url": os.getenv("DATABASE_URL"),
    }


def _run_prisma_command(
    command: str, extra_args: list[str] | None = None, use_npx: bool = True
) -> dict[str, Any]:
    """Run a Prisma CLI command."""
    config = _get_prisma_config()

    # Try npx first, then direct prisma command
    if use_npx:
        cmd = ["npx", "prisma"]
    else:
        cmd = ["prisma"]

    # Add the command (may be multiple parts like "migrate status")
    cmd.extend(command.split())

    # Add schema path if specified
    if config.get("schema_path"):
        cmd.extend(["--schema", config["schema_path"]])

    # Add extra args
    if extra_args:
        cmd.extend(extra_args)

    working_dir = config.get("working_dir", ".")

    # Set DATABASE_URL if provided
    env = os.environ.copy()
    if config.get("database_url"):
        env["DATABASE_URL"] = config["database_url"]

    logger.info("prisma_command_running", command=command)

    try:
        result = subprocess.run(
            cmd,
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minutes timeout
            env=env,
        )

        output = result.stdout
        error = result.stderr

        success = result.returncode == 0

        if not success:
            logger.warning(
                "prisma_command_failed",
                command=command,
                returncode=result.returncode,
                error=error[:500] if error else None,
            )
        else:
            logger.info("prisma_command_succeeded", command=command)

        return {
            "command": command,
            "success": success,
            "returncode": result.returncode,
            "output": output,
            "error": error if error else None,
        }

    except FileNotFoundError:
        if use_npx:
            # Try without npx
            return _run_prisma_command(command, extra_args, use_npx=False)
        raise ToolExecutionError(
            "prisma",
            "Prisma CLI not found. Install with: npm install prisma",
        )
    except subprocess.TimeoutExpired:
        raise ToolExecutionError(
            "prisma", f"Prisma command '{command}' timed out after 5 minutes"
        )
    except Exception as e:
        raise ToolExecutionError("prisma", str(e), e)


def prisma_migrate_status() -> dict[str, Any]:
    """
    Show the status of migrations.

    Returns information about:
    - Applied migrations
    - Pending migrations
    - Migration history

    Returns:
        Dict with migration status
    """
    try:
        result = _run_prisma_command("migrate status")

        if not result["success"]:
            return result

        output = result["output"]

        # Parse status
        is_up_to_date = "database is up to date" in output.lower()
        has_pending = "pending" in output.lower() or "not yet applied" in output.lower()
        has_failed = "failed" in output.lower()

        # Extract migration names if possible
        migrations = []
        lines = output.split("\n")
        for line in lines:
            # Look for migration names (usually in format: 20231201_migration_name)
            if "_" in line and any(c.isdigit() for c in line[:8]):
                parts = line.strip().split()
                if parts:
                    migrations.append({
                        "name": parts[0],
                        "applied": "applied" in line.lower() or "✔" in line,
                        "pending": "pending" in line.lower() or "..." in line,
                    })

        return {
            "success": True,
            "is_up_to_date": is_up_to_date,
            "has_pending_migrations": has_pending,
            "has_failed_migrations": has_failed,
            "migrations": migrations,
            "raw_output": output,
        }

    except Exception as e:
        logger.error("prisma_migrate_status_failed", error=str(e))
        raise


def prisma_migrate_deploy() -> dict[str, Any]:
    """
    Apply pending migrations to the database.

    This is the production-safe command that only applies migrations
    without creating new ones.

    WARNING: This modifies the database schema!

    Returns:
        Dict with deployment result
    """
    try:
        result = _run_prisma_command("migrate deploy")

        if result["success"]:
            # Get updated status
            status = prisma_migrate_status()
            return {
                "command": "migrate deploy",
                "success": True,
                "output": result["output"],
                "current_status": status,
            }

        return result

    except Exception as e:
        logger.error("prisma_migrate_deploy_failed", error=str(e))
        raise


def prisma_migrate_reset(confirm: bool = False, skip_seed: bool = False) -> dict[str, Any]:
    """
    Reset the database by dropping all data and reapplying migrations.

    WARNING: This is DESTRUCTIVE! All data will be lost!
    Use only in development/testing!

    Args:
        confirm: Must be True to execute (safety check)
        skip_seed: Skip running seed script

    Returns:
        Dict with reset result
    """
    if not confirm:
        return {
            "command": "migrate reset",
            "success": False,
            "error": "Safety check: set confirm=True to execute reset",
            "warning": "This will DROP ALL DATA in the database!",
        }

    try:
        extra_args = ["--force"]  # Skip confirmation prompt
        if skip_seed:
            extra_args.append("--skip-seed")

        result = _run_prisma_command("migrate reset", extra_args)

        return {
            "command": "migrate reset",
            "success": result["success"],
            "output": result["output"],
            "error": result.get("error"),
        }

    except Exception as e:
        logger.error("prisma_migrate_reset_failed", error=str(e))
        raise


def prisma_migrate_resolve(
    applied: str | None = None, rolled_back: str | None = None
) -> dict[str, Any]:
    """
    Resolve issues with migration history.

    Use this to mark migrations as applied or rolled back
    without actually running them.

    Args:
        applied: Migration name to mark as applied
        rolled_back: Migration name to mark as rolled back

    Returns:
        Dict with resolve result
    """
    if not applied and not rolled_back:
        return {
            "command": "migrate resolve",
            "success": False,
            "error": "Must specify either 'applied' or 'rolled_back' migration name",
        }

    try:
        extra_args = []
        if applied:
            extra_args.extend(["--applied", applied])
        if rolled_back:
            extra_args.extend(["--rolled-back", rolled_back])

        result = _run_prisma_command("migrate resolve", extra_args)

        return {
            "command": "migrate resolve",
            "success": result["success"],
            "applied": applied,
            "rolled_back": rolled_back,
            "output": result["output"],
            "error": result.get("error"),
        }

    except Exception as e:
        logger.error("prisma_migrate_resolve_failed", error=str(e))
        raise


def prisma_migrate_diff(
    from_schema: str | None = None,
    to_schema: str | None = None,
    from_url: str | None = None,
    to_url: str | None = None,
) -> dict[str, Any]:
    """
    Generate SQL diff between two schema states.

    Useful for:
    - Previewing migration SQL
    - Comparing schema states
    - Understanding changes

    Args:
        from_schema: Path to source schema file
        to_schema: Path to target schema file
        from_url: Source database URL
        to_url: Target database URL

    Returns:
        Dict with diff result
    """
    try:
        extra_args = []

        if from_schema:
            extra_args.extend(["--from-schema-datamodel", from_schema])
        elif from_url:
            extra_args.extend(["--from-url", from_url])
        else:
            extra_args.extend(["--from-schema-datasource", "prisma/schema.prisma"])

        if to_schema:
            extra_args.extend(["--to-schema-datamodel", to_schema])
        elif to_url:
            extra_args.extend(["--to-url", to_url])
        else:
            extra_args.extend(["--to-schema-datasource", "prisma/schema.prisma"])

        result = _run_prisma_command("migrate diff", extra_args)

        return {
            "command": "migrate diff",
            "success": result["success"],
            "sql_diff": result["output"],
            "has_changes": bool(result["output"].strip()),
            "error": result.get("error"),
        }

    except Exception as e:
        logger.error("prisma_migrate_diff_failed", error=str(e))
        raise


def prisma_db_push(accept_data_loss: bool = False) -> dict[str, Any]:
    """
    Push schema changes directly to the database without creating migrations.

    WARNING: This is for prototyping only! Not recommended for production!

    Args:
        accept_data_loss: Accept potential data loss

    Returns:
        Dict with push result
    """
    try:
        extra_args = []
        if accept_data_loss:
            extra_args.append("--accept-data-loss")

        result = _run_prisma_command("db push", extra_args)

        return {
            "command": "db push",
            "success": result["success"],
            "output": result["output"],
            "error": result.get("error"),
            "warning": "db push should only be used in development!",
        }

    except Exception as e:
        logger.error("prisma_db_push_failed", error=str(e))
        raise


def prisma_db_pull() -> dict[str, Any]:
    """
    Introspect database and update Prisma schema.

    Pulls the current database schema into the Prisma schema file.

    Returns:
        Dict with pull result
    """
    try:
        result = _run_prisma_command("db pull")

        return {
            "command": "db pull",
            "success": result["success"],
            "output": result["output"],
            "error": result.get("error"),
        }

    except Exception as e:
        logger.error("prisma_db_pull_failed", error=str(e))
        raise


def prisma_validate() -> dict[str, Any]:
    """
    Validate the Prisma schema.

    Checks for syntax errors and configuration issues.

    Returns:
        Dict with validation result
    """
    try:
        result = _run_prisma_command("validate")

        return {
            "command": "validate",
            "success": result["success"],
            "is_valid": result["success"],
            "output": result["output"],
            "error": result.get("error"),
        }

    except Exception as e:
        logger.error("prisma_validate_failed", error=str(e))
        raise


def prisma_format() -> dict[str, Any]:
    """
    Format the Prisma schema file.

    Returns:
        Dict with format result
    """
    try:
        result = _run_prisma_command("format")

        return {
            "command": "format",
            "success": result["success"],
            "output": result["output"],
            "error": result.get("error"),
        }

    except Exception as e:
        logger.error("prisma_format_failed", error=str(e))
        raise


# List of all Prisma tools for registration
PRISMA_TOOLS = [
    prisma_migrate_status,
    prisma_migrate_deploy,
    prisma_migrate_reset,
    prisma_migrate_resolve,
    prisma_migrate_diff,
    prisma_db_push,
    prisma_db_pull,
    prisma_validate,
    prisma_format,
]

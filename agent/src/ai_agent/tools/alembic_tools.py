"""Alembic database migration tools.

Wraps the Alembic CLI for SQLAlchemy-based database migrations.

Supports:
- Alembic with any SQLAlchemy-supported database
- Flask-Migrate (which uses Alembic)
- FastAPI + Alembic setups
"""

import os
import re
import subprocess
from typing import Any

from ..core.errors import ToolExecutionError
from ..core.execution_context import get_execution_context
from ..core.logging import get_logger

logger = get_logger(__name__)


def _get_alembic_config() -> dict:
    """Get Alembic configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("alembic")
        if config:
            return config

    # 2. Try environment variables (dev/testing fallback)
    return {
        "working_dir": os.getenv("ALEMBIC_WORKING_DIR", "."),
        "config_file": os.getenv("ALEMBIC_CONFIG", "alembic.ini"),
        "database_url": os.getenv("DATABASE_URL"),
    }


def _run_alembic_command(
    command: str, extra_args: list[str] | None = None
) -> dict[str, Any]:
    """Run an Alembic CLI command."""
    config = _get_alembic_config()

    cmd = ["alembic"]

    # Add config file if specified
    if config.get("config_file"):
        cmd.extend(["-c", config["config_file"]])

    # Add the command
    cmd.append(command)

    # Add extra args
    if extra_args:
        cmd.extend(extra_args)

    working_dir = config.get("working_dir", ".")

    # Set DATABASE_URL if provided
    env = os.environ.copy()
    if config.get("database_url"):
        env["DATABASE_URL"] = config["database_url"]

    logger.info("alembic_command_running", command=command)

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
                "alembic_command_failed",
                command=command,
                returncode=result.returncode,
                error=error[:500] if error else None,
            )
        else:
            logger.info("alembic_command_succeeded", command=command)

        return {
            "command": command,
            "success": success,
            "returncode": result.returncode,
            "output": output,
            "error": error if error else None,
        }

    except FileNotFoundError:
        raise ToolExecutionError(
            "alembic",
            "Alembic CLI not found. Install with: pip install alembic",
        )
    except subprocess.TimeoutExpired:
        raise ToolExecutionError(
            "alembic", f"Alembic command '{command}' timed out after 5 minutes"
        )
    except Exception as e:
        raise ToolExecutionError("alembic", str(e), e)


def _parse_alembic_history(output: str) -> list[dict]:
    """Parse Alembic history output into structured data."""
    migrations = []

    lines = output.strip().split("\n")

    for line in lines:
        if not line.strip():
            continue

        # Parse lines like: "abc123 -> def456 (head), migration description"
        # or: "abc123 -> <base>, initial migration"
        match = re.match(
            r"([a-f0-9]+)\s*->\s*([a-f0-9]+|<base>)(?:\s*\(([\w,\s]+)\))?,?\s*(.*)",
            line.strip(),
        )

        if match:
            migrations.append({
                "revision": match.group(1),
                "down_revision": match.group(2) if match.group(2) != "<base>" else None,
                "is_head": "head" in (match.group(3) or ""),
                "is_current": "current" in (match.group(3) or ""),
                "description": match.group(4).strip() if match.group(4) else "",
            })

    return migrations


def alembic_current() -> dict[str, Any]:
    """
    Display current revision(s) for the database.

    Returns:
        Dict with current revision information
    """
    try:
        result = _run_alembic_command("current")

        if not result["success"]:
            return result

        output = result["output"].strip()

        # Parse current revision
        current_revision = None
        if output:
            # Usually looks like: "abc123 (head)" or just "abc123"
            match = re.match(r"([a-f0-9]+)", output)
            if match:
                current_revision = match.group(1)

        return {
            "success": True,
            "current_revision": current_revision,
            "is_head": "(head)" in output,
            "raw_output": output,
        }

    except Exception as e:
        logger.error("alembic_current_failed", error=str(e))
        raise


def alembic_history(verbose: bool = False, limit: int | None = None) -> dict[str, Any]:
    """
    Show migration history.

    Args:
        verbose: Show verbose output
        limit: Limit number of revisions to show

    Returns:
        Dict with migration history
    """
    try:
        extra_args = []
        if verbose:
            extra_args.append("-v")
        if limit:
            extra_args.append(f"-r-{limit}:head")

        result = _run_alembic_command("history", extra_args)

        if not result["success"]:
            return result

        migrations = _parse_alembic_history(result["output"])

        return {
            "success": True,
            "migration_count": len(migrations),
            "migrations": migrations,
            "raw_output": result["output"],
        }

    except Exception as e:
        logger.error("alembic_history_failed", error=str(e))
        raise


def alembic_heads() -> dict[str, Any]:
    """
    Show current available heads.

    Useful for detecting branch points in migration history.

    Returns:
        Dict with head revisions
    """
    try:
        result = _run_alembic_command("heads")

        if not result["success"]:
            return result

        output = result["output"].strip()
        heads = []

        for line in output.split("\n"):
            if line.strip():
                match = re.match(r"([a-f0-9]+)", line.strip())
                if match:
                    heads.append({
                        "revision": match.group(1),
                        "description": line.strip(),
                    })

        return {
            "success": True,
            "head_count": len(heads),
            "heads": heads,
            "has_branches": len(heads) > 1,
            "raw_output": output,
        }

    except Exception as e:
        logger.error("alembic_heads_failed", error=str(e))
        raise


def alembic_branches() -> dict[str, Any]:
    """
    Show migration branches.

    Returns:
        Dict with branch information
    """
    try:
        result = _run_alembic_command("branches")

        if not result["success"]:
            return result

        output = result["output"].strip()

        return {
            "success": True,
            "has_branches": bool(output),
            "raw_output": output,
        }

    except Exception as e:
        logger.error("alembic_branches_failed", error=str(e))
        raise


def alembic_upgrade(
    revision: str = "head", sql: bool = False, dry_run: bool = False
) -> dict[str, Any]:
    """
    Apply migrations up to a revision.

    WARNING: This modifies the database schema!

    Args:
        revision: Target revision (default: 'head' for latest)
        sql: If True, output SQL instead of executing
        dry_run: If True, only show what would be applied

    Returns:
        Dict with upgrade result
    """
    try:
        extra_args = [revision]

        if sql or dry_run:
            extra_args.append("--sql")

        result = _run_alembic_command("upgrade", extra_args)

        if dry_run:
            return {
                "command": "upgrade (dry run)",
                "success": True,
                "dry_run": True,
                "sql_output": result["output"],
                "target_revision": revision,
            }

        if result["success"]:
            # Get updated status
            current = alembic_current()
            return {
                "command": "upgrade",
                "success": True,
                "target_revision": revision,
                "current_revision": current.get("current_revision"),
                "output": result["output"],
            }

        return result

    except Exception as e:
        logger.error("alembic_upgrade_failed", error=str(e))
        raise


def alembic_downgrade(
    revision: str = "-1", sql: bool = False, dry_run: bool = False
) -> dict[str, Any]:
    """
    Revert migrations down to a revision.

    WARNING: This modifies the database schema and may cause data loss!

    Args:
        revision: Target revision (default: '-1' for one step back)
        sql: If True, output SQL instead of executing
        dry_run: If True, only show what would be applied

    Returns:
        Dict with downgrade result
    """
    try:
        extra_args = [revision]

        if sql or dry_run:
            extra_args.append("--sql")

        result = _run_alembic_command("downgrade", extra_args)

        if dry_run:
            return {
                "command": "downgrade (dry run)",
                "success": True,
                "dry_run": True,
                "sql_output": result["output"],
                "target_revision": revision,
            }

        if result["success"]:
            # Get updated status
            current = alembic_current()
            return {
                "command": "downgrade",
                "success": True,
                "target_revision": revision,
                "current_revision": current.get("current_revision"),
                "output": result["output"],
            }

        return result

    except Exception as e:
        logger.error("alembic_downgrade_failed", error=str(e))
        raise


def alembic_stamp(revision: str) -> dict[str, Any]:
    """
    Stamp the revision table with a specific revision without running migrations.

    Use this to mark a database as being at a certain revision
    (useful for syncing with external schema changes).

    Args:
        revision: Revision to stamp

    Returns:
        Dict with stamp result
    """
    try:
        result = _run_alembic_command("stamp", [revision])

        return {
            "command": "stamp",
            "success": result["success"],
            "stamped_revision": revision,
            "output": result["output"],
            "error": result.get("error"),
        }

    except Exception as e:
        logger.error("alembic_stamp_failed", error=str(e))
        raise


def alembic_check() -> dict[str, Any]:
    """
    Check if there are any pending migrations.

    Returns exit code 0 if database is up to date, 1 if not.

    Returns:
        Dict with check result
    """
    try:
        result = _run_alembic_command("check")

        is_up_to_date = result["success"]

        return {
            "command": "check",
            "success": True,
            "is_up_to_date": is_up_to_date,
            "output": result["output"],
            "message": "Database is up to date"
            if is_up_to_date
            else "Pending migrations detected",
        }

    except Exception as e:
        logger.error("alembic_check_failed", error=str(e))
        raise


def alembic_show(revision: str) -> dict[str, Any]:
    """
    Show details of a specific revision.

    Args:
        revision: Revision identifier

    Returns:
        Dict with revision details
    """
    try:
        result = _run_alembic_command("show", [revision])

        if not result["success"]:
            return result

        return {
            "success": True,
            "revision": revision,
            "details": result["output"],
        }

    except Exception as e:
        logger.error("alembic_show_failed", error=str(e))
        raise


# List of all Alembic tools for registration
ALEMBIC_TOOLS = [
    alembic_current,
    alembic_history,
    alembic_heads,
    alembic_branches,
    alembic_upgrade,
    alembic_downgrade,
    alembic_stamp,
    alembic_check,
    alembic_show,
]

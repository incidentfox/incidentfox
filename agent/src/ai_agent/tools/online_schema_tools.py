"""Online schema change tools for zero-downtime MySQL migrations.

Supports:
- gh-ost (GitHub Online Schema Change)
- pt-online-schema-change (Percona Toolkit)

These tools allow safe ALTER TABLE operations on large MySQL tables
without blocking reads or writes.
"""

import os
import re
import subprocess
from typing import Any

from ..core.errors import ToolExecutionError
from ..core.execution_context import get_execution_context
from ..core.logging import get_logger

logger = get_logger(__name__)


def _get_osc_config() -> dict:
    """Get online schema change configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("online_schema_change")
        if config:
            return config

    # 2. Try environment variables (dev/testing fallback)
    return {
        "mysql_host": os.getenv("MYSQL_HOST"),
        "mysql_port": os.getenv("MYSQL_PORT", "3306"),
        "mysql_user": os.getenv("MYSQL_USER"),
        "mysql_password": os.getenv("MYSQL_PASSWORD"),
        "mysql_database": os.getenv("MYSQL_DATABASE"),
        # gh-ost specific
        "ghost_postpone_file": os.getenv("GHOST_POSTPONE_FILE", "/tmp/ghost.postpone"),
        "ghost_panic_file": os.getenv("GHOST_PANIC_FILE", "/tmp/ghost.panic"),
        # Safety limits
        "max_load": os.getenv("OSC_MAX_LOAD", "Threads_running=25"),
        "critical_load": os.getenv("OSC_CRITICAL_LOAD", "Threads_running=50"),
        "chunk_size": os.getenv("OSC_CHUNK_SIZE", "1000"),
    }


# ============================================================================
# gh-ost (GitHub Online Schema Change)
# ============================================================================


def gh_ost_run(
    database: str,
    table: str,
    alter: str,
    execute: bool = False,
    allow_on_master: bool = False,
    chunk_size: int | None = None,
    max_load: str | None = None,
    critical_load: str | None = None,
    postpone_cut_over: bool = False,
) -> dict[str, Any]:
    """
    Run gh-ost online schema change.

    gh-ost performs ALTER TABLE without blocking by:
    1. Creating a ghost table with new schema
    2. Copying data in chunks
    3. Tailing binlog for ongoing changes
    4. Atomic table swap

    WARNING: This modifies the database schema!

    Args:
        database: Database name
        table: Table name
        alter: ALTER statement (e.g., "ADD COLUMN phone VARCHAR(20)")
        execute: Actually execute (False = dry run)
        allow_on_master: Allow running on master (needed for single-server)
        chunk_size: Rows per chunk (default: 1000)
        max_load: Throttle if load exceeds (e.g., "Threads_running=25")
        critical_load: Abort if load exceeds (e.g., "Threads_running=50")
        postpone_cut_over: Create file to postpone cutover

    Returns:
        Dict with gh-ost result
    """
    config = _get_osc_config()

    cmd = [
        "gh-ost",
        f"--host={config.get('mysql_host', 'localhost')}",
        f"--port={config.get('mysql_port', '3306')}",
        f"--user={config.get('mysql_user', 'root')}",
        f"--database={database}",
        f"--table={table}",
        f"--alter={alter}",
    ]

    # Add password via environment
    env = os.environ.copy()
    if config.get("mysql_password"):
        env["MYSQL_PWD"] = config["mysql_password"]

    # Add options
    chunk = chunk_size or int(config.get("chunk_size", 1000))
    cmd.append(f"--chunk-size={chunk}")

    max_l = max_load or config.get("max_load", "Threads_running=25")
    cmd.append(f"--max-load={max_l}")

    crit_l = critical_load or config.get("critical_load", "Threads_running=50")
    cmd.append(f"--critical-load={crit_l}")

    if allow_on_master:
        cmd.append("--allow-on-master")

    if postpone_cut_over:
        postpone_file = config.get("ghost_postpone_file", "/tmp/ghost.postpone")
        cmd.append(f"--postpone-cut-over-flag-file={postpone_file}")

    # Add panic file for emergency abort
    panic_file = config.get("ghost_panic_file", "/tmp/ghost.panic")
    cmd.append(f"--panic-flag-file={panic_file}")

    # Other useful defaults
    cmd.extend([
        "--verbose",
        "--stack",  # Stack trace on errors
        "--ok-to-drop-table",  # Drop old table after swap
    ])

    if execute:
        cmd.append("--execute")
    else:
        # Dry run mode
        pass

    logger.info(
        "gh_ost_running",
        database=database,
        table=table,
        alter=alter[:100],
        execute=execute,
    )

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=7200,  # 2 hours timeout
            env=env,
        )

        output = result.stdout
        error = result.stderr
        success = result.returncode == 0

        # Parse progress from output
        progress_match = re.search(r"Copy: (\d+)/(\d+)", output + error)
        progress = None
        if progress_match:
            progress = {
                "copied": int(progress_match.group(1)),
                "total": int(progress_match.group(2)),
                "percent": round(
                    int(progress_match.group(1)) / int(progress_match.group(2)) * 100, 2
                )
                if int(progress_match.group(2)) > 0
                else 0,
            }

        logger.info(
            "gh_ost_completed",
            database=database,
            table=table,
            success=success,
        )

        return {
            "tool": "gh-ost",
            "database": database,
            "table": table,
            "alter": alter,
            "executed": execute,
            "success": success,
            "progress": progress,
            "output": output[-5000:] if len(output) > 5000 else output,
            "error": error[-2000:] if error and len(error) > 2000 else error,
            "postpone_file": config.get("ghost_postpone_file") if postpone_cut_over else None,
            "panic_file": panic_file,
        }

    except FileNotFoundError:
        raise ToolExecutionError(
            "gh_ost",
            "gh-ost not found. Install from: https://github.com/github/gh-ost/releases",
        )
    except subprocess.TimeoutExpired:
        raise ToolExecutionError(
            "gh_ost", "gh-ost timed out after 2 hours. Check database status."
        )
    except Exception as e:
        raise ToolExecutionError("gh_ost", str(e), e)


def gh_ost_cut_over(postpone_file: str | None = None) -> dict[str, Any]:
    """
    Trigger gh-ost cut-over by removing the postpone file.

    Use this when you're ready to perform the atomic table swap.

    Args:
        postpone_file: Path to postpone file (uses default if not specified)

    Returns:
        Dict with result
    """
    config = _get_osc_config()
    file_path = postpone_file or config.get("ghost_postpone_file", "/tmp/ghost.postpone")

    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info("gh_ost_cutover_triggered", file=file_path)
            return {
                "success": True,
                "action": "cut_over_triggered",
                "removed_file": file_path,
                "message": "Postpone file removed. gh-ost will perform cut-over.",
            }
        else:
            return {
                "success": False,
                "error": f"Postpone file not found: {file_path}",
                "message": "gh-ost may not be running with postpone enabled.",
            }
    except Exception as e:
        raise ToolExecutionError("gh_ost_cut_over", str(e), e)


def gh_ost_panic(panic_file: str | None = None) -> dict[str, Any]:
    """
    Create panic file to abort a running gh-ost operation.

    Use this for emergency abort!

    Args:
        panic_file: Path to panic file (uses default if not specified)

    Returns:
        Dict with result
    """
    config = _get_osc_config()
    file_path = panic_file or config.get("ghost_panic_file", "/tmp/ghost.panic")

    try:
        with open(file_path, "w") as f:
            f.write("PANIC")

        logger.warning("gh_ost_panic_triggered", file=file_path)

        return {
            "success": True,
            "action": "panic_triggered",
            "created_file": file_path,
            "message": "Panic file created. gh-ost will abort.",
        }
    except Exception as e:
        raise ToolExecutionError("gh_ost_panic", str(e), e)


# ============================================================================
# pt-online-schema-change (Percona Toolkit)
# ============================================================================


def pt_online_schema_change(
    database: str,
    table: str,
    alter: str,
    execute: bool = False,
    chunk_size: int | None = None,
    max_lag: int = 1,
    check_interval: int = 1,
    no_drop_old_table: bool = False,
) -> dict[str, Any]:
    """
    Run pt-online-schema-change (Percona Toolkit).

    pt-osc performs ALTER TABLE without blocking by:
    1. Creating a new table with the altered schema
    2. Installing triggers on the original table
    3. Copying data in chunks
    4. Atomic table swap

    WARNING: This modifies the database schema!

    Args:
        database: Database name
        table: Table name
        alter: ALTER statement (e.g., "ADD COLUMN phone VARCHAR(20)")
        execute: Actually execute (False = dry run)
        chunk_size: Rows per chunk (default: 1000)
        max_lag: Maximum replica lag in seconds before pausing
        check_interval: Seconds between lag checks
        no_drop_old_table: Keep old table after migration

    Returns:
        Dict with pt-osc result
    """
    config = _get_osc_config()

    # Build DSN
    dsn = f"D={database},t={table}"
    if config.get("mysql_host"):
        dsn += f",h={config['mysql_host']}"
    if config.get("mysql_port"):
        dsn += f",P={config['mysql_port']}"
    if config.get("mysql_user"):
        dsn += f",u={config['mysql_user']}"

    cmd = [
        "pt-online-schema-change",
        f"--alter={alter}",
        dsn,
    ]

    # Add password via environment
    env = os.environ.copy()
    if config.get("mysql_password"):
        env["MYSQL_PWD"] = config["mysql_password"]

    # Add options
    chunk = chunk_size or int(config.get("chunk_size", 1000))
    cmd.append(f"--chunk-size={chunk}")
    cmd.append(f"--max-lag={max_lag}")
    cmd.append(f"--check-interval={check_interval}")

    if no_drop_old_table:
        cmd.append("--no-drop-old-table")

    # Safety options
    cmd.extend([
        "--progress=percentage,10",  # Progress every 10%
        "--print",  # Print SQL
        "--statistics",  # Print statistics
    ])

    if execute:
        cmd.append("--execute")
    else:
        cmd.append("--dry-run")

    logger.info(
        "pt_osc_running",
        database=database,
        table=table,
        alter=alter[:100],
        execute=execute,
    )

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=7200,  # 2 hours timeout
            env=env,
        )

        output = result.stdout
        error = result.stderr
        success = result.returncode == 0

        # Parse progress from output
        progress_match = re.search(r"(\d+)% complete", output + error)
        progress = int(progress_match.group(1)) if progress_match else None

        logger.info(
            "pt_osc_completed",
            database=database,
            table=table,
            success=success,
        )

        return {
            "tool": "pt-online-schema-change",
            "database": database,
            "table": table,
            "alter": alter,
            "executed": execute,
            "success": success,
            "progress_percent": progress,
            "output": output[-5000:] if len(output) > 5000 else output,
            "error": error[-2000:] if error and len(error) > 2000 else error,
        }

    except FileNotFoundError:
        raise ToolExecutionError(
            "pt_online_schema_change",
            "pt-online-schema-change not found. Install with: apt install percona-toolkit",
        )
    except subprocess.TimeoutExpired:
        raise ToolExecutionError(
            "pt_online_schema_change",
            "pt-online-schema-change timed out after 2 hours. Check database status.",
        )
    except Exception as e:
        raise ToolExecutionError("pt_online_schema_change", str(e), e)


def osc_estimate_time(
    database: str,
    table: str,
    chunk_size: int = 1000,
    rows_per_second: int = 1000,
) -> dict[str, Any]:
    """
    Estimate time for online schema change.

    Connects to MySQL to get row count and estimates migration time.

    Args:
        database: Database name
        table: Table name
        chunk_size: Rows per chunk
        rows_per_second: Estimated processing speed

    Returns:
        Dict with time estimate
    """
    try:
        import mysql.connector
    except ImportError:
        raise ToolExecutionError(
            "osc_estimate",
            "mysql-connector-python not installed. Install with: pip install mysql-connector-python",
        )

    config = _get_osc_config()

    try:
        conn = mysql.connector.connect(
            host=config.get("mysql_host", "localhost"),
            port=int(config.get("mysql_port", 3306)),
            user=config.get("mysql_user"),
            password=config.get("mysql_password"),
            database=database,
        )
        cursor = conn.cursor(dictionary=True)

        # Get row count
        cursor.execute(f"SELECT COUNT(*) as cnt FROM `{table}`")
        row_count = cursor.fetchone()["cnt"]

        # Get table size
        cursor.execute(
            f"""
            SELECT
                DATA_LENGTH + INDEX_LENGTH as total_bytes
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
            """,
            (database, table),
        )
        size_result = cursor.fetchone()
        table_size = size_result["total_bytes"] if size_result else 0

        cursor.close()
        conn.close()

        # Calculate estimates
        chunks_needed = (row_count + chunk_size - 1) // chunk_size
        estimated_seconds = row_count / rows_per_second

        # Add overhead for triggers, binlog reading, etc. (roughly 50%)
        estimated_seconds *= 1.5

        hours = int(estimated_seconds // 3600)
        minutes = int((estimated_seconds % 3600) // 60)
        seconds = int(estimated_seconds % 60)

        return {
            "success": True,
            "database": database,
            "table": table,
            "row_count": row_count,
            "table_size_mb": round(table_size / (1024 * 1024), 2),
            "chunk_size": chunk_size,
            "chunks_needed": chunks_needed,
            "estimated_time": {
                "seconds": round(estimated_seconds),
                "formatted": f"{hours}h {minutes}m {seconds}s",
            },
            "recommendations": [
                "Run during low-traffic period if possible",
                "Monitor replica lag during migration",
                "Have rollback plan ready",
                "Test on staging first",
            ]
            if row_count > 1000000
            else [],
        }

    except Exception as e:
        logger.error("osc_estimate_failed", error=str(e))
        raise ToolExecutionError("osc_estimate", str(e), e)


# List of all Online Schema Change tools for registration
ONLINE_SCHEMA_TOOLS = [
    gh_ost_run,
    gh_ost_cut_over,
    gh_ost_panic,
    pt_online_schema_change,
    osc_estimate_time,
]

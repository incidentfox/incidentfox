"""MySQL tools for database queries and schema inspection.

Supports:
- AWS RDS MySQL
- AWS Aurora MySQL
- Standard MySQL
- MariaDB
- Any MySQL-compatible database
"""

import os
from typing import Any

from ..core.config_required import handle_integration_not_configured
from ..core.errors import ToolExecutionError
from ..core.execution_context import get_execution_context
from ..core.integration_errors import IntegrationNotConfiguredError
from ..core.logging import get_logger

logger = get_logger(__name__)


def _get_mysql_config() -> dict:
    """Get MySQL configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("mysql")
        if config and config.get("host") and config.get("database"):
            return config

    # 2. Try environment variables (dev/testing fallback)
    if os.getenv("MYSQL_HOST") and os.getenv("MYSQL_DATABASE"):
        return {
            "host": os.getenv("MYSQL_HOST"),
            "port": int(os.getenv("MYSQL_PORT", "3306")),
            "database": os.getenv("MYSQL_DATABASE"),
            "user": os.getenv("MYSQL_USER"),
            "password": os.getenv("MYSQL_PASSWORD"),
            "ssl_mode": os.getenv("MYSQL_SSL_MODE", "PREFERRED"),
            "charset": os.getenv("MYSQL_CHARSET", "utf8mb4"),
        }

    # 3. Not configured - raise error
    raise IntegrationNotConfiguredError(
        integration_id="mysql",
        tool_id="mysql_tools",
        missing_fields=["host", "database", "user", "password"],
    )


def _get_mysql_connection():
    """Get MySQL connection using configured credentials."""
    try:
        import mysql.connector
        from mysql.connector import Error as MySQLError
    except ImportError:
        raise ToolExecutionError(
            "mysql",
            "mysql-connector-python not installed. Install with: pip install mysql-connector-python",
        )

    config = _get_mysql_config()

    # Build connection kwargs
    conn_kwargs = {
        "host": config["host"],
        "port": config.get("port", 3306),
        "database": config["database"],
        "user": config.get("user"),
        "password": config.get("password"),
        "charset": config.get("charset", "utf8mb4"),
        "use_unicode": True,
        "autocommit": True,
    }

    # Add SSL if specified
    ssl_mode = config.get("ssl_mode", "PREFERRED")
    if ssl_mode and ssl_mode.upper() not in ("DISABLED", "NONE"):
        conn_kwargs["ssl_disabled"] = False
    else:
        conn_kwargs["ssl_disabled"] = True

    try:
        return mysql.connector.connect(**conn_kwargs)
    except MySQLError as e:
        raise ToolExecutionError("mysql_connection", f"Failed to connect: {e}")


def mysql_list_tables(database: str | None = None) -> dict[str, Any]:
    """
    List all tables in a MySQL database.

    Args:
        database: Database name (uses config default if not specified)

    Returns:
        Dict with table list including names, engines, and row counts
    """
    try:
        config = _get_mysql_config()
        database = database or config["database"]

        conn = _get_mysql_connection()
        cursor = conn.cursor(dictionary=True)

        query = """
            SELECT
                TABLE_NAME as table_name,
                ENGINE as engine,
                TABLE_ROWS as estimated_rows,
                DATA_LENGTH as data_bytes,
                INDEX_LENGTH as index_bytes,
                (DATA_LENGTH + INDEX_LENGTH) as total_bytes,
                CREATE_TIME as created_at,
                UPDATE_TIME as updated_at
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_NAME
        """

        cursor.execute(query, (database,))
        tables = cursor.fetchall()

        result = []
        for table in tables:
            result.append({
                "table_name": table["table_name"],
                "engine": table["engine"],
                "estimated_rows": table["estimated_rows"],
                "data_mb": round((table["data_bytes"] or 0) / (1024 * 1024), 2),
                "index_mb": round((table["index_bytes"] or 0) / (1024 * 1024), 2),
                "total_mb": round((table["total_bytes"] or 0) / (1024 * 1024), 2),
                "created_at": table["created_at"].isoformat() if table["created_at"] else None,
                "updated_at": table["updated_at"].isoformat() if table["updated_at"] else None,
            })

        cursor.close()
        conn.close()

        logger.info("mysql_tables_listed", database=database, count=len(result))

        return {
            "database": database,
            "table_count": len(result),
            "tables": result,
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "mysql_list_tables", "mysql")
    except Exception as e:
        logger.error("mysql_list_tables_failed", error=str(e))
        raise ToolExecutionError("mysql_list_tables", str(e), e)


def mysql_describe_table(
    table_name: str, database: str | None = None
) -> dict[str, Any]:
    """
    Get column details for a MySQL table.

    Args:
        table_name: Table name
        database: Database name (uses config default if not specified)

    Returns:
        Dict with table schema including columns, primary keys, foreign keys, and indexes
    """
    try:
        config = _get_mysql_config()
        database = database or config["database"]

        conn = _get_mysql_connection()
        cursor = conn.cursor(dictionary=True)

        # Get columns
        query = """
            SELECT
                COLUMN_NAME as name,
                DATA_TYPE as data_type,
                COLUMN_TYPE as full_type,
                CHARACTER_MAXIMUM_LENGTH as max_length,
                IS_NULLABLE as nullable,
                COLUMN_DEFAULT as default_value,
                COLUMN_KEY as key_type,
                EXTRA as extra,
                COLUMN_COMMENT as comment
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
            ORDER BY ORDINAL_POSITION
        """

        cursor.execute(query, (database, table_name))
        columns = cursor.fetchall()

        # Get indexes
        index_query = """
            SELECT
                INDEX_NAME as index_name,
                COLUMN_NAME as column_name,
                NON_UNIQUE as non_unique,
                SEQ_IN_INDEX as seq,
                INDEX_TYPE as index_type
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
            ORDER BY INDEX_NAME, SEQ_IN_INDEX
        """

        cursor.execute(index_query, (database, table_name))
        index_rows = cursor.fetchall()

        # Group indexes
        indexes = {}
        for row in index_rows:
            idx_name = row["index_name"]
            if idx_name not in indexes:
                indexes[idx_name] = {
                    "name": idx_name,
                    "unique": not row["non_unique"],
                    "type": row["index_type"],
                    "columns": [],
                }
            indexes[idx_name]["columns"].append(row["column_name"])

        # Get foreign keys
        fk_query = """
            SELECT
                COLUMN_NAME as column_name,
                REFERENCED_TABLE_NAME as ref_table,
                REFERENCED_COLUMN_NAME as ref_column,
                CONSTRAINT_NAME as constraint_name
            FROM information_schema.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = %s
                AND TABLE_NAME = %s
                AND REFERENCED_TABLE_NAME IS NOT NULL
        """

        cursor.execute(fk_query, (database, table_name))
        fk_rows = cursor.fetchall()

        foreign_keys = {
            row["column_name"]: {
                "constraint": row["constraint_name"],
                "ref_table": row["ref_table"],
                "ref_column": row["ref_column"],
            }
            for row in fk_rows
        }

        # Get row count
        cursor.execute(f"SELECT COUNT(*) as cnt FROM `{database}`.`{table_name}`")
        row_count = cursor.fetchone()["cnt"]

        # Get table status for additional info
        cursor.execute(f"SHOW TABLE STATUS FROM `{database}` LIKE %s", (table_name,))
        status = cursor.fetchone()

        result = []
        for col in columns:
            result.append({
                "name": col["name"],
                "type": col["data_type"],
                "full_type": col["full_type"],
                "max_length": col["max_length"],
                "nullable": col["nullable"] == "YES",
                "default": col["default_value"],
                "primary_key": col["key_type"] == "PRI",
                "unique": col["key_type"] == "UNI",
                "auto_increment": "auto_increment" in (col["extra"] or "").lower(),
                "foreign_key": foreign_keys.get(col["name"]),
                "comment": col["comment"] if col["comment"] else None,
            })

        cursor.close()
        conn.close()

        logger.info(
            "mysql_table_described",
            database=database,
            table=table_name,
            columns=len(result),
        )

        return {
            "database": database,
            "table": table_name,
            "engine": status["Engine"] if status else None,
            "row_count": row_count,
            "column_count": len(result),
            "columns": result,
            "indexes": list(indexes.values()),
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "mysql_describe_table", "mysql")
    except Exception as e:
        logger.error("mysql_describe_table_failed", error=str(e), table=table_name)
        raise ToolExecutionError("mysql_describe_table", str(e), e)


def mysql_execute_query(
    query: str,
    limit: int = 100,
) -> dict[str, Any]:
    """
    Execute a SQL query against MySQL and return results.

    Args:
        query: SQL query to execute
        limit: Maximum number of rows to return (default: 100)

    Returns:
        Dict with query results including rows and column names
    """
    try:
        config = _get_mysql_config()
        conn = _get_mysql_connection()
        cursor = conn.cursor(dictionary=True)

        # Add limit if not present (for SELECT queries)
        query_lower = query.lower().strip()
        if query_lower.startswith("select") and "limit" not in query_lower:
            query = f"{query.rstrip(';')} LIMIT {limit}"

        cursor.execute(query)

        # For SELECT queries
        if cursor.description:
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()

            # Convert special types
            results = []
            for row in rows:
                row_dict = {}
                for col in columns:
                    val = row[col]
                    # Handle special types
                    if hasattr(val, "isoformat"):
                        val = val.isoformat()
                    elif isinstance(val, bytes):
                        val = val.decode("utf-8", errors="replace")
                    elif isinstance(val, set):
                        val = list(val)
                    row_dict[col] = val
                results.append(row_dict)

            cursor.close()
            conn.close()

            logger.info(
                "mysql_query_executed", rows=len(results), query_type="SELECT"
            )

            return {
                "success": True,
                "row_count": len(results),
                "columns": columns,
                "rows": results,
            }
        else:
            # For INSERT/UPDATE/DELETE
            rows_affected = cursor.rowcount
            cursor.close()
            conn.close()

            logger.info("mysql_query_executed", rows_affected=rows_affected)

            return {"success": True, "rows_affected": rows_affected}

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "mysql_execute_query", "mysql")
    except Exception as e:
        logger.error("mysql_query_failed", error=str(e))
        raise ToolExecutionError("mysql_execute_query", str(e), e)


def mysql_show_processlist(full: bool = False) -> dict[str, Any]:
    """
    Show current MySQL processes/connections.

    Useful for identifying:
    - Long-running queries
    - Blocking queries
    - Connection issues
    - Lock contention

    Args:
        full: If True, show full query text (default: False, truncates to 100 chars)

    Returns:
        Dict with active processes
    """
    try:
        conn = _get_mysql_connection()
        cursor = conn.cursor(dictionary=True)

        if full:
            cursor.execute("SHOW FULL PROCESSLIST")
        else:
            cursor.execute("SHOW PROCESSLIST")

        processes = cursor.fetchall()

        result = []
        for proc in processes:
            result.append({
                "id": proc["Id"],
                "user": proc["User"],
                "host": proc["Host"],
                "database": proc["db"],
                "command": proc["Command"],
                "time_seconds": proc["Time"],
                "state": proc["State"],
                "info": proc["Info"],  # Query text
            })

        # Separate into categories
        active_queries = [p for p in result if p["command"] == "Query" and p["info"]]
        sleeping = [p for p in result if p["command"] == "Sleep"]
        long_running = [p for p in result if p["time_seconds"] and p["time_seconds"] > 60]

        cursor.close()
        conn.close()

        logger.info("mysql_processlist_retrieved", total=len(result))

        return {
            "success": True,
            "total_connections": len(result),
            "active_queries": len(active_queries),
            "sleeping_connections": len(sleeping),
            "long_running_queries": len(long_running),
            "processes": result,
            "long_running": long_running,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "mysql_show_processlist", "mysql")
    except Exception as e:
        logger.error("mysql_show_processlist_failed", error=str(e))
        raise ToolExecutionError("mysql_show_processlist", str(e), e)


def mysql_show_slave_status() -> dict[str, Any]:
    """
    Show MySQL replication status (for replicas).

    Returns key metrics:
    - Seconds_Behind_Master: Replication lag
    - Slave_IO_Running: Whether IO thread is running
    - Slave_SQL_Running: Whether SQL thread is running
    - Last_Error: Any replication errors

    Returns:
        Dict with replication status
    """
    try:
        conn = _get_mysql_connection()
        cursor = conn.cursor(dictionary=True)

        # Try MySQL 8.0+ syntax first
        try:
            cursor.execute("SHOW REPLICA STATUS")
        except Exception:
            # Fall back to older syntax
            cursor.execute("SHOW SLAVE STATUS")

        status = cursor.fetchone()

        cursor.close()
        conn.close()

        if not status:
            return {
                "success": True,
                "is_replica": False,
                "message": "This server is not configured as a replica",
            }

        # Extract key metrics
        result = {
            "success": True,
            "is_replica": True,
            "master_host": status.get("Master_Host") or status.get("Source_Host"),
            "master_port": status.get("Master_Port") or status.get("Source_Port"),
            "master_user": status.get("Master_User") or status.get("Source_User"),

            # Replication status
            "io_running": status.get("Slave_IO_Running") or status.get("Replica_IO_Running"),
            "sql_running": status.get("Slave_SQL_Running") or status.get("Replica_SQL_Running"),
            "seconds_behind_master": status.get("Seconds_Behind_Master") or status.get("Seconds_Behind_Source"),

            # Position info
            "master_log_file": status.get("Master_Log_File") or status.get("Source_Log_File"),
            "read_master_log_pos": status.get("Read_Master_Log_Pos") or status.get("Read_Source_Log_Pos"),
            "relay_log_file": status.get("Relay_Log_File"),
            "relay_log_pos": status.get("Relay_Log_Pos"),
            "exec_master_log_pos": status.get("Exec_Master_Log_Pos") or status.get("Exec_Source_Log_Pos"),

            # Errors
            "last_io_error": status.get("Last_IO_Error") or status.get("Last_IO_Error_Message"),
            "last_sql_error": status.get("Last_SQL_Error") or status.get("Last_SQL_Error_Message"),
            "last_io_errno": status.get("Last_IO_Errno"),
            "last_sql_errno": status.get("Last_SQL_Errno"),

            # GTID (if enabled)
            "gtid_mode": status.get("Retrieved_Gtid_Set") is not None,
            "retrieved_gtid_set": status.get("Retrieved_Gtid_Set"),
            "executed_gtid_set": status.get("Executed_Gtid_Set"),
        }

        # Determine health status
        io_ok = result["io_running"] in ("Yes", True)
        sql_ok = result["sql_running"] in ("Yes", True)
        lag = result["seconds_behind_master"]

        if io_ok and sql_ok and (lag is None or lag < 30):
            result["health"] = "healthy"
        elif io_ok and sql_ok and lag < 300:
            result["health"] = "lagging"
        elif io_ok and sql_ok:
            result["health"] = "severely_lagging"
        else:
            result["health"] = "broken"

        logger.info(
            "mysql_slave_status_retrieved",
            health=result["health"],
            lag=lag,
        )

        return result

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "mysql_show_slave_status", "mysql")
    except Exception as e:
        logger.error("mysql_show_slave_status_failed", error=str(e))
        raise ToolExecutionError("mysql_show_slave_status", str(e), e)


def mysql_show_engine_status(engine: str = "innodb") -> dict[str, Any]:
    """
    Show MySQL engine status (primarily InnoDB).

    Useful for identifying:
    - Lock waits and deadlocks
    - Buffer pool status
    - Transaction status
    - I/O status

    Args:
        engine: Storage engine (default: innodb)

    Returns:
        Dict with parsed engine status
    """
    try:
        conn = _get_mysql_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(f"SHOW ENGINE {engine.upper()} STATUS")
        status = cursor.fetchone()

        cursor.close()
        conn.close()

        if not status:
            return {
                "success": True,
                "engine": engine,
                "message": f"No status available for {engine}",
            }

        raw_status = status.get("Status", "")

        # Parse key sections from InnoDB status
        result = {
            "success": True,
            "engine": engine,
            "raw_status": raw_status[:5000] if len(raw_status) > 5000 else raw_status,
        }

        # Extract deadlock info if present
        if "LATEST DETECTED DEADLOCK" in raw_status:
            start = raw_status.find("LATEST DETECTED DEADLOCK")
            end = raw_status.find("---", start + 100)
            result["deadlock_info"] = raw_status[start:end] if end > start else raw_status[start:start+2000]
            result["has_recent_deadlock"] = True
        else:
            result["has_recent_deadlock"] = False

        # Extract transaction info
        if "TRANSACTIONS" in raw_status:
            start = raw_status.find("TRANSACTIONS")
            end = raw_status.find("---", start + 50)
            result["transactions_section"] = raw_status[start:end] if end > start else raw_status[start:start+1000]

        # Extract lock waits
        if "LOCK WAIT" in raw_status:
            result["has_lock_waits"] = True
        else:
            result["has_lock_waits"] = False

        logger.info(
            "mysql_engine_status_retrieved",
            engine=engine,
            has_deadlock=result["has_recent_deadlock"],
        )

        return result

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "mysql_show_engine_status", "mysql")
    except Exception as e:
        logger.error("mysql_show_engine_status_failed", error=str(e))
        raise ToolExecutionError("mysql_show_engine_status", str(e), e)


def mysql_get_table_locks() -> dict[str, Any]:
    """
    Get information about current table locks and lock waits.

    Returns:
        Dict with lock information from performance_schema
    """
    try:
        conn = _get_mysql_connection()
        cursor = conn.cursor(dictionary=True)

        # Check if performance_schema is available
        cursor.execute("SELECT @@performance_schema as ps_enabled")
        ps_enabled = cursor.fetchone()["ps_enabled"]

        if not ps_enabled:
            cursor.close()
            conn.close()
            return {
                "success": True,
                "message": "performance_schema is not enabled",
                "locks": [],
            }

        # Get current locks
        lock_query = """
            SELECT
                OBJECT_SCHEMA as `database`,
                OBJECT_NAME as `table`,
                LOCK_TYPE as lock_type,
                LOCK_MODE as lock_mode,
                LOCK_STATUS as status,
                OWNER_THREAD_ID as thread_id
            FROM performance_schema.metadata_locks
            WHERE OBJECT_TYPE = 'TABLE'
            ORDER BY OBJECT_SCHEMA, OBJECT_NAME
        """

        try:
            cursor.execute(lock_query)
            locks = cursor.fetchall()
        except Exception:
            # Fallback for older MySQL versions
            locks = []

        # Get lock waits
        wait_query = """
            SELECT
                r.trx_id AS waiting_trx_id,
                r.trx_mysql_thread_id AS waiting_thread,
                r.trx_query AS waiting_query,
                b.trx_id AS blocking_trx_id,
                b.trx_mysql_thread_id AS blocking_thread,
                b.trx_query AS blocking_query
            FROM information_schema.innodb_lock_waits w
            JOIN information_schema.innodb_trx b ON b.trx_id = w.blocking_trx_id
            JOIN information_schema.innodb_trx r ON r.trx_id = w.requesting_trx_id
        """

        try:
            cursor.execute(wait_query)
            waits = cursor.fetchall()
        except Exception:
            # Table doesn't exist in MySQL 8.0+ (use performance_schema instead)
            try:
                wait_query_8 = """
                    SELECT
                        r.REQUESTING_ENGINE_TRANSACTION_ID AS waiting_trx_id,
                        r.REQUESTING_THREAD_ID AS waiting_thread,
                        b.BLOCKING_ENGINE_TRANSACTION_ID AS blocking_trx_id,
                        b.BLOCKING_THREAD_ID AS blocking_thread
                    FROM performance_schema.data_lock_waits r
                    JOIN performance_schema.data_lock_waits b
                        ON r.BLOCKING_ENGINE_LOCK_ID = b.REQUESTING_ENGINE_LOCK_ID
                    LIMIT 100
                """
                cursor.execute(wait_query_8)
                waits = cursor.fetchall()
            except Exception:
                waits = []

        cursor.close()
        conn.close()

        logger.info(
            "mysql_table_locks_retrieved",
            lock_count=len(locks),
            wait_count=len(waits),
        )

        return {
            "success": True,
            "lock_count": len(locks),
            "wait_count": len(waits),
            "locks": locks,
            "lock_waits": waits,
            "has_contention": len(waits) > 0,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "mysql_get_table_locks", "mysql")
    except Exception as e:
        logger.error("mysql_get_table_locks_failed", error=str(e))
        raise ToolExecutionError("mysql_get_table_locks", str(e), e)


# List of all MySQL tools for registration
MYSQL_TOOLS = [
    mysql_list_tables,
    mysql_describe_table,
    mysql_execute_query,
    mysql_show_processlist,
    mysql_show_slave_status,
    mysql_show_engine_status,
    mysql_get_table_locks,
]

"""PostgreSQL tools for database queries and schema inspection.

Supports:
- AWS RDS PostgreSQL
- AWS Aurora PostgreSQL
- Standard PostgreSQL
- Any PostgreSQL-compatible database
"""

import os
from typing import Any

from ..core.config_required import handle_integration_not_configured
from ..core.errors import ToolExecutionError
from ..core.execution_context import get_execution_context
from ..core.integration_errors import IntegrationNotConfiguredError
from ..core.logging import get_logger

logger = get_logger(__name__)


def _get_postgres_config() -> dict:
    """Get PostgreSQL configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("postgresql")
        if config and config.get("host") and config.get("database"):
            return config

    # 2. Try environment variables (dev/testing fallback)
    if os.getenv("POSTGRES_HOST") and os.getenv("POSTGRES_DATABASE"):
        return {
            "host": os.getenv("POSTGRES_HOST"),
            "port": int(os.getenv("POSTGRES_PORT", "5432")),
            "database": os.getenv("POSTGRES_DATABASE"),
            "user": os.getenv("POSTGRES_USER"),
            "password": os.getenv("POSTGRES_PASSWORD"),
            "schema": os.getenv("POSTGRES_SCHEMA", "public"),
            "ssl_mode": os.getenv("POSTGRES_SSL_MODE", "prefer"),
        }

    # 3. Not configured - raise error
    raise IntegrationNotConfiguredError(
        integration_id="postgresql",
        tool_id="postgres_tools",
        missing_fields=["host", "database", "user", "password"],
    )


def _get_postgres_connection():
    """Get PostgreSQL connection using configured credentials."""
    try:
        import psycopg2
    except ImportError:
        raise ToolExecutionError(
            "postgres",
            "psycopg2 not installed. Install with: pip install psycopg2-binary",
        )

    config = _get_postgres_config()

    # Build connection kwargs
    conn_kwargs = {
        "host": config["host"],
        "port": config.get("port", 5432),
        "database": config["database"],
        "user": config.get("user"),
        "password": config.get("password"),
    }

    # Add SSL mode if specified
    ssl_mode = config.get("ssl_mode")
    if ssl_mode and ssl_mode != "disable":
        conn_kwargs["sslmode"] = ssl_mode

    return psycopg2.connect(**conn_kwargs)


def postgres_list_tables(schema: str | None = None) -> dict[str, Any]:
    """
    List all tables in a PostgreSQL database schema.

    Args:
        schema: Schema name (uses config default if not specified)

    Returns:
        Dict with table list including names and sizes
    """
    try:
        config = _get_postgres_config()
        schema = schema or config.get("schema", "public")

        conn = _get_postgres_connection()
        cursor = conn.cursor()

        query = """
            SELECT
                table_name,
                pg_total_relation_size(quote_ident(table_schema) || '.' || quote_ident(table_name)) as size_bytes
            FROM information_schema.tables
            WHERE table_schema = %s AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """

        cursor.execute(query, (schema,))
        tables = cursor.fetchall()

        result = []
        for table in tables:
            result.append(
                {
                    "table_name": table[0],
                    "size_bytes": table[1],
                    "size_mb": round(table[1] / (1024 * 1024), 2) if table[1] else 0,
                }
            )

        cursor.close()
        conn.close()

        logger.info("postgres_tables_listed", schema=schema, count=len(result))

        return {
            "database": config["database"],
            "schema": schema,
            "table_count": len(result),
            "tables": result,
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "postgres_list_tables", "postgresql"
        )
    except Exception as e:
        logger.error("postgres_list_tables_failed", error=str(e))
        raise ToolExecutionError("postgres_list_tables", str(e), e)


def postgres_describe_table(
    table_name: str, schema: str | None = None
) -> dict[str, Any]:
    """
    Get column details for a PostgreSQL table.

    Args:
        table_name: Table name
        schema: Schema name (uses config default if not specified)

    Returns:
        Dict with table schema including columns, primary keys, and foreign keys
    """
    try:
        config = _get_postgres_config()
        schema = schema or config.get("schema", "public")

        conn = _get_postgres_connection()
        cursor = conn.cursor()

        # Get columns
        query = """
            SELECT
                column_name,
                data_type,
                character_maximum_length,
                is_nullable,
                column_default
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
        """

        cursor.execute(query, (schema, table_name))
        columns = cursor.fetchall()

        # Get primary keys
        pk_query = """
            SELECT a.attname
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = %s::regclass AND i.indisprimary
        """

        cursor.execute(pk_query, (f"{schema}.{table_name}",))
        primary_keys = {row[0] for row in cursor.fetchall()}

        # Get foreign keys
        fk_query = """
            SELECT
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage AS ccu
                ON ccu.constraint_name = tc.constraint_name
                AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
                AND tc.table_schema = %s
                AND tc.table_name = %s
        """

        cursor.execute(fk_query, (schema, table_name))
        foreign_keys = {
            row[0]: {"foreign_table": row[1], "foreign_column": row[2]}
            for row in cursor.fetchall()
        }

        # Get row count
        count_query = f'SELECT COUNT(*) FROM "{schema}"."{table_name}"'
        cursor.execute(count_query)
        row_count = cursor.fetchone()[0]

        result = []
        for col in columns:
            col_name = col[0]
            result.append(
                {
                    "name": col_name,
                    "type": col[1],
                    "max_length": col[2],
                    "nullable": col[3] == "YES",
                    "default": col[4],
                    "primary_key": col_name in primary_keys,
                    "foreign_key": foreign_keys.get(col_name),
                }
            )

        cursor.close()
        conn.close()

        logger.info(
            "postgres_table_described",
            schema=schema,
            table=table_name,
            columns=len(result),
        )

        return {
            "database": config["database"],
            "schema": schema,
            "table": table_name,
            "row_count": row_count,
            "column_count": len(result),
            "columns": result,
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "postgres_describe_table", "postgresql"
        )
    except Exception as e:
        logger.error("postgres_describe_table_failed", error=str(e), table=table_name)
        raise ToolExecutionError("postgres_describe_table", str(e), e)


def postgres_execute_query(
    query: str,
    limit: int = 100,
) -> dict[str, Any]:
    """
    Execute a SQL query against PostgreSQL and return results.

    Args:
        query: SQL query to execute
        limit: Maximum number of rows to return (default: 100)

    Returns:
        Dict with query results including rows and column names
    """
    try:
        from psycopg2.extras import RealDictCursor
    except ImportError:
        raise ToolExecutionError(
            "postgres",
            "psycopg2 not installed. Install with: pip install psycopg2-binary",
        )

    try:
        config = _get_postgres_config()
        conn = _get_postgres_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Add limit if not present
        query_lower = query.lower().strip()
        if "limit" not in query_lower:
            query = f"{query.rstrip(';')} LIMIT {limit}"

        cursor.execute(query)

        # For SELECT queries
        if cursor.description:
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()

            # Convert to list of dicts
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
                    row_dict[col] = val
                results.append(row_dict)

            cursor.close()
            conn.close()

            logger.info(
                "postgres_query_executed", rows=len(results), query_hash=hash(query)
            )

            return {
                "success": True,
                "row_count": len(results),
                "columns": columns,
                "rows": results,
            }
        else:
            # For INSERT/UPDATE/DELETE
            conn.commit()
            rows_affected = cursor.rowcount
            cursor.close()
            conn.close()

            logger.info("postgres_query_executed", rows_affected=rows_affected)

            return {"success": True, "rows_affected": rows_affected}

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "postgres_execute_query", "postgresql"
        )
    except Exception as e:
        logger.error("postgres_query_failed", error=str(e))
        raise ToolExecutionError("postgres_execute_query", str(e), e)


def postgres_list_indexes(
    table_name: str | None = None, schema: str | None = None
) -> dict[str, Any]:
    """
    List indexes in a PostgreSQL database, optionally filtered by table.

    Args:
        table_name: Optional table name to filter indexes
        schema: Schema name (uses config default if not specified)

    Returns:
        Dict with index list including names, columns, types, and sizes
    """
    try:
        config = _get_postgres_config()
        schema = schema or config.get("schema", "public")

        conn = _get_postgres_connection()
        cursor = conn.cursor()

        query = """
            SELECT
                i.relname AS index_name,
                t.relname AS table_name,
                a.attname AS column_name,
                am.amname AS index_type,
                ix.indisunique AS is_unique,
                ix.indisprimary AS is_primary,
                pg_relation_size(i.oid) AS index_size_bytes,
                pg_size_pretty(pg_relation_size(i.oid)) AS index_size
            FROM pg_index ix
            JOIN pg_class t ON t.oid = ix.indrelid
            JOIN pg_class i ON i.oid = ix.indexrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            JOIN pg_am am ON am.oid = i.relam
            LEFT JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
            WHERE n.nspname = %s
        """

        params = [schema]
        if table_name:
            query += " AND t.relname = %s"
            params.append(table_name)

        query += " ORDER BY t.relname, i.relname, a.attnum"

        cursor.execute(query, params)
        rows = cursor.fetchall()

        # Group by index
        indexes = {}
        for row in rows:
            idx_name = row[0]
            if idx_name not in indexes:
                indexes[idx_name] = {
                    "index_name": row[0],
                    "table_name": row[1],
                    "columns": [],
                    "index_type": row[3],
                    "is_unique": row[4],
                    "is_primary": row[5],
                    "size_bytes": row[6],
                    "size": row[7],
                }
            if row[2]:  # column_name
                indexes[idx_name]["columns"].append(row[2])

        cursor.close()
        conn.close()

        result = list(indexes.values())

        logger.info("postgres_indexes_listed", schema=schema, count=len(result))

        return {
            "database": config["database"],
            "schema": schema,
            "table": table_name,
            "index_count": len(result),
            "indexes": result,
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "postgres_list_indexes", "postgresql"
        )
    except Exception as e:
        logger.error("postgres_list_indexes_failed", error=str(e))
        raise ToolExecutionError("postgres_list_indexes", str(e), e)


def postgres_list_constraints(
    table_name: str | None = None, schema: str | None = None
) -> dict[str, Any]:
    """
    List constraints in a PostgreSQL database, optionally filtered by table.

    Args:
        table_name: Optional table name to filter constraints
        schema: Schema name (uses config default if not specified)

    Returns:
        Dict with constraints including primary keys, foreign keys, checks, unique
    """
    try:
        config = _get_postgres_config()
        schema = schema or config.get("schema", "public")

        conn = _get_postgres_connection()
        cursor = conn.cursor()

        query = """
            SELECT
                tc.constraint_name,
                tc.table_name,
                tc.constraint_type,
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name,
                cc.check_clause
            FROM information_schema.table_constraints tc
            LEFT JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            LEFT JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
                AND tc.table_schema = ccu.table_schema
            LEFT JOIN information_schema.check_constraints cc
                ON tc.constraint_name = cc.constraint_name
                AND tc.table_schema = cc.constraint_schema
            WHERE tc.table_schema = %s
        """

        params = [schema]
        if table_name:
            query += " AND tc.table_name = %s"
            params.append(table_name)

        query += " ORDER BY tc.table_name, tc.constraint_type, tc.constraint_name"

        cursor.execute(query, params)
        rows = cursor.fetchall()

        # Group by constraint
        constraints = {}
        for row in rows:
            const_name = row[0]
            if const_name not in constraints:
                constraints[const_name] = {
                    "constraint_name": row[0],
                    "table_name": row[1],
                    "constraint_type": row[2],
                    "columns": [],
                    "foreign_table": row[4] if row[2] == "FOREIGN KEY" else None,
                    "foreign_column": row[5] if row[2] == "FOREIGN KEY" else None,
                    "check_clause": row[6] if row[2] == "CHECK" else None,
                }
            if row[3] and row[3] not in constraints[const_name]["columns"]:
                constraints[const_name]["columns"].append(row[3])

        cursor.close()
        conn.close()

        result = list(constraints.values())

        # Categorize
        primary_keys = [c for c in result if c["constraint_type"] == "PRIMARY KEY"]
        foreign_keys = [c for c in result if c["constraint_type"] == "FOREIGN KEY"]
        unique = [c for c in result if c["constraint_type"] == "UNIQUE"]
        checks = [c for c in result if c["constraint_type"] == "CHECK"]

        logger.info("postgres_constraints_listed", schema=schema, count=len(result))

        return {
            "database": config["database"],
            "schema": schema,
            "table": table_name,
            "total_count": len(result),
            "primary_keys": primary_keys,
            "foreign_keys": foreign_keys,
            "unique_constraints": unique,
            "check_constraints": checks,
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "postgres_list_constraints", "postgresql"
        )
    except Exception as e:
        logger.error("postgres_list_constraints_failed", error=str(e))
        raise ToolExecutionError("postgres_list_constraints", str(e), e)


def postgres_get_table_size(
    table_name: str | None = None, schema: str | None = None
) -> dict[str, Any]:
    """
    Get detailed size information for PostgreSQL tables.

    Args:
        table_name: Optional table name (returns all tables if not specified)
        schema: Schema name (uses config default if not specified)

    Returns:
        Dict with table sizes including data, indexes, toast, and total
    """
    try:
        config = _get_postgres_config()
        schema = schema or config.get("schema", "public")

        conn = _get_postgres_connection()
        cursor = conn.cursor()

        query = """
            SELECT
                t.relname AS table_name,
                pg_table_size(t.oid) AS table_bytes,
                pg_indexes_size(t.oid) AS indexes_bytes,
                pg_total_relation_size(t.oid) AS total_bytes,
                COALESCE(pg_total_relation_size(t.reltoastrelid), 0) AS toast_bytes,
                pg_size_pretty(pg_table_size(t.oid)) AS table_size,
                pg_size_pretty(pg_indexes_size(t.oid)) AS indexes_size,
                pg_size_pretty(pg_total_relation_size(t.oid)) AS total_size,
                c.reltuples::bigint AS estimated_rows
            FROM pg_class t
            JOIN pg_namespace n ON n.oid = t.relnamespace
            LEFT JOIN pg_class c ON c.oid = t.oid
            WHERE n.nspname = %s
                AND t.relkind = 'r'
        """

        params = [schema]
        if table_name:
            query += " AND t.relname = %s"
            params.append(table_name)

        query += " ORDER BY pg_total_relation_size(t.oid) DESC"

        cursor.execute(query, params)
        rows = cursor.fetchall()

        result = []
        total_table_bytes = 0
        total_index_bytes = 0
        total_bytes = 0

        for row in rows:
            table_info = {
                "table_name": row[0],
                "table_bytes": row[1],
                "indexes_bytes": row[2],
                "total_bytes": row[3],
                "toast_bytes": row[4],
                "table_size": row[5],
                "indexes_size": row[6],
                "total_size": row[7],
                "estimated_rows": row[8],
            }
            result.append(table_info)
            total_table_bytes += row[1] or 0
            total_index_bytes += row[2] or 0
            total_bytes += row[3] or 0

        cursor.close()
        conn.close()

        logger.info("postgres_table_size_retrieved", schema=schema, count=len(result))

        return {
            "database": config["database"],
            "schema": schema,
            "table_count": len(result),
            "total_table_bytes": total_table_bytes,
            "total_index_bytes": total_index_bytes,
            "total_bytes": total_bytes,
            "total_size_pretty": f"{total_bytes / (1024*1024*1024):.2f} GB",
            "tables": result,
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "postgres_get_table_size", "postgresql"
        )
    except Exception as e:
        logger.error("postgres_get_table_size_failed", error=str(e))
        raise ToolExecutionError("postgres_get_table_size", str(e), e)


def postgres_get_locks() -> dict[str, Any]:
    """
    Get current locks and lock waits in PostgreSQL.

    Useful for identifying:
    - Blocking queries
    - Lock contention
    - Deadlocks

    Returns:
        Dict with active locks and any blocking relationships
    """
    try:
        config = _get_postgres_config()
        conn = _get_postgres_connection()
        cursor = conn.cursor()

        # Get current locks
        lock_query = """
            SELECT
                l.locktype,
                l.relation::regclass AS table_name,
                l.mode,
                l.granted,
                l.pid,
                a.usename AS user,
                a.query,
                a.state,
                age(now(), a.query_start) AS duration,
                a.wait_event_type,
                a.wait_event
            FROM pg_locks l
            JOIN pg_stat_activity a ON l.pid = a.pid
            WHERE l.relation IS NOT NULL
            ORDER BY a.query_start
        """

        cursor.execute(lock_query)
        lock_rows = cursor.fetchall()

        locks = []
        for row in lock_rows:
            locks.append({
                "lock_type": row[0],
                "table_name": str(row[1]) if row[1] else None,
                "mode": row[2],
                "granted": row[3],
                "pid": row[4],
                "user": row[5],
                "query": row[6][:200] if row[6] else None,
                "state": row[7],
                "duration": str(row[8]) if row[8] else None,
                "wait_event_type": row[9],
                "wait_event": row[10],
            })

        # Get blocking queries
        blocking_query = """
            SELECT
                blocked_locks.pid AS blocked_pid,
                blocked_activity.usename AS blocked_user,
                blocked_activity.query AS blocked_query,
                blocking_locks.pid AS blocking_pid,
                blocking_activity.usename AS blocking_user,
                blocking_activity.query AS blocking_query,
                age(now(), blocked_activity.query_start) AS blocked_duration
            FROM pg_catalog.pg_locks blocked_locks
            JOIN pg_catalog.pg_stat_activity blocked_activity
                ON blocked_activity.pid = blocked_locks.pid
            JOIN pg_catalog.pg_locks blocking_locks
                ON blocking_locks.locktype = blocked_locks.locktype
                AND blocking_locks.database IS NOT DISTINCT FROM blocked_locks.database
                AND blocking_locks.relation IS NOT DISTINCT FROM blocked_locks.relation
                AND blocking_locks.page IS NOT DISTINCT FROM blocked_locks.page
                AND blocking_locks.tuple IS NOT DISTINCT FROM blocked_locks.tuple
                AND blocking_locks.virtualxid IS NOT DISTINCT FROM blocked_locks.virtualxid
                AND blocking_locks.transactionid IS NOT DISTINCT FROM blocked_locks.transactionid
                AND blocking_locks.classid IS NOT DISTINCT FROM blocked_locks.classid
                AND blocking_locks.objid IS NOT DISTINCT FROM blocked_locks.objid
                AND blocking_locks.objsubid IS NOT DISTINCT FROM blocked_locks.objsubid
                AND blocking_locks.pid != blocked_locks.pid
            JOIN pg_catalog.pg_stat_activity blocking_activity
                ON blocking_activity.pid = blocking_locks.pid
            WHERE NOT blocked_locks.granted
        """

        cursor.execute(blocking_query)
        blocking_rows = cursor.fetchall()

        blocking = []
        for row in blocking_rows:
            blocking.append({
                "blocked_pid": row[0],
                "blocked_user": row[1],
                "blocked_query": row[2][:200] if row[2] else None,
                "blocking_pid": row[3],
                "blocking_user": row[4],
                "blocking_query": row[5][:200] if row[5] else None,
                "blocked_duration": str(row[6]) if row[6] else None,
            })

        cursor.close()
        conn.close()

        waiting_locks = [l for l in locks if not l["granted"]]

        logger.info(
            "postgres_locks_retrieved",
            total=len(locks),
            waiting=len(waiting_locks),
            blocking=len(blocking),
        )

        return {
            "database": config["database"],
            "total_locks": len(locks),
            "waiting_locks": len(waiting_locks),
            "blocking_relationships": len(blocking),
            "has_contention": len(blocking) > 0,
            "locks": locks,
            "blocking": blocking,
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "postgres_get_locks", "postgresql")
    except Exception as e:
        logger.error("postgres_get_locks_failed", error=str(e))
        raise ToolExecutionError("postgres_get_locks", str(e), e)


def postgres_get_replication_status() -> dict[str, Any]:
    """
    Get PostgreSQL replication status.

    Returns information about:
    - Replication slots
    - Streaming replicas
    - Replication lag

    Returns:
        Dict with replication status
    """
    try:
        config = _get_postgres_config()
        conn = _get_postgres_connection()
        cursor = conn.cursor()

        # Check if this is a primary or standby
        cursor.execute("SELECT pg_is_in_recovery()")
        is_standby = cursor.fetchone()[0]

        result = {
            "database": config["database"],
            "is_standby": is_standby,
            "success": True,
        }

        if is_standby:
            # Get standby status
            standby_query = """
                SELECT
                    pg_last_wal_receive_lsn() AS receive_lsn,
                    pg_last_wal_replay_lsn() AS replay_lsn,
                    pg_last_xact_replay_timestamp() AS last_replay_time,
                    EXTRACT(EPOCH FROM (now() - pg_last_xact_replay_timestamp())) AS lag_seconds
            """
            cursor.execute(standby_query)
            standby = cursor.fetchone()

            result["standby_status"] = {
                "receive_lsn": str(standby[0]) if standby[0] else None,
                "replay_lsn": str(standby[1]) if standby[1] else None,
                "last_replay_time": standby[2].isoformat() if standby[2] else None,
                "lag_seconds": float(standby[3]) if standby[3] else None,
            }

            # Determine health
            lag = result["standby_status"]["lag_seconds"]
            if lag is None:
                result["health"] = "unknown"
            elif lag < 10:
                result["health"] = "healthy"
            elif lag < 60:
                result["health"] = "lagging"
            elif lag < 300:
                result["health"] = "severely_lagging"
            else:
                result["health"] = "critical"

        else:
            # Get primary replication status
            repl_query = """
                SELECT
                    client_addr,
                    state,
                    sent_lsn,
                    write_lsn,
                    flush_lsn,
                    replay_lsn,
                    pg_wal_lsn_diff(sent_lsn, replay_lsn) AS lag_bytes,
                    sync_state,
                    application_name
                FROM pg_stat_replication
            """

            cursor.execute(repl_query)
            repl_rows = cursor.fetchall()

            replicas = []
            for row in repl_rows:
                replicas.append({
                    "client_addr": str(row[0]) if row[0] else None,
                    "state": row[1],
                    "sent_lsn": str(row[2]) if row[2] else None,
                    "write_lsn": str(row[3]) if row[3] else None,
                    "flush_lsn": str(row[4]) if row[4] else None,
                    "replay_lsn": str(row[5]) if row[5] else None,
                    "lag_bytes": row[6],
                    "sync_state": row[7],
                    "application_name": row[8],
                })

            result["replicas"] = replicas
            result["replica_count"] = len(replicas)

            # Get replication slots
            slot_query = """
                SELECT
                    slot_name,
                    slot_type,
                    active,
                    pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) AS lag_bytes
                FROM pg_replication_slots
            """

            cursor.execute(slot_query)
            slot_rows = cursor.fetchall()

            slots = []
            for row in slot_rows:
                slots.append({
                    "slot_name": row[0],
                    "slot_type": row[1],
                    "active": row[2],
                    "lag_bytes": row[3],
                })

            result["replication_slots"] = slots
            result["slot_count"] = len(slots)

            # Determine health
            max_lag = max([r["lag_bytes"] or 0 for r in replicas], default=0)
            if len(replicas) == 0:
                result["health"] = "no_replicas"
            elif max_lag < 1024 * 1024:  # < 1MB
                result["health"] = "healthy"
            elif max_lag < 100 * 1024 * 1024:  # < 100MB
                result["health"] = "lagging"
            else:
                result["health"] = "severely_lagging"

        cursor.close()
        conn.close()

        logger.info(
            "postgres_replication_status_retrieved",
            is_standby=is_standby,
            health=result.get("health"),
        )

        return result

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "postgres_get_replication_status", "postgresql"
        )
    except Exception as e:
        logger.error("postgres_get_replication_status_failed", error=str(e))
        raise ToolExecutionError("postgres_get_replication_status", str(e), e)


def postgres_get_long_running_queries(min_duration_seconds: int = 60) -> dict[str, Any]:
    """
    Get long-running queries in PostgreSQL.

    Args:
        min_duration_seconds: Minimum duration to include (default: 60 seconds)

    Returns:
        Dict with long-running queries
    """
    try:
        config = _get_postgres_config()
        conn = _get_postgres_connection()
        cursor = conn.cursor()

        query = """
            SELECT
                pid,
                usename AS user,
                datname AS database,
                state,
                query,
                query_start,
                EXTRACT(EPOCH FROM (now() - query_start)) AS duration_seconds,
                wait_event_type,
                wait_event,
                client_addr,
                application_name
            FROM pg_stat_activity
            WHERE state != 'idle'
                AND query NOT LIKE '%pg_stat_activity%'
                AND EXTRACT(EPOCH FROM (now() - query_start)) > %s
            ORDER BY query_start
        """

        cursor.execute(query, (min_duration_seconds,))
        rows = cursor.fetchall()

        queries = []
        for row in rows:
            queries.append({
                "pid": row[0],
                "user": row[1],
                "database": row[2],
                "state": row[3],
                "query": row[4][:500] if row[4] else None,
                "query_start": row[5].isoformat() if row[5] else None,
                "duration_seconds": round(row[6], 1) if row[6] else None,
                "wait_event_type": row[7],
                "wait_event": row[8],
                "client_addr": str(row[9]) if row[9] else None,
                "application_name": row[10],
            })

        cursor.close()
        conn.close()

        logger.info(
            "postgres_long_running_queries_retrieved",
            count=len(queries),
            min_duration=min_duration_seconds,
        )

        return {
            "database": config["database"],
            "min_duration_seconds": min_duration_seconds,
            "query_count": len(queries),
            "queries": queries,
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "postgres_get_long_running_queries", "postgresql"
        )
    except Exception as e:
        logger.error("postgres_get_long_running_queries_failed", error=str(e))
        raise ToolExecutionError("postgres_get_long_running_queries", str(e), e)


# List of all Postgres tools for registration
POSTGRES_TOOLS = [
    postgres_list_tables,
    postgres_describe_table,
    postgres_execute_query,
    postgres_list_indexes,
    postgres_list_constraints,
    postgres_get_table_size,
    postgres_get_locks,
    postgres_get_replication_status,
    postgres_get_long_running_queries,
]

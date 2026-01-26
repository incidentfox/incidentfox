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


# List of all Postgres tools for registration
POSTGRES_TOOLS = [
    postgres_list_tables,
    postgres_describe_table,
    postgres_execute_query,
]

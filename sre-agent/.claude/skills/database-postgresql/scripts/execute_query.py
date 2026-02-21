#!/usr/bin/env python3
"""Execute a read-only SQL query against PostgreSQL.

Security: Only SELECT, SHOW, EXPLAIN, and DESCRIBE statements are allowed.
DML/DDL (INSERT, UPDATE, DELETE, DROP, etc.) is blocked to prevent data modification.
"""

import argparse
import re
import sys

from pg_client import format_output, get_connection

# Allowed read-only statement types (case-insensitive, anchored to start of query)
_READONLY_PATTERN = re.compile(
    r"^\s*(SELECT|SHOW|EXPLAIN|DESCRIBE|WITH)\b", re.IGNORECASE
)


def _validate_readonly(query: str) -> None:
    """Reject non-read-only statements."""
    if not _READONLY_PATTERN.match(query):
        raise ValueError(
            "Only read-only queries are allowed (SELECT, SHOW, EXPLAIN, DESCRIBE, WITH). "
            "DML/DDL statements are blocked for safety."
        )
    # Block semicolons that could enable multi-statement injection
    # (allow trailing semicolon only)
    stripped = query.rstrip().rstrip(";").rstrip()
    if ";" in stripped:
        raise ValueError(
            "Multi-statement queries are not allowed. Submit one query at a time."
        )


def main():
    parser = argparse.ArgumentParser(description="Execute PostgreSQL query (read-only)")
    parser.add_argument("--query", required=True, help="SQL query to execute")
    parser.add_argument(
        "--limit", type=int, default=100, help="Max rows to return (default: 100)"
    )
    args = parser.parse_args()

    try:
        _validate_readonly(args.query)

        from psycopg2.extras import RealDictCursor

        conn = get_connection()
        # Use a read-only transaction for defense-in-depth
        conn.set_session(readonly=True, autocommit=False)
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        query = args.query
        if "limit" not in query.lower():
            query = f"{query.rstrip(';')} LIMIT {args.limit}"

        cursor.execute(query)

        if cursor.description:
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()

            results = []
            for row in rows:
                row_dict = {}
                for col in columns:
                    val = row[col]
                    if hasattr(val, "isoformat"):
                        val = val.isoformat()
                    elif isinstance(val, bytes):
                        val = val.decode("utf-8", errors="replace")
                    row_dict[col] = val
                results.append(row_dict)

            cursor.close()
            conn.close()

            print(
                format_output(
                    {
                        "row_count": len(results),
                        "columns": columns,
                        "rows": results,
                    }
                )
            )
        else:
            cursor.close()
            conn.close()

            print(format_output({"row_count": 0, "columns": [], "rows": []}))

    except Exception as e:
        print(format_output({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()

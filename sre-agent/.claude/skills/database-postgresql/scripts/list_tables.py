#!/usr/bin/env python3
"""List all tables in a PostgreSQL database schema."""

import argparse
import sys

from pg_client import format_output, get_connection, get_default_schema


def main():
    parser = argparse.ArgumentParser(description="List PostgreSQL tables")
    parser.add_argument(
        "--schema", help=f"Schema name (default: {get_default_schema()})"
    )
    args = parser.parse_args()

    schema = args.schema or get_default_schema()

    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                table_name,
                pg_total_relation_size(quote_ident(table_schema) || '.' || quote_ident(table_name)) as size_bytes
            FROM information_schema.tables
            WHERE table_schema = %s AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """,
            (schema,),
        )

        tables = []
        for row in cursor.fetchall():
            tables.append(
                {
                    "table_name": row[0],
                    "size_bytes": row[1],
                    "size_mb": round(row[1] / (1024 * 1024), 2) if row[1] else 0,
                }
            )

        cursor.close()
        conn.close()

        print(
            format_output(
                {
                    "schema": schema,
                    "table_count": len(tables),
                    "tables": tables,
                }
            )
        )

    except Exception as e:
        print(format_output({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Get detailed size information for PostgreSQL tables."""

import argparse
import sys

from pg_client import format_output, get_connection, get_default_schema


def main():
    parser = argparse.ArgumentParser(description="Get PostgreSQL table sizes")
    parser.add_argument("--table", help="Optional table name filter")
    parser.add_argument("--schema", help="Schema name")
    args = parser.parse_args()

    schema = args.schema or get_default_schema()

    try:
        conn = get_connection()
        cursor = conn.cursor()

        query = """
            SELECT
                t.relname AS table_name,
                pg_table_size(t.oid) AS table_bytes,
                pg_indexes_size(t.oid) AS indexes_bytes,
                pg_total_relation_size(t.oid) AS total_bytes,
                pg_size_pretty(pg_table_size(t.oid)) AS table_size,
                pg_size_pretty(pg_indexes_size(t.oid)) AS indexes_size,
                pg_size_pretty(pg_total_relation_size(t.oid)) AS total_size,
                c.reltuples::bigint AS estimated_rows
            FROM pg_class t
            JOIN pg_namespace n ON n.oid = t.relnamespace
            LEFT JOIN pg_class c ON c.oid = t.oid
            WHERE n.nspname = %s AND t.relkind = 'r'
        """
        params = [schema]

        if args.table:
            query += " AND t.relname = %s"
            params.append(args.table)

        query += " ORDER BY pg_total_relation_size(t.oid) DESC"

        cursor.execute(query, params)
        rows = cursor.fetchall()

        tables = []
        total_bytes = 0
        for row in rows:
            tables.append(
                {
                    "table_name": row[0],
                    "table_bytes": row[1],
                    "indexes_bytes": row[2],
                    "total_bytes": row[3],
                    "table_size": row[4],
                    "indexes_size": row[5],
                    "total_size": row[6],
                    "estimated_rows": row[7],
                }
            )
            total_bytes += row[3] or 0

        cursor.close()
        conn.close()

        print(
            format_output(
                {
                    "schema": schema,
                    "table_count": len(tables),
                    "total_bytes": total_bytes,
                    "total_size_pretty": f"{total_bytes / (1024*1024*1024):.2f} GB",
                    "tables": tables,
                }
            )
        )

    except Exception as e:
        print(format_output({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""List indexes in a PostgreSQL database."""

import argparse
import sys

from pg_client import format_output, get_connection, get_default_schema


def main():
    parser = argparse.ArgumentParser(description="List PostgreSQL indexes")
    parser.add_argument("--table", help="Optional table name filter")
    parser.add_argument("--schema", help="Schema name")
    args = parser.parse_args()

    schema = args.schema or get_default_schema()

    try:
        conn = get_connection()
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

        if args.table:
            query += " AND t.relname = %s"
            params.append(args.table)

        query += " ORDER BY t.relname, i.relname, a.attnum"

        cursor.execute(query, params)
        rows = cursor.fetchall()

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
            if row[2]:
                indexes[idx_name]["columns"].append(row[2])

        cursor.close()
        conn.close()

        result = list(indexes.values())

        print(
            format_output(
                {
                    "schema": schema,
                    "table": args.table,
                    "index_count": len(result),
                    "indexes": result,
                }
            )
        )

    except Exception as e:
        print(format_output({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()

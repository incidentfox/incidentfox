#!/usr/bin/env python3
"""Get column details for a PostgreSQL table."""

import argparse
import sys

from pg_client import format_output, get_connection, get_default_schema


def main():
    parser = argparse.ArgumentParser(description="Describe PostgreSQL table")
    parser.add_argument("--table", required=True, help="Table name")
    parser.add_argument("--schema", help="Schema name")
    args = parser.parse_args()

    schema = args.schema or get_default_schema()

    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Get columns
        cursor.execute(
            """
            SELECT column_name, data_type, character_maximum_length, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
        """,
            (schema, args.table),
        )
        columns_raw = cursor.fetchall()

        # Get primary keys
        cursor.execute(
            """
            SELECT a.attname
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = %s::regclass AND i.indisprimary
        """,
            (f"{schema}.{args.table}",),
        )
        primary_keys = {row[0] for row in cursor.fetchall()}

        # Get foreign keys
        cursor.execute(
            """
            SELECT kcu.column_name, ccu.table_name, ccu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
                ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = %s AND tc.table_name = %s
        """,
            (schema, args.table),
        )
        foreign_keys = {
            row[0]: {"foreign_table": row[1], "foreign_column": row[2]}
            for row in cursor.fetchall()
        }

        # Get row count
        cursor.execute(f'SELECT COUNT(*) FROM "{schema}"."{args.table}"')
        row_count = cursor.fetchone()[0]

        columns = []
        for col in columns_raw:
            columns.append(
                {
                    "name": col[0],
                    "type": col[1],
                    "max_length": col[2],
                    "nullable": col[3] == "YES",
                    "default": col[4],
                    "primary_key": col[0] in primary_keys,
                    "foreign_key": foreign_keys.get(col[0]),
                }
            )

        cursor.close()
        conn.close()

        print(
            format_output(
                {
                    "schema": schema,
                    "table": args.table,
                    "row_count": row_count,
                    "column_count": len(columns),
                    "columns": columns,
                }
            )
        )

    except Exception as e:
        print(format_output({"error": str(e), "table": args.table}))
        sys.exit(1)


if __name__ == "__main__":
    main()

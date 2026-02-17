#!/usr/bin/env python3
"""Get column details for a Snowflake table."""

import argparse
import sys

from snowflake_client import format_output, get_connection


def main():
    parser = argparse.ArgumentParser(description="Describe Snowflake table")
    parser.add_argument("--table", required=True, help="Table name")
    parser.add_argument("--database", help="Database name")
    parser.add_argument("--schema", help="Schema name")
    args = parser.parse_args()

    try:
        conn = get_connection()
        cursor = conn.cursor()

        full_table_name = args.table
        if args.database and args.schema:
            full_table_name = f"{args.database}.{args.schema}.{args.table}"
        elif args.schema:
            full_table_name = f"{args.schema}.{args.table}"

        cursor.execute(f"DESCRIBE TABLE {full_table_name}")
        columns = cursor.fetchall()

        result = []
        for col in columns:
            result.append(
                {
                    "name": col[0],
                    "type": col[1],
                    "kind": col[2],
                    "null": col[3] == "Y",
                    "default": col[4],
                    "primary_key": col[5] == "Y",
                    "unique_key": col[6] == "Y",
                }
            )

        cursor.close()
        conn.close()

        print(
            format_output(
                {
                    "table": args.table,
                    "column_count": len(result),
                    "columns": result,
                }
            )
        )

    except Exception as e:
        print(format_output({"error": str(e), "table": args.table}))
        sys.exit(1)


if __name__ == "__main__":
    main()

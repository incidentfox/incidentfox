#!/usr/bin/env python3
"""List tables in a Snowflake database/schema."""

import argparse
import sys

from snowflake_client import format_output, get_connection


def main():
    parser = argparse.ArgumentParser(description="List Snowflake tables")
    parser.add_argument("--database", help="Database name")
    parser.add_argument("--schema", help="Schema name")
    args = parser.parse_args()

    try:
        conn = get_connection()
        cursor = conn.cursor()

        query = "SHOW TABLES"
        if args.database:
            query += f" IN DATABASE {args.database}"
        if args.schema:
            query += f" IN SCHEMA {args.schema}"

        cursor.execute(query)
        tables = cursor.fetchall()

        result = []
        for table in tables:
            result.append(
                {
                    "name": table[1],
                    "database": table[2],
                    "schema": table[3],
                    "owner": table[4],
                    "rows": table[5],
                    "bytes": table[6],
                    "created": str(table[0]),
                }
            )

        cursor.close()
        conn.close()

        print(
            format_output(
                {
                    "table_count": len(result),
                    "tables": result,
                }
            )
        )

    except Exception as e:
        print(format_output({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()

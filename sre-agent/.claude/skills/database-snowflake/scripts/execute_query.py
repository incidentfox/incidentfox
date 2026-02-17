#!/usr/bin/env python3
"""Execute a SQL query against Snowflake."""

import argparse
import sys

from snowflake_client import format_output, get_connection


def main():
    parser = argparse.ArgumentParser(description="Execute Snowflake query")
    parser.add_argument("--query", required=True, help="SQL query to execute")
    parser.add_argument(
        "--limit", type=int, default=100, help="Max rows to return (default: 100)"
    )
    args = parser.parse_args()

    try:
        conn = get_connection()
        cursor = conn.cursor()

        query = args.query
        if "limit" not in query.lower():
            query = f"{query.rstrip(';')} LIMIT {args.limit}"

        cursor.execute(query)

        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()

        results = []
        for row in rows:
            row_dict = {}
            for i, col in enumerate(columns):
                val = row[i]
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

    except Exception as e:
        print(format_output({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()

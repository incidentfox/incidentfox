#!/usr/bin/env python3
"""List all tables in a MySQL database."""

import argparse
import sys

from mysql_client import format_output, get_config, get_connection


def main():
    parser = argparse.ArgumentParser(description="List MySQL tables")
    parser.add_argument(
        "--database", help="Database name (uses default if not specified)"
    )
    args = parser.parse_args()

    config = get_config()
    database = args.database or config["database"]

    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                TABLE_NAME as table_name, ENGINE as engine,
                TABLE_ROWS as estimated_rows,
                DATA_LENGTH as data_bytes, INDEX_LENGTH as index_bytes,
                (DATA_LENGTH + INDEX_LENGTH) as total_bytes,
                CREATE_TIME as created_at, UPDATE_TIME as updated_at
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_NAME
        """,
            (database,),
        )

        tables = []
        for row in cursor.fetchall():
            tables.append(
                {
                    "table_name": row["table_name"],
                    "engine": row["engine"],
                    "estimated_rows": row["estimated_rows"],
                    "data_mb": round((row["data_bytes"] or 0) / (1024 * 1024), 2),
                    "index_mb": round((row["index_bytes"] or 0) / (1024 * 1024), 2),
                    "total_mb": round((row["total_bytes"] or 0) / (1024 * 1024), 2),
                    "created_at": (
                        row["created_at"].isoformat() if row["created_at"] else None
                    ),
                    "updated_at": (
                        row["updated_at"].isoformat() if row["updated_at"] else None
                    ),
                }
            )

        cursor.close()
        conn.close()

        print(
            format_output(
                {
                    "database": database,
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

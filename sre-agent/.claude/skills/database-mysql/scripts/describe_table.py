#!/usr/bin/env python3
"""Get column details for a MySQL table."""

import argparse
import sys

from mysql_client import format_output, get_config, get_connection


def main():
    parser = argparse.ArgumentParser(description="Describe MySQL table")
    parser.add_argument("--table", required=True, help="Table name")
    parser.add_argument("--database", help="Database name")
    args = parser.parse_args()

    config = get_config()
    database = args.database or config["database"]

    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        # Get columns
        cursor.execute(
            """
            SELECT COLUMN_NAME as name, DATA_TYPE as data_type, COLUMN_TYPE as full_type,
                   CHARACTER_MAXIMUM_LENGTH as max_length, IS_NULLABLE as nullable,
                   COLUMN_DEFAULT as default_value, COLUMN_KEY as key_type,
                   EXTRA as extra, COLUMN_COMMENT as comment
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
            ORDER BY ORDINAL_POSITION
        """,
            (database, args.table),
        )
        columns_raw = cursor.fetchall()

        # Get indexes
        cursor.execute(
            """
            SELECT INDEX_NAME as index_name, COLUMN_NAME as column_name,
                   NON_UNIQUE as non_unique, INDEX_TYPE as index_type
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
            ORDER BY INDEX_NAME, SEQ_IN_INDEX
        """,
            (database, args.table),
        )

        indexes = {}
        for row in cursor.fetchall():
            idx_name = row["index_name"]
            if idx_name not in indexes:
                indexes[idx_name] = {
                    "name": idx_name,
                    "unique": not row["non_unique"],
                    "type": row["index_type"],
                    "columns": [],
                }
            indexes[idx_name]["columns"].append(row["column_name"])

        # Get foreign keys
        cursor.execute(
            """
            SELECT COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME, CONSTRAINT_NAME
            FROM information_schema.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND REFERENCED_TABLE_NAME IS NOT NULL
        """,
            (database, args.table),
        )

        foreign_keys = {
            row["COLUMN_NAME"]: {
                "constraint": row["CONSTRAINT_NAME"],
                "ref_table": row["REFERENCED_TABLE_NAME"],
                "ref_column": row["REFERENCED_COLUMN_NAME"],
            }
            for row in cursor.fetchall()
        }

        # Get row count
        cursor.execute(f"SELECT COUNT(*) as cnt FROM `{database}`.`{args.table}`")
        row_count = cursor.fetchone()["cnt"]

        columns = []
        for col in columns_raw:
            columns.append(
                {
                    "name": col["name"],
                    "type": col["data_type"],
                    "full_type": col["full_type"],
                    "nullable": col["nullable"] == "YES",
                    "default": col["default_value"],
                    "primary_key": col["key_type"] == "PRI",
                    "auto_increment": "auto_increment" in (col["extra"] or "").lower(),
                    "foreign_key": foreign_keys.get(col["name"]),
                    "comment": col["comment"] if col["comment"] else None,
                }
            )

        cursor.close()
        conn.close()

        print(
            format_output(
                {
                    "database": database,
                    "table": args.table,
                    "row_count": row_count,
                    "column_count": len(columns),
                    "columns": columns,
                    "indexes": list(indexes.values()),
                }
            )
        )

    except Exception as e:
        print(format_output({"error": str(e), "table": args.table}))
        sys.exit(1)


if __name__ == "__main__":
    main()

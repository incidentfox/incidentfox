#!/usr/bin/env python3
"""Get schema for a BigQuery table."""

import argparse
import sys

from bq_client import format_output, get_client, get_config


def main():
    parser = argparse.ArgumentParser(description="Get BigQuery table schema")
    parser.add_argument("--dataset", required=True, help="Dataset ID")
    parser.add_argument("--table", required=True, help="Table ID")
    args = parser.parse_args()

    try:
        client = get_client()
        config = get_config()

        table_ref = f"{config['project_id']}.{args.dataset}.{args.table}"
        table_obj = client.get_table(table_ref)

        schema = []
        for field in table_obj.schema:
            schema.append(
                {
                    "name": field.name,
                    "type": field.field_type,
                    "mode": field.mode,
                    "description": field.description or "",
                }
            )

        print(
            format_output(
                {
                    "dataset": args.dataset,
                    "table": args.table,
                    "num_rows": table_obj.num_rows,
                    "num_bytes": table_obj.num_bytes,
                    "schema": schema,
                }
            )
        )

    except Exception as e:
        print(
            format_output(
                {"error": str(e), "dataset": args.dataset, "table": args.table}
            )
        )
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""List tables in a BigQuery dataset."""

import argparse
import sys

from bq_client import format_output, get_client, get_config


def main():
    parser = argparse.ArgumentParser(description="List BigQuery tables")
    parser.add_argument("--dataset", required=True, help="Dataset ID")
    args = parser.parse_args()

    try:
        client = get_client()
        config = get_config()

        dataset_ref = f"{config['project_id']}.{args.dataset}"
        tables = []

        for table in client.list_tables(dataset_ref):
            table_ref = client.get_table(f"{dataset_ref}.{table.table_id}")
            tables.append(
                {
                    "table_id": table.table_id,
                    "full_name": f"{dataset_ref}.{table.table_id}",
                    "table_type": table.table_type,
                    "num_rows": table_ref.num_rows,
                    "num_bytes": table_ref.num_bytes,
                    "created": str(table_ref.created),
                    "modified": str(table_ref.modified),
                }
            )

        print(
            format_output(
                {
                    "dataset": args.dataset,
                    "table_count": len(tables),
                    "tables": tables,
                }
            )
        )

    except Exception as e:
        print(format_output({"error": str(e), "dataset": args.dataset}))
        sys.exit(1)


if __name__ == "__main__":
    main()

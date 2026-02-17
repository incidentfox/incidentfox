#!/usr/bin/env python3
"""Execute a SQL query on BigQuery."""

import argparse
import sys

from bq_client import format_output, get_client, get_config


def main():
    parser = argparse.ArgumentParser(description="Execute BigQuery query")
    parser.add_argument("--query", required=True, help="SQL query to execute")
    parser.add_argument("--dataset", help="Default dataset")
    parser.add_argument(
        "--max-results", type=int, default=1000, help="Max rows (default: 1000)"
    )
    args = parser.parse_args()

    try:
        from google.cloud import bigquery

        client = get_client()
        config = get_config()

        default_dataset = args.dataset or config.get("dataset")

        job_config = None
        if default_dataset:
            job_config = bigquery.QueryJobConfig(
                default_dataset=f"{config['project_id']}.{default_dataset}"
            )

        query_job = client.query(args.query, job_config=job_config)
        results = query_job.result(max_results=args.max_results)

        rows = []
        for row in results:
            rows.append(dict(row))

        print(
            format_output(
                {
                    "row_count": len(rows),
                    "total_rows": results.total_rows,
                    "schema": [
                        {"name": field.name, "type": field.field_type}
                        for field in results.schema
                    ],
                    "rows": rows,
                }
            )
        )

    except Exception as e:
        print(format_output({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Execute a read-only SQL query on BigQuery.

Security: Only SELECT, SHOW, DESCRIBE, and WITH statements are allowed.
DML/DDL (INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, MERGE, TRUNCATE, etc.)
is blocked to prevent data modification and unexpected cost.
"""

import argparse
import re
import sys

from bq_client import format_output, get_client, get_config

# Allowed read-only statement types (case-insensitive, anchored to start of query)
_READONLY_PATTERN = re.compile(r"^\s*(SELECT|SHOW|DESCRIBE|WITH)\b", re.IGNORECASE)

# Maximum bytes that a query is allowed to scan (10 GB)
_MAX_BYTES_BILLED = 10 * 1024 * 1024 * 1024


def _validate_readonly(query: str) -> None:
    """Reject non-read-only statements."""
    if not _READONLY_PATTERN.match(query):
        raise ValueError(
            "Only read-only queries are allowed (SELECT, SHOW, DESCRIBE, WITH). "
            "DML/DDL statements are blocked for safety."
        )
    # Block semicolons that could enable multi-statement injection
    # (allow trailing semicolon only)
    stripped = query.rstrip().rstrip(";").rstrip()
    if ";" in stripped:
        raise ValueError("Multi-statement queries are not allowed. Submit one query at a time.")


def main():
    parser = argparse.ArgumentParser(description="Execute BigQuery query (read-only)")
    parser.add_argument("--query", required=True, help="SQL query to execute")
    parser.add_argument("--dataset", help="Default dataset")
    parser.add_argument("--max-results", type=int, default=1000, help="Max rows (default: 1000)")
    parser.add_argument(
        "--max-bytes-billed",
        type=int,
        default=_MAX_BYTES_BILLED,
        help=f"Max bytes billed safety cap (default: {_MAX_BYTES_BILLED // (1024**3)} GB)",
    )
    args = parser.parse_args()

    try:
        _validate_readonly(args.query)

        from google.cloud import bigquery

        client = get_client()
        config = get_config()

        default_dataset = args.dataset or config.get("dataset")

        job_config = bigquery.QueryJobConfig(
            maximum_bytes_billed=args.max_bytes_billed,
        )
        if default_dataset:
            job_config.default_dataset = f"{config['project_id']}.{default_dataset}"

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
                        {"name": field.name, "type": field.field_type} for field in results.schema
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

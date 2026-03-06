#!/usr/bin/env python3
"""Query Azure Log Analytics using KQL.

Safety: Queries are automatically capped with a `| limit` clause to prevent
unbounded result sets. The default cap is 1000 rows.
"""

import argparse
import re
import sys
from datetime import datetime, timedelta

from azure_client import format_output, get_credentials

# Maximum rows to return from a KQL query (safety cap)
_DEFAULT_MAX_RESULTS = 1000
_ABSOLUTE_MAX_RESULTS = 10000


def _ensure_kql_limit(query: str, max_results: int) -> str:
    """Append a '| limit N' clause to KQL if no limit/take is present.

    This prevents unbounded queries from returning millions of rows.
    """
    # Check if query already contains a limit/take clause (case-insensitive)
    # Match patterns like: | limit 50, | take 100
    if re.search(r"\|\s*(limit|take)\s+\d+", query, re.IGNORECASE):
        return query
    # Also check if query ends with a summarize/count (aggregations are bounded)
    if re.search(r"\|\s*(summarize|count)\b", query, re.IGNORECASE):
        return query
    return f"{query.rstrip().rstrip(';')} | limit {max_results}"


def main():
    parser = argparse.ArgumentParser(description="Query Azure Log Analytics")
    parser.add_argument("--workspace-id", required=True, help="Log Analytics workspace ID (GUID)")
    parser.add_argument("--query", required=True, help="KQL query string")
    parser.add_argument("--timespan", help="ISO 8601 duration (e.g., PT1H, P1D). Default: PT24H")
    parser.add_argument(
        "--max-results",
        type=int,
        default=_DEFAULT_MAX_RESULTS,
        help=f"Max rows to return (default: {_DEFAULT_MAX_RESULTS}, max: {_ABSOLUTE_MAX_RESULTS})",
    )
    args = parser.parse_args()

    try:
        max_results = min(args.max_results, _ABSOLUTE_MAX_RESULTS)

        from azure.monitor.query import LogsQueryClient

        credential = get_credentials()
        client = LogsQueryClient(credential)

        timespan = args.timespan if args.timespan else timedelta(hours=24)

        # Ensure query has a result limit to prevent unbounded scans
        safe_query = _ensure_kql_limit(args.query, max_results)

        response = client.query_workspace(
            workspace_id=args.workspace_id,
            query=safe_query,
            timespan=timespan,
        )

        if response.status == "Success":
            tables = []
            for table in response.tables:
                rows = []
                for row in table.rows:
                    row_dict = {}
                    for i, column in enumerate(table.columns):
                        value = row[i]
                        if isinstance(value, datetime):
                            value = value.isoformat()
                        row_dict[column.name] = value
                    rows.append(row_dict)
                tables.append({"name": table.name, "row_count": len(rows), "rows": rows})

            print(
                format_output(
                    {
                        "workspace_id": args.workspace_id,
                        "query": safe_query,
                        "status": "Success",
                        "tables": tables,
                    }
                )
            )
        else:
            print(
                format_output(
                    {
                        "workspace_id": args.workspace_id,
                        "query": safe_query,
                        "status": "Partial",
                        "error": "Partial results or query timeout",
                    }
                )
            )

    except Exception as e:
        print(format_output({"error": str(e), "workspace_id": args.workspace_id}))
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Query Azure Log Analytics using KQL."""

import argparse
import sys
from datetime import datetime, timedelta

from azure_client import format_output, get_credentials


def main():
    parser = argparse.ArgumentParser(description="Query Azure Log Analytics")
    parser.add_argument(
        "--workspace-id", required=True, help="Log Analytics workspace ID (GUID)"
    )
    parser.add_argument("--query", required=True, help="KQL query string")
    parser.add_argument(
        "--timespan", help="ISO 8601 duration (e.g., PT1H, P1D). Default: PT24H"
    )
    args = parser.parse_args()

    try:
        from azure.monitor.query import LogsQueryClient

        credential = get_credentials()
        client = LogsQueryClient(credential)

        timespan = args.timespan if args.timespan else timedelta(hours=24)

        response = client.query_workspace(
            workspace_id=args.workspace_id,
            query=args.query,
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
                tables.append(
                    {"name": table.name, "row_count": len(rows), "rows": rows}
                )

            print(
                format_output(
                    {
                        "workspace_id": args.workspace_id,
                        "query": args.query,
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
                        "query": args.query,
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

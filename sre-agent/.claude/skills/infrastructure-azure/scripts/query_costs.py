#!/usr/bin/env python3
"""Query Azure Cost Management data."""

import argparse
import sys

from azure_client import format_output, get_credentials, get_subscription_id


def main():
    parser = argparse.ArgumentParser(description="Query Azure Cost Management")
    parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument(
        "--granularity",
        default="Monthly",
        choices=["Daily", "Monthly"],
        help="Granularity",
    )
    parser.add_argument(
        "--group-by",
        help="Comma-separated dimensions (e.g., ResourceGroup,ServiceName)",
    )
    parser.add_argument("--scope", help="Scope (default: /subscriptions/<sub-id>)")
    args = parser.parse_args()

    try:
        from azure.mgmt.costmanagement import CostManagementClient
        from azure.mgmt.costmanagement.models import (
            QueryAggregation,
            QueryDataset,
            QueryDefinition,
            QueryGrouping,
            QueryTimePeriod,
        )

        credential = get_credentials()
        subscription_id = get_subscription_id()
        cost_client = CostManagementClient(credential)

        dataset = QueryDataset(
            granularity=args.granularity,
            aggregation={"totalCost": QueryAggregation(name="Cost", function="Sum")},
        )

        if args.group_by:
            dataset.grouping = [
                QueryGrouping(type="Dimension", name=dim.strip())
                for dim in args.group_by.split(",")
            ]

        query = QueryDefinition(
            type="Usage",
            timeframe="Custom",
            time_period=QueryTimePeriod(from_property=args.start, to=args.end),
            dataset=dataset,
        )

        scope = args.scope or f"/subscriptions/{subscription_id}"
        result = cost_client.query.usage(scope, query)

        rows = []
        if result.rows:
            columns = [col.name for col in result.columns]
            for row in result.rows:
                row_dict = {}
                for i, col in enumerate(columns):
                    row_dict[col] = row[i]
                rows.append(row_dict)

        total_cost = sum(float(row.get("Cost", 0)) for row in rows)

        print(
            format_output(
                {
                    "scope": scope,
                    "time_period": {"start": args.start, "end": args.end},
                    "granularity": args.granularity,
                    "total_cost": round(total_cost, 2),
                    "currency": "USD",
                    "row_count": len(rows),
                    "rows": rows,
                }
            )
        )

    except Exception as e:
        print(format_output({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()

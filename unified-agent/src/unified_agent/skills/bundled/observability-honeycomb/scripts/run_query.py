#!/usr/bin/env python3
"""Run custom queries on Honeycomb datasets.

Supports various calculations, filters, and breakdowns for detailed analysis.

Usage:
    python run_query.py DATASET --calc CALCULATION [options]

Examples:
    python run_query.py production --calc COUNT
    python run_query.py production --calc P99 --column duration_ms --breakdown service.name
    python run_query.py production --calc COUNT --filter "http.status_code >= 500" --breakdown error.message
"""

import argparse
import json
import sys

from honeycomb_client import (
    format_results,
    list_slos,
    list_triggers,
    run_query,
)

VALID_CALCULATIONS = [
    "COUNT",
    "SUM",
    "AVG",
    "MAX",
    "MIN",
    "P50",
    "P75",
    "P90",
    "P95",
    "P99",
    "HEATMAP",
    "COUNT_DISTINCT",
    "CONCURRENCY",
    "RATE_AVG",
    "RATE_SUM",
    "RATE_MAX",
]


def main():
    parser = argparse.ArgumentParser(description="Run custom Honeycomb queries")
    parser.add_argument("dataset", help="Dataset slug to query")
    parser.add_argument(
        "--calc",
        action="append",
        help=f"Calculation to perform. Options: {', '.join(VALID_CALCULATIONS)}. Can specify multiple.",
    )
    parser.add_argument(
        "--column",
        action="append",
        help="Column for calculation (required for SUM, AVG, MAX, MIN, percentiles)",
    )
    parser.add_argument(
        "--breakdown",
        action="append",
        help="Column to group by (can specify multiple)",
    )
    parser.add_argument(
        "--filter",
        action="append",
        help="Filter expression (e.g., 'http.status_code >= 500'). Can specify multiple.",
    )
    parser.add_argument(
        "--time-range",
        type=int,
        default=3600,
        help="Time range in seconds (default: 3600 = 1 hour)",
    )
    parser.add_argument(
        "--granularity",
        type=int,
        help="Time bucket size in seconds for time series",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum results per group (default: 100)",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument(
        "--list-slos", action="store_true", help="List SLOs for this dataset"
    )
    parser.add_argument(
        "--list-triggers", action="store_true", help="List triggers for this dataset"
    )
    args = parser.parse_args()

    try:
        dataset = args.dataset

        # Handle SLO listing
        if args.list_slos:
            slos = list_slos(dataset)
            if args.json:
                print(json.dumps(slos, indent=2))
            else:
                print(f"SLOs for {dataset}:")
                print("-" * 40)
                if not slos:
                    print("No SLOs found.")
                else:
                    for slo in slos:
                        print(f"  {slo['name']}")
                        print(f"    ID: {slo['id']}")
                        print(f"    Target: {slo['target_percentage']}%")
                        print(f"    Period: {slo['time_period_days']} days")
                        print()
            return

        # Handle trigger listing
        if args.list_triggers:
            triggers = list_triggers(dataset)
            if args.json:
                print(json.dumps(triggers, indent=2))
            else:
                print(f"Triggers for {dataset}:")
                print("-" * 40)
                if not triggers:
                    print("No triggers found.")
                else:
                    for trigger in triggers:
                        status = "DISABLED" if trigger["disabled"] else "ACTIVE"
                        fired = " [TRIGGERED]" if trigger["triggered"] else ""
                        print(f"  [{status}] {trigger['name']}{fired}")
                        print(f"    ID: {trigger['id']}")
                        if trigger.get("description"):
                            print(f"    Description: {trigger['description']}")
                        print()
            return

        # Build calculations
        calculations = []
        calcs = args.calc or ["COUNT"]
        columns = args.column or []

        for i, calc in enumerate(calcs):
            calc_upper = calc.upper()
            if calc_upper not in VALID_CALCULATIONS:
                print(
                    f"Invalid calculation: {calc}. Valid options: {', '.join(VALID_CALCULATIONS)}",
                    file=sys.stderr,
                )
                sys.exit(1)

            calc_spec = {"op": calc_upper}

            # Add column if specified and calculation needs it
            if calc_upper not in ["COUNT", "CONCURRENCY"]:
                if i < len(columns):
                    calc_spec["column"] = columns[i]
                elif columns:
                    calc_spec["column"] = columns[0]
                else:
                    print(
                        f"Calculation {calc_upper} requires --column",
                        file=sys.stderr,
                    )
                    sys.exit(1)

            calculations.append(calc_spec)

        # Build filters
        filters = []
        if args.filter:
            for f in args.filter:
                filters.append(parse_filter(f))

        # Run query
        result = run_query(
            dataset,
            calculations=calculations,
            filters=filters if filters else None,
            breakdowns=args.breakdown,
            time_range=args.time_range,
            granularity=args.granularity,
            limit=args.limit,
        )

        # Output
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("=" * 60)
            print("HONEYCOMB QUERY RESULTS")
            print("=" * 60)
            print(f"Dataset: {dataset}")
            print(f"Calculations: {[c['op'] for c in calculations]}")
            if args.breakdown:
                print(f"Breakdowns: {args.breakdown}")
            if filters:
                print(f"Filters: {args.filter}")
            print(f"Time Range: {args.time_range}s")
            print()

            data = result.get("data", [])
            if not data:
                print("No results found.")
            else:
                print(f"Results ({len(data)} rows):")
                print("-" * 40)
                print(format_results(data, args.breakdown))

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def parse_filter(filter_expr: str) -> dict:
    """Parse a simple filter expression into Honeycomb filter format."""
    operators = [
        ">=",
        "<=",
        "!=",
        "=",
        ">",
        "<",
        "exists",
        "does-not-exist",
        "contains",
        "starts-with",
        "in",
    ]

    for op in operators:
        if f" {op} " in filter_expr or filter_expr.endswith(f" {op}"):
            parts = filter_expr.split(op, 1)
            if len(parts) >= 1:
                column = parts[0].strip()
                value = parts[1].strip() if len(parts) > 1 else None

                result = {"column": column, "op": op}

                if value is not None:
                    # Try to parse as number
                    try:
                        if "." in value:
                            result["value"] = float(value)
                        else:
                            result["value"] = int(value)
                    except ValueError:
                        # Try to parse as boolean
                        if value.lower() == "true":
                            result["value"] = True
                        elif value.lower() == "false":
                            result["value"] = False
                        else:
                            # Keep as string, remove quotes
                            result["value"] = value.strip("\"'")

                return result

    raise ValueError(f"Could not parse filter: {filter_expr}")


if __name__ == "__main__":
    main()

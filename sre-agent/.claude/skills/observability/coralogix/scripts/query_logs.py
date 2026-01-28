#!/usr/bin/env python3
"""Execute DataPrime queries against Coralogix.

Usage:
    python query_logs.py "<dataprime_query>" [--time-range MINUTES] [--limit N]

Examples:
    # List services
    python query_logs.py "source logs | groupby \$l.subsystemname aggregate count() as cnt | orderby cnt desc | limit 20"

    # Get errors
    python query_logs.py "source logs | filter \$m.severity == ERROR | limit 50"

Environment:
    CORALOGIX_API_KEY - Required
    CORALOGIX_DOMAIN - Team hostname (e.g., myteam.app.cx498.coralogix.com)
    CORALOGIX_REGION - Region code (e.g., us2, eu1)
"""

import argparse
import json
import sys

# Import from shared client module
from coralogix_client import execute_query, format_log_entry


def main():
    parser = argparse.ArgumentParser(
        description="Execute DataPrime query against Coralogix"
    )
    parser.add_argument("query", help="DataPrime query string")
    parser.add_argument(
        "--time-range", type=int, default=60, help="Time range in minutes (default: 60)"
    )
    parser.add_argument(
        "--limit", type=int, default=100, help="Result limit (default: 100)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        results = execute_query(
            query=args.query,
            time_range_minutes=args.time_range,
            limit=args.limit,
        )

        if args.json:
            print(
                json.dumps(
                    {
                        "query": args.query,
                        "time_range": f"Last {args.time_range} minutes",
                        "result_count": len(results),
                        "results": results[: args.limit],
                    },
                    indent=2,
                )
            )
        else:
            print(f"Query: {args.query}")
            print(f"Time range: Last {args.time_range} minutes")
            print(f"Results: {len(results)}")
            print("-" * 60)

            for result in results[: args.limit]:
                # Format depends on query type
                if isinstance(result, dict):
                    # Check if aggregation result
                    if any(
                        k in result
                        for k in ("cnt", "count", "errors", "total", "warnings")
                    ):
                        # Group by result - print key-value pairs
                        for k, v in result.items():
                            print(f"  {k}: {v}")
                        print()
                    else:
                        # Log entry
                        print(format_log_entry(result))
                else:
                    print(result)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

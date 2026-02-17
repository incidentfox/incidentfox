#!/usr/bin/env python3
"""Get APM summary for an application from New Relic."""

import argparse
import sys

from newrelic_client import format_output, newrelic_graphql


def _run_nrql(account_id: str, query: str):
    """Run a single NRQL query and return results."""
    graphql_query = """
    query($accountId: Int!, $nrql: Nrql!) {
        actor {
            account(id: $accountId) {
                nrql(query: $nrql) {
                    results
                }
            }
        }
    }
    """
    data = newrelic_graphql(
        graphql_query,
        variables={"accountId": int(account_id), "nrql": query},
    )
    results = (
        data.get("data", {})
        .get("actor", {})
        .get("account", {})
        .get("nrql", {})
        .get("results", [])
    )
    return results[0] if results else None


def main():
    parser = argparse.ArgumentParser(description="Get APM summary")
    parser.add_argument("--account-id", required=True, help="New Relic account ID")
    parser.add_argument(
        "--app-name", required=True, help="Application name in New Relic"
    )
    parser.add_argument(
        "--time-range", default="30m", help="Time range (e.g., 30m, 1h)"
    )
    args = parser.parse_args()

    try:
        queries = {
            "response_time": f"SELECT average(duration) FROM Transaction WHERE appName = '{args.app_name}' SINCE {args.time_range} ago",
            "throughput": f"SELECT count(*) FROM Transaction WHERE appName = '{args.app_name}' SINCE {args.time_range} ago",
            "error_rate": f"SELECT percentage(count(*), WHERE error = true) FROM Transaction WHERE appName = '{args.app_name}' SINCE {args.time_range} ago",
            "apdex": f"SELECT apdex(duration, t: 0.5) FROM Transaction WHERE appName = '{args.app_name}' SINCE {args.time_range} ago",
        }

        summary = {}
        for metric_name, query in queries.items():
            try:
                summary[metric_name] = _run_nrql(args.account_id, query)
            except Exception:
                summary[metric_name] = None

        print(
            format_output(
                {
                    "app_name": args.app_name,
                    "account_id": args.account_id,
                    "time_range": args.time_range,
                    "summary": summary,
                }
            )
        )

    except Exception as e:
        print(format_output({"error": str(e), "app_name": args.app_name}))
        sys.exit(1)


if __name__ == "__main__":
    main()

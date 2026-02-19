#!/usr/bin/env python3
"""Get latency statistics for a service from Jaeger."""

import argparse
import json
import sys

from jaeger_client import (
    calculate_latency_stats,
    format_duration,
    get_operations,
    search_traces,
)


def main():
    parser = argparse.ArgumentParser(description="Get latency statistics for a service")
    parser.add_argument(
        "--service", "-s", required=True, help="Service name (required)"
    )
    parser.add_argument("--operation", "-o", help="Filter to specific operation")
    parser.add_argument(
        "--lookback", type=float, default=1, help="Hours to look back (default: 1)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        if args.operation:
            # Stats for single operation
            operations = [args.operation]
        else:
            # Get all operations
            operations = get_operations(args.service)

        stats_by_operation = {}

        for op in operations:
            traces = search_traces(
                service=args.service,
                operation=op,
                limit=100,  # Get more traces for better stats
                lookback_hours=args.lookback,
            )
            stats = calculate_latency_stats(traces)
            if stats["count"] > 0:
                stats_by_operation[op] = stats

        if args.json:
            # Convert durations to formatted strings for JSON
            output = {}
            for op, stats in stats_by_operation.items():
                output[op] = {
                    "count": stats["count"],
                    "p50": format_duration(stats["p50"]),
                    "p95": format_duration(stats["p95"]),
                    "p99": format_duration(stats["p99"]),
                    "min": format_duration(stats["min"]),
                    "max": format_duration(stats["max"]),
                    "avg": format_duration(stats["avg"]),
                    "p50_us": stats["p50"],
                    "p95_us": stats["p95"],
                    "p99_us": stats["p99"],
                }
            print(
                json.dumps(
                    {
                        "service": args.service,
                        "lookback_hours": args.lookback,
                        "operations": output,
                    },
                    indent=2,
                )
            )
        else:
            print(f"Latency Statistics for '{args.service}'")
            print(f"Time window: last {args.lookback}h")
            print()

            if not stats_by_operation:
                print("No trace data found.")
                return

            # Print header
            print(
                f"{'Operation':<40} {'Count':>8} {'p50':>10} {'p95':>10} {'p99':>10} {'Max':>10}"
            )
            print("-" * 98)

            # Sort by p99 descending
            sorted_ops = sorted(
                stats_by_operation.items(),
                key=lambda x: x[1]["p99"],
                reverse=True,
            )

            for op, stats in sorted_ops:
                # Truncate long operation names
                op_display = op[:38] + ".." if len(op) > 40 else op
                print(
                    f"{op_display:<40} "
                    f"{stats['count']:>8} "
                    f"{format_duration(stats['p50']):>10} "
                    f"{format_duration(stats['p95']):>10} "
                    f"{format_duration(stats['p99']):>10} "
                    f"{format_duration(stats['max']):>10}"
                )

            print()
            print("Note: High p99 indicates tail latency issues.")
            print(
                "      Large gap between p50 and p99 suggests inconsistent performance."
            )

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

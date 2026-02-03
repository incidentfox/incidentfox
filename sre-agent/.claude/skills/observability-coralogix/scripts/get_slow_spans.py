#!/usr/bin/env python3
"""Find slow spans (latency analysis) from Coralogix.

Use this to identify performance bottlenecks and slow operations.

Usage:
    python get_slow_spans.py --min-duration 500 --service checkout
    python get_slow_spans.py --min-duration 1000 --time-range 30

Examples:
    # Find spans slower than 500ms
    python get_slow_spans.py --min-duration 500

    # Find slow spans in checkout service
    python get_slow_spans.py --min-duration 200 --service checkout

    # Get latency statistics by service
    python get_slow_spans.py --stats

Environment:
    CORALOGIX_API_KEY - Required
    CORALOGIX_DOMAIN - Team hostname
"""

import argparse
import json
import sys

from coralogix_client import execute_query


def format_slow_span(span: dict) -> str:
    """Format a slow span for readable output."""
    operation = span.get("operationName", "unknown")
    service = span.get("serviceName", span.get("subsystemName", "unknown"))
    duration = span.get("duration", 0)

    # Duration is in microseconds - convert to ms
    duration_ms = duration / 1000

    # Color code by latency
    if duration_ms > 1000:
        icon = "🔴"  # > 1s
    elif duration_ms > 500:
        icon = "🟠"  # > 500ms
    elif duration_ms > 200:
        icon = "🟡"  # > 200ms
    else:
        icon = "🟢"

    # Format timestamp (spans have startTime in epoch microseconds)
    start_time = span.get("startTime", span.get("timestamp", ""))
    if isinstance(start_time, (int, float)) and start_time > 1_000_000_000_000:
        # Microseconds epoch - convert to datetime
        from datetime import datetime

        ts = datetime.fromtimestamp(start_time / 1_000_000).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    elif "T" in str(start_time):
        ts = str(start_time).split(".")[0].replace("T", " ")
    else:
        ts = str(start_time)

    # Get trace ID from references or direct field
    trace_id = ""
    refs = span.get("references", [])
    if refs and isinstance(refs, list) and len(refs) > 0:
        trace_id = refs[0].get("traceID", "")[:16]
    if not trace_id:
        trace_id = span.get("traceId", span.get("traceID", ""))
        if trace_id:
            trace_id = trace_id[:16]

    lines = [
        f"{icon} {duration_ms:.1f}ms | {operation} | {service}",
        f"  Time: {ts}",
    ]

    if trace_id:
        lines.append(f"  Trace: {trace_id}...")

    # Add pod context if available
    process = span.get("process", {})
    if isinstance(process, dict):
        tags = process.get("tags", {})
        pod = tags.get("k8s.pod.name", "")
        if pod:
            lines.append(f"  Pod: {pod}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Find slow spans (latency analysis)")
    parser.add_argument(
        "--min-duration",
        type=int,
        default=500,
        help="Minimum duration in milliseconds (default: 500)",
    )
    parser.add_argument("--service", help="Service name filter")
    parser.add_argument("--app", help="Application name filter")
    parser.add_argument("--operation", help="Operation name filter")
    parser.add_argument(
        "--time-range", type=int, default=60, help="Time range in minutes (default: 60)"
    )
    parser.add_argument(
        "--limit", type=int, default=50, help="Maximum spans to return (default: 50)"
    )
    parser.add_argument(
        "--stats", action="store_true", help="Show latency statistics by service"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        if args.stats:
            # Get latency statistics grouped by service
            # Note: Spans use serviceName, applicationName (not $l. prefix like logs)
            query = "source spans"
            if args.app:
                query += f" | filter applicationName == '{args.app}'"
            if args.service:
                query += f" | filter serviceName == '{args.service}'"

            # Group by service, calculate avg/max duration (duration is in microseconds)
            query += " | groupby serviceName aggregate count() as span_count, avg(duration) as avg_duration, max(duration) as max_duration"
            query += " | orderby avg_duration desc | limit 20"

            results = execute_query(query, args.time_range, limit=20)

            if args.json:
                print(
                    json.dumps(
                        {
                            "time_range_minutes": args.time_range,
                            "service_stats": results,
                        },
                        indent=2,
                    )
                )
            else:
                print("📊 Latency Statistics by Service")
                print(f"Time range: Last {args.time_range} minutes")
                print("=" * 70)
                print(f"{'SERVICE':<25} {'COUNT':>10} {'AVG':>12} {'MAX':>12}")
                print("-" * 70)

                for r in results:
                    service = r.get("serviceName", "unknown")
                    count = r.get("span_count", 0)
                    avg_dur = r.get("avg_duration", 0)
                    max_dur = r.get("max_duration", 0)

                    # Duration is in microseconds - convert to ms
                    avg_ms = avg_dur / 1000
                    max_ms = max_dur / 1000

                    print(
                        f"{service:<25} {count:>10} {avg_ms:>10.1f}ms {max_ms:>10.1f}ms"
                    )

            return

        # Build query for slow spans
        # Note: Spans use serviceName, applicationName, operationName, duration (not $l./$m. prefix)
        query = "source spans"

        if args.app:
            query += f" | filter applicationName == '{args.app}'"
        if args.service:
            query += f" | filter serviceName == '{args.service}'"
        if args.operation:
            query += f" | filter operationName ~~ '{args.operation}'"

        # Filter by duration (duration is in microseconds)
        duration_us = args.min_duration * 1000  # Convert ms to µs
        query += f" | filter duration > {duration_us}"

        # Order by duration descending
        query += " | orderby duration desc"
        query += f" | limit {args.limit}"

        results = execute_query(query, args.time_range, limit=args.limit)

        if args.json:
            print(
                json.dumps(
                    {
                        "min_duration_ms": args.min_duration,
                        "service": args.service,
                        "time_range_minutes": args.time_range,
                        "slow_span_count": len(results),
                        "spans": results,
                    },
                    indent=2,
                )
            )
        else:
            print(f"🐢 Slow Spans (>{args.min_duration}ms)")
            if args.service:
                print(f"Service: {args.service}")
            print(f"Time range: Last {args.time_range} minutes")
            print(f"Found: {len(results)} slow spans")
            print("=" * 60)

            if not results:
                print(f"\nNo spans slower than {args.min_duration}ms found.")
                print("Try lowering --min-duration or increasing --time-range")
            else:
                for span in results[:20]:
                    print(format_slow_span(span))
                    print()

                if len(results) > 20:
                    print(f"... and {len(results) - 20} more slow spans")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

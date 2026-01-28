#!/usr/bin/env python3
"""Get distributed traces/spans from Coralogix.

Use this to understand request flow, identify slow operations, and trace errors.

Usage:
    python get_traces.py --service checkout --time-range 30
    python get_traces.py --operation "/api/checkout" --limit 20
    python get_traces.py --trace-id abc123def456

Examples:
    # List recent spans for a service
    python get_traces.py --service payment --time-range 15

    # Find a specific trace
    python get_traces.py --trace-id abc123def456

    # Find spans for an operation
    python get_traces.py --operation "HTTP GET" --service checkout

Environment:
    CORALOGIX_API_KEY - Required
    CORALOGIX_DOMAIN - Team hostname
"""

import argparse
import json
import sys

from coralogix_client import execute_query


def format_span(span: dict, include_context: bool = True) -> str:
    """Format a span for readable output."""
    from datetime import datetime

    # Extract key fields (spans use serviceName, operationName directly)
    operation = span.get("operationName", "unknown")
    service = span.get("serviceName", span.get("subsystemName", "unknown"))
    duration = span.get("duration", 0)

    # Duration is in microseconds - convert to ms
    duration_ms = duration / 1000
    if duration_ms >= 1:
        duration_str = f"{duration_ms:.1f}ms"
    else:
        duration_str = f"{duration}µs"

    # Get IDs from references or direct fields
    trace_id = ""
    span_id = span.get("spanID", "")[:8] if span.get("spanID") else ""
    refs = span.get("references", [])
    if refs and isinstance(refs, list) and len(refs) > 0:
        trace_id = refs[0].get("traceID", "")[:16]

    # Status - check tags for error status
    tags = span.get("tags", {})
    is_error = tags.get("error", False) or tags.get("otel.status_code") == "ERROR"
    status_icon = "❌" if is_error else "✓"

    # Format timestamp (spans have startTime in epoch microseconds)
    start_time = span.get("startTime", span.get("timestamp", ""))
    if isinstance(start_time, (int, float)) and start_time > 1_000_000_000_000:
        ts = datetime.fromtimestamp(start_time / 1_000_000).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    elif "T" in str(start_time):
        ts = str(start_time).split(".")[0].replace("T", " ")
    else:
        ts = str(start_time)

    lines = [
        f"{status_icon} [{duration_str}] {operation} | {service}",
        f"  Time: {ts}",
    ]

    if trace_id or span_id:
        lines.append(f"  IDs: trace={trace_id}... span={span_id}...")

    if include_context:
        # Add pod context from process.tags
        process = span.get("process", {})
        if isinstance(process, dict):
            proc_tags = process.get("tags", {})
            pod = proc_tags.get("k8s.pod.name", "")
            if pod:
                lines.append(f"  Pod: {pod}")

        # Add span tags (filter to interesting ones)
        if isinstance(tags, dict) and tags:
            interesting_keys = [
                "http.method",
                "http.status_code",
                "http.url",
                "db.system",
                "rpc.method",
            ]
            tag_items = [(k, v) for k, v in tags.items() if k in interesting_keys][:3]
            if tag_items:
                tag_str = ", ".join(f"{k}={v}" for k, v in tag_items)
                lines.append(f"  Tags: {tag_str}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Get distributed traces/spans from Coralogix"
    )
    parser.add_argument("--service", help="Service name (subsystemname)")
    parser.add_argument("--app", help="Application name (applicationname)")
    parser.add_argument("--operation", help="Operation/span name filter")
    parser.add_argument("--trace-id", help="Get all spans for a specific trace ID")
    parser.add_argument(
        "--time-range", type=int, default=60, help="Time range in minutes (default: 60)"
    )
    parser.add_argument(
        "--limit", type=int, default=50, help="Maximum spans to return (default: 50)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        # Build DataPrime query
        # Note: Spans use serviceName, applicationName, operationName (not $l. prefix like logs)
        query = "source spans"

        if args.trace_id:
            # Get all spans for a specific trace
            # Use top-level traceID field (full 32-char hex string)
            query += f" | filter traceID == '{args.trace_id}'"
        else:
            if args.app:
                query += f" | filter applicationName == '{args.app}'"
            if args.service:
                query += f" | filter serviceName == '{args.service}'"
            if args.operation:
                query += f" | filter operationName ~~ '{args.operation}'"

        query += f" | limit {args.limit}"

        results = execute_query(query, args.time_range, limit=args.limit)

        # When viewing a specific trace, sort by startTime to show request flow
        if args.trace_id and results:
            results.sort(key=lambda s: s.get("startTime", 0))

        if args.json:
            print(
                json.dumps(
                    {
                        "service": args.service,
                        "operation": args.operation,
                        "trace_id": args.trace_id,
                        "time_range_minutes": args.time_range,
                        "span_count": len(results),
                        "spans": results,
                    },
                    indent=2,
                )
            )
        else:
            print("🔍 Trace Search")
            if args.trace_id:
                print(f"Trace ID: {args.trace_id}")
            if args.service:
                print(f"Service: {args.service}")
            if args.operation:
                print(f"Operation: {args.operation}")
            print(f"Time range: Last {args.time_range} minutes")
            print(f"Spans found: {len(results)}")
            print("=" * 60)

            if not results:
                print("\nNo spans found matching criteria.")
            else:
                for span in results[:20]:
                    print(format_span(span))
                    print()

                if len(results) > 20:
                    print(f"... and {len(results) - 20} more spans")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

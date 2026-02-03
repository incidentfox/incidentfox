#!/usr/bin/env python3
"""Find slow traces in Jaeger."""

import argparse
import json
import sys

from jaeger_client import extract_span_info, format_duration, search_traces


def main():
    parser = argparse.ArgumentParser(description="Find slow traces in Jaeger")
    parser.add_argument(
        "--service", "-s", required=True, help="Service name (required)"
    )
    parser.add_argument("--operation", "-o", help="Operation name filter")
    parser.add_argument(
        "--min-duration",
        type=int,
        default=1000,
        help="Minimum duration threshold in ms (default: 1000)",
    )
    parser.add_argument(
        "--limit", "-l", type=int, default=20, help="Max traces to return (default: 20)"
    )
    parser.add_argument(
        "--lookback", type=float, default=1, help="Hours to look back (default: 1)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        traces = search_traces(
            service=args.service,
            operation=args.operation,
            min_duration=args.min_duration,
            limit=args.limit,
            lookback_hours=args.lookback,
        )

        # Sort by duration descending
        trace_info = []
        for trace in traces:
            spans = trace.get("spans", [])
            processes = trace.get("processes", {})
            if spans:
                root_span = min(spans, key=lambda s: s.get("startTime", float("inf")))
                info = extract_span_info(root_span, processes)

                # Find slowest child span
                slowest_child = max(spans, key=lambda s: s.get("duration", 0))
                slowest_info = extract_span_info(slowest_child, processes)

                trace_info.append(
                    {
                        "trace_id": info["trace_id"],
                        "service": info["service"],
                        "operation": info["operation"],
                        "duration": info["duration"],
                        "duration_us": info["duration_us"],
                        "has_error": info["has_error"],
                        "span_count": len(spans),
                        "slowest_span": {
                            "service": slowest_info["service"],
                            "operation": slowest_info["operation"],
                            "duration": slowest_info["duration"],
                            "duration_us": slowest_info["duration_us"],
                        },
                    }
                )

        # Sort by duration
        trace_info.sort(key=lambda x: x["duration_us"], reverse=True)

        if args.json:
            print(
                json.dumps({"traces": trace_info, "count": len(trace_info)}, indent=2)
            )
        else:
            print(f"Slow traces for '{args.service}' (>{args.min_duration}ms)")
            print(f"Found {len(trace_info)} traces in the last {args.lookback}h")
            print()

            if not trace_info:
                print("No slow traces found.")
                return

            for t in trace_info:
                error_marker = " [ERROR]" if t["has_error"] else ""
                print(f"Trace: {t['trace_id']}")
                print(f"  Total Duration: {t['duration']}{error_marker}")
                print(f"  Operation: {t['operation']}")
                print(f"  Spans: {t['span_count']}")
                print(
                    f"  Slowest Span: {t['slowest_span']['service']}: {t['slowest_span']['operation']} ({t['slowest_span']['duration']})"
                )
                print()

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

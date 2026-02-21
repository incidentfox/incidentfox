#!/usr/bin/env python3
"""Search for traces in Jaeger with filters."""

import argparse
import json
import sys

from jaeger_client import extract_span_info, search_traces


def parse_tags(tag_strings: list[str] | None) -> dict[str, str]:
    """Parse tag strings in key=value format."""
    if not tag_strings:
        return {}
    tags = {}
    for tag in tag_strings:
        if "=" in tag:
            key, value = tag.split("=", 1)
            tags[key] = value
    return tags


def main():
    parser = argparse.ArgumentParser(description="Search for traces in Jaeger")
    parser.add_argument(
        "--service", "-s", required=True, help="Service name (required)"
    )
    parser.add_argument("--operation", "-o", help="Operation name filter")
    parser.add_argument(
        "--tags", "-t", action="append", help="Tag filter (key=value, can repeat)"
    )
    parser.add_argument("--min-duration", type=int, help="Minimum duration in ms")
    parser.add_argument("--max-duration", type=int, help="Maximum duration in ms")
    parser.add_argument(
        "--limit", "-l", type=int, default=20, help="Max traces to return (default: 20)"
    )
    parser.add_argument(
        "--lookback", type=float, default=1, help="Hours to look back (default: 1)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        tags = parse_tags(args.tags)

        traces = search_traces(
            service=args.service,
            operation=args.operation,
            tags=tags,
            min_duration=args.min_duration,
            max_duration=args.max_duration,
            limit=args.limit,
            lookback_hours=args.lookback,
        )

        if args.json:
            # Simplified JSON output
            output = []
            for trace in traces:
                spans = trace.get("spans", [])
                processes = trace.get("processes", {})
                if spans:
                    root_span = min(
                        spans, key=lambda s: s.get("startTime", float("inf"))
                    )
                    info = extract_span_info(root_span, processes)
                    output.append(
                        {
                            "trace_id": info["trace_id"],
                            "service": info["service"],
                            "operation": info["operation"],
                            "duration": info["duration"],
                            "duration_us": info["duration_us"],
                            "has_error": info["has_error"],
                            "span_count": len(spans),
                        }
                    )
            print(json.dumps({"traces": output, "count": len(output)}, indent=2))
        else:
            print(f"Found {len(traces)} traces for service '{args.service}'")
            if args.operation:
                print(f"Operation filter: {args.operation}")
            if tags:
                print(f"Tag filters: {tags}")
            if args.min_duration:
                print(f"Min duration: {args.min_duration}ms")
            print()

            for trace in traces:
                spans = trace.get("spans", [])
                processes = trace.get("processes", {})
                if spans:
                    root_span = min(
                        spans, key=lambda s: s.get("startTime", float("inf"))
                    )
                    info = extract_span_info(root_span, processes)
                    error_marker = " [ERROR]" if info["has_error"] else ""
                    print(f"Trace: {info['trace_id']}")
                    print(f"  Operation: {info['operation']}")
                    print(f"  Duration: {info['duration']}{error_marker}")
                    print(f"  Spans: {len(spans)}")
                    print()

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

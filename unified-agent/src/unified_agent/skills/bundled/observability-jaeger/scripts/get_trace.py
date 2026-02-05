#!/usr/bin/env python3
"""Get a specific trace by ID from Jaeger."""

import argparse
import json
import sys
from datetime import datetime, timezone

from jaeger_client import extract_span_info, format_duration, get_trace


def build_span_tree(spans: list[dict], processes: dict) -> list[dict]:
    """Build a tree structure from flat span list."""
    # Extract span info for all spans
    span_map = {}
    for span in spans:
        info = extract_span_info(span, processes)
        info["children"] = []
        info["parent_id"] = None
        # Find parent from references
        for ref in span.get("references", []):
            if ref.get("refType") == "CHILD_OF":
                info["parent_id"] = ref.get("spanID")
                break
        span_map[info["span_id"]] = info

    # Build tree
    roots = []
    for span_id, span_info in span_map.items():
        parent_id = span_info["parent_id"]
        if parent_id and parent_id in span_map:
            span_map[parent_id]["children"].append(span_info)
        else:
            roots.append(span_info)

    # Sort children by start time
    def sort_children(node):
        node["children"].sort(key=lambda x: x["start_time"])
        for child in node["children"]:
            sort_children(child)

    for root in roots:
        sort_children(root)

    return sorted(roots, key=lambda x: x["start_time"])


def print_span_tree(spans: list[dict], indent: int = 0):
    """Print span tree with indentation."""
    for span in spans:
        prefix = "  " * indent
        error_marker = " [ERROR]" if span["has_error"] else ""
        print(f"{prefix}├─ {span['service']}: {span['operation']}")
        print(f"{prefix}│  Duration: {span['duration']}{error_marker}")

        # Print relevant tags
        important_tags = [
            "http.method",
            "http.url",
            "http.status_code",
            "db.type",
            "db.statement",
            "error",
        ]
        for tag in important_tags:
            if tag in span["tags"]:
                value = span["tags"][tag]
                # Truncate long values
                if isinstance(value, str) and len(value) > 80:
                    value = value[:77] + "..."
                print(f"{prefix}│  {tag}: {value}")

        # Print error logs if any
        if span["has_error"] and span["logs"]:
            for log in span["logs"][:2]:  # Limit to first 2 logs
                for field in log.get("fields", []):
                    if field.get("key") in ["message", "error", "event"]:
                        print(f"{prefix}│  Log: {field.get('value', '')[:100]}")

        print(f"{prefix}│")

        if span["children"]:
            print_span_tree(span["children"], indent + 1)


def main():
    parser = argparse.ArgumentParser(description="Get a specific trace by ID")
    parser.add_argument("trace_id", help="Trace ID")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        trace = get_trace(args.trace_id)

        if not trace:
            print(f"Trace not found: {args.trace_id}", file=sys.stderr)
            sys.exit(1)

        spans = trace.get("spans", [])
        processes = trace.get("processes", {})

        if args.json:
            # Build simplified span tree for JSON
            tree = build_span_tree(spans, processes)
            print(
                json.dumps(
                    {
                        "trace_id": args.trace_id,
                        "span_count": len(spans),
                        "spans": tree,
                    },
                    indent=2,
                    default=str,
                )
            )
        else:
            # Find root span for summary
            if spans:
                root_span = min(spans, key=lambda s: s.get("startTime", float("inf")))
                root_info = extract_span_info(root_span, processes)
                total_duration = root_info["duration"]

                # Calculate time
                start_time = datetime.fromtimestamp(
                    root_span.get("startTime", 0) / 1_000_000, tz=timezone.utc
                )

                print(f"Trace: {args.trace_id}")
                print(f"Time: {start_time.isoformat()}")
                print(f"Total Duration: {total_duration}")
                print(f"Span Count: {len(spans)}")

                # Count errors
                error_count = sum(
                    1
                    for s in spans
                    if extract_span_info(s, processes).get("has_error", False)
                )
                if error_count:
                    print(f"Errors: {error_count} spans with errors")

                # Find slowest spans
                sorted_spans = sorted(
                    spans, key=lambda s: s.get("duration", 0), reverse=True
                )
                print("\nSlowest Spans:")
                for span in sorted_spans[:5]:
                    info = extract_span_info(span, processes)
                    error = " [ERROR]" if info["has_error"] else ""
                    print(
                        f"  {info['duration']:>10} - {info['service']}: {info['operation']}{error}"
                    )

                print("\nSpan Tree:")
                print("-" * 60)
                tree = build_span_tree(spans, processes)
                print_span_tree(tree)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Find traces with errors in Jaeger."""

import argparse
import json
import sys

from jaeger_client import extract_span_info, search_traces


def main():
    parser = argparse.ArgumentParser(description="Find traces with errors in Jaeger")
    parser.add_argument(
        "--service", "-s", required=True, help="Service name (required)"
    )
    parser.add_argument("--operation", "-o", help="Operation name filter")
    parser.add_argument(
        "--limit", "-l", type=int, default=20, help="Max traces to return (default: 20)"
    )
    parser.add_argument(
        "--lookback", type=float, default=1, help="Hours to look back (default: 1)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        # Search for traces with error tag
        traces = search_traces(
            service=args.service,
            operation=args.operation,
            tags={"error": "true"},
            limit=args.limit,
            lookback_hours=args.lookback,
        )

        error_traces = []
        for trace in traces:
            spans = trace.get("spans", [])
            processes = trace.get("processes", {})

            if not spans:
                continue

            root_span = min(spans, key=lambda s: s.get("startTime", float("inf")))
            root_info = extract_span_info(root_span, processes)

            # Find error spans
            error_spans = []
            for span in spans:
                info = extract_span_info(span, processes)
                if info["has_error"]:
                    # Try to extract error message from logs or tags
                    error_msg = info["tags"].get("error.message", "")
                    if not error_msg:
                        for log in info["logs"]:
                            for field in log.get("fields", []):
                                if field.get("key") in [
                                    "message",
                                    "error",
                                    "error.message",
                                ]:
                                    error_msg = str(field.get("value", ""))[:200]
                                    break
                            if error_msg:
                                break

                    error_spans.append(
                        {
                            "service": info["service"],
                            "operation": info["operation"],
                            "duration": info["duration"],
                            "error_message": error_msg or "Unknown error",
                            "http_status": info["tags"].get("http.status_code"),
                        }
                    )

            if error_spans:
                error_traces.append(
                    {
                        "trace_id": root_info["trace_id"],
                        "service": root_info["service"],
                        "operation": root_info["operation"],
                        "duration": root_info["duration"],
                        "duration_us": root_info["duration_us"],
                        "span_count": len(spans),
                        "error_spans": error_spans,
                    }
                )

        if args.json:
            print(
                json.dumps(
                    {"traces": error_traces, "count": len(error_traces)}, indent=2
                )
            )
        else:
            print(f"Error traces for '{args.service}'")
            print(
                f"Found {len(error_traces)} traces with errors in the last {args.lookback}h"
            )
            print()

            if not error_traces:
                print("No error traces found.")
                return

            for t in error_traces:
                print(f"Trace: {t['trace_id']}")
                print(f"  Duration: {t['duration']}")
                print(f"  Operation: {t['operation']}")
                print(f"  Error Spans ({len(t['error_spans'])}):")
                for err_span in t["error_spans"][:3]:  # Limit to first 3
                    status = (
                        f" (HTTP {err_span['http_status']})"
                        if err_span["http_status"]
                        else ""
                    )
                    print(
                        f"    - {err_span['service']}: {err_span['operation']}{status}"
                    )
                    if err_span["error_message"]:
                        msg = err_span["error_message"][:80]
                        if len(err_span["error_message"]) > 80:
                            msg += "..."
                        print(f"      Error: {msg}")
                print()

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

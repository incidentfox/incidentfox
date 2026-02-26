#!/usr/bin/env python3
"""Get recent Lambda invocation logs from CloudWatch.

Usage:
    python get_lambda_logs.py --function-name api-handler --hours 1
    python get_lambda_logs.py --function-name api-handler --filter "ERROR" --limit 20
"""

import argparse
import sys
import time

from aws_client import format_output, format_timestamp, get_client


def main():
    parser = argparse.ArgumentParser(description="Get Lambda function logs")
    parser.add_argument("--function-name", required=True, help="Lambda function name")
    parser.add_argument("--filter", default="", help="Filter pattern")
    parser.add_argument(
        "--hours", type=float, default=1, help="Hours to look back (default: 1)"
    )
    parser.add_argument(
        "--limit", type=int, default=50, help="Max events to return (default: 50)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        logs = get_client("logs")

        log_group = f"/aws/lambda/{args.function_name}"

        now_ms = int(time.time() * 1000)
        start_ms = now_ms - int(args.hours * 3600 * 1000)

        kwargs = {
            "logGroupName": log_group,
            "startTime": start_ms,
            "endTime": now_ms,
            "limit": args.limit,
            "interleaved": True,
        }
        if args.filter:
            kwargs["filterPattern"] = args.filter

        events = []
        try:
            response = logs.filter_log_events(**kwargs)
            events.extend(response.get("events", []))

            while "nextToken" in response and len(events) < args.limit:
                kwargs["nextToken"] = response["nextToken"]
                response = logs.filter_log_events(**kwargs)
                events.extend(response.get("events", []))
        except logs.exceptions.ResourceNotFoundException:
            print(
                f"Log group {log_group} not found. Function may not have been invoked yet.",
                file=sys.stderr,
            )
            sys.exit(1)

        events = events[: args.limit]

        formatted_events = [
            {
                "timestamp": format_timestamp(e.get("timestamp", 0)),
                "message": e.get("message", "").strip(),
            }
            for e in events
        ]

        if args.json:
            print(
                format_output(
                    {
                        "function_name": args.function_name,
                        "log_group": log_group,
                        "filter": args.filter,
                        "hours": args.hours,
                        "count": len(formatted_events),
                        "events": formatted_events,
                    }
                )
            )
        else:
            print(f"Function: {args.function_name}")
            print(f"Log Group: {log_group}")
            print(f"Filter: {args.filter or '(none)'}")
            print(f"Time Range: last {args.hours}h")
            print(f"Events: {len(formatted_events)}")
            print()
            for event in formatted_events:
                print(f"[{event['timestamp']}] {event['message']}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Query CloudWatch Logs with filter pattern.

Usage:
    python get_cloudwatch_logs.py --log-group /aws/lambda/my-function --filter "ERROR" --hours 1
    python get_cloudwatch_logs.py --log-group /ecs/my-service --hours 6 --limit 50
    python get_cloudwatch_logs.py --log-group /aws/lambda/api --filter "statusCode=500" --hours 24
"""

import argparse
import sys
import time

from aws_client import format_output, format_timestamp, get_client


def main():
    parser = argparse.ArgumentParser(description="Query CloudWatch Logs")
    parser.add_argument("--log-group", required=True, help="Log group name")
    parser.add_argument(
        "--filter", default="", help="Filter pattern (CloudWatch filter syntax)"
    )
    parser.add_argument(
        "--hours", type=float, default=1, help="Hours to look back (default: 1)"
    )
    parser.add_argument(
        "--limit", type=int, default=100, help="Max events to return (default: 100)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        logs = get_client("logs")

        now_ms = int(time.time() * 1000)
        start_ms = now_ms - int(args.hours * 3600 * 1000)

        kwargs = {
            "logGroupName": args.log_group,
            "startTime": start_ms,
            "endTime": now_ms,
            "limit": args.limit,
            "interleaved": True,
        }
        if args.filter:
            kwargs["filterPattern"] = args.filter

        events = []
        response = logs.filter_log_events(**kwargs)
        events.extend(response.get("events", []))

        # Paginate if needed (up to limit)
        while "nextToken" in response and len(events) < args.limit:
            kwargs["nextToken"] = response["nextToken"]
            response = logs.filter_log_events(**kwargs)
            events.extend(response.get("events", []))

        events = events[: args.limit]

        formatted_events = [
            {
                "timestamp": format_timestamp(e.get("timestamp", 0)),
                "log_stream": e.get("logStreamName", ""),
                "message": e.get("message", "").strip(),
            }
            for e in events
        ]

        if args.json:
            print(
                format_output(
                    {
                        "log_group": args.log_group,
                        "filter": args.filter,
                        "hours": args.hours,
                        "count": len(formatted_events),
                        "events": formatted_events,
                    }
                )
            )
        else:
            print(f"Log Group: {args.log_group}")
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

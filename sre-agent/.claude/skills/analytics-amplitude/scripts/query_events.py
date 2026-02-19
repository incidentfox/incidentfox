#!/usr/bin/env python3
"""Query Amplitude event segmentation data.

Usage:
    python query_events.py --event "Button Clicked" --start 2026-02-10 --end 2026-02-17
    python query_events.py --event "Page Viewed" --start 2026-02-10 --end 2026-02-17 --group-by "platform"
    python query_events.py --event "Error Occurred" --start 2026-02-10 --end 2026-02-17 --interval daily
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from amplitude_client import amplitude_request, format_event_data


def main():
    parser = argparse.ArgumentParser(description="Query Amplitude event segmentation")
    parser.add_argument(
        "--event", required=True, help="Event name (e.g., 'Button Clicked')"
    )
    parser.add_argument(
        "--start", required=True, help="Start date (YYYYMMDD or YYYY-MM-DD)"
    )
    parser.add_argument(
        "--end", required=True, help="End date (YYYYMMDD or YYYY-MM-DD)"
    )
    parser.add_argument(
        "--interval",
        default="-300000",
        help="Interval: -300000 (realtime), 1 (daily), 7 (weekly), 30 (monthly), or use 'daily'/'weekly'/'realtime'",
    )
    parser.add_argument(
        "--group-by", help="Group by event property (e.g., 'platform', 'country')"
    )
    parser.add_argument(
        "--metric",
        default="uniques",
        help="Metric: uniques, totals, avg, pct_dau (default: uniques)",
    )
    parser.add_argument(
        "--filters",
        help='JSON array of filters, e.g., \'[{"subprop_type": "event", "subprop_key": "platform", "subprop_op": "is", "subprop_value": ["iOS"]}]\'',
    )
    parser.add_argument("--raw", action="store_true", help="Output raw JSON response")
    args = parser.parse_args()

    # Normalize dates to YYYYMMDD
    start = args.start.replace("-", "")
    end = args.end.replace("-", "")

    # Normalize interval (Amplitude V2 API values)
    interval_map = {"realtime": "-300000", "daily": "1", "weekly": "7", "monthly": "30"}
    interval = interval_map.get(args.interval, args.interval)

    # Build event spec
    event = {"event_type": args.event}
    if args.filters:
        event["filters"] = json.loads(args.filters)
    if args.group_by:
        event["group_by"] = [{"type": "event", "value": args.group_by}]

    params = {
        "e": json.dumps(event, separators=(",", ":")),
        "start": start,
        "end": end,
        "i": interval,
        "m": args.metric,
    }

    data = amplitude_request("GET", "/events/segmentation", params=params)

    if args.raw:
        print(json.dumps(data, indent=2))
    else:
        event_name = args.event
        metric = args.metric
        print(f"Event: {event_name} ({metric})")
        print(f"Period: {start} to {end}")
        if args.group_by:
            print(f"Grouped by: {args.group_by}")
        print("---")
        print(format_event_data(data))


if __name__ == "__main__":
    main()

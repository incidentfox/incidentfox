#!/usr/bin/env python3
"""List CloudWatch alarms with state.

Usage:
    python list_cloudwatch_alarms.py
    python list_cloudwatch_alarms.py --state ALARM
    python list_cloudwatch_alarms.py --json
"""

import argparse
import sys

from aws_client import format_output, get_client


def main():
    parser = argparse.ArgumentParser(description="List CloudWatch alarms")
    parser.add_argument(
        "--state", choices=["OK", "ALARM", "INSUFFICIENT_DATA"], help="Filter by state"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        cw = get_client("cloudwatch")

        kwargs = {}
        if args.state:
            kwargs["StateValue"] = args.state

        alarms = []
        response = cw.describe_alarms(**kwargs)
        for alarm in response.get("MetricAlarms", []):
            alarms.append(
                {
                    "name": alarm["AlarmName"],
                    "state": alarm["StateValue"],
                    "metric": alarm.get("MetricName", ""),
                    "namespace": alarm.get("Namespace", ""),
                    "description": alarm.get("AlarmDescription", ""),
                    "state_reason": alarm.get("StateReason", ""),
                    "state_updated": str(alarm.get("StateUpdatedTimestamp", "")),
                    "threshold": alarm.get("Threshold"),
                    "comparison": alarm.get("ComparisonOperator", ""),
                    "period": alarm.get("Period"),
                }
            )

        # Also include composite alarms
        for alarm in response.get("CompositeAlarms", []):
            alarms.append(
                {
                    "name": alarm["AlarmName"],
                    "state": alarm["StateValue"],
                    "metric": "(composite)",
                    "namespace": "",
                    "description": alarm.get("AlarmDescription", ""),
                    "state_reason": alarm.get("StateReason", ""),
                    "state_updated": str(alarm.get("StateUpdatedTimestamp", "")),
                }
            )

        if args.json:
            print(format_output({"count": len(alarms), "alarms": alarms}))
        else:
            print(f"CloudWatch Alarms: {len(alarms)}")
            print()
            if alarms:
                print(f"{'NAME':<40} {'STATE':<20} {'NAMESPACE':<16} {'METRIC':<20}")
                print("-" * 96)
                for alarm in alarms:
                    print(
                        f"{alarm['name']:<40} {alarm['state']:<20} "
                        f"{alarm['namespace']:<16} {alarm['metric']:<20}"
                    )
                    if alarm["state"] == "ALARM" and alarm.get("state_reason"):
                        print(f"  → {alarm['state_reason'][:100]}")
            else:
                print("No alarms found.")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

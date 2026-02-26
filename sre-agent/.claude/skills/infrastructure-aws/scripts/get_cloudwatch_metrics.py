#!/usr/bin/env python3
"""Get CloudWatch metrics for a resource.

Usage:
    python get_cloudwatch_metrics.py --namespace AWS/EC2 --metric CPUUtilization --dimension InstanceId=i-1234 --hours 1
    python get_cloudwatch_metrics.py --namespace AWS/ECS --metric CPUUtilization --dimension ClusterName=prod,ServiceName=api --hours 6 --period 300
    python get_cloudwatch_metrics.py --namespace AWS/Lambda --metric Errors --dimension FunctionName=handler --hours 24 --stat Sum
"""

import argparse
import sys
from datetime import datetime, timedelta

from aws_client import format_output, get_client


def parse_dimensions(dim_str: str) -> list[dict]:
    """Parse dimension string like 'InstanceId=i-1234,ClusterName=prod'."""
    dimensions = []
    for pair in dim_str.split(","):
        name, _, value = pair.partition("=")
        if name and value:
            dimensions.append({"Name": name.strip(), "Value": value.strip()})
    return dimensions


def main():
    parser = argparse.ArgumentParser(description="Get CloudWatch metrics")
    parser.add_argument(
        "--namespace", required=True, help="Metric namespace (e.g., AWS/EC2)"
    )
    parser.add_argument(
        "--metric", required=True, help="Metric name (e.g., CPUUtilization)"
    )
    parser.add_argument(
        "--dimension", required=True, help="Dimensions (e.g., InstanceId=i-1234)"
    )
    parser.add_argument(
        "--hours", type=float, default=1, help="Hours to look back (default: 1)"
    )
    parser.add_argument(
        "--period", type=int, default=60, help="Period in seconds (default: 60)"
    )
    parser.add_argument(
        "--stat",
        default="Average",
        help="Statistic: Average, Sum, Maximum, Minimum, SampleCount (default: Average)",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        cw = get_client("cloudwatch")

        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=args.hours)

        response = cw.get_metric_statistics(
            Namespace=args.namespace,
            MetricName=args.metric,
            Dimensions=parse_dimensions(args.dimension),
            StartTime=start_time,
            EndTime=end_time,
            Period=args.period,
            Statistics=[args.stat],
        )

        datapoints = sorted(
            response.get("Datapoints", []),
            key=lambda dp: dp["Timestamp"],
        )

        formatted_points = [
            {
                "timestamp": dp["Timestamp"].isoformat(),
                "value": dp.get(args.stat, 0),
                "unit": dp.get("Unit", ""),
            }
            for dp in datapoints
        ]

        if args.json:
            print(
                format_output(
                    {
                        "namespace": args.namespace,
                        "metric": args.metric,
                        "dimension": args.dimension,
                        "stat": args.stat,
                        "period": args.period,
                        "hours": args.hours,
                        "count": len(formatted_points),
                        "datapoints": formatted_points,
                    }
                )
            )
        else:
            print(f"Namespace: {args.namespace}")
            print(f"Metric: {args.metric} ({args.stat})")
            print(f"Dimensions: {args.dimension}")
            print(f"Period: {args.period}s, Range: last {args.hours}h")
            print(f"Datapoints: {len(formatted_points)}")
            print()
            if formatted_points:
                print(f"{'TIMESTAMP':<28} {'VALUE':>12} {'UNIT':<10}")
                print("-" * 50)
                for dp in formatted_points:
                    print(
                        f"{dp['timestamp']:<28} {dp['value']:>12.2f} {dp['unit']:<10}"
                    )
            else:
                print("No datapoints found for the specified time range.")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

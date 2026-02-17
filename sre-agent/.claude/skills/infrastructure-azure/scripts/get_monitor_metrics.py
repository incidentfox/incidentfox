#!/usr/bin/env python3
"""Get Azure Monitor metrics for a resource."""

import argparse
import sys
from datetime import timedelta

from azure_client import format_output, get_credentials


def main():
    parser = argparse.ArgumentParser(description="Get Azure Monitor metrics")
    parser.add_argument("--resource-id", required=True, help="Full Azure resource ID")
    parser.add_argument("--metrics", required=True, help="Comma-separated metric names")
    parser.add_argument("--timespan", help="ISO 8601 duration (default: PT1H)")
    parser.add_argument(
        "--interval", default="PT5M", help="Aggregation interval (default: PT5M)"
    )
    parser.add_argument(
        "--aggregations",
        default="Average",
        help="Comma-separated aggregations (default: Average)",
    )
    args = parser.parse_args()

    try:
        from azure.monitor.query import MetricsQueryClient

        credential = get_credentials()
        client = MetricsQueryClient(credential)

        metric_names = [m.strip() for m in args.metrics.split(",")]
        aggregations = [a.strip() for a in args.aggregations.split(",")]
        timespan = args.timespan if args.timespan else timedelta(hours=1)

        response = client.query_resource(
            resource_uri=args.resource_id,
            metric_names=metric_names,
            timespan=timespan,
            granularity=args.interval,
            aggregations=aggregations,
        )

        metrics_data = []
        for metric in response.metrics:
            metric_dict = {
                "name": metric.name,
                "unit": str(metric.unit),
                "timeseries": [],
            }
            for timeseries in metric.timeseries:
                ts_data = {"data": []}
                for data_point in timeseries.data:
                    point = {"timestamp": data_point.timestamp.isoformat()}
                    if data_point.average is not None:
                        point["average"] = data_point.average
                    if data_point.maximum is not None:
                        point["maximum"] = data_point.maximum
                    if data_point.minimum is not None:
                        point["minimum"] = data_point.minimum
                    if data_point.total is not None:
                        point["total"] = data_point.total
                    ts_data["data"].append(point)
                metric_dict["timeseries"].append(ts_data)
            metrics_data.append(metric_dict)

        print(
            format_output(
                {
                    "resource_id": args.resource_id,
                    "interval": args.interval,
                    "metrics": metrics_data,
                }
            )
        )

    except Exception as e:
        print(format_output({"error": str(e), "resource_id": args.resource_id}))
        sys.exit(1)


if __name__ == "__main__":
    main()

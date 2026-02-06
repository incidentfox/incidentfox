#!/usr/bin/env python3
"""Calculate Mean Time To Resolve (MTTR) for PagerDuty incidents.

Usage:
    python calculate_mttr.py [--service SERVICE_ID] [--days N]

Examples:
    python calculate_mttr.py
    python calculate_mttr.py --days 30
    python calculate_mttr.py --service PSERVICE123 --days 90
"""

import argparse
import json
import sys

from pagerduty_client import calculate_mttr


def main():
    parser = argparse.ArgumentParser(
        description="Calculate MTTR for PagerDuty incidents"
    )
    parser.add_argument(
        "--service",
        help="Filter by service ID",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days to analyze (default: 30)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    args = parser.parse_args()

    try:
        result = calculate_mttr(
            service_id=args.service,
            days=args.days,
        )

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("=" * 60)
            print("MEAN TIME TO RESOLVE (MTTR)")
            print("=" * 60)
            print(f"Days analyzed: {result.get('days_analyzed', args.days)}")
            if args.service:
                print(f"Service: {args.service}")
            print(f"Sample size: {result.get('sample_size', 0)} resolved incidents")
            print()

            if result.get("sample_size", 0) == 0:
                print(result.get("message", "No data available"))
            else:
                mttr = result.get("mttr_minutes", {})

                def format_duration(minutes):
                    if minutes is None:
                        return "N/A"
                    if minutes < 60:
                        return f"{minutes:.1f} minutes"
                    hours = minutes / 60
                    if hours < 24:
                        return f"{hours:.1f} hours"
                    days = hours / 24
                    return f"{days:.1f} days"

                print("RESOLUTION TIME STATISTICS:")
                print("-" * 40)
                print(f"  Mean:   {format_duration(mttr.get('mean'))}")
                print(f"  Median: {format_duration(mttr.get('median'))}")
                if mttr.get("p95"):
                    print(f"  P95:    {format_duration(mttr.get('p95'))}")
                print(f"  Min:    {format_duration(mttr.get('min'))}")
                print(f"  Max:    {format_duration(mttr.get('max'))}")
                print()

                # Interpretation
                mean_mins = mttr.get("mean", 0)
                if mean_mins < 30:
                    print("✅ Excellent MTTR - incidents resolved quickly")
                elif mean_mins < 60:
                    print("🟢 Good MTTR - within typical SLO targets")
                elif mean_mins < 240:
                    print("🟡 Moderate MTTR - room for improvement")
                else:
                    print("🔴 High MTTR - consider process improvements")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

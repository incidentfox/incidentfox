#!/usr/bin/env python3
"""Get comprehensive log statistics from Datadog - THE MANDATORY FIRST STEP.

This should ALWAYS be called before fetching raw logs. It provides:
- Total count and error rate
- Status distribution (info, warn, error)
- Top services by log volume
- Top error patterns
- Actionable recommendations

Usage:
    python get_statistics.py [--service SERVICE] [--time-range MINUTES]

Examples:
    python get_statistics.py --time-range 60
    python get_statistics.py --service payment
"""

import argparse
import json
import sys

from datadog_client import aggregate_logs, search_logs


def main():
    parser = argparse.ArgumentParser(
        description="Get comprehensive log statistics from Datadog (ALWAYS call first)"
    )
    parser.add_argument("--service", help="Service name to filter")
    parser.add_argument("--host", help="Host to filter")
    parser.add_argument(
        "--time-range", type=int, default=60, help="Time range in minutes (default: 60)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        # Build base query
        query_parts = ["*"]
        if args.service:
            query_parts = [f"service:{args.service}"]
        if args.host:
            query_parts.append(f"host:{args.host}")

        base_query = " ".join(query_parts)

        # 1. Get status distribution (total count by status)
        status_result = aggregate_logs(
            query=base_query,
            group_by=["status"],
            time_range_minutes=args.time_range,
            compute="count",
        )

        # Parse status distribution
        status_dist = {}
        total_count = 0
        error_count = 0
        warn_count = 0

        buckets = status_result.get("data", {}).get("buckets", [])
        for bucket in buckets:
            status = bucket.get("by", {}).get("status", "unknown")
            count = bucket.get("computes", {}).get("c0", 0)
            status_dist[status] = count
            total_count += count
            if status == "error":
                error_count = count
            elif status in ("warn", "warning"):
                warn_count = count

        error_rate = round(error_count / total_count * 100, 2) if total_count > 0 else 0
        warn_rate = round(warn_count / total_count * 100, 2) if total_count > 0 else 0

        # 2. Get top services
        service_result = aggregate_logs(
            query=base_query,
            group_by=["service"],
            time_range_minutes=args.time_range,
            compute="count",
        )

        top_services = []
        service_buckets = service_result.get("data", {}).get("buckets", [])
        for bucket in service_buckets[:10]:
            svc = bucket.get("by", {}).get("service", "unknown")
            count = bucket.get("computes", {}).get("c0", 0)
            top_services.append({"service": svc, "count": count})

        # Sort by count descending
        top_services.sort(key=lambda x: x["count"], reverse=True)

        # 3. Get top error patterns (sample error messages)
        error_query = f"{base_query} status:error"
        error_logs = search_logs(
            query=error_query,
            time_range_minutes=args.time_range,
            limit=50,
        )

        # Extract unique error patterns
        from collections import Counter

        error_patterns = Counter()
        for log in error_logs:
            msg = log.get("message", "")
            # Normalize: remove timestamps, UUIDs, IPs, numbers for grouping
            import re

            normalized = re.sub(
                r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
                "<UUID>",
                msg,
            )
            normalized = re.sub(
                r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "<IP>", normalized
            )
            normalized = re.sub(r"\b\d+\b", "<NUM>", normalized)
            normalized = normalized[:100]  # Truncate for grouping
            error_patterns[normalized] += 1

        top_error_patterns = [
            {"pattern": pattern, "count": count}
            for pattern, count in error_patterns.most_common(10)
        ]

        # 4. Build recommendation
        if total_count == 0:
            recommendation = "No logs found in the specified time range."
        elif error_rate > 10:
            recommendation = f"HIGH error rate ({error_rate}%). Investigate top error patterns immediately."
        elif error_rate > 5:
            recommendation = (
                f"Elevated error rate ({error_rate}%). Review error patterns."
            )
        elif total_count > 10000:
            recommendation = (
                f"High volume ({total_count:,} logs). Use targeted service filter."
            )
        else:
            recommendation = (
                f"Normal volume ({total_count:,} logs). Error rate: {error_rate}%"
            )

        # Build result
        result = {
            "total_count": total_count,
            "error_count": error_count,
            "warning_count": warn_count,
            "error_rate_percent": error_rate,
            "warning_rate_percent": warn_rate,
            "status_distribution": status_dist,
            "top_services": top_services,
            "top_error_patterns": top_error_patterns,
            "time_range_minutes": args.time_range,
            "query": base_query,
            "recommendation": recommendation,
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("=" * 60)
            print("DATADOG LOG STATISTICS")
            print("=" * 60)
            print(f"Query: {base_query}")
            print(f"Time Range: {args.time_range} minutes")
            print()
            print(f"Total Logs: {total_count:,}")
            print(f"Errors: {error_count:,} ({error_rate}%)")
            print(f"Warnings: {warn_count:,} ({warn_rate}%)")
            print()
            print("Status Distribution:")
            for status, count in sorted(status_dist.items(), key=lambda x: -x[1]):
                pct = round(count / total_count * 100, 1) if total_count > 0 else 0
                print(f"  {status}: {count:,} ({pct}%)")
            print()
            print("Top Services:")
            for svc in top_services[:5]:
                print(f"  {svc['service']}: {svc['count']:,}")
            print()
            if top_error_patterns:
                print("Top Error Patterns:")
                for pat in top_error_patterns[:5]:
                    print(f"  [{pat['count']}x] {pat['pattern'][:80]}")
            print()
            print(f"Recommendation: {recommendation}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

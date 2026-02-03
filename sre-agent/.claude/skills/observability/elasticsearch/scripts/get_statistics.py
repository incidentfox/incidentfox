#!/usr/bin/env python3
"""Get comprehensive log statistics from Elasticsearch - THE MANDATORY FIRST STEP.

This should ALWAYS be called before fetching raw logs. It provides:
- Total count and error rate
- Log level distribution
- Top services/applications
- Top error patterns
- Actionable recommendations

Usage:
    python get_statistics.py [--service SERVICE] [--index INDEX] [--time-range MINUTES]

Examples:
    python get_statistics.py --time-range 60
    python get_statistics.py --service payment --index logs-prod-*
"""

import argparse
import json
import sys

from elasticsearch_client import (
    aggregate,
    build_time_range_query,
    search,
)


def main():
    parser = argparse.ArgumentParser(
        description="Get comprehensive log statistics from Elasticsearch (ALWAYS call first)"
    )
    parser.add_argument("--service", help="Service name to filter")
    parser.add_argument("--index", help="Index pattern (default: logs-*)")
    parser.add_argument(
        "--time-range", type=int, default=60, help="Time range in minutes (default: 60)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        # Build base query with time range
        filters = []
        if args.service:
            # Try multiple common service field names
            filters.append(
                {
                    "bool": {
                        "should": [
                            {"term": {"service.name": args.service}},
                            {"term": {"service": args.service}},
                            {"term": {"application": args.service}},
                            {"term": {"kubernetes.container.name": args.service}},
                        ],
                        "minimum_should_match": 1,
                    }
                }
            )

        query = build_time_range_query(args.time_range, filters)

        # 1. Get level distribution with total count
        level_aggs = {
            "level_distribution": {
                "terms": {
                    "field": "level.keyword",
                    "size": 20,
                    "missing": "INFO",
                }
            },
            "level_alt": {
                "terms": {
                    "field": "log.level.keyword",
                    "size": 20,
                    "missing": "INFO",
                }
            },
        }

        level_result = aggregate(query, level_aggs, index=args.index)

        total_count = level_result.get("hits", {}).get("total", {})
        if isinstance(total_count, dict):
            total_count = total_count.get("value", 0)

        # Parse level distribution (use whichever field has data)
        level_dist = {}
        error_count = 0
        warn_count = 0

        # Try primary level field
        buckets = (
            level_result.get("aggregations", {})
            .get("level_distribution", {})
            .get("buckets", [])
        )
        if not buckets:
            buckets = (
                level_result.get("aggregations", {})
                .get("level_alt", {})
                .get("buckets", [])
            )

        for bucket in buckets:
            level = bucket.get("key", "unknown")
            count = bucket.get("doc_count", 0)
            level_dist[level] = count
            if level.lower() in ("error", "err", "critical", "fatal"):
                error_count += count
            elif level.lower() in ("warn", "warning"):
                warn_count += count

        error_rate = round(error_count / total_count * 100, 2) if total_count > 0 else 0
        warn_rate = round(warn_count / total_count * 100, 2) if total_count > 0 else 0

        # 2. Get top services
        service_aggs = {
            "services": {
                "terms": {
                    "field": "service.name.keyword",
                    "size": 10,
                }
            },
            "services_alt": {
                "terms": {
                    "field": "kubernetes.container.name.keyword",
                    "size": 10,
                }
            },
        }

        service_result = aggregate(query, service_aggs, index=args.index)

        top_services = []
        buckets = (
            service_result.get("aggregations", {})
            .get("services", {})
            .get("buckets", [])
        )
        if not buckets:
            buckets = (
                service_result.get("aggregations", {})
                .get("services_alt", {})
                .get("buckets", [])
            )

        for bucket in buckets:
            top_services.append(
                {
                    "service": bucket.get("key"),
                    "count": bucket.get("doc_count", 0),
                }
            )

        # 3. Get sample error messages for pattern analysis
        error_query = build_time_range_query(
            args.time_range,
            filters
            + [
                {
                    "bool": {
                        "should": [
                            {
                                "terms": {
                                    "level.keyword": [
                                        "error",
                                        "ERROR",
                                        "Error",
                                        "critical",
                                        "CRITICAL",
                                        "fatal",
                                        "FATAL",
                                    ]
                                }
                            },
                            {
                                "terms": {
                                    "log.level.keyword": [
                                        "error",
                                        "ERROR",
                                        "Error",
                                        "critical",
                                        "CRITICAL",
                                        "fatal",
                                        "FATAL",
                                    ]
                                }
                            },
                        ],
                        "minimum_should_match": 1,
                    }
                }
            ],
        )

        error_result = search(error_query, index=args.index, size=50)
        error_hits = error_result.get("hits", {}).get("hits", [])

        # Extract unique error patterns
        import re
        from collections import Counter

        error_patterns = Counter()

        for hit in error_hits:
            source = hit.get("_source", {})
            msg = source.get("message") or source.get("log") or source.get("msg") or ""
            # Normalize variable parts
            normalized = re.sub(
                r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
                "<UUID>",
                str(msg),
            )
            normalized = re.sub(
                r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "<IP>", normalized
            )
            normalized = re.sub(r"\b\d+\b", "<NUM>", normalized)
            normalized = normalized[:100]
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
        elif total_count > 100000:
            recommendation = (
                f"Very high volume ({total_count:,} logs). Use targeted service filter."
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
            "level_distribution": level_dist,
            "top_services": top_services,
            "top_error_patterns": top_error_patterns,
            "time_range_minutes": args.time_range,
            "index": args.index or "logs-*",
            "recommendation": recommendation,
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("=" * 60)
            print("ELASTICSEARCH LOG STATISTICS")
            print("=" * 60)
            print(f"Index: {args.index or 'logs-*'}")
            print(f"Time Range: {args.time_range} minutes")
            print()
            print(f"Total Logs: {total_count:,}")
            print(f"Errors: {error_count:,} ({error_rate}%)")
            print(f"Warnings: {warn_count:,} ({warn_rate}%)")
            print()
            print("Level Distribution:")
            for level, count in sorted(level_dist.items(), key=lambda x: -x[1]):
                pct = round(count / total_count * 100, 1) if total_count > 0 else 0
                print(f"  {level}: {count:,} ({pct}%)")
            print()
            if top_services:
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

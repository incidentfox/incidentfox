#!/usr/bin/env python3
"""Sample logs from Elasticsearch using intelligent strategies.

Choose the right sampling strategy based on your investigation needs.

Usage:
    python sample_logs.py --strategy STRATEGY [--service SERVICE] [--index INDEX] [--limit N]

Strategies:
    errors_only   - Only error logs (default for incidents)
    warnings_up   - Warning and error logs
    around_time   - Logs around a specific timestamp
    all           - All log levels

Examples:
    python sample_logs.py --strategy errors_only --service payment
    python sample_logs.py --strategy around_time --timestamp "2026-01-27T05:00:00Z" --window 5
    python sample_logs.py --strategy all --index logs-prod-* --limit 20
"""

import argparse
import json
import sys
from datetime import datetime, timedelta

from elasticsearch_client import (
    build_time_range_query,
    format_log_entry,
    search,
)


def main():
    parser = argparse.ArgumentParser(
        description="Sample logs from Elasticsearch using intelligent strategies"
    )
    parser.add_argument(
        "--strategy",
        choices=["errors_only", "warnings_up", "around_time", "all"],
        default="errors_only",
        help="Sampling strategy (default: errors_only)",
    )
    parser.add_argument("--service", help="Service name to filter")
    parser.add_argument("--index", help="Index pattern (default: logs-*)")
    parser.add_argument(
        "--time-range", type=int, default=60, help="Time range in minutes (default: 60)"
    )
    parser.add_argument(
        "--limit", type=int, default=50, help="Maximum logs to return (default: 50)"
    )
    parser.add_argument(
        "--timestamp",
        help="ISO timestamp for around_time strategy (e.g., 2026-01-27T05:00:00Z)",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=5,
        help="Window in minutes for around_time strategy (default: 5)",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        # Build filters based on strategy and options
        filters = []

        # Service filter
        if args.service:
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

        # Strategy-based level filter
        if args.strategy == "errors_only":
            filters.append(
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
            )
        elif args.strategy == "warnings_up":
            filters.append(
                {
                    "bool": {
                        "should": [
                            {
                                "terms": {
                                    "level.keyword": [
                                        "warn",
                                        "WARN",
                                        "warning",
                                        "WARNING",
                                        "error",
                                        "ERROR",
                                        "critical",
                                        "CRITICAL",
                                    ]
                                }
                            },
                            {
                                "terms": {
                                    "log.level.keyword": [
                                        "warn",
                                        "WARN",
                                        "warning",
                                        "WARNING",
                                        "error",
                                        "ERROR",
                                        "critical",
                                        "CRITICAL",
                                    ]
                                }
                            },
                        ],
                        "minimum_should_match": 1,
                    }
                }
            )

        # Handle around_time strategy
        time_range = args.time_range
        if args.strategy == "around_time":
            if not args.timestamp:
                print(
                    "Error: --timestamp required for around_time strategy",
                    file=sys.stderr,
                )
                sys.exit(1)
            try:
                target = datetime.fromisoformat(args.timestamp.replace("Z", "+00:00"))
                window = timedelta(minutes=args.window)
                start = target - window
                end = target + window

                # Override time range filter
                filters = [
                    f for f in filters if "range" not in str(f)
                ]  # Remove default time range
                filters.append(
                    {
                        "range": {
                            "@timestamp": {
                                "gte": start.isoformat(),
                                "lte": end.isoformat(),
                            }
                        }
                    }
                )
                time_range = args.window * 2
            except ValueError as e:
                print(f"Error parsing timestamp: {e}", file=sys.stderr)
                sys.exit(1)

        # Build query
        if args.strategy != "around_time":
            query = build_time_range_query(time_range, filters)
        else:
            query = {"bool": {"must": filters}} if filters else {"match_all": {}}

        # Execute search
        response = search(query, index=args.index, size=args.limit)

        hits = response.get("hits", {}).get("hits", [])

        # Extract log data
        logs = []
        for hit in hits:
            source = hit.get("_source", {})
            logs.append(
                {
                    "id": hit.get("_id"),
                    "index": hit.get("_index"),
                    "timestamp": source.get("@timestamp"),
                    "level": source.get("level") or source.get("log.level") or "INFO",
                    "service": source.get("service.name")
                    or source.get("service")
                    or source.get("kubernetes.container.name"),
                    "message": source.get("message")
                    or source.get("log")
                    or source.get("msg"),
                    "source": source,
                }
            )

        result = {
            "strategy": args.strategy,
            "index": args.index or "logs-*",
            "count": len(logs),
            "limit": args.limit,
            "time_range_minutes": time_range,
            "logs": logs,
        }

        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print("=" * 60)
            print(f"ELASTICSEARCH LOG SAMPLE ({args.strategy})")
            print("=" * 60)
            print(f"Index: {args.index or 'logs-*'}")
            print(f"Found: {len(logs)} logs")
            print()

            if not logs:
                print("No logs found matching criteria.")
            else:
                for hit in hits:
                    print(format_log_entry(hit))
                    print("-" * 40)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

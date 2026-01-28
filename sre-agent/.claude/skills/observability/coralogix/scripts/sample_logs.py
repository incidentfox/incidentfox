#!/usr/bin/env python3
"""Sample logs using intelligent strategies - NEVER fetch all logs.

Strategies:
- errors_only: Only ERROR/CRITICAL logs (default for incidents)
- around_anomaly: Logs within window of specific timestamp
- first_last: First N/2 and last N/2 logs (timeline view)
- random: Random sample across time range
- all: All severity levels (use with caution)

Usage:
    python sample_logs.py --strategy errors_only --service payment
    python sample_logs.py --strategy around_anomaly --timestamp "2026-01-27T05:00:00Z" --window 60
    python sample_logs.py --strategy first_last --service checkout --limit 50

Environment:
    CORALOGIX_API_KEY - Required
    CORALOGIX_DOMAIN - Team hostname
"""

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta

import httpx
from coralogix_client import execute_query, format_log_entry, get_api_url, get_headers


def extract_log_body(log: dict) -> str:
    """Extract the body/message from a log entry.

    Handles multiple log formats:
    - OTEL logs with nested logRecord.body
    - Direct body field
    - Structured logs without body (creates pattern from fields)
    """
    # Try nested logRecord.body (OTEL format)
    log_record = log.get("logRecord", {})
    if isinstance(log_record, dict):
        body = log_record.get("body", "")
        if body:
            return str(body)

    # Try direct body or message fields
    body = log.get("body", log.get("message", ""))
    if body:
        return str(body)

    # Structured logs - create pattern from key fields
    parts = []
    for key in [
        "limit_event_type",
        "limit_name",
        "error_type",
        "error_code",
        "exception",
        "error",
    ]:
        if key in log:
            parts.append(f"{key}={log[key]}")
    if parts:
        return " ".join(parts)

    return ""


def extract_pattern_summary(logs: list[dict], top_n: int = 5) -> list[dict]:
    """Extract top patterns from log messages.

    Normalizes messages by replacing variable parts with placeholders,
    then counts frequency of each normalized pattern.
    """

    def normalize_message(msg: str) -> str:
        if not msg:
            return "empty"

        normalized = msg
        # UUIDs
        normalized = re.sub(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            "{uuid}",
            normalized,
            flags=re.I,
        )
        # Numbers
        normalized = re.sub(r"\b\d+\b", "{num}", normalized)
        # IP addresses
        normalized = re.sub(
            r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "{ip}", normalized
        )
        # Timestamps
        normalized = re.sub(
            r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}", "{ts}", normalized
        )
        # Hex strings
        normalized = re.sub(r"\b[0-9a-f]{16,}\b", "{hex}", normalized, flags=re.I)

        return normalized[:80]

    pattern_counts = Counter()
    for log in logs:
        msg = extract_log_body(log)
        pattern = normalize_message(msg)
        pattern_counts[pattern] += 1

    return (
        [
            {"pattern": p, "count": c, "percentage": round(c / len(logs) * 100, 1)}
            for p, c in pattern_counts.most_common(top_n)
        ]
        if logs
        else []
    )


def sample_around_anomaly(
    timestamp: str,
    window_seconds: int,
    service: str | None,
    app: str | None,
    limit: int,
) -> dict:
    """Sample logs around a specific timestamp."""
    try:
        ts = datetime.fromisoformat(timestamp.replace("Z", ""))
    except ValueError:
        return {
            "error": f"Invalid timestamp format: {timestamp}. Use ISO format like 2026-01-27T05:00:00Z"
        }

    window_start = ts - timedelta(seconds=window_seconds)
    window_end = ts + timedelta(seconds=window_seconds)

    # Build query
    query = "source logs"
    if app:
        query += f" | filter $l.applicationname == '{app}'"
    if service:
        query += f" | filter $l.subsystemname == '{service}'"
    query += f" | limit {limit}"

    # Custom time range
    url = get_api_url("/api/v1/dataprime/query")
    payload = {
        "query": query,
        "metadata": {
            "startDate": window_start.isoformat() + "Z",
            "endDate": window_end.isoformat() + "Z",
            "tier": "TIER_FREQUENT_SEARCH",
        },
        "limit": limit,
    }

    with httpx.Client(timeout=60.0) as client:
        response = client.post(url, headers=get_headers(), json=payload)
        response.raise_for_status()

        results = []
        for line in response.text.strip().split("\n"):
            if line.strip():
                try:
                    obj = json.loads(line)
                    if "result" in obj and "results" in obj["result"]:
                        for item in obj["result"]["results"]:
                            # Parse userData
                            user_data = item.get("userData", {})
                            if isinstance(user_data, str):
                                try:
                                    user_data = json.loads(user_data)
                                except json.JSONDecodeError:
                                    user_data = {"body": user_data}
                            results.append(user_data)
                except json.JSONDecodeError:
                    continue

    # Categorize logs
    logs_before = []
    logs_at = []
    logs_after = []

    for log in results:
        log_ts_str = log.get("timestamp", "")
        try:
            log_ts = datetime.fromisoformat(log_ts_str.replace("Z", ""))
            if log_ts < ts - timedelta(seconds=2):
                logs_before.append(log)
            elif log_ts > ts + timedelta(seconds=2):
                logs_after.append(log)
            else:
                logs_at.append(log)
        except (ValueError, TypeError):
            logs_at.append(log)

    return {
        "strategy": "around_anomaly",
        "target_timestamp": timestamp,
        "window_seconds": window_seconds,
        "window": {
            "start": window_start.isoformat() + "Z",
            "end": window_end.isoformat() + "Z",
        },
        "logs_before": logs_before[-10:],  # Last 10 before
        "logs_at": logs_at[:10],  # Up to 10 at target
        "logs_after": logs_after[:10],  # First 10 after
        "total_in_window": len(results),
        "summary": f"{len(logs_before)} before, {len(logs_at)} at event, {len(logs_after)} after",
    }


def main():
    parser = argparse.ArgumentParser(
        description="Sample logs using intelligent strategies"
    )
    parser.add_argument(
        "--strategy",
        choices=["errors_only", "around_anomaly", "first_last", "random", "all"],
        default="errors_only",
        help="Sampling strategy (default: errors_only)",
    )
    parser.add_argument("--service", help="Service name (subsystemname)")
    parser.add_argument("--app", help="Application name (applicationname)")
    parser.add_argument(
        "--time-range", type=int, default=60, help="Time range in minutes (default: 60)"
    )
    parser.add_argument(
        "--limit", type=int, default=50, help="Maximum logs to return (default: 50)"
    )
    parser.add_argument(
        "--timestamp", help="[around_anomaly] Target timestamp (ISO format)"
    )
    parser.add_argument(
        "--window",
        type=int,
        default=60,
        help="[around_anomaly] Window seconds (default: 60)",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        # Handle around_anomaly specially
        if args.strategy == "around_anomaly":
            if not args.timestamp:
                print(
                    "Error: --timestamp required for around_anomaly strategy",
                    file=sys.stderr,
                )
                sys.exit(1)

            result = sample_around_anomaly(
                args.timestamp, args.window, args.service, args.app, args.limit
            )

            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print("🎯 Logs Around Anomaly")
                print(f"Target: {args.timestamp}")
                print(f"Window: ±{args.window} seconds")
                print("=" * 60)
                print(f"\n{result['summary']}")

                if result.get("logs_before"):
                    print(f"\n📤 BEFORE ({len(result['logs_before'])} logs)")
                    for log in result["logs_before"][-5:]:
                        print(f"   {format_log_entry(log, max_body_length=100)}")

                if result.get("logs_at"):
                    print(f"\n🎯 AT TARGET ({len(result['logs_at'])} logs)")
                    for log in result["logs_at"][:5]:
                        print(f"   {format_log_entry(log, max_body_length=100)}")

                if result.get("logs_after"):
                    print(f"\n📥 AFTER ({len(result['logs_after'])} logs)")
                    for log in result["logs_after"][:5]:
                        print(f"   {format_log_entry(log, max_body_length=100)}")

            return

        # Build query based on strategy
        query = "source logs"

        if args.app:
            query += f" | filter $l.applicationname == '{args.app}'"
        if args.service:
            query += f" | filter $l.subsystemname == '{args.service}'"

        if args.strategy == "errors_only":
            query += " | filter $m.severity == ERROR || $m.severity == CRITICAL"
        elif args.strategy == "first_last":
            # Get first half
            first_query = (
                query + f" | orderby $m.timestamp asc | limit {args.limit // 2}"
            )
            last_query = (
                query + f" | orderby $m.timestamp desc | limit {args.limit // 2}"
            )

            first_results = execute_query(
                first_query, args.time_range, limit=args.limit // 2
            )
            last_results = execute_query(
                last_query, args.time_range, limit=args.limit // 2
            )

            # Combine
            all_results = first_results + last_results

            pattern_summary = extract_pattern_summary(all_results)

            result = {
                "strategy": "first_last",
                "service": args.service,
                "application": args.app,
                "time_range_minutes": args.time_range,
                "first_logs": first_results,
                "last_logs": last_results,
                "total_sampled": len(all_results),
                "pattern_summary": pattern_summary,
            }

            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print("📊 First/Last Sample")
                print(f"Time range: Last {args.time_range} minutes")
                print("=" * 60)

                print(f"\n🏁 FIRST {len(first_results)} LOGS")
                for log in first_results[:10]:
                    print(f"   {format_log_entry(log, max_body_length=100)}")

                print(f"\n🏁 LAST {len(last_results)} LOGS")
                for log in last_results[:10]:
                    print(f"   {format_log_entry(log, max_body_length=100)}")

                if pattern_summary:
                    print("\n🔍 PATTERN SUMMARY")
                    for p in pattern_summary:
                        print(f"   [{p['count']}x, {p['percentage']}%] {p['pattern']}")

            return

        # Default: errors_only, random, or all
        query += f" | limit {args.limit}"

        results = execute_query(query, args.time_range, limit=args.limit)

        # Extract pattern summary
        pattern_summary = extract_pattern_summary(results)

        result = {
            "strategy": args.strategy,
            "service": args.service,
            "application": args.app,
            "time_range_minutes": args.time_range,
            "sample_size": len(results),
            "logs": results,
            "pattern_summary": pattern_summary,
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            strategy_names = {
                "errors_only": "🔴 Errors Only",
                "random": "🎲 Random Sample",
                "all": "📋 All Logs",
            }
            print(f"{strategy_names.get(args.strategy, args.strategy)}")
            if args.service:
                print(f"Service: {args.service}")
            print(f"Time range: Last {args.time_range} minutes")
            print(f"Sampled: {len(results)} logs")
            print("=" * 60)

            if not results:
                print("\nNo logs found matching criteria.")
            else:
                for log in results[:20]:  # Show first 20
                    print(format_log_entry(log, max_body_length=150))

                if len(results) > 20:
                    print(f"\n... and {len(results) - 20} more logs")

            if pattern_summary:
                print("\n🔍 PATTERN SUMMARY")
                for p in pattern_summary:
                    print(f"   [{p['count']}x, {p['percentage']}%] {p['pattern']}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

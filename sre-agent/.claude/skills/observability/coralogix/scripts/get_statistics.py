#!/usr/bin/env python3
"""Get comprehensive log statistics - THE MANDATORY FIRST STEP.

This should ALWAYS be called before fetching raw logs. It provides:
- Total count and error rate (to decide if sampling is needed)
- Severity distribution
- Top error patterns (crucial for quick triage)
- Time buckets for anomaly/spike detection
- Actionable recommendations

Usage:
    python get_statistics.py [--service SERVICE] [--app APPLICATION] [--time-range MINUTES]

Examples:
    python get_statistics.py --time-range 60
    python get_statistics.py --service payment --app otel-demo
    python get_statistics.py --service checkout --time-range 30

Environment:
    CORALOGIX_API_KEY - Required
    CORALOGIX_DOMAIN - Team hostname
"""

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime

from coralogix_client import execute_query


def detect_anomalies(time_buckets: list[dict], threshold_z: float = 2.0) -> list[dict]:
    """Detect anomalies in time series data using z-score.

    Args:
        time_buckets: List of {timestamp, count} dicts
        threshold_z: Z-score threshold for anomaly (default 2.0)

    Returns:
        List of anomalies with timestamp, count, z_score, type
    """
    if len(time_buckets) < 3:
        return []

    counts = [b.get("count", 0) for b in time_buckets]
    mean = sum(counts) / len(counts)
    variance = sum((x - mean) ** 2 for x in counts) / len(counts)
    std_dev = variance**0.5 if variance > 0 else 1

    anomalies = []
    for bucket in time_buckets:
        count = bucket.get("count", 0)
        z_score = (count - mean) / std_dev if std_dev > 0 else 0

        if abs(z_score) > threshold_z:
            anomalies.append(
                {
                    "timestamp": bucket.get("timestamp"),
                    "count": count,
                    "z_score": round(z_score, 2),
                    "type": "spike" if z_score > 0 else "drop",
                    "description": f"{'Unusually high' if z_score > 0 else 'Unusually low'} ({count} vs avg {round(mean)})",
                }
            )

    return anomalies


def main():
    parser = argparse.ArgumentParser(
        description="Get comprehensive log statistics (ALWAYS call first)"
    )
    parser.add_argument("--service", help="Service name (subsystemname)")
    parser.add_argument("--app", help="Application name (applicationname)")
    parser.add_argument(
        "--time-range", type=int, default=60, help="Time range in minutes (default: 60)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        # 1. Get severity distribution
        severity_query = "source logs"
        if args.app:
            severity_query += f" | filter $l.applicationname == '{args.app}'"
        if args.service:
            severity_query += f" | filter $l.subsystemname == '{args.service}'"
        severity_query += " | groupby $m.severity aggregate count() as cnt"

        severity_results = execute_query(severity_query, args.time_range, limit=20)

        # Parse severity distribution
        severity_dist = {}
        total_count = 0
        error_count = 0
        warning_count = 0

        # Coralogix returns severity as "Info", "Error", etc.
        error_severities = {"error", "critical", "5", "6"}
        warning_severities = {"warning", "warn", "4"}

        for r in severity_results:
            sev = str(r.get("severity", "UNKNOWN"))
            cnt = int(r.get("cnt", 0))
            severity_dist[sev] = cnt
            total_count += cnt
            if sev.lower() in error_severities:
                error_count += cnt
            elif sev.lower() in warning_severities:
                warning_count += cnt

        # 2. Get top error patterns (crucial for triage)
        # Fetch error samples and extract patterns client-side (more reliable than groupby on body)
        pattern_query = (
            "source logs | filter $m.severity == ERROR || $m.severity == CRITICAL"
        )
        if args.app:
            pattern_query = f"source logs | filter $l.applicationname == '{args.app}' | filter $m.severity == ERROR || $m.severity == CRITICAL"
        if args.service:
            if args.app:
                pattern_query += f" | filter $l.subsystemname == '{args.service}'"
            else:
                pattern_query = f"source logs | filter $l.subsystemname == '{args.service}' | filter $m.severity == ERROR || $m.severity == CRITICAL"
        pattern_query += " | limit 100"

        pattern_results = execute_query(pattern_query, args.time_range, limit=100)

        # Extract patterns client-side by normalizing and counting
        pattern_counts = Counter()

        for r in pattern_results:
            # Try multiple locations for the log body
            body = ""
            # OTEL logs: nested in logRecord.body
            log_record = r.get("logRecord", {})
            if isinstance(log_record, dict):
                body = log_record.get("body", "")
            # Direct body field
            if not body:
                body = r.get("body", r.get("message", ""))
            # Structured logs without body - create pattern from key fields
            if not body:
                # Use key fields that describe the error
                parts = []
                for key in [
                    "limit_event_type",
                    "limit_name",
                    "error_type",
                    "error_code",
                    "exception",
                ]:
                    if key in r:
                        parts.append(f"{key}={r[key]}")
                body = " ".join(parts) if parts else str(r)[:100]

            body = str(body)
            # Normalize: replace numbers, UUIDs, IPs with placeholders
            normalized = re.sub(
                r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                "{uuid}",
                body,
                flags=re.I,
            )
            normalized = re.sub(r"\b\d+\b", "{num}", normalized)
            normalized = re.sub(
                r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "{ip}", normalized
            )
            pattern_counts[normalized[:100]] += 1

        top_patterns = [
            {"pattern": p, "count": c} for p, c in pattern_counts.most_common(10)
        ]

        # 3. Get time buckets for anomaly detection (5-minute buckets)
        # Use DataPrime timestamp division for bucketing: $m.timestamp / 5.toInterval('m')
        time_query = "source logs"
        if args.app:
            time_query += f" | filter $l.applicationname == '{args.app}'"
        if args.service:
            time_query += f" | filter $l.subsystemname == '{args.service}'"
        time_query += " | create bucket from $m.timestamp / 5.toInterval('m') | groupby bucket aggregate count() as cnt | orderby bucket asc"

        time_results = execute_query(time_query, args.time_range, limit=100)

        time_buckets = []
        for r in time_results:
            # bucket is a nanosecond timestamp
            bucket_ns = r.get("bucket", 0)
            # Convert nanoseconds to ISO timestamp
            if bucket_ns:
                ts = datetime.fromtimestamp(bucket_ns / 1_000_000_000)
                time_buckets.append(
                    {"timestamp": ts.isoformat(), "count": r.get("cnt", 0)}
                )
            else:
                time_buckets.append(
                    {"timestamp": str(bucket_ns), "count": r.get("cnt", 0)}
                )

        # Detect anomalies
        anomalies = detect_anomalies(time_buckets)

        # 4. Get top services (if not filtering by service)
        top_services = []
        if not args.service:
            service_query = "source logs"
            if args.app:
                service_query += f" | filter $l.applicationname == '{args.app}'"
            service_query += " | groupby $l.subsystemname aggregate count() as cnt | orderby cnt desc | limit 10"

            service_results = execute_query(service_query, args.time_range, limit=10)
            for r in service_results:
                top_services.append(
                    {
                        "service": r.get("subsystemname", "unknown"),
                        "count": r.get("cnt", 0),
                    }
                )

        # Calculate error rate
        error_rate = round(error_count / total_count * 100, 2) if total_count > 0 else 0

        # Generate recommendation
        if total_count > 100000:
            recommendation = f"HIGH volume ({total_count:,} logs). Use narrow time range and sampling with limit."
        elif total_count > 10000:
            recommendation = (
                f"MODERATE volume ({total_count:,} logs). Sampling recommended."
            )
        elif error_count > 100:
            recommendation = f"ELEVATED errors ({error_count} errors, {error_rate}% rate). Investigate top patterns."
        elif error_count > 0:
            recommendation = f"LOW error rate ({error_count} errors, {error_rate}%). Check top patterns for root cause."
        else:
            recommendation = (
                f"HEALTHY ({total_count:,} logs, no errors). Monitor for changes."
            )

        result = {
            "time_range_minutes": args.time_range,
            "service": args.service,
            "application": args.app,
            "total_count": total_count,
            "error_count": error_count,
            "warning_count": warning_count,
            "error_rate_percent": error_rate,
            "severity_distribution": severity_dist,
            "top_error_patterns": top_patterns,
            "top_services": top_services,
            "anomalies_detected": len(anomalies),
            "anomalies": anomalies[:5],  # Top 5 anomalies
            "recommendation": recommendation,
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            # Determine status
            if error_count == 0:
                status_icon = "🟢"
                status = "HEALTHY"
            elif error_rate < 1:
                status_icon = "🟡"
                status = "DEGRADED"
            elif error_rate < 5:
                status_icon = "🟠"
                status = "WARNING"
            else:
                status_icon = "🔴"
                status = "CRITICAL"

            print(f"{status_icon} Log Statistics - {status}")
            print(f"Time range: Last {args.time_range} minutes")
            if args.service:
                print(f"Service: {args.service}")
            if args.app:
                print(f"Application: {args.app}")
            print("=" * 60)

            print("\n📊 VOLUME")
            print(f"   Total logs: {total_count:,}")
            print(f"   Errors: {error_count:,} ({error_rate}%)")
            print(f"   Warnings: {warning_count:,}")

            if severity_dist:
                print("\n📈 SEVERITY DISTRIBUTION")
                for sev, cnt in sorted(severity_dist.items(), key=lambda x: -x[1]):
                    pct = round(cnt / total_count * 100, 1) if total_count > 0 else 0
                    print(f"   {sev}: {cnt:,} ({pct}%)")

            if top_patterns:
                print("\n🔥 TOP ERROR PATTERNS")
                for i, p in enumerate(top_patterns[:5], 1):
                    print(f"   {i}. [{p['count']}x] {p['pattern'][:60]}...")

            if top_services:
                print("\n🏷️  TOP SERVICES")
                for s in top_services[:5]:
                    print(f"   {s['service']}: {s['count']:,} logs")

            if anomalies:
                print(f"\n⚠️  ANOMALIES DETECTED: {len(anomalies)}")
                for a in anomalies[:3]:
                    print(
                        f"   {a['type'].upper()}: {a['description']} at {a['timestamp']}"
                    )

            print("\n💡 RECOMMENDATION")
            print(f"   {recommendation}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

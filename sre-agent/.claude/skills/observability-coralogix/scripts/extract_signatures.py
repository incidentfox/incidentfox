#!/usr/bin/env python3
"""Extract and cluster log signatures for root cause analysis.

This tool normalizes log messages by replacing variable parts with placeholders,
then clusters similar messages to show the VARIETY of issues without reading
every log entry.

Normalization replaces:
- UUIDs → {uuid}
- Numbers → {num}
- IP addresses → {ip}
- Timestamps → {ts}
- Hex strings → {hex}
- URLs → {url}

Usage:
    python extract_signatures.py --service payment --time-range 60
    python extract_signatures.py --app otel-demo --severity ERROR
    python extract_signatures.py --service checkout --max-signatures 30

Environment:
    CORALOGIX_API_KEY - Required
    CORALOGIX_DOMAIN - Team hostname
"""

import argparse
import json
import re
import sys
from collections import Counter

from coralogix_client import execute_query


def normalize_message(msg: str) -> str:
    """Normalize a log message by replacing variable parts with placeholders."""
    if not msg:
        return "empty"

    normalized = str(msg)

    # URLs (do this early before other patterns match parts of URLs)
    normalized = re.sub(r"https?://[^\s]+", "{url}", normalized)

    # UUIDs
    normalized = re.sub(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        "{uuid}",
        normalized,
        flags=re.I,
    )

    # Long hex strings (like trace IDs, span IDs)
    normalized = re.sub(r"\b[0-9a-f]{16,}\b", "{hex}", normalized, flags=re.I)

    # IP addresses
    normalized = re.sub(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "{ip}", normalized)

    # Timestamps in various formats
    normalized = re.sub(
        r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?Z?", "{ts}", normalized
    )
    normalized = re.sub(r"\d{2}/\w{3}/\d{4}:\d{2}:\d{2}:\d{2}", "{ts}", normalized)

    # Duration/latency values (e.g., 123ms, 4.5s)
    normalized = re.sub(
        r"\b\d+(\.\d+)?(ms|s|sec|seconds|milliseconds)\b",
        "{duration}",
        normalized,
        flags=re.I,
    )

    # File paths with line numbers
    normalized = re.sub(r":[0-9]+:[0-9]+", ":{line}", normalized)

    # Numbers (do this last)
    normalized = re.sub(r"\b\d+\b", "{num}", normalized)

    # Collapse multiple whitespace
    normalized = re.sub(r"\s+", " ", normalized)

    return normalized.strip()[:120]


def main():
    parser = argparse.ArgumentParser(
        description="Extract and cluster log signatures for RCA"
    )
    parser.add_argument("--service", help="Service name (subsystemname)")
    parser.add_argument("--app", help="Application name (applicationname)")
    parser.add_argument(
        "--time-range", type=int, default=60, help="Time range in minutes (default: 60)"
    )
    parser.add_argument(
        "--severity", default="ERROR", help="Severity filter (default: ERROR)"
    )
    parser.add_argument(
        "--max-signatures",
        type=int,
        default=20,
        help="Max signatures to return (default: 20)",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=500,
        help="Logs to sample for analysis (default: 500)",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        # Build query
        query = "source logs"

        if args.app:
            query += f" | filter $l.applicationname == '{args.app}'"
        if args.service:
            query += f" | filter $l.subsystemname == '{args.service}'"

        # Apply severity filter
        severity = args.severity.upper()
        if severity == "ERROR":
            query += " | filter $m.severity == ERROR || $m.severity == CRITICAL"
        elif severity == "WARNING":
            query += " | filter $m.severity == WARNING || $m.severity == ERROR || $m.severity == CRITICAL"
        elif severity == "ALL":
            pass  # No filter
        else:
            query += f" | filter $m.severity == {severity}"

        query += f" | limit {args.sample_size}"

        # Fetch logs
        results = execute_query(query, args.time_range, limit=args.sample_size)

        if not results:
            if args.json:
                print(json.dumps({"signatures": [], "message": "No logs found"}))
            else:
                print("No logs found matching criteria.")
            return

        # Extract and normalize signatures
        signature_counts = Counter()
        signature_examples = {}
        signature_services = {}
        signature_first_seen = {}
        signature_last_seen = {}

        for log in results:
            # Get the message body - handle multiple formats
            body = ""
            # OTEL format: nested in logRecord.body
            log_record = log.get("logRecord", {})
            if isinstance(log_record, dict):
                body = log_record.get("body", "")
            # Direct body field
            if not body:
                body = log.get("body", log.get("message", ""))
            # Structured logs - create pattern from fields
            if not body:
                parts = []
                for key in [
                    "limit_event_type",
                    "limit_name",
                    "error_type",
                    "error_code",
                    "exception",
                ]:
                    if key in log:
                        parts.append(f"{key}={log[key]}")
                body = " ".join(parts) if parts else ""

            msg = str(body)
            sig = normalize_message(msg)

            signature_counts[sig] += 1

            if sig not in signature_examples:
                signature_examples[sig] = msg[:300]
                signature_first_seen[sig] = log.get("timestamp", "")
                signature_services[sig] = set()

            signature_last_seen[sig] = log.get("timestamp", "")

            service = log.get("subsystemname", log.get("service", ""))
            if service:
                signature_services[sig].add(service)

        # Build signature list
        total_analyzed = len(results)
        signatures = []

        for i, (pattern, count) in enumerate(
            signature_counts.most_common(args.max_signatures)
        ):
            signatures.append(
                {
                    "id": i + 1,
                    "pattern": pattern,
                    "count": count,
                    "percentage": round(count / total_analyzed * 100, 1),
                    "first_seen": signature_first_seen.get(pattern, ""),
                    "last_seen": signature_last_seen.get(pattern, ""),
                    "sample_message": signature_examples.get(pattern, ""),
                    "affected_services": list(signature_services.get(pattern, set())),
                }
            )

        # Generate insights
        if signatures:
            top_pattern = signatures[0]
            if top_pattern["percentage"] > 50:
                insight = f"DOMINANT ISSUE: {top_pattern['percentage']}% of errors share one pattern. Focus on: {top_pattern['pattern'][:50]}..."
            elif len(signatures) <= 3:
                insight = f"FEW UNIQUE ISSUES: Only {len(signatures)} distinct error patterns. Good candidates for targeted fixes."
            else:
                insight = f"DIVERSE ISSUES: {len(signatures)} unique patterns. Top pattern accounts for {top_pattern['percentage']}% of errors."
        else:
            insight = "No error patterns found."

        result = {
            "time_range_minutes": args.time_range,
            "service": args.service,
            "application": args.app,
            "severity_filter": args.severity,
            "total_logs_analyzed": total_analyzed,
            "unique_signatures": len(signatures),
            "signatures": signatures,
            "insight": insight,
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("🔬 Log Signature Analysis")
            print(f"Time range: Last {args.time_range} minutes")
            print(f"Severity: {args.severity}")
            if args.service:
                print(f"Service: {args.service}")
            print(f"Analyzed: {total_analyzed} logs")
            print("=" * 60)

            print(f"\n💡 INSIGHT: {insight}")

            print(f"\n📊 SIGNATURES ({len(signatures)} unique patterns)")
            print("-" * 60)

            for sig in signatures:
                # Color code by percentage
                if sig["percentage"] > 30:
                    emoji = "🔴"
                elif sig["percentage"] > 10:
                    emoji = "🟠"
                else:
                    emoji = "🟡"

                print(
                    f"\n{emoji} #{sig['id']} - {sig['count']} occurrences ({sig['percentage']}%)"
                )
                print(f"   Pattern: {sig['pattern']}")
                if sig["affected_services"]:
                    print(f"   Services: {', '.join(sig['affected_services'])}")
                print(f"   Sample: {sig['sample_message'][:100]}...")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

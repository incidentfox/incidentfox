#!/usr/bin/env python3
"""Get comprehensive log statistics from Splunk - THE MANDATORY FIRST STEP.

This should ALWAYS be called before fetching raw logs. It provides:
- Total count and error rate
- Log level distribution
- Top sourcetypes and hosts
- Top error patterns
- Actionable recommendations

Usage:
    python get_statistics.py [--index INDEX] [--sourcetype SOURCETYPE] [--time-range MINUTES]

Examples:
    python get_statistics.py --time-range 60
    python get_statistics.py --index main --sourcetype access_combined
"""

import argparse
import json
import sys
from collections import Counter

from splunk_client import execute_search


def main():
    parser = argparse.ArgumentParser(
        description="Get comprehensive log statistics from Splunk (ALWAYS call first)"
    )
    parser.add_argument("--index", help="Index name (default: main)")
    parser.add_argument("--sourcetype", help="Sourcetype to filter")
    parser.add_argument("--host", help="Host to filter")
    parser.add_argument(
        "--time-range", type=int, default=60, help="Time range in minutes (default: 60)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        # Build base search
        base_parts = []
        if args.index:
            base_parts.append(f"index={args.index}")
        else:
            base_parts.append("index=*")
        if args.sourcetype:
            base_parts.append(f"sourcetype={args.sourcetype}")
        if args.host:
            base_parts.append(f"host={args.host}")

        base_search = " ".join(base_parts)

        # 1. Get total count and log level distribution
        stats_query = f'{base_search} | stats count as total, count(eval(log_level="ERROR" OR log_level="error" OR severity="ERROR")) as errors, count(eval(log_level="WARN" OR log_level="warn" OR log_level="WARNING" OR severity="WARN")) as warnings'

        stats_results = execute_search(stats_query, args.time_range, max_results=1)

        total_count = 0
        error_count = 0
        warn_count = 0

        if stats_results:
            stat = stats_results[0]
            total_count = int(stat.get("total", 0))
            error_count = int(stat.get("errors", 0))
            warn_count = int(stat.get("warnings", 0))

        error_rate = round(error_count / total_count * 100, 2) if total_count > 0 else 0
        warn_rate = round(warn_count / total_count * 100, 2) if total_count > 0 else 0

        # 2. Get level distribution
        level_query = f'{base_search} | eval level=coalesce(log_level, severity, "INFO") | stats count by level | sort -count'
        level_results = execute_search(level_query, args.time_range, max_results=20)

        level_dist = {}
        for result in level_results:
            level = result.get("level", "unknown")
            count = int(result.get("count", 0))
            level_dist[level] = count

        # 3. Get top sourcetypes
        sourcetype_query = (
            f"{base_search} | stats count by sourcetype | sort -count | head 10"
        )
        sourcetype_results = execute_search(
            sourcetype_query, args.time_range, max_results=10
        )

        top_sourcetypes = [
            {"sourcetype": r.get("sourcetype"), "count": int(r.get("count", 0))}
            for r in sourcetype_results
        ]

        # 4. Get top hosts
        host_query = f"{base_search} | stats count by host | sort -count | head 10"
        host_results = execute_search(host_query, args.time_range, max_results=10)

        top_hosts = [
            {"host": r.get("host"), "count": int(r.get("count", 0))}
            for r in host_results
        ]

        # 5. Get sample errors for pattern analysis
        error_query = f"{base_search} (log_level=ERROR OR log_level=error OR severity=ERROR) | head 50"
        error_results = execute_search(error_query, args.time_range, max_results=50)

        # Extract unique error patterns
        import re

        error_patterns = Counter()
        for result in error_results:
            msg = result.get("_raw") or result.get("message") or ""
            # Normalize
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

        # 6. Build recommendation
        if total_count == 0:
            recommendation = "No logs found in the specified time range."
        elif error_rate > 10:
            recommendation = f"HIGH error rate ({error_rate}%). Investigate top error patterns immediately."
        elif error_rate > 5:
            recommendation = (
                f"Elevated error rate ({error_rate}%). Review error patterns."
            )
        elif total_count > 100000:
            recommendation = f"Very high volume ({total_count:,} logs). Use targeted sourcetype/index filter."
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
            "top_sourcetypes": top_sourcetypes,
            "top_hosts": top_hosts,
            "top_error_patterns": top_error_patterns,
            "time_range_minutes": args.time_range,
            "base_search": base_search,
            "recommendation": recommendation,
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("=" * 60)
            print("SPLUNK LOG STATISTICS")
            print("=" * 60)
            print(f"Search: {base_search}")
            print(f"Time Range: {args.time_range} minutes")
            print()
            print(f"Total Logs: {total_count:,}")
            print(f"Errors: {error_count:,} ({error_rate}%)")
            print(f"Warnings: {warn_count:,} ({warn_rate}%)")
            print()
            if level_dist:
                print("Level Distribution:")
                for level, count in sorted(level_dist.items(), key=lambda x: -x[1]):
                    pct = round(count / total_count * 100, 1) if total_count > 0 else 0
                    print(f"  {level}: {count:,} ({pct}%)")
                print()
            if top_sourcetypes:
                print("Top Sourcetypes:")
                for st in top_sourcetypes[:5]:
                    print(f"  {st['sourcetype']}: {st['count']:,}")
                print()
            if top_hosts:
                print("Top Hosts:")
                for h in top_hosts[:5]:
                    print(f"  {h['host']}: {h['count']:,}")
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

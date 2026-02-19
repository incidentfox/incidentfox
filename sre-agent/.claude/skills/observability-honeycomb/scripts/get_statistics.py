#!/usr/bin/env python3
"""Get comprehensive statistics from Honeycomb - THE MANDATORY FIRST STEP.

This should ALWAYS be called before running detailed queries. It provides:
- Total event count
- Error rate and distribution
- Top services/endpoints
- Top error patterns
- Actionable recommendations

Usage:
    python get_statistics.py DATASET [--time-range SECONDS] [--filter FILTER]

Examples:
    python get_statistics.py production --time-range 3600
    python get_statistics.py api-requests --filter "http.status_code >= 500"
"""

import argparse
import json
import re
import sys

from honeycomb_client import run_query


def main():
    parser = argparse.ArgumentParser(
        description="Get comprehensive Honeycomb statistics (ALWAYS call first)"
    )
    parser.add_argument("dataset", help="Dataset slug to analyze")
    parser.add_argument(
        "--time-range",
        type=int,
        default=3600,
        help="Time range in seconds (default: 3600 = 1 hour)",
    )
    parser.add_argument(
        "--filter", help="Filter expression (e.g., 'service.name = api')"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        dataset = args.dataset
        time_range = args.time_range

        # Build base filters
        base_filters = []
        if args.filter:
            # Parse simple filter expression
            base_filters.append(parse_filter(args.filter))

        # 1. Get total count
        total_result = run_query(
            dataset,
            calculations=[{"op": "COUNT"}],
            filters=base_filters if base_filters else None,
            time_range=time_range,
        )
        total_count = extract_count(total_result)

        # 2. Get error count (try common error indicators)
        error_count = 0
        error_filters = list(base_filters)

        # Try http.status_code >= 500 first
        try:
            http_error_filters = error_filters + [
                {"column": "http.status_code", "op": ">=", "value": 500}
            ]
            error_result = run_query(
                dataset,
                calculations=[{"op": "COUNT"}],
                filters=http_error_filters,
                time_range=time_range,
            )
            error_count = extract_count(error_result)
        except Exception:
            # Try error=true
            try:
                bool_error_filters = error_filters + [
                    {"column": "error", "op": "=", "value": True}
                ]
                error_result = run_query(
                    dataset,
                    calculations=[{"op": "COUNT"}],
                    filters=bool_error_filters,
                    time_range=time_range,
                )
                error_count = extract_count(error_result)
            except Exception:
                pass  # No error field available

        error_rate = round(error_count / total_count * 100, 2) if total_count > 0 else 0

        # 3. Get service distribution
        service_dist = []
        try:
            service_result = run_query(
                dataset,
                calculations=[{"op": "COUNT"}],
                filters=base_filters if base_filters else None,
                breakdowns=["service.name"],
                time_range=time_range,
                limit=10,
            )
            for row in service_result.get("data", []):
                svc = row.get("service.name", "unknown")
                count = row.get("COUNT", 0)
                service_dist.append({"service": svc, "count": count})
        except Exception:
            pass

        # Sort by count descending
        service_dist.sort(key=lambda x: x["count"], reverse=True)

        # 4. Get status code distribution (for HTTP services)
        status_dist = {}
        try:
            status_result = run_query(
                dataset,
                calculations=[{"op": "COUNT"}],
                filters=base_filters if base_filters else None,
                breakdowns=["http.status_code"],
                time_range=time_range,
                limit=20,
            )
            for row in status_result.get("data", []):
                status = str(row.get("http.status_code", "unknown"))
                count = row.get("COUNT", 0)
                status_dist[status] = count
        except Exception:
            pass

        # 5. Get top error messages
        top_error_patterns = []
        try:
            error_msg_result = run_query(
                dataset,
                calculations=[{"op": "COUNT"}],
                filters=[{"column": "error", "op": "=", "value": True}]
                + (base_filters if base_filters else []),
                breakdowns=["error.message"],
                time_range=time_range,
                limit=10,
            )
            for row in error_msg_result.get("data", []):
                msg = row.get("error.message", "")
                count = row.get("COUNT", 0)
                if msg:
                    # Normalize message
                    normalized = normalize_message(msg)
                    top_error_patterns.append({"pattern": normalized, "count": count})
        except Exception:
            # Try exception.message instead
            try:
                exc_result = run_query(
                    dataset,
                    calculations=[{"op": "COUNT"}],
                    filters=[{"column": "http.status_code", "op": ">=", "value": 500}]
                    + (base_filters if base_filters else []),
                    breakdowns=["exception.message"],
                    time_range=time_range,
                    limit=10,
                )
                for row in exc_result.get("data", []):
                    msg = row.get("exception.message", "")
                    count = row.get("COUNT", 0)
                    if msg:
                        normalized = normalize_message(msg)
                        top_error_patterns.append(
                            {"pattern": normalized, "count": count}
                        )
            except Exception:
                pass

        # 6. Build recommendation
        if total_count == 0:
            recommendation = "No events found in the specified time range."
        elif error_rate > 10:
            recommendation = f"HIGH error rate ({error_rate}%). Investigate top error patterns immediately."
        elif error_rate > 5:
            recommendation = (
                f"Elevated error rate ({error_rate}%). Review error patterns."
            )
        elif total_count > 100000:
            recommendation = (
                f"High volume ({total_count:,} events). Use targeted service filter."
            )
        else:
            recommendation = (
                f"Normal volume ({total_count:,} events). Error rate: {error_rate}%"
            )

        # Build result
        result = {
            "dataset": dataset,
            "total_count": total_count,
            "error_count": error_count,
            "error_rate_percent": error_rate,
            "status_distribution": status_dist,
            "top_services": service_dist,
            "top_error_patterns": top_error_patterns,
            "time_range_seconds": time_range,
            "recommendation": recommendation,
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("=" * 60)
            print("HONEYCOMB STATISTICS")
            print("=" * 60)
            print(f"Dataset: {dataset}")
            print(f"Time Range: {time_range} seconds ({time_range // 60} minutes)")
            print()
            print(f"Total Events: {total_count:,}")
            print(f"Errors: {error_count:,} ({error_rate}%)")
            print()

            if status_dist:
                print("Status Code Distribution:")
                for status, count in sorted(status_dist.items(), key=lambda x: -x[1])[
                    :10
                ]:
                    pct = round(count / total_count * 100, 1) if total_count > 0 else 0
                    print(f"  {status}: {count:,} ({pct}%)")
                print()

            if service_dist:
                print("Top Services:")
                for svc in service_dist[:5]:
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


def extract_count(result: dict) -> int:
    """Extract count from query result."""
    data = result.get("data", [])
    if data and len(data) > 0:
        return data[0].get("COUNT", 0)
    return 0


def normalize_message(msg: str) -> str:
    """Normalize error message for pattern grouping."""
    # Remove UUIDs
    normalized = re.sub(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
        "<UUID>",
        msg,
    )
    # Remove IPs
    normalized = re.sub(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "<IP>", normalized)
    # Remove numbers
    normalized = re.sub(r"\b\d+\b", "<NUM>", normalized)
    # Truncate
    return normalized[:100]


def parse_filter(filter_expr: str) -> dict:
    """Parse a simple filter expression into Honeycomb filter format.

    Supports: =, !=, >, >=, <, <=, exists, contains, starts-with

    Examples:
        "service.name = api" -> {"column": "service.name", "op": "=", "value": "api"}
        "http.status_code >= 500" -> {"column": "http.status_code", "op": ">=", "value": 500}
    """
    # Try operators in order of length (longer first to avoid partial matches)
    operators = [">=", "<=", "!=", "=", ">", "<", "exists", "contains", "starts-with"]

    for op in operators:
        if op in filter_expr:
            parts = filter_expr.split(op, 1)
            if len(parts) == 2:
                column = parts[0].strip()
                value = parts[1].strip()

                # Try to parse value as number
                try:
                    if "." in value:
                        value = float(value)
                    else:
                        value = int(value)
                except ValueError:
                    # Keep as string, remove quotes if present
                    value = value.strip("\"'")

                return {"column": column, "op": op, "value": value}

    raise ValueError(f"Could not parse filter: {filter_expr}")


if __name__ == "__main__":
    main()

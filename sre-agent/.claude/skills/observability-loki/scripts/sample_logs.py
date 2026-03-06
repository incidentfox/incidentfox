#!/usr/bin/env python3
"""Sample log entries from Loki."""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone

from loki_client import format_log_entry, query

# Maximum lookback hours to prevent scanning excessive log history (7 days)
_MAX_LOOKBACK_HOURS = 168

# Maximum result limit
_MAX_LIMIT = 1000

# Characters that are safe in LogQL line filter patterns.
# Allow alphanumeric, common log keywords, and basic regex alternation (|).
# Block characters that could break out of the quoted context or inject LogQL.
_SAFE_LOGQL_FILTER = re.compile(r"^[a-zA-Z0-9_\-.*|:/ ]+$")


def _validate_logql_filter(pattern: str) -> str:
    """Validate and escape a LogQL line filter pattern to prevent injection.

    Only simple keyword/alternation patterns are allowed (e.g., 'error|exception').
    Complex regex or LogQL syntax characters are rejected.
    """
    if not _SAFE_LOGQL_FILTER.match(pattern):
        raise ValueError(
            f"Invalid filter pattern: '{pattern}'. "
            f"Only alphanumeric, underscore, hyphen, dot, pipe (|), colon, slash, "
            f"and space are allowed. Use simple keywords like 'error|exception'."
        )
    return pattern


def main():
    parser = argparse.ArgumentParser(description="Sample logs from Loki")
    parser.add_argument(
        "--selector",
        "-s",
        required=True,
        help="Stream selector (e.g., '{app=\"api\"}')",
    )
    parser.add_argument(
        "--filter",
        "-f",
        help="Line filter pattern (e.g., 'error|exception')",
    )
    parser.add_argument(
        "--limit",
        "-l",
        type=int,
        default=20,
        help="Max entries to return (default: 20)",
    )
    parser.add_argument(
        "--lookback",
        type=float,
        default=1,
        help="Hours to look back (default: 1)",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        # Enforce safety limits
        if args.lookback > _MAX_LOOKBACK_HOURS:
            raise ValueError(
                f"Lookback {args.lookback}h exceeds maximum ({_MAX_LOOKBACK_HOURS}h / 7 days). "
                f"Use a shorter window."
            )
        args.limit = min(args.limit, _MAX_LIMIT)

        # Build query with validated filter
        logql = args.selector
        if args.filter:
            safe_filter = _validate_logql_filter(args.filter)
            logql = f'{args.selector} |~ "{safe_filter}"'

        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=args.lookback)

        result = query(logql, limit=args.limit, start=start, end=now)

        data = result.get("data", {})
        data.get("resultType", "streams")
        streams = data.get("result", [])

        if args.json:
            # Flatten for JSON output
            entries = []
            for stream in streams:
                labels = stream.get("stream", {})
                for entry in stream.get("values", []):
                    ts_ns, line = entry
                    ts = datetime.fromtimestamp(int(ts_ns) / 1e9, tz=timezone.utc)
                    entries.append(
                        {
                            "timestamp": ts.isoformat(),
                            "labels": labels,
                            "line": line,
                        }
                    )
            # Sort by timestamp descending
            entries.sort(key=lambda x: x["timestamp"], reverse=True)
            print(
                json.dumps(
                    {
                        "query": logql,
                        "count": len(entries),
                        "entries": entries[: args.limit],
                    },
                    indent=2,
                )
            )
        else:
            print(f"Logs matching: {logql}")
            print(f"Time window: last {args.lookback}h")
            print()

            # Collect all entries with their stream labels
            all_entries = []
            for stream in streams:
                labels = stream.get("stream", {})
                for entry in stream.get("values", []):
                    all_entries.append((labels, entry))

            # Sort by timestamp descending
            all_entries.sort(key=lambda x: x[1][0], reverse=True)

            if not all_entries:
                print("No logs found matching the query.")
                return

            for labels, entry in all_entries[: args.limit]:
                print(format_log_entry(labels, entry))
                print()

            print("-" * 60)
            print(f"Showing {min(len(all_entries), args.limit)} of {len(all_entries)} entries")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

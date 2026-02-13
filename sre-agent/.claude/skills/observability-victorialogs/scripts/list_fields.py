#!/usr/bin/env python3
"""Discover available fields and values in VictoriaLogs.

Lightweight metadata query — helps the agent understand log structure before querying.

Usage:
    python list_fields.py                                    # List all field names
    python list_fields.py --query '_stream:{app="api"}'      # Scoped to a stream
    python list_fields.py --field level                      # List values for 'level'
    python list_fields.py --field service --limit 20 --json  # Top 20 service values

Examples:
    python list_fields.py
    python list_fields.py --field level
    python list_fields.py --query '_stream:{namespace="prod"}' --field service
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

from victorialogs_client import get_field_names, get_field_values


def main():
    parser = argparse.ArgumentParser(
        description="Discover fields and values in VictoriaLogs"
    )
    parser.add_argument(
        "--query",
        "-q",
        default="*",
        help="LogsQL filter to scope results (default: * = all)",
    )
    parser.add_argument(
        "--field",
        help="Get values for this specific field (omit to list all field names)",
    )
    parser.add_argument(
        "--time-range",
        type=int,
        default=60,
        help="Time range in minutes (default: 60)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Max values to display (default: 50)",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=args.time_range)

        if args.field:
            # Get values for a specific field
            values = get_field_values(
                args.query, args.field, start=start, end=now, limit=args.limit
            )

            if args.json:
                print(
                    json.dumps(
                        {
                            "field": args.field,
                            "query": args.query,
                            "values": values,
                            "count": len(values),
                        },
                        indent=2,
                    )
                )
            else:
                print(f"Values for field '{args.field}':")
                print(f"  Query: {args.query}")
                print(f"  Found: {len(values)} values")
                print()
                for v in values:
                    value = v.get("value", v.get(args.field, str(v)))
                    hits = v.get("hits", "")
                    if hits:
                        print(f"  {value} ({hits} hits)")
                    else:
                        print(f"  {value}")
        else:
            # List all field names
            fields = get_field_names(args.query, start=start, end=now)

            if args.json:
                print(
                    json.dumps(
                        {
                            "query": args.query,
                            "fields": fields,
                            "count": len(fields),
                        },
                        indent=2,
                    )
                )
            else:
                print(f"Available fields ({len(fields)}):")
                print(f"  Query: {args.query}")
                print()
                for f in fields:
                    name = f.get("value", f.get("field", str(f)))
                    hits = f.get("hits", "")
                    if hits:
                        print(f"  {name} ({hits} hits)")
                    else:
                        print(f"  {name}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

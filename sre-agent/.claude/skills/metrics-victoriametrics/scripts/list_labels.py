#!/usr/bin/env python3
"""Discover available labels and values in VictoriaMetrics.

Lightweight metadata query — returns compact lists, not raw series data.

Usage:
    python list_labels.py                           # List all label names
    python list_labels.py --label job               # List values for 'job'
    python list_labels.py --label namespace --match '{job="api"}'  # Scoped values

Examples:
    python list_labels.py
    python list_labels.py --label service --limit 20 --json
"""

import argparse
import json
import sys

from victoriametrics_client import get_label_values, get_labels


def main():
    parser = argparse.ArgumentParser(
        description="Discover labels and values in VictoriaMetrics"
    )
    parser.add_argument(
        "--label", help="Get values for this specific label (omit to list all labels)"
    )
    parser.add_argument(
        "--match", help="Series selector to scope results (e.g., '{job=\"api\"}')"
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
        if args.label:
            # Get values for a specific label
            values = get_label_values(args.label, match=args.match)
            total = len(values)
            values = values[: args.limit]

            if args.json:
                output = {
                    "label": args.label,
                    "values": values,
                    "count": len(values),
                    "total": total,
                }
                if args.match:
                    output["match"] = args.match
                print(json.dumps(output, indent=2))
            else:
                scope = f" (scoped to {args.match})" if args.match else ""
                print(f"Values for label '{args.label}'{scope}:")
                print(f"  Total: {total}")
                print()
                for v in values:
                    print(f"  {v}")
                if total > args.limit:
                    print(f"\n  ... showing {args.limit} of {total} values")
        else:
            # List all label names
            labels = get_labels()

            if args.json:
                print(json.dumps({"labels": labels, "count": len(labels)}, indent=2))
            else:
                print(f"Available labels ({len(labels)}):")
                print()
                for label in labels:
                    print(f"  {label}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

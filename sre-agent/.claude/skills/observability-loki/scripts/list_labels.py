#!/usr/bin/env python3
"""List available labels and their values from Loki."""

import argparse
import json
import sys

from loki_client import get_label_values, get_labels


def main():
    parser = argparse.ArgumentParser(description="List Loki labels and values")
    parser.add_argument("--label", "-l", help="Get values for a specific label")
    parser.add_argument(
        "--lookback",
        type=float,
        default=6,
        help="Hours to look back for labels (default: 6)",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        if args.label:
            # Get values for specific label
            values = get_label_values(args.label)

            if args.json:
                print(json.dumps({"label": args.label, "values": values}, indent=2))
            else:
                print(f"Values for label '{args.label}':")
                print()
                if not values:
                    print("  No values found")
                else:
                    for value in sorted(values):
                        print(f"  {value}")
                print()
                print(f"Total: {len(values)} values")
        else:
            # Get all labels
            labels = get_labels()

            if args.json:
                print(json.dumps({"labels": labels}, indent=2))
            else:
                print("Available Labels:")
                print()
                if not labels:
                    print("  No labels found")
                else:
                    for label in sorted(labels):
                        print(f"  {label}")
                print()
                print(f"Total: {len(labels)} labels")
                print()
                print("Tip: Use --label <name> to see values for a specific label")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""List all datasets available in Honeycomb.

Use this to discover what datasets are available for analysis.

Usage:
    python list_datasets.py [--json]

Examples:
    python list_datasets.py
    python list_datasets.py --json
"""

import argparse
import json
import sys

from honeycomb_client import list_datasets


def main():
    parser = argparse.ArgumentParser(description="List Honeycomb datasets")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        datasets = list_datasets()

        if args.json:
            print(json.dumps(datasets, indent=2))
        else:
            print("=" * 60)
            print("HONEYCOMB DATASETS")
            print("=" * 60)
            print()

            if not datasets:
                print("No datasets found.")
            else:
                print(f"Found {len(datasets)} dataset(s):")
                print()

                for ds in datasets:
                    print(f"  {ds['name']}")
                    print(f"    Slug: {ds['slug']}")
                    if ds.get("description"):
                        print(f"    Description: {ds['description']}")
                    if ds.get("last_written_at"):
                        print(f"    Last Written: {ds['last_written_at']}")
                    print()

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

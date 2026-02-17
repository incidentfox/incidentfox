#!/usr/bin/env python3
"""List Grafana datasources.

Usage:
    python list_datasources.py
"""

import argparse
import json
import sys

from grafana_client import grafana_request


def main():
    parser = argparse.ArgumentParser(description="List Grafana datasources")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        data = grafana_request("GET", "api/datasources")
        datasources = [
            {
                "id": ds.get("id"),
                "name": ds.get("name"),
                "type": ds.get("type"),
                "url": ds.get("url"),
                "is_default": ds.get("isDefault"),
            }
            for ds in data
        ]
        result = {"ok": True, "datasources": datasources, "count": len(datasources)}

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Grafana Datasources ({len(datasources)})")
            for ds in datasources:
                default = " (default)" if ds.get("is_default") else ""
                print(
                    f"  [{ds.get('id', '?')}] {ds.get('name', '?'):30s} ({ds.get('type', '?')}){default}"
                )

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

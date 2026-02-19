#!/usr/bin/env python3
"""Create a Grafana dashboard from a JSON template.

Usage:
    python create_dashboard.py --title "My Dashboard" --template path/to/template.json
    python create_dashboard.py --title "My Dashboard" --template path/to/template.json --folder-uid abc123
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from grafana_client import grafana_request


def main():
    parser = argparse.ArgumentParser(
        description="Create a Grafana dashboard from a template"
    )
    parser.add_argument("--title", required=True, help="Dashboard title")
    parser.add_argument(
        "--template", required=True, help="Path to dashboard JSON template"
    )
    parser.add_argument(
        "--folder-uid", help="Grafana folder UID to create dashboard in"
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite if dashboard with same title exists",
    )
    args = parser.parse_args()

    # Read template
    template_path = Path(args.template)
    if not template_path.exists():
        print(f"ERROR: Template file not found: {template_path}")
        sys.exit(1)

    with open(template_path) as f:
        dashboard = json.load(f)

    # Override title
    dashboard["title"] = args.title
    # Reset id and uid so Grafana creates a new dashboard
    dashboard.pop("id", None)
    dashboard.pop("uid", None)
    dashboard.pop("version", None)

    # Build request payload
    payload = {
        "dashboard": dashboard,
        "overwrite": args.overwrite,
    }
    if args.folder_uid:
        payload["folderUid"] = args.folder_uid

    result = grafana_request("POST", "api/dashboards/db", json_body=payload)

    print("Dashboard created successfully!")
    print(f"  ID: {result.get('id')}")
    print(f"  UID: {result.get('uid')}")
    print(f"  URL: {result.get('url')}")
    print(f"  Status: {result.get('status')}")


if __name__ == "__main__":
    main()

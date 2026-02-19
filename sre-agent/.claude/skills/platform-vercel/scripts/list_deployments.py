#!/usr/bin/env python3
"""List Vercel deployments with optional filters.

Usage:
    python list_deployments.py [--project PROJECT] [--state STATE] [--target TARGET] [--limit 20] [--json]

Examples:
    python list_deployments.py --project my-webapp
    python list_deployments.py --project my-webapp --state ERROR
    python list_deployments.py --project my-webapp --target production --limit 5
    python list_deployments.py --project my-webapp --json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vercel_client import format_deployment, list_deployments


def main():
    parser = argparse.ArgumentParser(description="List Vercel deployments")
    parser.add_argument("--project", help="Filter by project ID or name")
    parser.add_argument(
        "--state",
        choices=["BUILDING", "READY", "ERROR", "CANCELED", "QUEUED"],
        help="Filter by deployment state",
    )
    parser.add_argument(
        "--target",
        choices=["production", "preview"],
        help="Filter by deployment target",
    )
    parser.add_argument(
        "--limit", type=int, default=20, help="Max deployments to return (default: 20)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        deployments = list_deployments(
            project_id=args.project,
            state=args.state,
            target=args.target,
            limit=args.limit,
        )

        if args.json:
            result = {
                "ok": True,
                "deployments": deployments,
                "count": len(deployments),
            }
            print(json.dumps(result, indent=2))
        else:
            filters = []
            if args.project:
                filters.append(f"project={args.project}")
            if args.state:
                filters.append(f"state={args.state}")
            if args.target:
                filters.append(f"target={args.target}")
            filter_str = f" ({', '.join(filters)})" if filters else ""

            print(f"Vercel Deployments{filter_str}: {len(deployments)}\n")
            for d in deployments:
                print(format_deployment(d))
                print()

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

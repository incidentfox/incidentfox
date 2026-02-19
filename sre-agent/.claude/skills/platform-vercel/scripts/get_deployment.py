#!/usr/bin/env python3
"""Get details of a specific Vercel deployment.

Usage:
    python get_deployment.py --deployment DEPLOYMENT_ID_OR_URL [--json]

Examples:
    python get_deployment.py --deployment dpl_abc123
    python get_deployment.py --deployment my-webapp-abc123.vercel.app
    python get_deployment.py --deployment dpl_abc123 --json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vercel_client import format_deployment, get_deployment


def main():
    parser = argparse.ArgumentParser(description="Get Vercel deployment details")
    parser.add_argument(
        "--deployment", required=True, help="Deployment ID (dpl_...) or deployment URL"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        deployment = get_deployment(args.deployment)

        if args.json:
            result = {
                "ok": True,
                "deployment": deployment,
            }
            print(json.dumps(result, indent=2))
        else:
            print(format_deployment(deployment))

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

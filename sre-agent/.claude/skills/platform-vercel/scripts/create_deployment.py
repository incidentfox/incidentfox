#!/usr/bin/env python3
"""Create a new Vercel deployment.

Usage:
    python create_deployment.py --name PROJECT_NAME --repo OWNER/REPO --ref BRANCH_OR_SHA [--target preview] [--json]

Examples:
    python create_deployment.py --name my-webapp --repo acme/my-webapp --ref main --target production
    python create_deployment.py --name my-webapp --repo acme/my-webapp --ref fix/login-bug
    python create_deployment.py --name my-webapp --repo acme/my-webapp --ref abc123def --json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vercel_client import create_deployment, format_deployment


def main():
    parser = argparse.ArgumentParser(description="Create a Vercel deployment")
    parser.add_argument("--name", required=True, help="Project name")
    parser.add_argument("--repo", required=True, help="Git repository (OWNER/REPO)")
    parser.add_argument("--ref", required=True, help="Git branch, tag, or commit SHA")
    parser.add_argument(
        "--target",
        default="preview",
        choices=["production", "preview"],
        help="Deployment target (default: preview)",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        git_source = {
            "type": "github",
            "repo": args.repo,
            "ref": args.ref,
        }

        deployment = create_deployment(
            name=args.name,
            git_source=git_source,
            target=args.target,
        )

        if args.json:
            result = {
                "ok": True,
                "deployment": deployment,
            }
            print(json.dumps(result, indent=2))
        else:
            print("Deployment created successfully!\n")
            print(format_deployment(deployment))

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

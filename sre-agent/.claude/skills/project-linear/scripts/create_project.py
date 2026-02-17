#!/usr/bin/env python3
"""Create a new Linear project."""

import argparse
import json
import sys

from linear_client import graphql_request


def main():
    parser = argparse.ArgumentParser(description="Create Linear project")
    parser.add_argument("--name", required=True)
    parser.add_argument("--description", default="")
    parser.add_argument("--team-id", help="Team ID")
    parser.add_argument("--lead-id", help="Project lead user ID")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        mutation = """mutation CreateProject($input: ProjectCreateInput!) { projectCreate(input: $input) { success project { id name url } } }"""
        input_data = {"name": args.name, "description": args.description}
        if args.team_id:
            input_data["teamIds"] = [args.team_id]
        if args.lead_id:
            input_data["leadId"] = args.lead_id

        data = graphql_request(mutation, {"input": input_data})
        project = data["projectCreate"]["project"]
        result = {
            "id": project["id"],
            "name": project["name"],
            "url": project["url"],
            "success": True,
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Created project: {project['name']}\nURL: {project['url']}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

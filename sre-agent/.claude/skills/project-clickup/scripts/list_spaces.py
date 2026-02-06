#!/usr/bin/env python3
"""List ClickUp spaces and their structure.

Use this to discover available spaces, folders, and lists for task queries.

Usage:
    python list_spaces.py [--json]

Examples:
    python list_spaces.py
    python list_spaces.py --json
    python list_spaces.py --include-lists
"""

import argparse
import json
import sys

from clickup_client import list_folders, list_lists, list_spaces, list_teams


def main():
    parser = argparse.ArgumentParser(description="List ClickUp spaces and structure")
    parser.add_argument(
        "--include-lists", "-l", action="store_true", help="Include lists in output"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        # Get teams
        teams = list_teams()

        if not teams:
            print("No teams/workspaces found.", file=sys.stderr)
            sys.exit(1)

        result = []

        for team in teams:
            team_data = {
                "id": team.get("id"),
                "name": team.get("name"),
                "spaces": [],
            }

            # Get spaces for this team
            spaces = list_spaces(team.get("id"))

            for space in spaces:
                space_data = {
                    "id": space.get("id"),
                    "name": space.get("name"),
                    "private": space.get("private", False),
                }

                if args.include_lists:
                    space_data["folders"] = []
                    space_data["lists"] = []

                    # Get folders
                    folders = list_folders(space.get("id"))
                    for folder in folders:
                        folder_data = {
                            "id": folder.get("id"),
                            "name": folder.get("name"),
                            "lists": [],
                        }

                        # Get lists in folder
                        folder_lists = list_lists(folder_id=folder.get("id"))
                        for lst in folder_lists:
                            folder_data["lists"].append(
                                {
                                    "id": lst.get("id"),
                                    "name": lst.get("name"),
                                    "task_count": lst.get("task_count"),
                                }
                            )

                        space_data["folders"].append(folder_data)

                    # Get folderless lists
                    folderless_lists = list_lists(space_id=space.get("id"))
                    for lst in folderless_lists:
                        space_data["lists"].append(
                            {
                                "id": lst.get("id"),
                                "name": lst.get("name"),
                                "task_count": lst.get("task_count"),
                            }
                        )

                team_data["spaces"].append(space_data)

            result.append(team_data)

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("=" * 60)
            print("CLICKUP WORKSPACE STRUCTURE")
            print("=" * 60)
            print()

            for team in result:
                print(f"Team: {team['name']} (ID: {team['id']})")
                print("-" * 40)

                if not team["spaces"]:
                    print("  No spaces found.")
                else:
                    for space in team["spaces"]:
                        private = " [Private]" if space.get("private") else ""
                        print(f"  Space: {space['name']}{private}")
                        print(f"    ID: {space['id']}")

                        if args.include_lists:
                            # Folders
                            for folder in space.get("folders", []):
                                print(
                                    f"    Folder: {folder['name']} (ID: {folder['id']})"
                                )
                                for lst in folder.get("lists", []):
                                    count = lst.get("task_count", "?")
                                    print(f"      List: {lst['name']} ({count} tasks)")
                                    print(f"        ID: {lst['id']}")

                            # Folderless lists
                            for lst in space.get("lists", []):
                                count = lst.get("task_count", "?")
                                print(f"    List: {lst['name']} ({count} tasks)")
                                print(f"      ID: {lst['id']}")

                        print()

                print()

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

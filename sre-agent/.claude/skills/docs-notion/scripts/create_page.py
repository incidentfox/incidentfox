#!/usr/bin/env python3
"""Create a new Notion page."""

import argparse
import json
import sys

from notion_client import notion_request


def main():
    parser = argparse.ArgumentParser(description="Create Notion page")
    parser.add_argument("--title", required=True)
    parser.add_argument("--parent-page-id", help="Parent page ID")
    parser.add_argument("--parent-database-id", help="Parent database ID")
    parser.add_argument("--content", help="Page content text")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not args.parent_page_id and not args.parent_database_id:
        print(
            "Error: Must provide --parent-page-id or --parent-database-id",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        parent = (
            {"database_id": args.parent_database_id}
            if args.parent_database_id
            else {"page_id": args.parent_page_id}
        )
        properties = {"title": {"title": [{"text": {"content": args.title}}]}}
        children = []
        if args.content:
            for para in args.content.split("\n\n"):
                if para.strip():
                    children.append(
                        {
                            "object": "block",
                            "type": "paragraph",
                            "paragraph": {
                                "rich_text": [
                                    {"type": "text", "text": {"content": para.strip()}}
                                ]
                            },
                        }
                    )

        body = {"parent": parent, "properties": properties}
        if children:
            body["children"] = children
        page = notion_request("POST", "/pages", json_body=body)

        result = {
            "id": page["id"],
            "url": page.get("url"),
            "title": args.title,
            "success": True,
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Created: {args.title}")
            print(f"ID: {page['id']}")
            if page.get("url"):
                print(f"URL: {page['url']}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

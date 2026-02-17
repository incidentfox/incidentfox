#!/usr/bin/env python3
"""Write or append content to a Notion page."""

import argparse
import json
import sys

from notion_client import notion_request


def main():
    parser = argparse.ArgumentParser(description="Write to Notion page")
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--content", required=True)
    parser.add_argument(
        "--replace", action="store_true", help="Replace content (default: append)"
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        children = []
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

        if args.replace:
            blocks = notion_request("GET", f"/blocks/{args.page_id}/children")
            for block in blocks.get("results", []):
                try:
                    notion_request("DELETE", f"/blocks/{block['id']}")
                except Exception:
                    pass

        notion_request(
            "PATCH",
            f"/blocks/{args.page_id}/children",
            json_body={"children": children},
        )

        result = {
            "page_id": args.page_id,
            "success": True,
            "blocks_added": len(children),
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            action = "Replaced" if args.replace else "Appended"
            print(f"{action} {len(children)} blocks to page {args.page_id}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

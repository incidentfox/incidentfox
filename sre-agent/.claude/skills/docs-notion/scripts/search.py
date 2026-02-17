#!/usr/bin/env python3
"""Search Notion pages."""

import argparse
import json
import sys

from notion_client import notion_request


def main():
    parser = argparse.ArgumentParser(description="Search Notion pages")
    parser.add_argument("--query", required=True)
    parser.add_argument("--max-results", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        data = notion_request(
            "POST",
            "/search",
            json_body={"query": args.query, "page_size": args.max_results},
        )
        results = []
        for item in data.get("results", []):
            if item["object"] == "page":
                title = ""
                if "properties" in item and "title" in item["properties"]:
                    title_prop = item["properties"]["title"]
                    if "title" in title_prop and title_prop["title"]:
                        title = title_prop["title"][0]["text"]["content"]
                results.append(
                    {
                        "id": item["id"],
                        "title": title,
                        "url": item.get("url"),
                        "last_edited": item.get("last_edited_time"),
                    }
                )

        if args.json:
            print(json.dumps(results, indent=2))
        else:
            print(f"Found: {len(results)} pages")
            for r in results:
                print(f"  {r['title'] or '(untitled)'}")
                print(f"    ID: {r['id']} | Edited: {r.get('last_edited', '?')}")
                if r.get("url"):
                    print(f"    {r['url']}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

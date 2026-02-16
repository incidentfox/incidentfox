#!/usr/bin/env python3
"""Search the RAPTOR knowledge base for relevant information.

Usage:
    python search.py --query SEARCH_QUERY [--tree TREE] [--top-k N]

Examples:
    python search.py --query "how to debug OOMKilled pods"
    python search.py --query "database connection pool" --top-k 10
"""

import argparse
import json
import sys

from raptor_client import raptor_post


def main():
    parser = argparse.ArgumentParser(description="Search the RAPTOR knowledge base")
    parser.add_argument(
        "--query",
        required=True,
        help="Natural language search query",
    )
    parser.add_argument(
        "--tree",
        help="Knowledge tree to search (default: server default)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of results to return (default: 5)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    args = parser.parse_args()

    try:
        payload = {
            "query": args.query,
            "top_k": args.top_k,
            "include_summaries": True,
        }
        if args.tree:
            payload["tree"] = args.tree

        data = raptor_post("/api/v1/search", payload)

        results = data.get("results", [])

        if args.json:
            print(json.dumps(data, indent=2))
        else:
            print(f"\nFound {len(results)} result(s) for: {args.query}\n")

            for i, result in enumerate(results, 1):
                score = result.get("score", 0)
                text = result.get("text", "")
                layer = result.get("layer", 0)
                is_summary = result.get("is_summary", False)

                label = " [summary]" if is_summary else ""
                print(f"{i}. [{score:.2f}] (layer {layer}){label}")
                # Show first 300 chars, preserve readability
                preview = text[:300].replace("\n", " ")
                if len(text) > 300:
                    preview += "..."
                print(f"   {preview}")
                print()

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

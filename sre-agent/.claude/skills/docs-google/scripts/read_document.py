#!/usr/bin/env python3
"""Read content from a Google Doc."""

import argparse
import json
import sys

from google_client import _is_proxy_mode, docs_request, get_docs_service


def main():
    parser = argparse.ArgumentParser(description="Read Google Doc")
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        if _is_proxy_mode():
            doc = docs_request("GET", f"/documents/{args.document_id}")
        else:
            service = get_docs_service(readonly=True)
            doc = service.documents().get(documentId=args.document_id).execute()

        parts = []
        for el in doc.get("body", {}).get("content", []):
            if "paragraph" in el:
                for text_run in el["paragraph"].get("elements", []):
                    if "textRun" in text_run:
                        parts.append(text_run["textRun"]["content"])
        text = "".join(parts)

        result = {
            "title": doc.get("title"),
            "document_id": args.document_id,
            "content": text,
            "url": f"https://docs.google.com/document/d/{args.document_id}",
        }

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Title: {result['title']}")
            print(f"URL: {result['url']}")
            print(f"Length: {len(text)} chars\n")
            print(text[:2000])
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

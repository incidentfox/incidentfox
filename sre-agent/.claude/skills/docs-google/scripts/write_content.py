#!/usr/bin/env python3
"""Write content to a Google Doc with markdown header formatting."""

import argparse
import json
import sys

from google_client import _is_proxy_mode, docs_request, get_docs_service


def main():
    parser = argparse.ArgumentParser(description="Write to Google Doc")
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--content", required=True)
    parser.add_argument(
        "--replace", action="store_true", help="Replace (default: append)"
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        if _is_proxy_mode():
            doc = docs_request("GET", f"/documents/{args.document_id}")
        else:
            service = get_docs_service()
            doc = service.documents().get(documentId=args.document_id).execute()

        requests = []
        if args.replace:
            end_index = doc["body"]["content"][-1]["endIndex"] - 1
            if end_index > 1:
                requests.append(
                    {
                        "deleteContentRange": {
                            "range": {"startIndex": 1, "endIndex": end_index}
                        }
                    }
                )

        requests.append(
            {"insertText": {"location": {"index": 1}, "text": args.content}}
        )

        lines = args.content.split("\n")
        idx = 1
        for line in lines:
            line_len = len(line) + 1
            style = None
            if line.startswith("### "):
                style = "HEADING_3"
            elif line.startswith("## "):
                style = "HEADING_2"
            elif line.startswith("# "):
                style = "HEADING_1"
            if style:
                requests.append(
                    {
                        "updateParagraphStyle": {
                            "range": {
                                "startIndex": idx,
                                "endIndex": idx + line_len - 1,
                            },
                            "paragraphStyle": {"namedStyleType": style},
                            "fields": "namedStyleType",
                        }
                    }
                )
            idx += line_len

        if _is_proxy_mode():
            docs_request(
                "POST",
                f"/documents/{args.document_id}:batchUpdate",
                json_body={"requests": requests},
            )
        else:
            service.documents().batchUpdate(
                documentId=args.document_id, body={"requests": requests}
            ).execute()

        result = {
            "document_id": args.document_id,
            "success": True,
            "characters_written": len(args.content),
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Wrote {len(args.content)} chars to {args.document_id}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

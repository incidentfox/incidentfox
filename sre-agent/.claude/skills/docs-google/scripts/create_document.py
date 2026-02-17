#!/usr/bin/env python3
"""Create a new Google Doc."""

import argparse
import json
import sys

from google_client import (
    _is_proxy_mode,
    docs_request,
    drive_request,
    get_docs_service,
    get_drive_service,
)


def main():
    parser = argparse.ArgumentParser(description="Create Google Doc")
    parser.add_argument("--title", required=True)
    parser.add_argument("--folder-id", help="Optional folder to create in")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        if _is_proxy_mode():
            doc = docs_request("POST", "/documents", json_body={"title": args.title})
            doc_id = doc["documentId"]
            if args.folder_id:
                f = drive_request(
                    "GET", f"/files/{doc_id}", params={"fields": "parents"}
                )
                prev = ",".join(f.get("parents", []))
                drive_request(
                    "PATCH",
                    f"/files/{doc_id}",
                    params={
                        "addParents": args.folder_id,
                        "removeParents": prev,
                        "fields": "id,parents",
                    },
                )
        else:
            docs = get_docs_service()
            doc = docs.documents().create(body={"title": args.title}).execute()
            doc_id = doc["documentId"]
            if args.folder_id:
                drive = get_drive_service()
                f = drive.files().get(fileId=doc_id, fields="parents").execute()
                prev = ",".join(f.get("parents", []))
                drive.files().update(
                    fileId=doc_id,
                    addParents=args.folder_id,
                    removeParents=prev,
                    fields="id,parents",
                ).execute()

        result = {
            "document_id": doc_id,
            "title": args.title,
            "url": f"https://docs.google.com/document/d/{doc_id}/edit",
            "success": True,
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Created: {args.title}\nURL: {result['url']}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

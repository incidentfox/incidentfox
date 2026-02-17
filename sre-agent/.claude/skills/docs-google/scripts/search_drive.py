#!/usr/bin/env python3
"""Search Google Drive for files."""

import argparse
import json
import sys

from google_client import _is_proxy_mode, drive_request, get_drive_service


def main():
    parser = argparse.ArgumentParser(description="Search Google Drive")
    parser.add_argument("--query", required=True)
    parser.add_argument("--mime-type", help="MIME type filter")
    parser.add_argument("--max-results", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        q = f"name contains '{args.query}'"
        if args.mime_type:
            q += f" and mimeType = '{args.mime_type}'"

        if _is_proxy_mode():
            data = drive_request(
                "GET",
                "/files",
                params={
                    "q": q,
                    "pageSize": args.max_results,
                    "fields": "files(id,name,mimeType,webViewLink,modifiedTime)",
                },
            )
        else:
            service = get_drive_service(readonly=True)
            data = (
                service.files()
                .list(
                    q=q,
                    pageSize=args.max_results,
                    fields="files(id,name,mimeType,webViewLink,modifiedTime)",
                )
                .execute()
            )

        files = [
            {
                "id": f["id"],
                "name": f["name"],
                "type": f["mimeType"],
                "url": f.get("webViewLink"),
                "modified": f.get("modifiedTime"),
            }
            for f in data.get("files", [])
        ]

        if args.json:
            print(json.dumps(files, indent=2))
        else:
            print(f"Found: {len(files)} files")
            for f in files:
                print(f"  {f['name']} ({f['type'][:30]})\n    {f.get('url', '')}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

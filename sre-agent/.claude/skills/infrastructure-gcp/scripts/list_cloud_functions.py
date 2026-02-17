#!/usr/bin/env python3
"""List GCP Cloud Functions."""

import sys

from gcp_client import build_service, format_output, get_project_id


def main():
    try:
        project_id = get_project_id()
        functions = build_service("cloudfunctions", "v1")

        parent = f"projects/{project_id}/locations/-"
        result = (
            functions.projects().locations().functions().list(parent=parent).execute()
        )

        function_list = []
        for function in result.get("functions", []):
            function_list.append(
                {
                    "name": function["name"].split("/")[-1],
                    "runtime": function.get("runtime"),
                    "status": function.get("status"),
                    "entry_point": function.get("entryPoint"),
                    "https_trigger": function.get("httpsTrigger", {}).get("url"),
                    "update_time": function.get("updateTime"),
                }
            )

        print(
            format_output(
                {
                    "project_id": project_id,
                    "function_count": len(function_list),
                    "functions": function_list,
                }
            )
        )

    except Exception as e:
        print(format_output({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()

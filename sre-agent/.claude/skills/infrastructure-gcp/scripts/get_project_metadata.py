#!/usr/bin/env python3
"""Get GCP project metadata."""

import sys

from gcp_client import build_service, format_output, get_project_id


def main():
    try:
        project_id = get_project_id()
        crm = build_service("cloudresourcemanager", "v1")

        project = crm.projects().get(projectId=project_id).execute()

        print(
            format_output(
                {
                    "project_id": project["projectId"],
                    "project_number": project["projectNumber"],
                    "name": project.get("name"),
                    "lifecycle_state": project.get("lifecycleState"),
                    "create_time": project.get("createTime"),
                }
            )
        )

    except Exception as e:
        print(format_output({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()

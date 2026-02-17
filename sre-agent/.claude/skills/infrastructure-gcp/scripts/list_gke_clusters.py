#!/usr/bin/env python3
"""List Google Kubernetes Engine (GKE) clusters."""

import sys

from gcp_client import build_service, format_output, get_project_id


def main():
    try:
        project_id = get_project_id()
        container = build_service("container", "v1")

        parent = f"projects/{project_id}/locations/-"
        result = (
            container.projects().locations().clusters().list(parent=parent).execute()
        )

        clusters = []
        for cluster in result.get("clusters", []):
            clusters.append(
                {
                    "name": cluster["name"],
                    "location": cluster["location"],
                    "status": cluster["status"],
                    "current_master_version": cluster.get("currentMasterVersion"),
                    "current_node_version": cluster.get("currentNodeVersion"),
                    "current_node_count": cluster.get("currentNodeCount"),
                    "endpoint": cluster.get("endpoint"),
                }
            )

        print(
            format_output(
                {
                    "project_id": project_id,
                    "cluster_count": len(clusters),
                    "clusters": clusters,
                }
            )
        )

    except Exception as e:
        print(format_output({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()

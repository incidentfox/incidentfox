#!/usr/bin/env python3
"""List GCP Cloud SQL instances."""

import sys

from gcp_client import build_service, format_output, get_project_id


def main():
    try:
        project_id = get_project_id()
        sqladmin = build_service("sqladmin", "v1beta4")

        result = sqladmin.instances().list(project=project_id).execute()

        instances = []
        for instance in result.get("items", []):
            instances.append(
                {
                    "name": instance["name"],
                    "database_version": instance.get("databaseVersion"),
                    "state": instance.get("state"),
                    "region": instance.get("region"),
                    "tier": instance["settings"].get("tier"),
                    "ip_addresses": [
                        ip["ipAddress"] for ip in instance.get("ipAddresses", [])
                    ],
                }
            )

        print(
            format_output(
                {
                    "project_id": project_id,
                    "instance_count": len(instances),
                    "instances": instances,
                }
            )
        )

    except Exception as e:
        print(format_output({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()

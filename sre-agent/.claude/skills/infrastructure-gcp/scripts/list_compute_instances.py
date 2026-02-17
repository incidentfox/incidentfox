#!/usr/bin/env python3
"""List GCP Compute Engine VM instances."""

import argparse
import sys

from gcp_client import build_service, format_output, get_project_id


def main():
    parser = argparse.ArgumentParser(description="List Compute Engine instances")
    parser.add_argument(
        "--zone", help="Zone filter (e.g., us-central1-a). Default: all zones"
    )
    args = parser.parse_args()

    try:
        project_id = get_project_id()
        compute = build_service("compute", "v1")

        instances = []

        if args.zone:
            result = (
                compute.instances().list(project=project_id, zone=args.zone).execute()
            )
            for instance in result.get("items", []):
                instances.append(_parse_instance(instance, args.zone))
        else:
            zones_result = compute.zones().list(project=project_id).execute()
            for zone_data in zones_result.get("items", []):
                zone_name = zone_data["name"]
                result = (
                    compute.instances()
                    .list(project=project_id, zone=zone_name)
                    .execute()
                )
                for instance in result.get("items", []):
                    instances.append(_parse_instance(instance, zone_name))

        print(
            format_output(
                {
                    "project_id": project_id,
                    "zone": args.zone or "all",
                    "instance_count": len(instances),
                    "instances": instances,
                }
            )
        )

    except Exception as e:
        print(format_output({"error": str(e)}))
        sys.exit(1)


def _parse_instance(instance: dict, zone: str) -> dict:
    return {
        "name": instance["name"],
        "zone": zone,
        "machine_type": instance["machineType"].split("/")[-1],
        "status": instance["status"],
        "internal_ip": (
            instance["networkInterfaces"][0].get("networkIP")
            if instance.get("networkInterfaces")
            else None
        ),
        "external_ip": (
            instance["networkInterfaces"][0].get("accessConfigs", [{}])[0].get("natIP")
            if instance.get("networkInterfaces")
            else None
        ),
    }


if __name__ == "__main__":
    main()

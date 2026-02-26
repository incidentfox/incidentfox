#!/usr/bin/env python3
"""List EC2 instances with status, type, and IPs.

Usage:
    python list_ec2_instances.py [--filters "Name=tag:env,Values=production"]
    python list_ec2_instances.py --filters "Name=instance-state-name,Values=running"
    python list_ec2_instances.py --json
"""

import argparse
import sys

from aws_client import format_output, get_client


def parse_filters(filter_str: str) -> list[dict]:
    """Parse AWS filter string into filter list.

    Format: "Name=tag:env,Values=production Name=instance-state-name,Values=running"
    """
    filters = []
    for part in filter_str.split(" "):
        part = part.strip()
        if not part:
            continue
        kv = {}
        for item in part.split(","):
            key, _, val = item.partition("=")
            if key == "Name":
                kv["Name"] = val
            elif key == "Values":
                kv.setdefault("Values", []).append(val)
        if "Name" in kv and "Values" in kv:
            filters.append(kv)
    return filters


def get_instance_name(instance: dict) -> str:
    """Extract Name tag from instance."""
    for tag in instance.get("Tags", []):
        if tag["Key"] == "Name":
            return tag["Value"]
    return ""


def main():
    parser = argparse.ArgumentParser(description="List EC2 instances")
    parser.add_argument(
        "--filters", help="AWS filters (e.g., 'Name=tag:env,Values=production')"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        ec2 = get_client("ec2")
        kwargs = {}
        if args.filters:
            kwargs["Filters"] = parse_filters(args.filters)

        response = ec2.describe_instances(**kwargs)

        instances = []
        for reservation in response.get("Reservations", []):
            for inst in reservation.get("Instances", []):
                instances.append(
                    {
                        "instance_id": inst["InstanceId"],
                        "name": get_instance_name(inst),
                        "state": inst["State"]["Name"],
                        "type": inst["InstanceType"],
                        "private_ip": inst.get("PrivateIpAddress", ""),
                        "public_ip": inst.get("PublicIpAddress", ""),
                        "az": inst.get("Placement", {}).get("AvailabilityZone", ""),
                        "launch_time": str(inst.get("LaunchTime", "")),
                    }
                )

        if args.json:
            print(format_output({"count": len(instances), "instances": instances}))
        else:
            print(f"EC2 Instances: {len(instances)}")
            print()
            print(
                f"{'INSTANCE ID':<22} {'NAME':<30} {'STATE':<12} {'TYPE':<14} {'PRIVATE IP':<16} {'PUBLIC IP':<16}"
            )
            print("-" * 110)
            for inst in instances:
                print(
                    f"{inst['instance_id']:<22} {inst['name']:<30} {inst['state']:<12} "
                    f"{inst['type']:<14} {inst['private_ip']:<16} {inst['public_ip']:<16}"
                )

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

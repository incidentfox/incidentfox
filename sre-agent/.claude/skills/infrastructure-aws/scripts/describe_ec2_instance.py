#!/usr/bin/env python3
"""Describe an EC2 instance with detailed info and status checks.

Usage:
    python describe_ec2_instance.py --instance-id i-1234567890abcdef0
"""

import argparse
import sys

from aws_client import format_output, get_client


def get_instance_name(instance: dict) -> str:
    """Extract Name tag from instance."""
    for tag in instance.get("Tags", []):
        if tag["Key"] == "Name":
            return tag["Value"]
    return ""


def main():
    parser = argparse.ArgumentParser(description="Describe EC2 instance")
    parser.add_argument("--instance-id", required=True, help="EC2 instance ID")
    args = parser.parse_args()

    try:
        ec2 = get_client("ec2")

        # Describe instance
        response = ec2.describe_instances(InstanceIds=[args.instance_id])
        if not response["Reservations"] or not response["Reservations"][0]["Instances"]:
            print(f"Instance {args.instance_id} not found", file=sys.stderr)
            sys.exit(1)

        inst = response["Reservations"][0]["Instances"][0]

        # Get status checks
        status_response = ec2.describe_instance_status(InstanceIds=[args.instance_id])
        status_info = {}
        if status_response.get("InstanceStatuses"):
            status = status_response["InstanceStatuses"][0]
            status_info = {
                "instance_status": status.get("InstanceStatus", {}).get(
                    "Status", "unknown"
                ),
                "system_status": status.get("SystemStatus", {}).get(
                    "Status", "unknown"
                ),
            }

        # Build output
        result = {
            "instance_id": inst["InstanceId"],
            "name": get_instance_name(inst),
            "state": inst["State"]["Name"],
            "type": inst["InstanceType"],
            "platform": inst.get("PlatformDetails", ""),
            "architecture": inst.get("Architecture", ""),
            "private_ip": inst.get("PrivateIpAddress", ""),
            "public_ip": inst.get("PublicIpAddress", ""),
            "vpc_id": inst.get("VpcId", ""),
            "subnet_id": inst.get("SubnetId", ""),
            "az": inst.get("Placement", {}).get("AvailabilityZone", ""),
            "launch_time": str(inst.get("LaunchTime", "")),
            "ami_id": inst.get("ImageId", ""),
            "key_name": inst.get("KeyName", ""),
            "security_groups": [
                {"id": sg["GroupId"], "name": sg["GroupName"]}
                for sg in inst.get("SecurityGroups", [])
            ],
            "iam_role": inst.get("IamInstanceProfile", {}).get("Arn", ""),
            "tags": {tag["Key"]: tag["Value"] for tag in inst.get("Tags", [])},
            "status_checks": status_info,
            "root_device": {
                "type": inst.get("RootDeviceType", ""),
                "name": inst.get("RootDeviceName", ""),
            },
            "ebs_optimized": inst.get("EbsOptimized", False),
        }

        print(format_output(result))

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

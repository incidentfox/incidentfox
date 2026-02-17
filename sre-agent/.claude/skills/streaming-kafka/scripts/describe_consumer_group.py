#!/usr/bin/env python3
"""Get detailed information about a Kafka consumer group."""

import argparse
import sys

from kafka_client import format_output, get_admin_client


def main():
    parser = argparse.ArgumentParser(description="Describe Kafka consumer group")
    parser.add_argument("--group", required=True, help="Consumer group ID")
    args = parser.parse_args()

    try:
        admin = get_admin_client()

        describe_futures = admin.describe_consumer_groups([args.group])

        group_info = None
        for gid, future in describe_futures.items():
            try:
                group_info = future.result()
            except Exception as e:
                print(format_output({"error": f"Failed to describe group: {e}"}))
                sys.exit(1)

        if not group_info:
            print(format_output({"error": f"Consumer group '{args.group}' not found"}))
            sys.exit(1)

        members = []
        for member in group_info.members:
            assignment = []
            if hasattr(member, "assignment") and member.assignment:
                for tp in member.assignment.topic_partitions:
                    assignment.append({"topic": tp.topic, "partition": tp.partition})

            members.append(
                {
                    "member_id": member.member_id,
                    "client_id": member.client_id,
                    "host": member.host,
                    "assignment": assignment,
                }
            )

        print(
            format_output(
                {
                    "group_id": args.group,
                    "state": str(group_info.state),
                    "coordinator": {
                        "id": (
                            group_info.coordinator.id
                            if group_info.coordinator
                            else None
                        ),
                        "host": (
                            group_info.coordinator.host
                            if group_info.coordinator
                            else None
                        ),
                    },
                    "protocol_type": group_info.protocol_type,
                    "protocol": group_info.protocol,
                    "member_count": len(members),
                    "members": members,
                }
            )
        )

    except Exception as e:
        print(format_output({"error": str(e), "group": args.group}))
        sys.exit(1)


if __name__ == "__main__":
    main()

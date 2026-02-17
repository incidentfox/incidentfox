#!/usr/bin/env python3
"""List Kafka consumer groups."""

import sys

from kafka_client import format_output, get_admin_client


def main():
    try:
        admin = get_admin_client()

        groups_future = admin.list_consumer_groups()
        groups_result = groups_future.result()

        groups = []
        for group in groups_result.valid:
            groups.append(
                {
                    "group_id": group.group_id,
                    "is_simple": group.is_simple_consumer_group,
                    "state": str(group.state) if hasattr(group, "state") else None,
                }
            )

        groups.sort(key=lambda g: g["group_id"])

        print(
            format_output(
                {
                    "group_count": len(groups),
                    "groups": groups,
                }
            )
        )

    except Exception as e:
        print(format_output({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()

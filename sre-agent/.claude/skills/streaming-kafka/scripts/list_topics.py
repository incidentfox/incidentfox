#!/usr/bin/env python3
"""List Kafka topics."""

import argparse
import sys

from kafka_client import format_output, get_admin_client


def main():
    parser = argparse.ArgumentParser(description="List Kafka topics")
    parser.add_argument(
        "--include-internal", action="store_true", help="Include internal topics (__*)"
    )
    args = parser.parse_args()

    try:
        admin = get_admin_client()
        metadata = admin.list_topics(timeout=10)

        topics = []
        for topic_name, topic_metadata in metadata.topics.items():
            if not args.include_internal and topic_name.startswith("__"):
                continue

            partitions = []
            for partition_id, partition_metadata in topic_metadata.partitions.items():
                partitions.append(
                    {
                        "id": partition_id,
                        "leader": partition_metadata.leader,
                        "replicas": list(partition_metadata.replicas),
                        "isrs": list(partition_metadata.isrs),
                    }
                )

            topics.append(
                {
                    "name": topic_name,
                    "partition_count": len(topic_metadata.partitions),
                    "partitions": partitions,
                }
            )

        topics.sort(key=lambda t: t["name"])

        print(
            format_output(
                {
                    "cluster_id": metadata.cluster_id,
                    "broker_count": len(metadata.brokers),
                    "topic_count": len(topics),
                    "topics": topics,
                }
            )
        )

    except Exception as e:
        print(format_output({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()

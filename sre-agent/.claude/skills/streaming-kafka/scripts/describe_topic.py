#!/usr/bin/env python3
"""Get detailed information about a Kafka topic."""

import argparse
import sys

from kafka_client import format_output, get_admin_client, get_consumer


def main():
    parser = argparse.ArgumentParser(description="Describe Kafka topic")
    parser.add_argument("--topic", required=True, help="Topic name")
    args = parser.parse_args()

    try:
        from confluent_kafka import TopicPartition
        from confluent_kafka.admin import ConfigResource, ResourceType

        admin = get_admin_client()
        metadata = admin.list_topics(topic=args.topic, timeout=10)

        if args.topic not in metadata.topics:
            print(format_output({"error": f"Topic '{args.topic}' not found"}))
            sys.exit(1)

        topic_metadata = metadata.topics[args.topic]

        partitions = []
        for partition_id, partition_metadata in topic_metadata.partitions.items():
            partitions.append(
                {
                    "id": partition_id,
                    "leader": partition_metadata.leader,
                    "replicas": list(partition_metadata.replicas),
                    "isrs": list(partition_metadata.isrs),
                    "in_sync": len(partition_metadata.isrs)
                    == len(partition_metadata.replicas),
                }
            )

        # Get topic config
        config_resource = ConfigResource(ResourceType.TOPIC, args.topic)
        config_futures = admin.describe_configs([config_resource])

        topic_config = {}
        for resource, future in config_futures.items():
            try:
                config = future.result()
                for key, value in config.items():
                    topic_config[key] = {
                        "value": value.value,
                        "source": str(value.source),
                        "is_default": value.is_default,
                    }
            except Exception:
                pass

        # Get offsets
        consumer = get_consumer()
        partition_offsets = []
        try:
            for partition in partitions:
                tp = TopicPartition(args.topic, partition["id"])
                low, high = consumer.get_watermark_offsets(tp, timeout=5)
                partition_offsets.append(
                    {
                        "partition": partition["id"],
                        "low_offset": low,
                        "high_offset": high,
                        "message_count": high - low,
                    }
                )
            consumer.close()
        except Exception:
            try:
                consumer.close()
            except Exception:
                pass

        total_messages = sum(p.get("message_count", 0) for p in partition_offsets)
        under_replicated = [p for p in partitions if not p["in_sync"]]

        print(
            format_output(
                {
                    "name": args.topic,
                    "partition_count": len(partitions),
                    "replication_factor": (
                        len(partitions[0]["replicas"]) if partitions else 0
                    ),
                    "total_messages": total_messages,
                    "under_replicated_partitions": len(under_replicated),
                    "partitions": partitions,
                    "partition_offsets": partition_offsets,
                    "config": topic_config,
                }
            )
        )

    except Exception as e:
        print(format_output({"error": str(e), "topic": args.topic}))
        sys.exit(1)


if __name__ == "__main__":
    main()

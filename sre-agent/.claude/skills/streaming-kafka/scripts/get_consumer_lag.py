#!/usr/bin/env python3
"""Get consumer lag for a Kafka consumer group."""

import argparse
import sys

from kafka_client import format_output, get_admin_client, get_consumer


def main():
    parser = argparse.ArgumentParser(description="Get Kafka consumer lag")
    parser.add_argument("--group", required=True, help="Consumer group ID")
    parser.add_argument("--topic", help="Optional topic filter")
    args = parser.parse_args()

    try:
        from confluent_kafka import TopicPartition

        admin = get_admin_client()

        # Get committed offsets
        list_offsets_futures = admin.list_consumer_group_offsets([args.group])

        committed_offsets = {}
        for gid, future in list_offsets_futures.items():
            try:
                result = future.result()
                for tp in result.topic_partitions:
                    if args.topic and tp.topic != args.topic:
                        continue
                    committed_offsets[(tp.topic, tp.partition)] = tp.offset
            except Exception:
                pass

        if not committed_offsets:
            print(
                format_output(
                    {
                        "group_id": args.group,
                        "message": "No committed offsets found",
                        "partitions": [],
                    }
                )
            )
            return

        # Get high watermarks
        consumer = get_consumer(f"{args.group}-lag-check")

        partitions = []
        total_lag = 0
        topics_set = set()

        try:
            for (topic_name, partition), committed in committed_offsets.items():
                tp = TopicPartition(topic_name, partition)
                low, high = consumer.get_watermark_offsets(tp, timeout=5)

                lag = max(0, high - committed if committed >= 0 else high - low)

                partitions.append(
                    {
                        "topic": topic_name,
                        "partition": partition,
                        "committed_offset": committed,
                        "high_watermark": high,
                        "low_watermark": low,
                        "lag": lag,
                    }
                )

                total_lag += lag
                topics_set.add(topic_name)

            consumer.close()
        except Exception:
            try:
                consumer.close()
            except Exception:
                pass

        partitions.sort(key=lambda p: p["lag"], reverse=True)

        if total_lag == 0:
            health = "healthy"
        elif total_lag < 1000:
            health = "minor_lag"
        elif total_lag < 100000:
            health = "lagging"
        else:
            health = "severely_lagging"

        print(
            format_output(
                {
                    "group_id": args.group,
                    "topic_filter": args.topic,
                    "topics_subscribed": list(topics_set),
                    "partition_count": len(partitions),
                    "total_lag": total_lag,
                    "health": health,
                    "partitions": partitions,
                }
            )
        )

    except Exception as e:
        print(format_output({"error": str(e), "group": args.group}))
        sys.exit(1)


if __name__ == "__main__":
    main()

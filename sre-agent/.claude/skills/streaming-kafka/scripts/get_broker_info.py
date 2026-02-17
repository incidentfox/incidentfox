#!/usr/bin/env python3
"""Get Kafka broker information."""

import sys

from kafka_client import format_output, get_admin_client


def main():
    try:
        admin = get_admin_client()
        metadata = admin.list_topics(timeout=10)

        brokers = []
        for broker_id, broker in metadata.brokers.items():
            brokers.append(
                {
                    "id": broker_id,
                    "host": broker.host,
                    "port": broker.port,
                }
            )

        brokers.sort(key=lambda b: b["id"])

        print(
            format_output(
                {
                    "cluster_id": metadata.cluster_id,
                    "controller_id": metadata.controller_id,
                    "broker_count": len(brokers),
                    "brokers": brokers,
                }
            )
        )

    except Exception as e:
        print(format_output({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()

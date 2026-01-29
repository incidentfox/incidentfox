"""Kafka tools for topic and consumer group management.

Supports:
- Apache Kafka
- Confluent Platform
- Amazon MSK
- Azure Event Hubs (Kafka protocol)
- Any Kafka-compatible broker
"""

import os
from typing import Any

from ..core.config_required import handle_integration_not_configured
from ..core.errors import ToolExecutionError
from ..core.execution_context import get_execution_context
from ..core.integration_errors import IntegrationNotConfiguredError
from ..core.logging import get_logger

logger = get_logger(__name__)


def _get_kafka_config() -> dict:
    """Get Kafka configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("kafka")
        if config and config.get("bootstrap_servers"):
            return config

    # 2. Try environment variables (dev/testing fallback)
    if os.getenv("KAFKA_BOOTSTRAP_SERVERS"):
        return {
            "bootstrap_servers": os.getenv("KAFKA_BOOTSTRAP_SERVERS"),
            "security_protocol": os.getenv("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT"),
            "sasl_mechanism": os.getenv("KAFKA_SASL_MECHANISM"),
            "sasl_username": os.getenv("KAFKA_SASL_USERNAME"),
            "sasl_password": os.getenv("KAFKA_SASL_PASSWORD"),
            "ssl_cafile": os.getenv("KAFKA_SSL_CAFILE"),
            "ssl_certfile": os.getenv("KAFKA_SSL_CERTFILE"),
            "ssl_keyfile": os.getenv("KAFKA_SSL_KEYFILE"),
        }

    # 3. Not configured - raise error
    raise IntegrationNotConfiguredError(
        integration_id="kafka",
        tool_id="kafka_tools",
        missing_fields=["bootstrap_servers"],
    )


def _get_admin_client():
    """Get Kafka AdminClient using configured credentials."""
    try:
        from confluent_kafka.admin import AdminClient
    except ImportError:
        raise ToolExecutionError(
            "kafka",
            "confluent-kafka not installed. Install with: pip install confluent-kafka",
        )

    config = _get_kafka_config()

    # Build admin client config
    admin_config = {
        "bootstrap.servers": config["bootstrap_servers"],
    }

    # Add security settings
    security_protocol = config.get("security_protocol", "PLAINTEXT")
    admin_config["security.protocol"] = security_protocol

    if security_protocol in ("SASL_SSL", "SASL_PLAINTEXT"):
        admin_config["sasl.mechanism"] = config.get("sasl_mechanism", "PLAIN")
        if config.get("sasl_username"):
            admin_config["sasl.username"] = config["sasl_username"]
        if config.get("sasl_password"):
            admin_config["sasl.password"] = config["sasl_password"]

    if security_protocol in ("SSL", "SASL_SSL"):
        if config.get("ssl_cafile"):
            admin_config["ssl.ca.location"] = config["ssl_cafile"]
        if config.get("ssl_certfile"):
            admin_config["ssl.certificate.location"] = config["ssl_certfile"]
        if config.get("ssl_keyfile"):
            admin_config["ssl.key.location"] = config["ssl_keyfile"]

    return AdminClient(admin_config)


def _get_consumer(group_id: str = "incidentfox-admin"):
    """Get Kafka Consumer for offset queries."""
    try:
        from confluent_kafka import Consumer
    except ImportError:
        raise ToolExecutionError(
            "kafka",
            "confluent-kafka not installed. Install with: pip install confluent-kafka",
        )

    config = _get_kafka_config()

    consumer_config = {
        "bootstrap.servers": config["bootstrap_servers"],
        "group.id": group_id,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    }

    # Add security settings
    security_protocol = config.get("security_protocol", "PLAINTEXT")
    consumer_config["security.protocol"] = security_protocol

    if security_protocol in ("SASL_SSL", "SASL_PLAINTEXT"):
        consumer_config["sasl.mechanism"] = config.get("sasl_mechanism", "PLAIN")
        if config.get("sasl_username"):
            consumer_config["sasl.username"] = config["sasl_username"]
        if config.get("sasl_password"):
            consumer_config["sasl.password"] = config["sasl_password"]

    if security_protocol in ("SSL", "SASL_SSL"):
        if config.get("ssl_cafile"):
            consumer_config["ssl.ca.location"] = config["ssl_cafile"]

    return Consumer(consumer_config)


def kafka_list_topics(include_internal: bool = False) -> dict[str, Any]:
    """
    List all Kafka topics.

    Args:
        include_internal: Include internal topics (starting with __) (default: False)

    Returns:
        Dict with topic list
    """
    try:
        admin = _get_admin_client()

        # Get cluster metadata
        metadata = admin.list_topics(timeout=10)

        topics = []
        for topic_name, topic_metadata in metadata.topics.items():
            # Skip internal topics unless requested
            if not include_internal and topic_name.startswith("__"):
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

        # Sort by name
        topics.sort(key=lambda t: t["name"])

        logger.info("kafka_topics_listed", count=len(topics))

        return {
            "cluster_id": metadata.cluster_id,
            "broker_count": len(metadata.brokers),
            "topic_count": len(topics),
            "topics": topics,
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "kafka_list_topics", "kafka")
    except Exception as e:
        logger.error("kafka_list_topics_failed", error=str(e))
        raise ToolExecutionError("kafka_list_topics", str(e), e)


def kafka_describe_topic(topic_name: str) -> dict[str, Any]:
    """
    Get detailed information about a Kafka topic.

    Args:
        topic_name: Name of the topic

    Returns:
        Dict with topic details including partitions, configs, and offsets
    """
    try:
        from confluent_kafka.admin import ConfigResource, ResourceType
    except ImportError:
        raise ToolExecutionError(
            "kafka",
            "confluent-kafka not installed. Install with: pip install confluent-kafka",
        )

    try:
        admin = _get_admin_client()

        # Get topic metadata
        metadata = admin.list_topics(topic=topic_name, timeout=10)

        if topic_name not in metadata.topics:
            return {
                "success": False,
                "error": f"Topic '{topic_name}' not found",
            }

        topic_metadata = metadata.topics[topic_name]

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
        config_resource = ConfigResource(ResourceType.TOPIC, topic_name)
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
            except Exception as e:
                logger.warning("kafka_config_fetch_failed", error=str(e))

        # Get offsets using consumer
        consumer = _get_consumer()

        try:
            from confluent_kafka import TopicPartition

            # Get beginning and end offsets for each partition
            partition_offsets = []
            for partition in partitions:
                tp = TopicPartition(topic_name, partition["id"])

                # Get low and high watermarks
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

        except Exception as e:
            logger.warning("kafka_offset_fetch_failed", error=str(e))
            partition_offsets = []
            try:
                consumer.close()
            except Exception:
                pass

        # Calculate totals
        total_messages = sum(p.get("message_count", 0) for p in partition_offsets)
        under_replicated = [p for p in partitions if not p["in_sync"]]

        logger.info(
            "kafka_topic_described",
            topic=topic_name,
            partitions=len(partitions),
        )

        return {
            "name": topic_name,
            "partition_count": len(partitions),
            "replication_factor": len(partitions[0]["replicas"]) if partitions else 0,
            "total_messages": total_messages,
            "under_replicated_partitions": len(under_replicated),
            "partitions": partitions,
            "partition_offsets": partition_offsets,
            "config": topic_config,
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "kafka_describe_topic", "kafka")
    except Exception as e:
        logger.error("kafka_describe_topic_failed", error=str(e), topic=topic_name)
        raise ToolExecutionError("kafka_describe_topic", str(e), e)


def kafka_list_consumer_groups() -> dict[str, Any]:
    """
    List all Kafka consumer groups.

    Returns:
        Dict with consumer group list
    """
    try:
        admin = _get_admin_client()

        # List consumer groups
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

        # Sort by group_id
        groups.sort(key=lambda g: g["group_id"])

        logger.info("kafka_consumer_groups_listed", count=len(groups))

        return {
            "group_count": len(groups),
            "groups": groups,
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "kafka_list_consumer_groups", "kafka"
        )
    except Exception as e:
        logger.error("kafka_list_consumer_groups_failed", error=str(e))
        raise ToolExecutionError("kafka_list_consumer_groups", str(e), e)


def kafka_describe_consumer_group(group_id: str) -> dict[str, Any]:
    """
    Get detailed information about a Kafka consumer group.

    Args:
        group_id: Consumer group ID

    Returns:
        Dict with consumer group details including members and offsets
    """
    try:
        admin = _get_admin_client()

        # Describe consumer group
        describe_futures = admin.describe_consumer_groups([group_id])

        group_info = None
        for gid, future in describe_futures.items():
            try:
                result = future.result()
                group_info = result
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Failed to describe group: {e}",
                }

        if not group_info:
            return {
                "success": False,
                "error": f"Consumer group '{group_id}' not found",
            }

        members = []
        for member in group_info.members:
            assignment = []
            if hasattr(member, "assignment") and member.assignment:
                for tp in member.assignment.topic_partitions:
                    assignment.append(
                        {
                            "topic": tp.topic,
                            "partition": tp.partition,
                        }
                    )

            members.append(
                {
                    "member_id": member.member_id,
                    "client_id": member.client_id,
                    "host": member.host,
                    "assignment": assignment,
                }
            )

        logger.info(
            "kafka_consumer_group_described",
            group=group_id,
            members=len(members),
        )

        return {
            "group_id": group_id,
            "state": str(group_info.state),
            "coordinator": {
                "id": group_info.coordinator.id if group_info.coordinator else None,
                "host": group_info.coordinator.host if group_info.coordinator else None,
            },
            "protocol_type": group_info.protocol_type,
            "protocol": group_info.protocol,
            "member_count": len(members),
            "members": members,
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "kafka_describe_consumer_group", "kafka"
        )
    except Exception as e:
        logger.error(
            "kafka_describe_consumer_group_failed", error=str(e), group=group_id
        )
        raise ToolExecutionError("kafka_describe_consumer_group", str(e), e)


def kafka_get_consumer_lag(group_id: str, topic: str | None = None) -> dict[str, Any]:
    """
    Get consumer lag for a consumer group.

    Consumer lag = high watermark - committed offset

    Args:
        group_id: Consumer group ID
        topic: Optional topic to filter (returns all subscribed topics if not specified)

    Returns:
        Dict with lag information per partition
    """
    try:
        from confluent_kafka import TopicPartition
    except ImportError:
        raise ToolExecutionError(
            "kafka",
            "confluent-kafka not installed. Install with: pip install confluent-kafka",
        )

    try:
        admin = _get_admin_client()

        # Get committed offsets for the consumer group
        list_offsets_futures = admin.list_consumer_group_offsets([group_id])

        committed_offsets = {}
        for gid, future in list_offsets_futures.items():
            try:
                result = future.result()
                for tp in result.topic_partitions:
                    if topic and tp.topic != topic:
                        continue
                    key = (tp.topic, tp.partition)
                    committed_offsets[key] = tp.offset
            except Exception as e:
                logger.warning("kafka_offsets_fetch_failed", error=str(e))

        if not committed_offsets:
            return {
                "success": True,
                "group_id": group_id,
                "message": "No committed offsets found for this consumer group",
                "partitions": [],
            }

        # Get high watermarks using consumer
        consumer = _get_consumer(f"{group_id}-lag-check")

        partitions = []
        total_lag = 0
        topics_set = set()

        try:
            for (topic_name, partition), committed in committed_offsets.items():
                tp = TopicPartition(topic_name, partition)

                # Get high watermark
                low, high = consumer.get_watermark_offsets(tp, timeout=5)

                lag = high - committed if committed >= 0 else high - low
                if lag < 0:
                    lag = 0

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

        except Exception as e:
            logger.warning("kafka_watermark_fetch_failed", error=str(e))
            try:
                consumer.close()
            except Exception:
                pass

        # Sort by lag (descending)
        partitions.sort(key=lambda p: p["lag"], reverse=True)

        # Determine health
        if total_lag == 0:
            health = "healthy"
        elif total_lag < 1000:
            health = "minor_lag"
        elif total_lag < 100000:
            health = "lagging"
        else:
            health = "severely_lagging"

        logger.info(
            "kafka_consumer_lag_retrieved",
            group=group_id,
            total_lag=total_lag,
        )

        return {
            "group_id": group_id,
            "topic_filter": topic,
            "topics_subscribed": list(topics_set),
            "partition_count": len(partitions),
            "total_lag": total_lag,
            "health": health,
            "partitions": partitions,
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "kafka_get_consumer_lag", "kafka")
    except Exception as e:
        logger.error("kafka_get_consumer_lag_failed", error=str(e), group=group_id)
        raise ToolExecutionError("kafka_get_consumer_lag", str(e), e)


def kafka_get_broker_info() -> dict[str, Any]:
    """
    Get information about Kafka brokers in the cluster.

    Returns:
        Dict with broker information
    """
    try:
        admin = _get_admin_client()

        # Get cluster metadata
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

        # Sort by ID
        brokers.sort(key=lambda b: b["id"])

        # Get controller
        controller_id = metadata.controller_id

        logger.info("kafka_broker_info_retrieved", count=len(brokers))

        return {
            "cluster_id": metadata.cluster_id,
            "controller_id": controller_id,
            "broker_count": len(brokers),
            "brokers": brokers,
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "kafka_get_broker_info", "kafka")
    except Exception as e:
        logger.error("kafka_get_broker_info_failed", error=str(e))
        raise ToolExecutionError("kafka_get_broker_info", str(e), e)


# List of all Kafka tools for registration
KAFKA_TOOLS = [
    kafka_list_topics,
    kafka_describe_topic,
    kafka_list_consumer_groups,
    kafka_describe_consumer_group,
    kafka_get_consumer_lag,
    kafka_get_broker_info,
]

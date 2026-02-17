#!/usr/bin/env python3
"""Shared Kafka client with credential support.

Credentials are injected transparently by the proxy layer.
"""

import json
import os


def get_config() -> dict[str, str | None]:
    """Get Kafka configuration from environment."""
    return {
        "tenant_id": os.getenv("INCIDENTFOX_TENANT_ID", "local"),
        "team_id": os.getenv("INCIDENTFOX_TEAM_ID", "local"),
        "bootstrap_servers": os.getenv("KAFKA_BOOTSTRAP_SERVERS", ""),
        "security_protocol": os.getenv("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT"),
        "sasl_mechanism": os.getenv("KAFKA_SASL_MECHANISM"),
        "sasl_username": os.getenv("KAFKA_SASL_USERNAME"),
        "sasl_password": os.getenv("KAFKA_SASL_PASSWORD"),
        "ssl_cafile": os.getenv("KAFKA_SSL_CAFILE"),
    }


def get_bootstrap_servers() -> str:
    """Get Kafka bootstrap servers."""
    servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "")
    if not servers:
        raise RuntimeError("KAFKA_BOOTSTRAP_SERVERS must be set")
    return servers


def _build_base_config() -> dict:
    """Build base Kafka client configuration."""
    config = get_config()
    base = {
        "bootstrap.servers": config["bootstrap_servers"],
        "security.protocol": config.get("security_protocol") or "PLAINTEXT",
    }

    security_protocol = base["security.protocol"]

    if security_protocol in ("SASL_SSL", "SASL_PLAINTEXT"):
        base["sasl.mechanism"] = config.get("sasl_mechanism") or "PLAIN"
        if config.get("sasl_username"):
            base["sasl.username"] = config["sasl_username"]
        if config.get("sasl_password"):
            base["sasl.password"] = config["sasl_password"]

    if security_protocol in ("SSL", "SASL_SSL"):
        if config.get("ssl_cafile"):
            base["ssl.ca.location"] = config["ssl_cafile"]

    return base


def get_admin_client():
    """Get Kafka AdminClient."""
    from confluent_kafka.admin import AdminClient

    return AdminClient(_build_base_config())


def get_consumer(group_id: str = "incidentfox-admin"):
    """Get Kafka Consumer for offset queries."""
    from confluent_kafka import Consumer

    cfg = _build_base_config()
    cfg["group.id"] = group_id
    cfg["auto.offset.reset"] = "earliest"
    cfg["enable.auto.commit"] = False
    return Consumer(cfg)


def format_output(data: dict) -> str:
    """Format output as JSON string."""
    return json.dumps(data, indent=2, default=str)

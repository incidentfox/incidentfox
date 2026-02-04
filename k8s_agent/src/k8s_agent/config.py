"""Configuration for K8s Agent."""

import os
from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """K8s Agent settings."""

    # Required configuration
    api_key: str = ""  # IncidentFox API key (token)
    cluster_name: str = ""  # Name to identify this cluster

    # Gateway connection (default is IncidentFox SaaS gateway)
    gateway_url: str = "https://orchestrator.incidentfox.ai/gateway"

    # Reconnection settings
    initial_reconnect_delay: float = 1.0
    max_reconnect_delay: float = 60.0
    reconnect_multiplier: float = 2.0

    # Command execution
    command_timeout: float = 30.0

    # Agent info
    agent_version: str = "0.1.0"

    class Config:
        env_prefix = "INCIDENTFOX_"
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


def get_pod_name() -> str:
    """Get the pod name from environment (set by Kubernetes)."""
    return os.getenv("POD_NAME", "unknown")

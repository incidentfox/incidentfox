"""Configuration for K8s Gateway service."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Gateway service settings."""

    # Service configuration
    service_name: str = "k8s-gateway"
    debug: bool = False

    # Path prefix for when running behind a reverse proxy (e.g., /gateway)
    root_path: str = ""

    # Config service for token validation
    config_service_url: str = "http://config-service:8080"
    config_service_timeout: float = 10.0

    # Token validation
    token_pepper: str = ""  # Required for token validation

    # SSE connection settings
    heartbeat_interval_seconds: int = 30
    connection_timeout_seconds: int = 120
    max_connections_per_team: int = 100

    # Command execution
    command_timeout_seconds: float = 30.0
    max_pending_commands: int = 100

    # Internal service auth
    internal_service_secret: str = ""

    class Config:
        env_prefix = "K8S_GATEWAY_"
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()

"""Configuration utilities for IncidentFox MCP Server.

All configuration is via environment variables for simplicity.
"""

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(Exception):
    """Raised when required configuration is missing."""

    def __init__(self, integration: str, missing_vars: list[str]):
        self.integration = integration
        self.missing_vars = missing_vars
        super().__init__(
            f"{integration} not configured. Missing: {', '.join(missing_vars)}"
        )


@dataclass
class KubernetesConfig:
    """Kubernetes configuration."""

    kubeconfig_path: str | None
    context: str | None

    @classmethod
    def from_env(cls) -> "KubernetesConfig":
        return cls(
            kubeconfig_path=os.getenv(
                "KUBECONFIG", str(Path.home() / ".kube" / "config")
            ),
            context=os.getenv("K8S_CONTEXT"),
        )

    def validate(self) -> None:
        """Validate Kubernetes config is available."""
        kubeconfig = Path(self.kubeconfig_path) if self.kubeconfig_path else None
        in_cluster = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")

        if kubeconfig and kubeconfig.exists():
            return
        if in_cluster.exists():
            return
        raise ConfigError(
            "kubernetes", ["KUBECONFIG (file not found, not running in-cluster)"]
        )


@dataclass
class AWSConfig:
    """AWS configuration."""

    region: str

    @classmethod
    def from_env(cls) -> "AWSConfig":
        return cls(
            region=os.getenv(
                "AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1")
            ),
        )


@dataclass
class DatadogConfig:
    """Datadog configuration."""

    api_key: str | None
    app_key: str | None

    @classmethod
    def from_env(cls) -> "DatadogConfig":
        return cls(
            api_key=os.getenv("DATADOG_API_KEY"),
            app_key=os.getenv("DATADOG_APP_KEY"),
        )

    def validate(self) -> None:
        """Validate Datadog config is available."""
        missing = []
        if not self.api_key:
            missing.append("DATADOG_API_KEY")
        if not self.app_key:
            missing.append("DATADOG_APP_KEY")
        if missing:
            raise ConfigError("datadog", missing)


@dataclass
class Config:
    """Complete configuration for IncidentFox MCP."""

    kubernetes: KubernetesConfig
    aws: AWSConfig
    datadog: DatadogConfig

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            kubernetes=KubernetesConfig.from_env(),
            aws=AWSConfig.from_env(),
            datadog=DatadogConfig.from_env(),
        )


_config: Config | None = None


def get_config() -> Config:
    """Get or create configuration singleton."""
    global _config
    if _config is None:
        _config = Config.from_env()
    return _config

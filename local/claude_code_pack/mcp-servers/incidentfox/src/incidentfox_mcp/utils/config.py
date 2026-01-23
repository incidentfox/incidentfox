"""Configuration utilities for IncidentFox MCP Server.

Configuration is loaded from:
1. ~/.incidentfox/.env file (persistent, user-editable)
2. Environment variables (override file values)

This allows credentials to be saved mid-session and persist across sessions.
"""

import os
from dataclasses import dataclass
from pathlib import Path

# Persistent config file location
CONFIG_DIR = Path.home() / ".incidentfox"
CONFIG_FILE = CONFIG_DIR / ".env"


def _load_env_file() -> dict[str, str]:
    """Load configuration from ~/.incidentfox/.env file.

    Returns a dict of key-value pairs. Does NOT modify os.environ.
    """
    config = {}
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith("#"):
                    continue
                # Parse KEY=VALUE
                if "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip()
                    # Remove quotes if present
                    if value and value[0] in ('"', "'") and value[-1] == value[0]:
                        value = value[1:-1]
                    config[key] = value
    return config


def get_env(key: str, default: str | None = None) -> str | None:
    """Get a config value, checking .env file then environment.

    Priority:
    1. Environment variable (allows override)
    2. ~/.incidentfox/.env file (persistent storage)
    3. Default value
    """
    # Environment variables take precedence
    env_value = os.environ.get(key)
    if env_value:
        return env_value

    # Then check .env file
    file_config = _load_env_file()
    if key in file_config:
        return file_config[key]

    return default


def save_credential(key: str, value: str) -> None:
    """Save a credential to ~/.incidentfox/.env file.

    Creates the directory and file if they don't exist.
    Updates existing keys, appends new ones.
    """
    # Ensure directory exists
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Read existing config
    existing = {}
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            for line in f:
                line_stripped = line.strip()
                if not line_stripped or line_stripped.startswith("#"):
                    continue
                if "=" in line_stripped:
                    k, _, v = line_stripped.partition("=")
                    existing[k.strip()] = v.strip()

    # Update or add the key
    existing[key] = value

    # Write back
    with open(CONFIG_FILE, "w") as f:
        f.write("# IncidentFox Configuration\n")
        f.write("# Generated automatically - you can edit this file\n\n")
        for k, v in sorted(existing.items()):
            # Quote values with spaces
            if " " in v or not v:
                f.write(f'{k}="{v}"\n')
            else:
                f.write(f"{k}={v}\n")


def get_config_status() -> dict:
    """Get status of all configured integrations.

    Returns a dict showing which integrations are configured.
    """
    file_config = _load_env_file()

    def is_set(key: str) -> bool:
        return bool(os.environ.get(key) or file_config.get(key))

    return {
        "config_file": str(CONFIG_FILE),
        "config_file_exists": CONFIG_FILE.exists(),
        "integrations": {
            "kubernetes": {
                "configured": is_set("KUBECONFIG")
                or Path.home().joinpath(".kube/config").exists(),
                "variables": {
                    "KUBECONFIG": "set" if is_set("KUBECONFIG") else "using default",
                    "K8S_CONTEXT": (
                        "set" if is_set("K8S_CONTEXT") else "not set (optional)"
                    ),
                },
            },
            "aws": {
                "configured": True,  # Uses default credential chain
                "variables": {
                    "AWS_REGION": get_env("AWS_REGION", "us-east-1"),
                },
            },
            "datadog": {
                "configured": is_set("DATADOG_API_KEY") and is_set("DATADOG_APP_KEY"),
                "variables": {
                    "DATADOG_API_KEY": (
                        "set" if is_set("DATADOG_API_KEY") else "NOT SET"
                    ),
                    "DATADOG_APP_KEY": (
                        "set" if is_set("DATADOG_APP_KEY") else "NOT SET"
                    ),
                },
            },
            "prometheus": {
                "configured": is_set("PROMETHEUS_URL") or is_set("PROM_URL"),
                "variables": {
                    "PROMETHEUS_URL": get_env("PROMETHEUS_URL")
                    or get_env("PROM_URL")
                    or "NOT SET",
                },
            },
            "elasticsearch": {
                "configured": is_set("ELASTICSEARCH_URL") or is_set("ES_URL"),
                "variables": {
                    "ELASTICSEARCH_URL": get_env("ELASTICSEARCH_URL")
                    or get_env("ES_URL")
                    or "NOT SET",
                },
            },
            "loki": {
                "configured": is_set("LOKI_URL"),
                "variables": {
                    "LOKI_URL": get_env("LOKI_URL") or "NOT SET",
                },
            },
        },
    }


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
            kubeconfig_path=get_env(
                "KUBECONFIG", str(Path.home() / ".kube" / "config")
            ),
            context=get_env("K8S_CONTEXT"),
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
            region=get_env("AWS_REGION")
            or get_env("AWS_DEFAULT_REGION")
            or "us-east-1",
        )


@dataclass
class DatadogConfig:
    """Datadog configuration."""

    api_key: str | None
    app_key: str | None

    @classmethod
    def from_env(cls) -> "DatadogConfig":
        return cls(
            api_key=get_env("DATADOG_API_KEY"),
            app_key=get_env("DATADOG_APP_KEY"),
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
class PrometheusConfig:
    """Prometheus configuration."""

    url: str | None
    alertmanager_url: str | None

    @classmethod
    def from_env(cls) -> "PrometheusConfig":
        return cls(
            url=get_env("PROMETHEUS_URL") or get_env("PROM_URL"),
            alertmanager_url=get_env("ALERTMANAGER_URL") or get_env("AM_URL"),
        )

    def validate(self) -> None:
        """Validate Prometheus config is available."""
        if not self.url:
            raise ConfigError("prometheus", ["PROMETHEUS_URL"])


@dataclass
class Config:
    """Complete configuration for IncidentFox MCP."""

    kubernetes: KubernetesConfig
    aws: AWSConfig
    datadog: DatadogConfig
    prometheus: PrometheusConfig

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            kubernetes=KubernetesConfig.from_env(),
            aws=AWSConfig.from_env(),
            datadog=DatadogConfig.from_env(),
            prometheus=PrometheusConfig.from_env(),
        )


def get_config() -> Config:
    """Get configuration - reloads from .env file each time.

    No caching - always reads fresh values so mid-session
    credential updates work immediately.
    """
    return Config.from_env()

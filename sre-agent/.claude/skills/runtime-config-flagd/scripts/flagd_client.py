#!/usr/bin/env python3
"""Shared flagd client for reading and writing feature flags via Kubernetes ConfigMap.

The OpenTelemetry Demo uses flagd with a ConfigMap-backed JSON file as its flag source.
Flags are read/written by manipulating the ConfigMap directly, which triggers flagd's
file-watcher to hot-reload.

Environment variables:
    FLAGD_NAMESPACE  - K8s namespace where flagd runs (default: otel-demo)
    FLAGD_CONFIGMAP  - ConfigMap name containing flags (default: flagd-config)
    FLAGD_KEY        - Key within ConfigMap holding the JSON (default: demo.flagd.json)
"""

import json
import os
import re
import subprocess
import tempfile
from typing import Any

_RFC1123_RE = re.compile(r"^[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?$")


def _validate_k8s_name(value: str, label: str) -> str:
    """Validate a Kubernetes resource name against RFC 1123."""
    if not _RFC1123_RE.match(value):
        raise ValueError(
            f"Invalid {label} name '{value}': must be lowercase alphanumeric/hyphens, 1-63 chars"
        )
    return value


def get_config() -> dict[str, str]:
    """Get flagd configuration from environment."""
    ns = os.getenv("FLAGD_NAMESPACE", "otel-demo")
    cm = os.getenv("FLAGD_CONFIGMAP", "flagd-config")
    _validate_k8s_name(ns, "namespace")
    _validate_k8s_name(cm, "configmap")
    return {
        "namespace": ns,
        "configmap": cm,
        "key": os.getenv("FLAGD_KEY", "demo.flagd.json"),
    }


_SA_TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"
_SA_CA_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"


def _run_kubectl(args: list[str], input_data: str | None = None) -> str:
    """Run a kubectl command and return stdout.

    When running in-cluster (SA token mounted), creates a temporary kubeconfig
    file with the SA token instead of passing --token on the command line.
    Command-line args are visible via /proc/*/cmdline, so tokens must not
    appear there.

    Args:
        args: kubectl arguments (without 'kubectl' prefix)
        input_data: Optional stdin data

    Returns:
        Command stdout

    Raises:
        RuntimeError: If kubectl fails
    """
    cmd = ["kubectl"]
    env = os.environ.copy()

    if os.path.exists(_SA_TOKEN_PATH):
        # In-cluster: build a temp kubeconfig with SA token (avoids exposing
        # the token on the command line via /proc/*/cmdline)
        with open(_SA_TOKEN_PATH) as f:
            token = f.read().strip()
        kubeconfig_data = json.dumps(
            {
                "apiVersion": "v1",
                "kind": "Config",
                "clusters": [
                    {
                        "name": "in-cluster",
                        "cluster": {
                            "server": "https://kubernetes.default.svc",
                            "certificate-authority": _SA_CA_PATH,
                        },
                    }
                ],
                "users": [
                    {
                        "name": "sa-user",
                        "user": {"token": token},
                    }
                ],
                "contexts": [
                    {
                        "name": "default",
                        "context": {"cluster": "in-cluster", "user": "sa-user"},
                    }
                ],
                "current-context": "default",
            }
        )
        # Write to temp file; pass via KUBECONFIG env var
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".kubeconfig", delete=False)
        try:
            tmp.write(kubeconfig_data)
            tmp.close()
            os.chmod(tmp.name, 0o600)
            env["KUBECONFIG"] = tmp.name
            cmd += args
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                input=input_data,
                env=env,
            )
        finally:
            os.unlink(tmp.name)
    else:
        cmd += args
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            input=input_data,
        )

    if result.returncode != 0:
        raise RuntimeError(
            f"kubectl failed (exit {result.returncode}): {result.stderr.strip()}"
        )
    return result.stdout


def get_flags_json() -> dict[str, Any]:
    """Read the full flags JSON from the ConfigMap.

    Returns:
        Parsed flag configuration dict with 'flags' key
    """
    config = get_config()
    # Use -o json and extract in Python to avoid jsonpath issues with dots in key names
    raw = _run_kubectl(
        [
            "get",
            "configmap",
            config["configmap"],
            "-n",
            config["namespace"],
            "-o",
            "json",
        ]
    )

    cm = json.loads(raw)
    data = cm.get("data", {})
    flag_json_str = data.get(config["key"])

    if not flag_json_str:
        raise RuntimeError(
            f"ConfigMap {config['configmap']} in namespace {config['namespace']} "
            f"has no data at key '{config['key']}'"
        )

    return json.loads(flag_json_str)


def get_all_flags() -> dict[str, dict[str, Any]]:
    """Get all flags with their current configuration.

    Returns:
        Dict mapping flag_key -> {variants, defaultVariant, state, ...}
    """
    data = get_flags_json()
    return data.get("flags", {})


def get_flag(flag_key: str) -> dict[str, Any] | None:
    """Get a single flag's configuration.

    Args:
        flag_key: The flag key (e.g., 'paymentFailure')

    Returns:
        Flag configuration dict, or None if not found
    """
    flags = get_all_flags()
    return flags.get(flag_key)


def set_flag_variant(
    flag_key: str, variant: str, dry_run: bool = False
) -> dict[str, Any]:
    """Set a flag's default variant.

    This patches the ConfigMap which triggers flagd's hot-reload.

    Args:
        flag_key: The flag key (e.g., 'paymentFailure')
        variant: The variant to set as default (e.g., 'off', 'on', '50%')
        dry_run: If True, show what would change without applying

    Returns:
        Dict with old and new values

    Raises:
        ValueError: If flag_key or variant is invalid
    """
    config = get_config()
    data = get_flags_json()
    flags = data.get("flags", {})

    if not flags:
        raise ValueError(f"No flags found in ConfigMap '{config['configmap']}'")

    if flag_key not in flags:
        available = ", ".join(sorted(flags.keys()))
        raise ValueError(f"Unknown flag '{flag_key}'. Available: {available}")

    flag = flags[flag_key]
    variants = flag.get("variants", {})
    available_variants = list(variants.keys())

    if variant not in available_variants:
        raise ValueError(
            f"Invalid variant '{variant}' for flag '{flag_key}'. "
            f"Available: {', '.join(available_variants)}"
        )

    old_variant = flag.get("defaultVariant", "unknown")

    result = {
        "flag": flag_key,
        "old_variant": old_variant,
        "new_variant": variant,
        "old_value": variants.get(old_variant),
        "new_value": variants.get(variant),
        "dry_run": dry_run,
    }

    if dry_run:
        return result

    # Update the flag
    flags[flag_key]["defaultVariant"] = variant
    updated_json = json.dumps(data, indent=2)

    # Patch the ConfigMap via stdin to handle large JSON and special characters safely
    patch = json.dumps({"data": {config["key"]: updated_json}})
    _run_kubectl(
        [
            "patch",
            "configmap",
            config["configmap"],
            "-n",
            config["namespace"],
            "--type=merge",
            "-p",
            patch,
        ]
    )

    return result

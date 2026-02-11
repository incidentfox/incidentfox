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
import subprocess
import sys
from typing import Any


def get_config() -> dict[str, str]:
    """Get flagd configuration from environment."""
    return {
        "namespace": os.getenv("FLAGD_NAMESPACE", "otel-demo"),
        "configmap": os.getenv("FLAGD_CONFIGMAP", "flagd-config"),
        "key": os.getenv("FLAGD_KEY", "demo.flagd.json"),
    }


def _run_kubectl(args: list[str], input_data: str | None = None) -> str:
    """Run a kubectl command and return stdout.

    Args:
        args: kubectl arguments (without 'kubectl' prefix)
        input_data: Optional stdin data

    Returns:
        Command stdout

    Raises:
        RuntimeError: If kubectl fails
    """
    cmd = ["kubectl"] + args
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
    raw = _run_kubectl([
        "get", "configmap", config["configmap"],
        "-n", config["namespace"],
        "-o", f"jsonpath={{.data['{config['key']}']}}"
    ])

    if not raw.strip():
        raise RuntimeError(
            f"ConfigMap {config['configmap']} in namespace {config['namespace']} "
            f"has no data at key '{config['key']}'"
        )

    return json.loads(raw)


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


def set_flag_variant(flag_key: str, variant: str, dry_run: bool = False) -> dict[str, Any]:
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

    if flag_key not in flags:
        available = ", ".join(sorted(flags.keys()))
        raise ValueError(f"Unknown flag '{flag_key}'. Available: {available}")

    flag = flags[flag_key]
    available_variants = list(flag.get("variants", {}).keys())

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
        "old_value": flag["variants"].get(old_variant),
        "new_value": flag["variants"].get(variant),
        "dry_run": dry_run,
    }

    if dry_run:
        return result

    # Update the flag
    flags[flag_key]["defaultVariant"] = variant
    updated_json = json.dumps(data, indent=2)

    # Patch the ConfigMap using kubectl create --dry-run + apply pattern
    # This avoids issues with special characters in JSON
    _run_kubectl(
        [
            "create", "configmap", config["configmap"],
            "-n", config["namespace"],
            f"--from-literal={config['key']}={updated_json}",
            "--dry-run=client", "-o", "yaml",
        ]
    )

    # Actually apply the update via kubectl patch
    patch = json.dumps({
        "data": {
            config["key"]: updated_json
        }
    })
    _run_kubectl([
        "patch", "configmap", config["configmap"],
        "-n", config["namespace"],
        "--type=merge",
        f"-p={patch}",
    ])

    return result

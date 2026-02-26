#!/usr/bin/env python3
"""Shared AWS client with credential-resolver support.

Credentials are fetched from the credential-resolver at runtime.
In local dev, boto3 auto-discovers from environment or profile.
"""

import json
import os
import sys
from datetime import datetime

import boto3
import requests


def get_boto3_session() -> boto3.Session:
    """Create boto3 session with credentials from credential-resolver.

    Priority:
    1. Credential-resolver (multi-tenant sandbox mode)
    2. boto3 default chain (env vars, profile, IRSA — local dev)
    """
    cred_url = os.getenv("CREDENTIAL_RESOLVER_URL")
    jwt = os.getenv("SANDBOX_JWT")

    if cred_url and jwt:
        try:
            resp = requests.get(
                f"{cred_url}/api/credentials/aws",
                headers={"X-Sandbox-JWT": jwt},
                timeout=5,
            )
            resp.raise_for_status()
            creds = resp.json()
            return boto3.Session(
                aws_access_key_id=creds.get("aws_access_key_id")
                or creds.get("access_key_id"),
                aws_secret_access_key=creds.get("aws_secret_access_key")
                or creds.get("secret_access_key"),
                region_name=creds.get("region")
                or creds.get("aws_region_name")
                or "us-east-1",
            )
        except Exception as e:
            print(f"[aws-auth] Credential-resolver error: {e}", file=sys.stderr)
            print("[aws-auth] Falling back to default boto3 chain", file=sys.stderr)

    # Local dev: boto3 auto-discovers from env/profile
    return boto3.Session(region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"))


def get_client(service_name: str):
    """Get a boto3 client for the given AWS service."""
    session = get_boto3_session()
    return session.client(service_name)


def format_output(data: dict) -> str:
    """Format output as JSON string."""
    return json.dumps(data, indent=2, default=str)


def format_timestamp(ts) -> str:
    """Format a timestamp (datetime or epoch ms) to ISO string."""
    if isinstance(ts, (int, float)):
        return datetime.utcfromtimestamp(ts / 1000).isoformat() + "Z"
    if isinstance(ts, datetime):
        return ts.isoformat()
    return str(ts)

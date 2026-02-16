"""Shared RAPTOR knowledge base client.

The RAPTOR service is an internal K8s service — no authentication required.
Requests go directly to the service ClusterIP (no Envoy proxy needed).

Configuration:
    RAPTOR_URL: Base URL of the RAPTOR/ultimate_rag service.
        Production: http://incidentfox-rag.<namespace>.svc.cluster.local:8000
        Local dev:  http://localhost:8000
"""

import os
from typing import Any

import httpx

RAPTOR_URL = os.getenv("RAPTOR_URL", "http://localhost:8000")


def raptor_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Send a POST request to the RAPTOR API.

    Args:
        path: API path (e.g., "/api/v1/search")
        payload: JSON request body

    Returns:
        Parsed JSON response

    Raises:
        httpx.HTTPStatusError: On non-2xx response
        RuntimeError: If RAPTOR service is unreachable
    """
    url = f"{RAPTOR_URL.rstrip('/')}{path}"

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            return response.json()
    except httpx.ConnectError:
        raise RuntimeError(
            f"Cannot connect to RAPTOR service at {RAPTOR_URL}.\n"
            "Ensure the service is running and RAPTOR_URL is set correctly."
        )


def raptor_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Send a GET request to the RAPTOR API.

    Args:
        path: API path (e.g., "/health")
        params: Optional query parameters

    Returns:
        Parsed JSON response
    """
    url = f"{RAPTOR_URL.rstrip('/')}{path}"

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            return response.json()
    except httpx.ConnectError:
        raise RuntimeError(
            f"Cannot connect to RAPTOR service at {RAPTOR_URL}.\n"
            "Ensure the service is running and RAPTOR_URL is set correctly."
        )

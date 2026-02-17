#!/usr/bin/env python3
"""Shared Google Docs/Drive client with proxy and direct mode support."""

import json as json_mod
import os

import httpx


def _get_proxy_headers():
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    sandbox_jwt = os.getenv("SANDBOX_JWT")
    if sandbox_jwt:
        headers["X-Sandbox-JWT"] = sandbox_jwt
    else:
        headers["X-Tenant-Id"] = os.getenv("INCIDENTFOX_TENANT_ID", "local")
        headers["X-Team-Id"] = os.getenv("INCIDENTFOX_TEAM_ID", "local")
    return headers


def _is_proxy_mode():
    return bool(os.getenv("GOOGLE_DOCS_BASE_URL") or os.getenv("GOOGLE_DRIVE_BASE_URL"))


def _get_credentials(readonly=False):
    """Get Google API credentials for direct mode."""
    from google.oauth2 import service_account

    creds_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_KEY")
    creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE")
    scopes_suffix = ".readonly" if readonly else ""
    scopes = [
        f"https://www.googleapis.com/auth/documents{scopes_suffix}",
        f"https://www.googleapis.com/auth/drive{'.readonly' if readonly else '.file'}",
    ]
    if creds_json:
        return service_account.Credentials.from_service_account_info(
            json_mod.loads(creds_json), scopes=scopes
        )
    elif creds_file:
        return service_account.Credentials.from_service_account_file(
            creds_file, scopes=scopes
        )
    raise RuntimeError(
        "Neither GOOGLE_SERVICE_ACCOUNT_KEY nor GOOGLE_CREDENTIALS_FILE is set"
    )


def get_docs_service(readonly=False):
    """Get Google Docs API service (direct mode)."""
    from googleapiclient.discovery import build

    return build("docs", "v1", credentials=_get_credentials(readonly))


def get_drive_service(readonly=False):
    """Get Google Drive API service (direct mode)."""
    from googleapiclient.discovery import build

    return build("drive", "v3", credentials=_get_credentials(readonly))


def docs_request(method, path, params=None, json_body=None):
    """Make a Docs API request via proxy."""
    base = os.getenv("GOOGLE_DOCS_BASE_URL", "").rstrip("/")
    url = f"{base}/{path.lstrip('/')}"
    with httpx.Client(timeout=30.0) as client:
        resp = client.request(
            method, url, headers=_get_proxy_headers(), params=params, json=json_body
        )
        resp.raise_for_status()
        return resp.json() if resp.status_code != 204 else None


def drive_request(method, path, params=None, json_body=None):
    """Make a Drive API request via proxy."""
    base = os.getenv("GOOGLE_DRIVE_BASE_URL", "").rstrip("/")
    url = f"{base}/{path.lstrip('/')}"
    with httpx.Client(timeout=30.0) as client:
        resp = client.request(
            method, url, headers=_get_proxy_headers(), params=params, json=json_body
        )
        resp.raise_for_status()
        return resp.json() if resp.status_code != 204 else None

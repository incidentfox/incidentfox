#!/usr/bin/env python3
"""
Asset Manager - Upload and manage Slack-hosted assets per workspace

Uploads assets once per workspace on first use, then caches file IDs.
Much simpler than CDN and works in any enterprise environment.
"""

from pathlib import Path
from typing import Dict

from slack_sdk import WebClient

# In-memory cache (in production, use Redis/DB keyed by team_id)
_asset_cache: Dict[str, Dict[str, str]] = {}

ASSETS_DIR = Path(__file__).parent / "assets"

REQUIRED_ASSETS = {
    "loading": "loading.gif",
    "done": "done.png",
}


def get_asset_urls(client: WebClient, team_id: str) -> Dict[str, str]:
    """
    Get Slack-hosted URLs for all assets.

    Uploads on first call per workspace, then caches.

    Returns:
        Dict with keys: "loading", "done"
        Values are Slack file URLs or file IDs
    """
    # Check cache
    if team_id in _asset_cache:
        return _asset_cache[team_id]

    # Upload assets
    asset_urls = {}

    for asset_key, filename in REQUIRED_ASSETS.items():
        file_path = ASSETS_DIR / filename

        if not file_path.exists():
            raise FileNotFoundError(f"Asset not found: {file_path}")

        # Upload to Slack
        response = client.files_upload_v2(
            file=str(file_path),
            filename=filename,
            title=f"IncidentFox {asset_key.title()}",
        )

        # Get the file info
        file_info = response["file"]
        file_id = file_info["id"]

        # Store file ID - Slack expects this in slack_file blocks
        asset_urls[asset_key] = file_id

    # Cache for this workspace
    _asset_cache[team_id] = asset_urls

    return asset_urls


def get_asset_file_id(client: WebClient, team_id: str, asset_key: str) -> str:
    """Get a specific asset's Slack public URL."""
    urls = get_asset_urls(client, team_id)
    return urls[asset_key]


def clear_asset_cache(team_id: str) -> None:
    """Clear cached assets for a team (e.g., if file IDs become invalid)."""
    if team_id in _asset_cache:
        del _asset_cache[team_id]

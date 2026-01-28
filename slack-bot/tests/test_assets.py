#!/usr/bin/env python3
"""Test asset upload to Slack"""

import os
import sys
from pathlib import Path

# Add parent directory to path to import production modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from asset_manager import get_asset_urls
from slack_sdk import WebClient

# Initialize client
client = WebClient(token=os.environ.get("SLACK_BOT_TOKEN"))

# Test upload
team_id = "test-workspace"
print("Testing asset upload...")

try:
    asset_urls = get_asset_urls(client, team_id)
    print("✅ Assets uploaded successfully!")
    print(f"   Loading GIF: {asset_urls['loading']}")
    print(f"   Done PNG: {asset_urls['done']}")
except Exception as e:
    print(f"❌ Error: {e}")

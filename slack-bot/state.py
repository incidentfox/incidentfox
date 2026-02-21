"""
Shared state, data models, and caching for the IncidentFox Slack Bot.

This module contains:
- ThoughtSection and MessageState dataclasses
- In-memory investigation cache with TTL
- Session persistence to/from config-service DB
- User display name cache
"""

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional

logger = logging.getLogger(__name__)


# Import config_client lazily to avoid circular deps
def get_config_client():
    from config_client import get_config_client as _get_config_client

    return _get_config_client()


# Track channels where we've sent the welcome nudge (resets on restart, which is fine)
# Key format: "{team_id}:{channel_id}"
_nudge_sent_channels: set = set()

# Track threads where auto-listen is active (bot responds without @mention)
# Key: (channel_id, thread_ts), Value: True
_auto_listen_threads: Dict[tuple, bool] = {}

# Track button selections in memory (thread_id -> {q_idx: selected_value})
_button_selections = {}

# Track pending questions for displaying in submitted answer summary (thread_id -> questions list)
_pending_questions = {}

# Track question message timestamps for timeout updates (thread_id -> {message_ts, channel_id})
_question_messages = {}

# LRU cache for Slack user display name lookups (avoids repeated API calls
# when the same users keep chatting in the same thread)
_user_name_cache: Dict[str, str] = {}
_USER_NAME_CACHE_MAX = 200


def _get_user_display_name(client, user_id: str) -> str:
    """Look up a Slack user's display name, with in-memory LRU caching."""
    if user_id in _user_name_cache:
        return _user_name_cache[user_id]

    try:
        resp = client.users_info(user=user_id)
        if resp["ok"]:
            user = resp["user"]
            profile = user.get("profile", {})
            name = (
                profile.get("display_name")
                or profile.get("real_name")
                or user.get("name", f"User_{user_id}")
            )
        else:
            name = f"User_{user_id}"
    except Exception:
        name = f"User_{user_id}"

    # Evict oldest entry if at capacity (dict preserves insertion order in 3.7+)
    if len(_user_name_cache) >= _USER_NAME_CACHE_MAX:
        oldest_key = next(iter(_user_name_cache))
        del _user_name_cache[oldest_key]

    _user_name_cache[user_id] = name
    return name


@dataclass
class ThoughtSection:
    """A thought and its associated tool calls."""

    text: str
    tools: list = field(
        default_factory=list
    )  # Tool dicts: name, input, success, output
    completed: bool = False


@dataclass
class MessageState:
    """Tracks the state of a Slack message during investigation."""

    channel_id: str
    message_ts: str
    thread_ts: str
    thread_id: str

    # Hierarchical structure: thoughts with nested tools
    thoughts: list = field(default_factory=list)  # List of ThoughtSection
    current_tool: Optional[dict] = None  # Tool currently running

    # Final state
    final_result: Optional[str] = None
    result_images: Optional[list] = (
        None  # [{path, data, media_type, alt, file_id?}, ...]
    )
    result_files: Optional[list] = (
        None  # [{path, filename, description, media_type, file_id?}, ...]
    )
    error: Optional[str] = None

    # Chronological timeline for modal view (thoughts + tools interwoven)
    timeline: list = field(default_factory=list)

    # Tracking
    last_update_time: float = 0

    # Trigger context (for nudge-initiated investigations)
    trigger_user_id: Optional[str] = None  # Who clicked "Yes" on the nudge
    trigger_text: Optional[str] = None  # The message that triggered it

    # Subagent tracking
    # Key: tool_use_id of Task tool, Value: {description, subagent_type, completed, tools: [...]}
    subagents: Dict[str, dict] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialize to dict for DB persistence. Strips base64 image data."""

        def _strip_base64(items):
            if not items:
                return items
            return [{k: v for k, v in item.items() if k != "data"} for item in items]

        return {
            "channel_id": self.channel_id,
            "message_ts": self.message_ts,
            "thread_ts": self.thread_ts,
            "thread_id": self.thread_id,
            "thoughts": [
                {"text": t.text, "tools": t.tools, "completed": t.completed}
                for t in self.thoughts
            ],
            "final_result": self.final_result,
            "result_images": _strip_base64(self.result_images),
            "result_files": _strip_base64(self.result_files),
            "error": self.error,
            "timeline": self.timeline,
            "trigger_user_id": self.trigger_user_id,
            "trigger_text": self.trigger_text,
            "subagents": self.subagents,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MessageState":
        """Deserialize from dict (DB retrieval)."""
        thoughts = []
        for t in data.get("thoughts", []):
            if isinstance(t, ThoughtSection):
                thoughts.append(t)
            elif isinstance(t, dict):
                thoughts.append(
                    ThoughtSection(
                        text=t.get("text", ""),
                        tools=t.get("tools", []),
                        completed=t.get("completed", False),
                    )
                )
        state = cls(
            channel_id=data.get("channel_id", ""),
            message_ts=data.get("message_ts", ""),
            thread_ts=data.get("thread_ts", ""),
            thread_id=data.get("thread_id", ""),
        )
        state.thoughts = thoughts
        state.final_result = data.get("final_result")
        state.result_images = data.get("result_images")
        state.result_files = data.get("result_files")
        state.error = data.get("error")
        state.timeline = data.get("timeline", [])
        state.trigger_user_id = data.get("trigger_user_id")
        state.trigger_text = data.get("trigger_text")
        state.subagents = data.get("subagents", {})
        return state

    @property
    def current_thought(self) -> str:
        """Get the current (last) thought text."""
        if self.thoughts:
            return self.thoughts[-1].text
        return ""

    @property
    def current_thought_section(self) -> Optional["ThoughtSection"]:
        """Get the current (last) thought section."""
        if self.thoughts:
            return self.thoughts[-1]
        return None

    @property
    def completed_tools(self) -> list:
        """Get all completed tools across all thoughts (for backward compat)."""
        tools = []
        for thought in self.thoughts:
            tools.extend(thought.tools)
        return tools


# In-memory cache for investigation state (for modal views)
# Keyed by message_ts (unique per message, unlike thread_id which is shared)
# Falls back to config-service DB on cache miss (persisted for 3 days)
_investigation_cache: Dict[str, MessageState] = {}
_cache_timestamps: Dict[str, float] = {}  # Track when entries were added
CACHE_TTL_HOURS = 24  # Keep in-memory cache entries for 24 hours


def _cleanup_old_cache_entries():
    """Remove cache entries older than CACHE_TTL_HOURS."""
    now = time.time()
    ttl_seconds = CACHE_TTL_HOURS * 3600
    expired_keys = []

    for key, timestamp in _cache_timestamps.items():
        if now - timestamp > ttl_seconds:
            expired_keys.append(key)

    for key in expired_keys:
        _investigation_cache.pop(key, None)
        _cache_timestamps.pop(key, None)
        logger.info(f"Cleaned up expired cache entry: {key}")

    if expired_keys:
        logger.info(
            f"Cache cleanup: removed {len(expired_keys)} expired entries, {len(_investigation_cache)} remaining"
        )


def _persist_session_to_db(
    state: MessageState, org_id: str = None, team_node_id: str = None
):
    """Persist session state to config-service DB (fire-and-forget in background thread)."""

    def _save():
        try:
            config_client = get_config_client()
            config_client.save_session_state(
                message_ts=state.message_ts,
                state_json=state.to_dict(),
                thread_ts=state.thread_ts,
                org_id=org_id,
                team_node_id=team_node_id,
            )
            logger.info(
                f"Persisted session state to DB for message_ts={state.message_ts}"
            )
        except Exception as e:
            logger.warning(f"Failed to persist session state to DB: {e}")

    threading.Thread(target=_save, daemon=True).start()


def _load_session_from_db(message_ts: str) -> Optional[MessageState]:
    """Load session state from config-service DB. Returns MessageState or None."""
    try:
        config_client = get_config_client()
        state_json = config_client.get_session_state(message_ts)
        if state_json:
            state = MessageState.from_dict(state_json)
            # Populate in-memory cache for subsequent accesses
            _investigation_cache[message_ts] = state
            _cache_timestamps[message_ts] = time.time()
            logger.info(f"Loaded session state from DB for message_ts={message_ts}")
            return state
    except Exception as e:
        logger.warning(f"Failed to load session state from DB: {e}")
    return None


def save_investigation_snapshot(state: MessageState):
    """Save investigation state to file for testing/debugging."""
    # Check if snapshot recording is enabled (default: disabled for production)
    if os.getenv("ENABLE_SNAPSHOTS", "false").lower() not in ("true", "1", "yes"):
        return

    try:
        # Create snapshots directory
        snapshots_dir = os.path.join(
            os.path.dirname(__file__), "tests", "snapshots", "data"
        )
        os.makedirs(snapshots_dir, exist_ok=True)

        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"investigation_{timestamp}_{state.thread_id[-8:]}.json"
        filepath = os.path.join(snapshots_dir, filename)

        # Convert MessageState to dict (recursively handle dataclasses)
        def to_serializable(obj):
            if hasattr(obj, "__dict__"):
                return {k: to_serializable(v) for k, v in obj.__dict__.items()}
            elif isinstance(obj, list):
                return [to_serializable(item) for item in obj]
            elif isinstance(obj, dict):
                return {k: to_serializable(v) for k, v in obj.items()}
            else:
                return obj

        snapshot = {
            "captured_at": datetime.now().isoformat(),
            "thread_id": state.thread_id,
            "state": to_serializable(state),
        }

        # Save to file
        with open(filepath, "w") as f:
            json.dump(snapshot, f, indent=2)

        logger.info(f"Saved investigation snapshot: {filepath}")
        logger.info(
            f"   Thoughts: {len(state.thoughts)}, Final result: {bool(state.final_result)}"
        )

        return filepath
    except Exception as e:
        logger.warning(f"Failed to save investigation snapshot: {e}")
        return None

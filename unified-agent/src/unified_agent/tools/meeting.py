"""
Meeting transcription tools for incident context.

Supports multiple meeting transcription providers:
- Fireflies.ai (GraphQL API)
- Circleback (webhook-based, data stored locally)
- Otter.ai (REST API)
- Vexa (self-hosted, for on-prem deployments)

Configuration is read from team integrations in the execution context.
"""

import os
import re
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Any

import httpx

import json
import logging

from ..core.agent import function_tool
from . import register_tool

    IntegrationAuthenticationError,
    IntegrationConnectionError,
    IntegrationNotConfiguredError,
)

logger = logging.getLogger(__name__)

# =============================================================================
# Provider Abstraction
# =============================================================================


class MeetingProvider(ABC):
    """Abstract base class for meeting transcription providers."""

    @abstractmethod
    @function_tool
    def get_transcript(self, meeting_id: str) -> str:
        """Get full transcript for a meeting."""
        pass

    @abstractmethod
    @function_tool
    def search_meetings(self, query: str, hours_back: int = 24) -> str:
        """Search meetings by keyword."""
        pass

    @abstractmethod
    @function_tool
    def get_recent_meetings(self, hours: int = 24) -> str:
        """Get recent meetings."""
        pass


# =============================================================================
# Fireflies.ai Provider
# =============================================================================


class FirefliesProvider(MeetingProvider):
    """
    Fireflies.ai meeting transcription provider.

    Uses GraphQL API to fetch transcripts and search meetings.
    Docs: https://docs.fireflies.ai/
    """

    GRAPHQL_ENDPOINT = "https://api.fireflies.ai/graphql"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def _graphql_request(self, query: str, variables: dict = None) -> str:
        """Execute a GraphQL request to Fireflies API."""
        try:
            response = httpx.post(
                self.GRAPHQL_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"query": query, "variables": variables or {}},
                timeout=30,
            )

            if response.status_code == 401:
                raise IntegrationAuthenticationError("fireflies", "Invalid API key")
            if response.status_code != 200:
                raise IntegrationConnectionError(
                    "fireflies",
                    status_code=response.status_code,
                    details=response.text[:200],
                )

            data = response.json()
            if "errors" in data:
                return json.dumps({"ok": False, "error": "Tool execution error"})
                    "fireflies", f"GraphQL error: {data['errors']}"
                )

            return data.get("data", {})

        except httpx.RequestError as e:
            raise IntegrationConnectionError(
                "fireflies", details=f"Connection error: {str(e)}"
            )

    @function_tool
    def get_transcript(self, meeting_id: str) -> str:
        """Get full transcript from Fireflies."""
        query = """
        query Transcript($id: String!) {
            transcript(id: $id) {
                id
                title
                date
                duration
                host_email
                organizer_email
                participants
                transcript_url
                sentences {
                    text
                    speaker_name
                    start_time
                    end_time
                }
                summary {
                    overview
                    action_items
                    keywords
                }
            }
        }
        """
        data = self._graphql_request(query, {"id": meeting_id})
        transcript = data.get("transcript", {})

        if not transcript:
            return json.dumps({"ok": False, "error": "fireflies"})

        return self._normalize_transcript(transcript)

    @function_tool
    def search_meetings(self, query: str, hours_back: int = 24) -> str:
        """Search meetings by keyword in Fireflies."""
        # Calculate date range
        from_date = (datetime.utcnow() - timedelta(hours=hours_back)).isoformat() + "Z"

        gql_query = """
        query SearchMeetings($keyword: String!, $fromDate: DateTime, $limit: Int) {
            transcripts(keyword: $keyword, fromDate: $fromDate, limit: $limit) {
                id
                title
                date
                duration
                host_email
                participants
            }
        }
        """
        data = self._graphql_request(
            gql_query,
            {"keyword": query, "fromDate": from_date, "limit": 20},
        )

        meetings = data.get("transcripts", [])
        return [self._normalize_meeting(m) for m in meetings]

    @function_tool
    def get_recent_meetings(self, hours: int = 24) -> str:
        """Get recent meetings from Fireflies."""
        from_date = (datetime.utcnow() - timedelta(hours=hours)).isoformat() + "Z"

        query = """
        query RecentMeetings($fromDate: DateTime, $limit: Int) {
            transcripts(fromDate: $fromDate, limit: $limit) {
                id
                title
                date
                duration
                host_email
                participants
            }
        }
        """
        data = self._graphql_request(query, {"fromDate": from_date, "limit": 20})

        meetings = data.get("transcripts", [])
        return [self._normalize_meeting(m) for m in meetings]

    def _normalize_transcript(self, transcript: dict) -> str:
        """Normalize Fireflies transcript to common format."""
        sentences = transcript.get("sentences", [])
        return {
            "id": transcript.get("id"),
            "title": transcript.get("title"),
            "date": transcript.get("date"),
            "duration_seconds": transcript.get("duration"),
            "host": transcript.get("host_email"),
            "participants": transcript.get("participants", []),
            "segments": [
                {
                    "speaker": s.get("speaker_name", "Unknown"),
                    "text": s.get("text", ""),
                    "start_time": s.get("start_time"),
                    "end_time": s.get("end_time"),
                }
                for s in sentences
            ],
            "summary": transcript.get("summary", {}),
            "provider": "fireflies",
        }

    def _normalize_meeting(self, meeting: dict) -> str:
        """Normalize Fireflies meeting to common format."""
        return {
            "id": meeting.get("id"),
            "title": meeting.get("title"),
            "date": meeting.get("date"),
            "duration_seconds": meeting.get("duration"),
            "host": meeting.get("host_email"),
            "participants": meeting.get("participants", []),
            "provider": "fireflies",
        }


# =============================================================================
# Circleback Provider
# =============================================================================


class CirclebackProvider(MeetingProvider):
    """
    Circleback meeting transcription provider.

    Circleback uses webhooks to push data. This provider queries
    locally stored meeting data that was received via webhook.

    The webhook endpoint should store data in config_service DB.
    """

    def __init__(self, config_service_url: str, team_token: str):
        self.config_service_url = config_service_url.rstrip("/")
        self.team_token = team_token

    def _request(self, method: str, endpoint: str, **kwargs) -> str:
        """Make request to config service for meeting data."""
        try:
            response = httpx.request(
                method,
                f"{self.config_service_url}{endpoint}",
                headers={"Authorization": f"Bearer {self.team_token}"},
                timeout=30,
                **kwargs,
            )

            if response.status_code == 401:
                raise IntegrationAuthenticationError("circleback")
            if response.status_code == 404:
                return {}
            if response.status_code >= 400:
                raise IntegrationConnectionError(
                    "circleback",
                    status_code=response.status_code,
                    details=response.text[:200],
                )

            return response.json()

        except httpx.RequestError as e:
            raise IntegrationConnectionError(
                "circleback", details=f"Connection error: {str(e)}"
            )

    @function_tool
    def get_transcript(self, meeting_id: str) -> str:
        """Get transcript from locally stored Circleback data."""
        data = self._request("GET", f"/api/v1/meetings/{meeting_id}")

        if not data:
            return json.dumps({"ok": False, "error": "circleback"})

        return self._normalize_transcript(data)

    @function_tool
    def search_meetings(self, query: str, hours_back: int = 24) -> str:
        """Search locally stored Circleback meetings."""
        data = self._request(
            "GET",
            "/api/v1/meetings/search",
            params={"q": query, "hours_back": hours_back},
        )

        meetings = data.get("meetings", [])
        return [self._normalize_meeting(m) for m in meetings]

    @function_tool
    def get_recent_meetings(self, hours: int = 24) -> str:
        """Get recent Circleback meetings."""
        data = self._request(
            "GET",
            "/api/v1/meetings",
            params={"hours_back": hours, "limit": 20},
        )

        meetings = data.get("meetings", [])
        return [self._normalize_meeting(m) for m in meetings]

    def _normalize_transcript(self, data: dict) -> str:
        """Normalize Circleback transcript to common format."""
        transcript = data.get("transcript", [])
        return {
            "id": data.get("id"),
            "title": data.get("name"),
            "date": data.get("createdAt"),
            "duration_seconds": data.get("duration"),
            "host": None,  # Circleback doesn't distinguish host
            "participants": [a.get("email") for a in data.get("attendees", [])],
            "segments": [
                {
                    "speaker": t.get("speaker", "Unknown"),
                    "text": t.get("text", ""),
                    "start_time": t.get("timestamp"),
                    "end_time": None,
                }
                for t in transcript
            ],
            "summary": {
                "notes": data.get("notes"),
                "action_items": data.get("action_items", []),
            },
            "provider": "circleback",
        }

    def _normalize_meeting(self, meeting: dict) -> str:
        """Normalize Circleback meeting to common format."""
        return {
            "id": meeting.get("id"),
            "title": meeting.get("name"),
            "date": meeting.get("createdAt"),
            "duration_seconds": meeting.get("duration"),
            "host": None,
            "participants": [a.get("email") for a in meeting.get("attendees", [])],
            "provider": "circleback",
        }


# =============================================================================
# Vexa Provider (Self-hosted)
# =============================================================================


class VexaProvider(MeetingProvider):
    """
    Vexa self-hosted meeting transcription provider.

    For on-premises deployments where meeting data must stay in customer env.
    Docs: https://github.com/Vexa-ai/vexa
    """

    def __init__(self, api_key: str, api_host: str):
        self.api_key = api_key
        self.api_host = api_host.rstrip("/")

    def _request(self, method: str, endpoint: str, **kwargs) -> str:
        """Make request to Vexa API."""
        try:
            response = httpx.request(
                method,
                f"{self.api_host}{endpoint}",
                headers={"X-API-Key": self.api_key},
                timeout=30,
                **kwargs,
            )

            if response.status_code == 401:
                raise IntegrationAuthenticationError("vexa")
            if response.status_code == 404:
                return {}
            if response.status_code >= 400:
                raise IntegrationConnectionError(
                    "vexa",
                    status_code=response.status_code,
                    details=response.text[:200],
                )

            return response.json()

        except httpx.RequestError as e:
            raise IntegrationConnectionError(
                "vexa", details=f"Connection error: {str(e)}"
            )

    @function_tool
    def request_bot(
        self, platform: str, meeting_id: str, passcode: str = None
    ) -> str:
        """
        Request Vexa bot to join a meeting.

        Args:
            platform: 'google_meet' or 'teams'
            meeting_id: Native meeting ID
            passcode: Optional passcode (required for Teams)

        Returns:
            Bot status including bot_id
        """
        payload = {
            "platform": platform,
            "native_meeting_id": meeting_id,
        }
        if passcode:
            payload["passcode"] = passcode

        return self._request("POST", "/bots", json=payload)

    @function_tool
    def get_bot_status(self, bot_id: str) -> str:
        """Get status of a Vexa bot."""
        return self._request("GET", f"/bots/{bot_id}")

    @function_tool
    def get_transcript(self, meeting_id: str) -> str:
        """
        Get transcript from Vexa.

        meeting_id should be in format: {platform}/{native_id}
        e.g., 'google_meet/abc-defg-hij'
        """
        # Parse meeting_id if it contains platform
        if "/" in meeting_id:
            platform, native_id = meeting_id.split("/", 1)
        else:
            # Assume google_meet if no platform specified
            platform, native_id = "google_meet", meeting_id

        data = self._request("GET", f"/transcripts/{platform}/{native_id}")

        if not data:
            return json.dumps({"ok": False, "error": "vexa"})

        return self._normalize_transcript(data, platform, native_id)

    @function_tool
    def search_meetings(self, query: str, hours_back: int = 24) -> str:
        """Search meetings in Vexa (limited - mainly by meeting ID)."""
        # Vexa doesn't have full-text search; return recent meetings
        # and let caller filter by keyword
        return self.get_recent_meetings(hours_back)

    @function_tool
    def get_recent_meetings(self, hours: int = 24) -> str:
        """Get recent meetings from Vexa."""
        data = self._request(
            "GET",
            "/meetings",
            params={"hours_back": hours, "limit": 20},
        )

        meetings = data.get("meetings", [])
        return [self._normalize_meeting(m) for m in meetings]

    def _normalize_transcript(
        self, data: dict | list, platform: str, native_id: str
    ) -> str:
        """Normalize Vexa transcript to common format."""
        # Vexa returns list of segments directly
        segments = data if isinstance(data, list) else data.get("segments", [])

        return {
            "id": f"{platform}/{native_id}",
            "title": f"Meeting {native_id}",
            "date": None,
            "duration_seconds": None,
            "host": None,
            "participants": [],
            "segments": [
                {
                    "speaker": s.get("speaker", "Unknown"),
                    "text": s.get("text", ""),
                    "start_time": s.get("absolute_start_time"),
                    "end_time": s.get("absolute_end_time"),
                }
                for s in segments
            ],
            "summary": {},
            "provider": "vexa",
        }

    def _normalize_meeting(self, meeting: dict) -> str:
        """Normalize Vexa meeting to common format."""
        return {
            "id": f"{meeting.get('platform')}/{meeting.get('native_id')}",
            "title": meeting.get("title", f"Meeting {meeting.get('native_id')}"),
            "date": meeting.get("created_at"),
            "duration_seconds": meeting.get("duration"),
            "host": None,
            "participants": meeting.get("participants", []),
            "provider": "vexa",
        }


# =============================================================================
# Otter.ai Provider
# =============================================================================


class OtterProvider(MeetingProvider):
    """
    Otter.ai meeting transcription provider.

    Uses the new public REST API (launched October 2025).
    """

    API_BASE = "https://api.otter.ai/v1"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def _request(self, method: str, endpoint: str, **kwargs) -> str:
        """Make request to Otter API."""
        try:
            response = httpx.request(
                method,
                f"{self.API_BASE}{endpoint}",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=30,
                **kwargs,
            )

            if response.status_code == 401:
                raise IntegrationAuthenticationError("otter")
            if response.status_code == 404:
                return {}
            if response.status_code >= 400:
                raise IntegrationConnectionError(
                    "otter",
                    status_code=response.status_code,
                    details=response.text[:200],
                )

            return response.json()

        except httpx.RequestError as e:
            raise IntegrationConnectionError(
                "otter", details=f"Connection error: {str(e)}"
            )

    @function_tool
    def get_transcript(self, meeting_id: str) -> str:
        """Get transcript from Otter."""
        data = self._request("GET", f"/transcripts/{meeting_id}")

        if not data:
            return json.dumps({"ok": False, "error": "otter"})

        return self._normalize_transcript(data)

    @function_tool
    def search_meetings(self, query: str, hours_back: int = 24) -> str:
        """Search meetings in Otter."""
        data = self._request(
            "GET",
            "/transcripts",
            params={"q": query, "limit": 20},
        )

        meetings = data.get("transcripts", [])
        return [self._normalize_meeting(m) for m in meetings]

    @function_tool
    def get_recent_meetings(self, hours: int = 24) -> str:
        """Get recent meetings from Otter."""
        data = self._request(
            "GET",
            "/transcripts",
            params={"limit": 20},
        )

        meetings = data.get("transcripts", [])
        return [self._normalize_meeting(m) for m in meetings]

    def _normalize_transcript(self, data: dict) -> str:
        """Normalize Otter transcript to common format."""
        return {
            "id": data.get("id"),
            "title": data.get("title"),
            "date": data.get("created_at"),
            "duration_seconds": data.get("duration"),
            "host": data.get("owner_email"),
            "participants": data.get("participants", []),
            "segments": [
                {
                    "speaker": s.get("speaker", "Unknown"),
                    "text": s.get("text", ""),
                    "start_time": s.get("start_time"),
                    "end_time": s.get("end_time"),
                }
                for s in data.get("transcript", [])
            ],
            "summary": data.get("summary", {}),
            "provider": "otter",
        }

    def _normalize_meeting(self, meeting: dict) -> str:
        """Normalize Otter meeting to common format."""
        return {
            "id": meeting.get("id"),
            "title": meeting.get("title"),
            "date": meeting.get("created_at"),
            "duration_seconds": meeting.get("duration"),
            "host": meeting.get("owner_email"),
            "participants": meeting.get("participants", []),
            "provider": "otter",
        }


# =============================================================================
# Recall.ai Provider (Real-time Transcription)
# =============================================================================


class RecallProvider(MeetingProvider):
    """
    Recall.ai meeting bot provider for real-time transcription.

    Recall.ai provides a unified API for meeting bots across Zoom, Google Meet,
    Microsoft Teams, Webex, and other platforms. Bots join meetings as participants
    and stream real-time transcripts via webhooks.

    Key features:
    - White-label bots (appear as "IncidentFox Notetaker")
    - Real-time transcript streaming (~200ms latency)
    - Per-participant speaker diarization
    - SOC 2, HIPAA, GDPR compliant

    Docs: https://docs.recall.ai/
    """

    def __init__(
        self,
        api_key: str,
        region: str = "us-west-2",
        bot_name: str = "IncidentFox Notetaker",
        bot_image_url: str | None = None,
        webhook_url: str | None = None,
    ):
        self.api_key = api_key
        self.region = region
        self.bot_name = bot_name
        self.bot_image_url = bot_image_url
        self.webhook_url = webhook_url
        self.api_base = f"https://{region}.recall.ai/api/v1"

    def _request(self, method: str, endpoint: str, **kwargs) -> str:
        """Make request to Recall.ai API."""
        try:
            response = httpx.request(
                method,
                f"{self.api_base}{endpoint}",
                headers={
                    "Authorization": f"Token {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=30,
                **kwargs,
            )

            if response.status_code == 401:
                raise IntegrationAuthenticationError("recall")
            if response.status_code == 404:
                return {}
            if response.status_code >= 400:
                raise IntegrationConnectionError(
                    "recall",
                    status_code=response.status_code,
                    details=response.text[:500],
                )

            return response.json()

        except httpx.RequestError as e:
            raise IntegrationConnectionError(
                "recall", details=f"Connection error: {str(e)}"
            )

    @function_tool
    def create_bot(
        self,
        meeting_url: str,
        incident_id: str | None = None,
        custom_bot_name: str | None = None,
        enable_partial_transcripts: bool = False,
        slack_channel_id: str | None = None,
        slack_thread_ts: str | None = None,
    ) -> str:
        """
        Create a bot and send it to join a meeting.

        Args:
            meeting_url: The meeting URL (Zoom, Google Meet, Teams, etc.)
            incident_id: Optional incident ID to associate with this recording
            custom_bot_name: Override the default bot name
            enable_partial_transcripts: Enable low-latency partial transcripts
            slack_channel_id: Optional Slack channel for transcript summaries
            slack_thread_ts: Optional Slack thread for transcript summaries

        Returns:
            Bot creation response including bot_id
        """
        # Build bot configuration
        bot_config: dict[str, Any] = {
            "meeting_url": meeting_url,
            "bot_name": custom_bot_name or self.bot_name,
        }

        # Add bot image if configured
        if self.bot_image_url:
            bot_config["bot_image"] = self.bot_image_url

        # Configure transcription
        bot_config["recording_config"] = {
            "transcript": {
                "provider": {"meeting_captions": {}}  # Use platform's native captions
            }
        }

        # Configure real-time webhook endpoints
        if self.webhook_url:
            events = ["bot.status_change", "transcript.data"]
            if enable_partial_transcripts:
                events.append("transcript.partial_data")

            bot_config["real_time_endpoints"] = [
                {
                    "type": "webhook",
                    "url": self.webhook_url,
                    "events": events,
                }
            ]

        # Build metadata for webhook routing
        metadata: dict[str, Any] = {}
        if incident_id:
            metadata["incident_id"] = incident_id
        if slack_channel_id:
            metadata["slack_channel_id"] = slack_channel_id
        if slack_thread_ts:
            metadata["slack_thread_ts"] = slack_thread_ts
        if metadata:
            bot_config["metadata"] = metadata

        logger.info(
            "recall_creating_bot",
            meeting_url=meeting_url,
            bot_name=bot_config["bot_name"],
            incident_id=incident_id,
            slack_channel_id=slack_channel_id,
        )

        result = self._request("POST", "/bot", json=bot_config)

        bot_id = result.get("id")

        # Also register the bot with our orchestrator to store Slack thread info
        # This ensures the webhook handler can find the Slack context
        # Credentials from environment variables
        if ctx and (slack_channel_id or slack_thread_ts):
            try:
                self._register_bot_with_orchestrator(
                    bot_id=bot_id,
                    meeting_url=meeting_url,
                    bot_name=custom_bot_name or self.bot_name,
                    incident_id=incident_id,
                    slack_channel_id=slack_channel_id,
                    slack_thread_ts=slack_thread_ts,
                    org_id=ctx.org_id,
                    team_node_id=ctx.team_node_id,
                )
            except Exception as e:
                # Log but don't fail - bot was created in Recall
                logger.warning(
                    "recall_bot_orchestrator_registration_failed",
                    bot_id=bot_id,
                    error=str(e),
                )

        logger.info(
            "recall_bot_created",
            bot_id=bot_id,
            meeting_url=meeting_url,
        )

        return {
            "bot_id": bot_id,
            "status": result.get("status", {}).get("code", "unknown"),
            "meeting_url": meeting_url,
            "provider": "recall",
        }

    def _register_bot_with_orchestrator(
        self,
        bot_id: str,
        meeting_url: str,
        bot_name: str,
        incident_id: str | None,
        slack_channel_id: str | None,
        slack_thread_ts: str | None,
        org_id: str,
        team_node_id: str,
    ) -> None:
        """
        Register bot with orchestrator to store Slack thread info.

        This is called after creating the bot in Recall.ai to ensure
        our webhook handler can find the Slack context for posting summaries.
        """
        import uuid

        # Get config service URL and admin token
        config_service_url = os.getenv("CONFIG_SERVICE_URL", "").strip()
        admin_token = os.getenv("ORCHESTRATOR_INTERNAL_ADMIN_TOKEN", "").strip()

        if not config_service_url or not admin_token:
            logger.debug(
                "recall_bot_orchestrator_registration_skipped",
                reason="missing_config",
            )
            return

        internal_id = uuid.uuid4().hex

        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                f"{config_service_url}/api/v1/internal/recall-bots",
                headers={
                    "Authorization": f"Bearer {admin_token}",
                    "X-Internal-Service": "agent",
                },
                json={
                    "id": internal_id,
                    "org_id": org_id,
                    "team_node_id": team_node_id,
                    "recall_bot_id": bot_id,
                    "meeting_url": meeting_url,
                    "incident_id": incident_id,
                    "bot_name": bot_name,
                    "slack_channel_id": slack_channel_id,
                    "slack_thread_ts": slack_thread_ts,
                },
            )
            response.raise_for_status()

        logger.info(
            "recall_bot_registered_with_orchestrator",
            bot_id=bot_id,
            internal_id=internal_id,
            slack_channel_id=slack_channel_id,
        )

    @function_tool
    def get_bot_status(self, bot_id: str) -> str:
        """Get the current status of a bot."""
        result = self._request("GET", f"/bot/{bot_id}")

        if not result:
            return json.dumps({"ok": False, "error": "recall"})

        status = result.get("status", {})
        return {
            "bot_id": bot_id,
            "status_code": status.get("code", "unknown"),
            "status_message": status.get("message", ""),
            "meeting_url": result.get("meeting_url"),
            "created_at": result.get("created_at"),
            "provider": "recall",
        }

    @function_tool
    def stop_bot(self, bot_id: str) -> str:
        """
        Stop a bot and remove it from the meeting.

        Args:
            bot_id: The bot ID to stop

        Returns:
            Confirmation of bot stop
        """
        logger.info("recall_stopping_bot", bot_id=bot_id)

        self._request("POST", f"/bot/{bot_id}/leave_call")

        return {
            "bot_id": bot_id,
            "status": "stopped",
            "message": "Bot has been requested to leave the meeting",
            "provider": "recall",
        }

    @function_tool
    def get_transcript(self, meeting_id: str) -> str:
        """
        Get transcript for a completed meeting.

        For Recall.ai, meeting_id is the bot_id.
        """
        # First get bot info
        bot_info = self._request("GET", f"/bot/{meeting_id}")
        if not bot_info:
            return json.dumps({"ok": False, "error": "recall"})

        # Get transcript
        transcript_data = self._request("GET", f"/bot/{meeting_id}/transcript")

        return self._normalize_transcript(bot_info, transcript_data)

    @function_tool
    def search_meetings(self, query: str, hours_back: int = 24) -> str:
        """
        Search recent meetings/bots.

        Note: Recall.ai doesn't have full-text search. This returns recent bots
        and filters client-side by meeting URL or metadata.
        """
        # Get recent bots and filter
        bots = self.get_recent_meetings(hours_back)

        # Filter by query (match against meeting_url or title)
        query_lower = query.lower()
        return [
            bot
            for bot in bots
            if query_lower in (bot.get("title", "").lower())
            or query_lower in (bot.get("meeting_url", "").lower())
        ]

    @function_tool
    def get_recent_meetings(self, hours: int = 24) -> str:
        """Get recent bots/meetings."""
        # Calculate time range
        from_time = (datetime.utcnow() - timedelta(hours=hours)).isoformat() + "Z"

        result = self._request(
            "GET",
            "/bot",
            params={"created_at__gte": from_time, "limit": 50},
        )

        bots = result.get("results", []) if isinstance(result, dict) else []
        return [self._normalize_meeting(bot) for bot in bots]

    def _normalize_transcript(
        self, bot_info: dict, transcript_data: dict | list
    ) -> str:
        """Normalize Recall.ai transcript to common format."""
        # Transcript data may be a list of utterances or a dict with results
        if isinstance(transcript_data, dict):
            utterances = transcript_data.get("results", [])
        else:
            utterances = transcript_data or []

        return {
            "id": bot_info.get("id"),
            "title": f"Meeting ({bot_info.get('meeting_url', 'Unknown')})",
            "date": bot_info.get("created_at"),
            "duration_seconds": bot_info.get("duration_seconds"),
            "host": None,
            "participants": [p.get("name") for p in bot_info.get("participants", [])],
            "segments": [
                {
                    "speaker": u.get("speaker", "Unknown"),
                    "text": u.get("text", ""),
                    "start_time": u.get("start_time"),
                    "end_time": u.get("end_time"),
                }
                for u in utterances
            ],
            "summary": {},
            "provider": "recall",
        }

    def _normalize_meeting(self, bot: dict) -> str:
        """Normalize Recall.ai bot to common meeting format."""
        status = bot.get("status", {})
        return {
            "id": bot.get("id"),
            "title": f"Meeting ({bot.get('meeting_url', 'Unknown')})",
            "date": bot.get("created_at"),
            "duration_seconds": bot.get("duration_seconds"),
            "host": None,
            "participants": [p.get("name") for p in bot.get("participants", [])],
            "status": status.get("code", "unknown"),
            "meeting_url": bot.get("meeting_url"),
            "provider": "recall",
        }


# =============================================================================
# Provider Factory
# =============================================================================


def _get_meeting_config() -> str:
    """
    Get meeting provider configuration from execution context or environment.

    Returns:
        Meeting provider configuration dict

    Raises:
        IntegrationNotConfiguredError: If no meeting provider is configured
    """
    # 1. Try execution context (production, thread-safe)
    # Credentials from environment variables
    # 2. Try environment variables (dev/testing fallback)
    if os.getenv("MEETING_PROVIDER"):
        provider = os.getenv("MEETING_PROVIDER")
        logger.debug("meeting_config_from_env", provider=provider)

        config = {"provider": provider}

        if provider == "fireflies":
            config["fireflies_api_key"] = os.getenv("FIREFLIES_API_KEY")
        elif provider == "vexa":
            config["vexa_api_key"] = os.getenv("VEXA_API_KEY")
            config["vexa_api_host"] = os.getenv(
                "VEXA_API_HOST", "http://localhost:8056"
            )
        elif provider == "otter":
            config["otter_api_key"] = os.getenv("OTTER_API_KEY")
        elif provider == "circleback":
            config["config_service_url"] = os.getenv(
                "CONFIG_SERVICE_URL", "http://localhost:8001"
            )
            config["team_token"] = os.getenv("TEAM_TOKEN")
        elif provider == "recall":
            config["recall_api_key"] = os.getenv("RECALL_API_KEY")
            config["recall_region"] = os.getenv("RECALL_REGION", "us-west-2")
            config["recall_bot_name"] = os.getenv(
                "RECALL_BOT_NAME", "IncidentFox Notetaker"
            )
            config["recall_bot_image_url"] = os.getenv("RECALL_BOT_IMAGE_URL")
            config["recall_webhook_url"] = os.getenv("RECALL_WEBHOOK_URL")

        return config

    # 3. Not configured
    return {"error": "meeting not configured"}


def _get_provider() -> MeetingProvider:
    """
    Get the configured meeting provider for the current team.

    Returns:
        MeetingProvider instance

    Raises:
        IntegrationNotConfiguredError: If provider not configured properly
    """
    config = _get_meeting_config()
    provider = config.get("provider")

    if provider == "fireflies":
        api_key = config.get("fireflies_api_key")
        if not api_key:
            return {"error": "meeting not configured"}
        return FirefliesProvider(api_key)

    elif provider == "circleback":
        config_service_url = config.get("config_service_url")
        team_token = config.get("team_token")
        if not config_service_url or not team_token:
            return {"error": "meeting not configured"}
        return CirclebackProvider(config_service_url, team_token)

    elif provider == "vexa":
        api_key = config.get("vexa_api_key")
        api_host = config.get("vexa_api_host", "http://localhost:8056")
        if not api_key:
            return {"error": "meeting not configured"}
        return VexaProvider(api_key, api_host)

    elif provider == "otter":
        api_key = config.get("otter_api_key")
        if not api_key:
            return {"error": "meeting not configured"}
        return OtterProvider(api_key)

    elif provider == "recall":
        api_key = config.get("recall_api_key")
        if not api_key:
            return {"error": "meeting not configured"}
        return RecallProvider(
            api_key=api_key,
            region=config.get("recall_region", "us-west-2"),
            bot_name=config.get("recall_bot_name", "IncidentFox Notetaker"),
            bot_image_url=config.get("recall_bot_image_url"),
            webhook_url=config.get("recall_webhook_url"),
        )

    else:
        return {"error": "meeting not configured"}


# =============================================================================
# Meeting URL Parsing
# =============================================================================


def _parse_meeting_url(url: str) -> tuple[str, str, str | None]:
    """
    Parse meeting URL into platform, native_id, and optional passcode.

    Args:
        url: Meeting URL (Google Meet, Teams, Zoom)

    Returns:
        Tuple of (platform, native_id, passcode)

    Raises:
        ToolExecutionError: If URL format not recognized
    """
    # Google Meet: https://meet.google.com/abc-defg-hij
    if "meet.google.com" in url:
        match = re.search(r"meet\.google\.com/([a-z]{3}-[a-z]{4}-[a-z]{3})", url)
        if match:
            return "google_meet", match.group(1), None

    # Microsoft Teams (simplified - Teams URLs are complex)
    if "teams.microsoft.com" in url or "teams.live.com" in url:
        # Extract meeting ID from Teams URL
        match = re.search(r"meetup-join/([^/&?]+)", url)
        if match:
            return "teams", match.group(1), None
        # Try another common pattern
        match = re.search(r"meeting/([^/&?]+)", url)
        if match:
            return "teams", match.group(1), None

    # Zoom: https://zoom.us/j/123456789?pwd=xxx
    if "zoom.us" in url or "zoom.com" in url:
        match = re.search(r"/j/(\d+)", url)
        if match:
            meeting_id = match.group(1)
            # Extract passcode if present
            pwd_match = re.search(r"pwd=([^&]+)", url)
            passcode = pwd_match.group(1) if pwd_match else None
            return "zoom", meeting_id, passcode

    return json.dumps({"ok": False, "error": "Tool execution error"})
        "meeting_tools",
        f"Could not parse meeting URL: {url}. "
        "Supported formats: Google Meet, Microsoft Teams, Zoom",
    )


# =============================================================================
# Agent Tools
# =============================================================================


@function_tool
def meeting_get_transcript(meeting_id: str) -> str:
    """
    Get full transcript from a meeting.

    Use this tool to retrieve the complete transcript of a meeting,
    including speaker-attributed text and timestamps.

    Args:
        meeting_id: The meeting ID (from search results or incident context)

    Returns:
        Transcript with:
        - id: Meeting ID
        - title: Meeting title
        - date: Meeting date/time
        - duration_seconds: Meeting duration
        - participants: List of participants
        - segments: List of transcript segments with speaker, text, timestamps
        - summary: AI-generated summary (if available)
        - provider: Which provider the data came from
    """
    try:
        provider = _get_provider()
        result = provider.get_transcript(meeting_id)

        logger.info(
            "meeting_transcript_fetched",
            meeting_id=meeting_id,
            provider=result.get("provider"),
            segments=len(result.get("segments", [])),
        )

        return result

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except IntegrationAuthenticationError:
        raise
    except Exception as e:
        logger.error("meeting_transcript_failed", meeting_id=meeting_id, error=str(e))
        return json.dumps({"ok": False, "error": "meeting_get_transcript"})


@function_tool
def meeting_search(
    query: str,
    hours_back: int = 24,
) -> str:
    """
    Search recent meetings for relevant context.

    Use this tool to find meetings related to an incident by searching
    for keywords in meeting titles and transcripts.

    Args:
        query: Search query (e.g., "payment outage", "database", service name)
        hours_back: How many hours back to search (default: 24)

    Returns:
        List of matching meetings with:
        - id: Meeting ID (use with meeting_get_transcript)
        - title: Meeting title
        - date: Meeting date/time
        - duration_seconds: Meeting duration
        - participants: List of participants
        - provider: Which provider the data came from
    """
    try:
        provider = _get_provider()
        results = provider.search_meetings(query, hours_back)

        logger.info(
            "meeting_search_completed",
            query=query,
            hours_back=hours_back,
            results=len(results),
        )

        return results

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except IntegrationAuthenticationError:
        raise
    except Exception as e:
        logger.error("meeting_search_failed", query=query, error=str(e))
        return json.dumps({"ok": False, "error": "meeting_search"})


@function_tool
def meeting_get_recent(hours: int = 24) -> str:
    """
    Get recent meetings.

    Use this tool to see what meetings have happened recently,
    which may provide context for ongoing incidents.

    Args:
        hours: How many hours back to look (default: 24)

    Returns:
        List of recent meetings with:
        - id: Meeting ID (use with meeting_get_transcript)
        - title: Meeting title
        - date: Meeting date/time
        - duration_seconds: Meeting duration
        - participants: List of participants
        - provider: Which provider the data came from
    """
    try:
        provider = _get_provider()
        results = provider.get_recent_meetings(hours)

        logger.info(
            "meeting_recent_fetched",
            hours=hours,
            results=len(results),
        )

        return results

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except IntegrationAuthenticationError:
        raise
    except Exception as e:
        logger.error("meeting_recent_failed", hours=hours, error=str(e))
        return json.dumps({"ok": False, "error": "meeting_get_recent"})


@function_tool
def meeting_search_transcript(
    meeting_id: str,
    query: str,
) -> str:
    """
    Search within a specific meeting's transcript for relevant context.

    Use this tool to find specific discussions within a meeting
    related to an incident or topic.

    Args:
        meeting_id: The meeting ID
        query: Search query (keyword or phrase)

    Returns:
        List of matching transcript segments with:
        - speaker: Who said it
        - text: What was said
        - start_time: When it was said
    """
    try:
        provider = _get_provider()
        transcript = provider.get_transcript(meeting_id)

        # Search through segments
        query_lower = query.lower()
        matches = []
        for segment in transcript.get("segments", []):
            if query_lower in segment.get("text", "").lower():
                matches.append(segment)

        logger.info(
            "meeting_transcript_search_completed",
            meeting_id=meeting_id,
            query=query,
            matches=len(matches),
        )

        return matches

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except IntegrationAuthenticationError:
        raise
    except Exception as e:
        logger.error(
            "meeting_transcript_search_failed",
            meeting_id=meeting_id,
            query=query,
            error=str(e),
        )
        return json.dumps({"ok": False, "error": "meeting_search_transcript"})


@function_tool
def meeting_join(meeting_url: str) -> str:
    """
    Request bot to join a meeting and start transcribing.

    This tool is only available when using Vexa (self-hosted) provider.
    For other providers (Fireflies, Circleback, Otter), the bot is
    managed by the external service.

    Args:
        meeting_url: The meeting URL (Google Meet or Teams)

    Returns:
        Bot status including:
        - bot_id: ID to track the bot
        - status: Current status (requested, joining, active, etc.)
    """
    try:
        config = _get_meeting_config()
        provider_name = config.get("provider")

        if provider_name != "vexa":
            return {
                "error": f"meeting_join is only available for Vexa provider. "
                f"Current provider: {provider_name}. "
                "For Fireflies/Circleback/Otter, the bot is managed by the service.",
                "suggestion": "The user should invite the meeting bot through "
                "their Fireflies/Circleback/Otter dashboard or calendar integration.",
            }

        provider = _get_provider()
        if not isinstance(provider, VexaProvider):
            return json.dumps({"ok": False, "error": "Tool execution error"})
                "meeting_join", "Provider mismatch - expected VexaProvider"
            )

        platform, native_id, passcode = _parse_meeting_url(meeting_url)
        result = provider.request_bot(platform, native_id, passcode)

        logger.info(
            "meeting_bot_requested",
            platform=platform,
            native_id=native_id,
            bot_id=result.get("bot_id"),
        )

        return {
            "bot_id": result.get("bot_id"),
            "status": result.get("status"),
            "platform": platform,
            "meeting_id": f"{platform}/{native_id}",
            "message": f"Bot requested to join {platform} meeting. "
            "Use meeting_get_transcript with the meeting_id to get transcripts.",
        }

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except IntegrationAuthenticationError:
        raise
    except Exception as e:
        logger.error("meeting_join_failed", url=meeting_url, error=str(e))
        return json.dumps({"ok": False, "error": "meeting_join"})


# =============================================================================
# Recall.ai Real-Time Meeting Tools
# =============================================================================


@function_tool
def meeting_start_recording(
    meeting_url: str,
    incident_id: str | None = None,
    bot_name: str | None = None,
    slack_channel_id: str | None = None,
    slack_thread_ts: str | None = None,
) -> str:
    """
    Send an IncidentFox bot to join a meeting and start real-time transcription.

    Use this tool to add the IncidentFox meeting bot to an incident war room.
    The bot will join the meeting (Zoom, Google Meet, or Teams) and stream
    real-time transcripts that will be fed to the investigation.

    If invoked from a Slack thread, provide the slack_channel_id and slack_thread_ts
    to have transcript summaries automatically posted back to that thread.

    This tool requires Recall.ai to be configured as the meeting provider.

    Args:
        meeting_url: The meeting URL (Zoom, Google Meet, Teams, Webex, etc.)
        incident_id: Optional incident ID to associate transcripts with
        bot_name: Optional custom name for the bot (default: "IncidentFox Notetaker")
        slack_channel_id: Optional Slack channel ID to post transcript summaries
        slack_thread_ts: Optional Slack thread timestamp for transcript summaries

    Returns:
        Bot creation result including:
        - bot_id: ID to track the bot
        - status: Current status
        - meeting_url: The meeting URL
        - message: Instructions for next steps
    """
    try:
        config = _get_meeting_config()
        provider_name = config.get("provider")

        if provider_name != "recall":
            return {
                "error": f"meeting_start_recording requires Recall.ai provider. "
                f"Current provider: {provider_name}.",
                "suggestion": "Please configure Recall.ai in team settings to use "
                "real-time meeting transcription during incidents.",
            }

        provider = _get_provider()
        if not isinstance(provider, RecallProvider):
            return json.dumps({"ok": False, "error": "Tool execution error"})
                "meeting_start_recording", "Provider mismatch - expected RecallProvider"
            )

        # Try to get Slack context from execution context if not provided
        if not slack_channel_id or not slack_thread_ts:
            # Credentials from environment variables
            if ctx and ctx.team_config:
                # Check for Slack context in metadata (set during agent run)
                metadata = ctx.team_config.get("_run_metadata", {})
                slack_meta = metadata.get("slack", {})
                if not slack_channel_id:
                    slack_channel_id = slack_meta.get("channel_id")
                if not slack_thread_ts:
                    slack_thread_ts = slack_meta.get("thread_ts") or slack_meta.get(
                        "event_ts"
                    )

        result = provider.create_bot(
            meeting_url=meeting_url,
            incident_id=incident_id,
            custom_bot_name=bot_name,
            enable_partial_transcripts=False,  # Full transcripts only for less noise
            slack_channel_id=slack_channel_id,
            slack_thread_ts=slack_thread_ts,
        )

        logger.info(
            "meeting_recording_started",
            bot_id=result.get("bot_id"),
            meeting_url=meeting_url,
            incident_id=incident_id,
            slack_channel_id=slack_channel_id,
            slack_thread_ts=slack_thread_ts,
        )

        message = (
            f"IncidentFox bot is joining the meeting. "
            f"Bot ID: {result.get('bot_id')}. "
            "The bot will appear as a participant and start transcribing. "
            "Transcripts will be streamed to this investigation in real-time."
        )
        if slack_channel_id and slack_thread_ts:
            message += " Transcript summaries will be posted to this Slack thread."

        return {
            "bot_id": result.get("bot_id"),
            "status": result.get("status"),
            "meeting_url": meeting_url,
            "incident_id": incident_id,
            "slack_channel_id": slack_channel_id,
            "slack_thread_ts": slack_thread_ts,
            "message": message,
        }

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except IntegrationAuthenticationError:
        raise
    except Exception as e:
        logger.error("meeting_start_recording_failed", url=meeting_url, error=str(e))
        return json.dumps({"ok": False, "error": "meeting_start_recording"})


@function_tool
def meeting_stop_recording(bot_id: str) -> str:
    """
    Stop a meeting bot and remove it from the meeting.

    Use this tool to remove the IncidentFox bot from a meeting when
    the incident war room is no longer needed.

    Args:
        bot_id: The bot ID (returned from meeting_start_recording)

    Returns:
        Confirmation including:
        - bot_id: The bot that was stopped
        - status: "stopped"
        - message: Confirmation message
    """
    try:
        config = _get_meeting_config()
        provider_name = config.get("provider")

        if provider_name != "recall":
            return {
                "error": f"meeting_stop_recording requires Recall.ai provider. "
                f"Current provider: {provider_name}.",
            }

        provider = _get_provider()
        if not isinstance(provider, RecallProvider):
            return json.dumps({"ok": False, "error": "Tool execution error"})
                "meeting_stop_recording", "Provider mismatch - expected RecallProvider"
            )

        result = provider.stop_bot(bot_id)

        logger.info(
            "meeting_recording_stopped",
            bot_id=bot_id,
        )

        return result

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except IntegrationAuthenticationError:
        raise
    except Exception as e:
        logger.error("meeting_stop_recording_failed", bot_id=bot_id, error=str(e))
        return json.dumps({"ok": False, "error": "meeting_stop_recording"})


@function_tool
def meeting_get_bot_status(bot_id: str) -> str:
    """
    Get the current status of a meeting bot.

    Use this tool to check if a bot is still in a meeting, has left,
    or encountered an error.

    Args:
        bot_id: The bot ID (returned from meeting_start_recording)

    Returns:
        Bot status including:
        - bot_id: The bot ID
        - status_code: Current status (joining, in_call, recording, done, error)
        - status_message: Human-readable status message
        - meeting_url: The meeting URL
    """
    try:
        config = _get_meeting_config()
        provider_name = config.get("provider")

        if provider_name != "recall":
            return {
                "error": f"meeting_get_bot_status requires Recall.ai provider. "
                f"Current provider: {provider_name}.",
            }

        provider = _get_provider()
        if not isinstance(provider, RecallProvider):
            return json.dumps({"ok": False, "error": "Tool execution error"})
                "meeting_get_bot_status", "Provider mismatch - expected RecallProvider"
            )

        result = provider.get_bot_status(bot_id)

        logger.info(
            "meeting_bot_status_fetched",
            bot_id=bot_id,
            status=result.get("status_code"),
        )

        return result

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except IntegrationAuthenticationError:
        raise
    except Exception as e:
        logger.error("meeting_get_bot_status_failed", bot_id=bot_id, error=str(e))
        return json.dumps({"ok": False, "error": "meeting_get_bot_status"})


# =============================================================================
# Tool Exports
# =============================================================================

MEETING_TOOLS = [
    meeting_get_transcript,
    meeting_search,
    meeting_get_recent,
    meeting_search_transcript,
    meeting_join,
    # Recall.ai real-time tools
    meeting_start_recording,
    meeting_stop_recording,
    meeting_get_bot_status,
]


# Register tools
register_tool("meeting_get_transcript", meeting_get_transcript)
register_tool("meeting_search", meeting_search)
register_tool("meeting_get_recent", meeting_get_recent)
register_tool("meeting_search_transcript", meeting_search_transcript)
register_tool("meeting_join", meeting_join)
register_tool("meeting_start_recording", meeting_start_recording)
register_tool("meeting_stop_recording", meeting_stop_recording)
register_tool("meeting_get_bot_status", meeting_get_bot_status)

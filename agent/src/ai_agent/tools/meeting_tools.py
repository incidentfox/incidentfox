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

from ..core.config_required import handle_integration_not_configured
from ..core.errors import ToolExecutionError
from ..core.execution_context import get_execution_context
from ..core.integration_errors import (
    IntegrationAuthenticationError,
    IntegrationConnectionError,
    IntegrationNotConfiguredError,
)
from ..core.logging import get_logger

logger = get_logger(__name__)

# =============================================================================
# Provider Abstraction
# =============================================================================


class MeetingProvider(ABC):
    """Abstract base class for meeting transcription providers."""

    @abstractmethod
    def get_transcript(self, meeting_id: str) -> dict[str, Any]:
        """Get full transcript for a meeting."""
        pass

    @abstractmethod
    def search_meetings(self, query: str, hours_back: int = 24) -> list[dict[str, Any]]:
        """Search meetings by keyword."""
        pass

    @abstractmethod
    def get_recent_meetings(self, hours: int = 24) -> list[dict[str, Any]]:
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

    def _graphql_request(self, query: str, variables: dict = None) -> dict:
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
                raise ToolExecutionError(
                    "fireflies", f"GraphQL error: {data['errors']}"
                )

            return data.get("data", {})

        except httpx.RequestError as e:
            raise IntegrationConnectionError(
                "fireflies", details=f"Connection error: {str(e)}"
            )

    def get_transcript(self, meeting_id: str) -> dict[str, Any]:
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
            raise ToolExecutionError("fireflies", f"Meeting not found: {meeting_id}")

        return self._normalize_transcript(transcript)

    def search_meetings(self, query: str, hours_back: int = 24) -> list[dict[str, Any]]:
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

    def get_recent_meetings(self, hours: int = 24) -> list[dict[str, Any]]:
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

    def _normalize_transcript(self, transcript: dict) -> dict[str, Any]:
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

    def _normalize_meeting(self, meeting: dict) -> dict[str, Any]:
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

    def _request(self, method: str, endpoint: str, **kwargs) -> dict:
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

    def get_transcript(self, meeting_id: str) -> dict[str, Any]:
        """Get transcript from locally stored Circleback data."""
        data = self._request("GET", f"/api/v1/meetings/{meeting_id}")

        if not data:
            raise ToolExecutionError("circleback", f"Meeting not found: {meeting_id}")

        return self._normalize_transcript(data)

    def search_meetings(self, query: str, hours_back: int = 24) -> list[dict[str, Any]]:
        """Search locally stored Circleback meetings."""
        data = self._request(
            "GET",
            "/api/v1/meetings/search",
            params={"q": query, "hours_back": hours_back},
        )

        meetings = data.get("meetings", [])
        return [self._normalize_meeting(m) for m in meetings]

    def get_recent_meetings(self, hours: int = 24) -> list[dict[str, Any]]:
        """Get recent Circleback meetings."""
        data = self._request(
            "GET",
            "/api/v1/meetings",
            params={"hours_back": hours, "limit": 20},
        )

        meetings = data.get("meetings", [])
        return [self._normalize_meeting(m) for m in meetings]

    def _normalize_transcript(self, data: dict) -> dict[str, Any]:
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

    def _normalize_meeting(self, meeting: dict) -> dict[str, Any]:
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

    def _request(self, method: str, endpoint: str, **kwargs) -> dict:
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

    def request_bot(
        self, platform: str, meeting_id: str, passcode: str = None
    ) -> dict[str, Any]:
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

    def get_bot_status(self, bot_id: str) -> dict[str, Any]:
        """Get status of a Vexa bot."""
        return self._request("GET", f"/bots/{bot_id}")

    def get_transcript(self, meeting_id: str) -> dict[str, Any]:
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
            raise ToolExecutionError("vexa", f"Meeting not found: {meeting_id}")

        return self._normalize_transcript(data, platform, native_id)

    def search_meetings(self, query: str, hours_back: int = 24) -> list[dict[str, Any]]:
        """Search meetings in Vexa (limited - mainly by meeting ID)."""
        # Vexa doesn't have full-text search; return recent meetings
        # and let caller filter by keyword
        return self.get_recent_meetings(hours_back)

    def get_recent_meetings(self, hours: int = 24) -> list[dict[str, Any]]:
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
    ) -> dict[str, Any]:
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

    def _normalize_meeting(self, meeting: dict) -> dict[str, Any]:
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

    def _request(self, method: str, endpoint: str, **kwargs) -> dict:
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

    def get_transcript(self, meeting_id: str) -> dict[str, Any]:
        """Get transcript from Otter."""
        data = self._request("GET", f"/transcripts/{meeting_id}")

        if not data:
            raise ToolExecutionError("otter", f"Meeting not found: {meeting_id}")

        return self._normalize_transcript(data)

    def search_meetings(self, query: str, hours_back: int = 24) -> list[dict[str, Any]]:
        """Search meetings in Otter."""
        data = self._request(
            "GET",
            "/transcripts",
            params={"q": query, "limit": 20},
        )

        meetings = data.get("transcripts", [])
        return [self._normalize_meeting(m) for m in meetings]

    def get_recent_meetings(self, hours: int = 24) -> list[dict[str, Any]]:
        """Get recent meetings from Otter."""
        data = self._request(
            "GET",
            "/transcripts",
            params={"limit": 20},
        )

        meetings = data.get("transcripts", [])
        return [self._normalize_meeting(m) for m in meetings]

    def _normalize_transcript(self, data: dict) -> dict[str, Any]:
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

    def _normalize_meeting(self, meeting: dict) -> dict[str, Any]:
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
# Provider Factory
# =============================================================================


def _get_meeting_config() -> dict[str, Any]:
    """
    Get meeting provider configuration from execution context or environment.

    Returns:
        Meeting provider configuration dict

    Raises:
        IntegrationNotConfiguredError: If no meeting provider is configured
    """
    # 1. Try execution context (production, thread-safe)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("meeting")
        if config and config.get("provider"):
            logger.debug(
                "meeting_config_from_context",
                org_id=context.org_id,
                team_node_id=context.team_node_id,
                provider=config.get("provider"),
            )
            return config

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

        return config

    # 3. Not configured
    raise IntegrationNotConfiguredError(
        integration_id="meeting",
        tool_id="meeting_tools",
        missing_fields=["provider"],
        message="No meeting transcription provider configured. "
        "Please configure Fireflies, Circleback, Otter, or Vexa in team settings.",
    )


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
            raise IntegrationNotConfiguredError(
                "meeting",
                tool_id="meeting_tools",
                missing_fields=["fireflies_api_key"],
            )
        return FirefliesProvider(api_key)

    elif provider == "circleback":
        config_service_url = config.get("config_service_url")
        team_token = config.get("team_token")
        if not config_service_url or not team_token:
            raise IntegrationNotConfiguredError(
                "meeting",
                tool_id="meeting_tools",
                missing_fields=["config_service_url", "team_token"],
            )
        return CirclebackProvider(config_service_url, team_token)

    elif provider == "vexa":
        api_key = config.get("vexa_api_key")
        api_host = config.get("vexa_api_host", "http://localhost:8056")
        if not api_key:
            raise IntegrationNotConfiguredError(
                "meeting",
                tool_id="meeting_tools",
                missing_fields=["vexa_api_key"],
            )
        return VexaProvider(api_key, api_host)

    elif provider == "otter":
        api_key = config.get("otter_api_key")
        if not api_key:
            raise IntegrationNotConfiguredError(
                "meeting",
                tool_id="meeting_tools",
                missing_fields=["otter_api_key"],
            )
        return OtterProvider(api_key)

    else:
        raise IntegrationNotConfiguredError(
            "meeting",
            tool_id="meeting_tools",
            message=f"Unknown meeting provider: {provider}. "
            "Supported providers: fireflies, circleback, vexa, otter",
        )


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

    raise ToolExecutionError(
        "meeting_tools",
        f"Could not parse meeting URL: {url}. "
        "Supported formats: Google Meet, Microsoft Teams, Zoom",
    )


# =============================================================================
# Agent Tools
# =============================================================================


def meeting_get_transcript(meeting_id: str) -> dict[str, Any]:
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
        return handle_integration_not_configured(e, "meeting_get_transcript", "meeting")
    except IntegrationAuthenticationError:
        raise
    except Exception as e:
        logger.error("meeting_transcript_failed", meeting_id=meeting_id, error=str(e))
        raise ToolExecutionError("meeting_get_transcript", str(e), e)


def meeting_search(
    query: str,
    hours_back: int = 24,
) -> list[dict[str, Any]]:
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
        return handle_integration_not_configured(e, "meeting_search", "meeting")
    except IntegrationAuthenticationError:
        raise
    except Exception as e:
        logger.error("meeting_search_failed", query=query, error=str(e))
        raise ToolExecutionError("meeting_search", str(e), e)


def meeting_get_recent(hours: int = 24) -> list[dict[str, Any]]:
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
        return handle_integration_not_configured(e, "meeting_get_recent", "meeting")
    except IntegrationAuthenticationError:
        raise
    except Exception as e:
        logger.error("meeting_recent_failed", hours=hours, error=str(e))
        raise ToolExecutionError("meeting_get_recent", str(e), e)


def meeting_search_transcript(
    meeting_id: str,
    query: str,
) -> list[dict[str, Any]]:
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
        return handle_integration_not_configured(
            e, "meeting_search_transcript", "meeting"
        )
    except IntegrationAuthenticationError:
        raise
    except Exception as e:
        logger.error(
            "meeting_transcript_search_failed",
            meeting_id=meeting_id,
            query=query,
            error=str(e),
        )
        raise ToolExecutionError("meeting_search_transcript", str(e), e)


def meeting_join(meeting_url: str) -> dict[str, Any]:
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
            raise ToolExecutionError(
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
        return handle_integration_not_configured(e, "meeting_join", "meeting")
    except IntegrationAuthenticationError:
        raise
    except Exception as e:
        logger.error("meeting_join_failed", url=meeting_url, error=str(e))
        raise ToolExecutionError("meeting_join", str(e), e)


# =============================================================================
# Tool Exports
# =============================================================================

MEETING_TOOLS = [
    meeting_get_transcript,
    meeting_search,
    meeting_get_recent,
    meeting_search_transcript,
    meeting_join,
]

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any, Dict, List, Optional

import httpx


def _extract_token(authorization: str, x_admin_token: str) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    if x_admin_token:
        return x_admin_token.strip()
    return ""


class ConfigServiceClient:
    def __init__(
        self, *, base_url: str, http_client: Optional[httpx.Client] = None
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._http = http_client

    def _headers(self, raw_token: str) -> Dict[str, str]:
        return {"Authorization": f"Bearer {raw_token}"}

    def auth_me_admin(self, raw_token: str) -> dict[str, Any]:
        url = f"{self.base_url}/api/v1/auth/me"
        if self._http is not None:
            r = self._http.get(url, headers=self._headers(raw_token))
        else:
            with httpx.Client(timeout=10.0) as c:
                r = c.get(url, headers=self._headers(raw_token))
        r.raise_for_status()
        data = r.json()
        if data.get("role") != "admin":
            raise PermissionError("admin role required")
        return data

    def issue_team_token(self, raw_token: str, org_id: str, team_node_id: str) -> str:
        url = f"{self.base_url}/api/v1/admin/orgs/{org_id}/teams/{team_node_id}/tokens"
        if self._http is not None:
            r = self._http.post(url, headers=self._headers(raw_token))
        else:
            with httpx.Client(timeout=10.0) as c:
                r = c.post(url, headers=self._headers(raw_token))
        r.raise_for_status()
        return str(r.json()["token"])

    def list_team_tokens(
        self, raw_token: str, org_id: str, team_node_id: str
    ) -> list[dict[str, Any]]:
        url = f"{self.base_url}/api/v1/admin/orgs/{org_id}/teams/{team_node_id}/tokens"
        if self._http is not None:
            r = self._http.get(url, headers=self._headers(raw_token))
        else:
            with httpx.Client(timeout=10.0) as c:
                r = c.get(url, headers=self._headers(raw_token))
        r.raise_for_status()
        data = r.json()
        # Expected: list[{token_id, issued_at, revoked_at, issued_by}]
        if isinstance(data, list):
            return list(data)
        return []

    def issue_team_impersonation_token(
        self, raw_token: str, org_id: str, team_node_id: str
    ) -> dict[str, Any]:
        url = f"{self.base_url}/api/v1/admin/orgs/{org_id}/teams/{team_node_id}/impersonation-token"
        if self._http is not None:
            r = self._http.post(url, headers=self._headers(raw_token))
        else:
            with httpx.Client(timeout=10.0) as c:
                r = c.post(url, headers=self._headers(raw_token))
        r.raise_for_status()
        return dict(r.json())

    def patch_node_config(
        self, raw_token: str, org_id: str, node_id: str, patch: dict[str, Any]
    ) -> dict[str, Any]:
        url = f"{self.base_url}/api/v1/admin/orgs/{org_id}/nodes/{node_id}/config"
        if self._http is not None:
            r = self._http.put(
                url, headers=self._headers(raw_token), json={"patch": patch}
            )
        else:
            with httpx.Client(timeout=10.0) as c:
                r = c.put(url, headers=self._headers(raw_token), json={"patch": patch})
        r.raise_for_status()
        return dict(r.json())

    def lookup_routing(
        self,
        *,
        internal_service_name: str,
        identifiers: Dict[str, str],
        org_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Look up team routing via Config Service internal API.

        Returns: {found, org_id, team_node_id, matched_by, matched_value, tried}
        """
        url = f"{self.base_url}/api/v1/internal/routing/lookup"
        headers = {"X-Internal-Service": internal_service_name}
        payload: Dict[str, Any] = {"identifiers": identifiers}
        if org_id:
            payload["org_id"] = org_id
        if self._http is not None:
            r = self._http.post(url, headers=headers, json=payload)
        else:
            with httpx.Client(timeout=10.0) as c:
                r = c.post(url, headers=headers, json=payload)
        r.raise_for_status()
        return dict(r.json())

    def get_effective_config(
        self,
        *,
        team_token: str,
    ) -> Dict[str, Any]:
        """
        Get effective configuration for a team.

        Returns: Full merged effective config
        """
        url = f"{self.base_url}/api/v1/config/me"
        headers = {"Authorization": f"Bearer {team_token}"}
        if self._http is not None:
            r = self._http.get(url, headers=headers)
        else:
            with httpx.Client(timeout=10.0) as c:
                r = c.get(url, headers=headers)
        r.raise_for_status()
        data = r.json()
        # v2 API returns {effective_config: {...}, ...}, extract the config
        return (
            data.get("effective_config", data) if "effective_config" in data else data
        )

    def get_effective_config_for_node(
        self,
        raw_token: str,
        org_id: str,
        node_id: str,
    ) -> Dict[str, Any]:
        """
        Get effective configuration for a node using admin credentials.

        This uses the admin API to fetch the effective (merged) config for any node.

        Returns: Full merged effective config
        """
        url = f"{self.base_url}/api/v1/config/orgs/{org_id}/nodes/{node_id}/effective"
        if self._http is not None:
            r = self._http.get(url, headers=self._headers(raw_token))
        else:
            with httpx.Client(timeout=10.0) as c:
                r = c.get(url, headers=self._headers(raw_token))
        r.raise_for_status()
        data = r.json()
        # Extract effective_config from response
        return (
            data.get("effective_config", data) if "effective_config" in data else data
        )

    def store_meeting_data(
        self,
        *,
        admin_token: str,
        org_id: str,
        team_node_id: str,
        meeting_id: str,
        meeting_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Store meeting data from a webhook (e.g., Circleback).

        This stores meeting transcripts and metadata for later querying by agents.

        Args:
            admin_token: Admin token for authentication
            org_id: Organization ID
            team_node_id: Team node ID
            meeting_id: Unique meeting identifier
            meeting_data: Meeting data including transcript, attendees, etc.

        Returns: Stored meeting data confirmation
        """
        url = f"{self.base_url}/api/v1/internal/meetings"
        headers = {
            "Authorization": f"Bearer {admin_token}",
            "X-Internal-Service": "orchestrator",
        }
        payload = {
            "org_id": org_id,
            "team_node_id": team_node_id,
            "meeting_id": meeting_id,
            **meeting_data,
        }
        if self._http is not None:
            r = self._http.post(url, headers=headers, json=payload)
        else:
            with httpx.Client(timeout=30.0) as c:
                r = c.post(url, headers=headers, json=payload)
        r.raise_for_status()
        return dict(r.json())


class PipelineApiClient:
    def __init__(
        self, *, base_url: str, http_client: Optional[httpx.Client] = None
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._http = http_client

    def _headers(self, raw_token: str) -> Dict[str, str]:
        return {"Authorization": f"Bearer {raw_token}"}

    def bootstrap(self, raw_token: str, team_id: str) -> dict[str, Any]:
        url = f"{self.base_url}/api/v1/teams/{team_id}/bootstrap"
        if self._http is not None:
            r = self._http.post(url, headers=self._headers(raw_token))
        else:
            with httpx.Client(timeout=10.0) as c:
                r = c.post(url, headers=self._headers(raw_token))
        r.raise_for_status()
        return dict(r.json())

    def trigger_run(
        self, raw_token: str, *, team_id: str, org_id: str
    ) -> dict[str, Any]:
        """
        Manually trigger an AI Pipeline run for a team.

        This creates a one-off K8s Job that runs immediately.
        """
        url = f"{self.base_url}/api/v1/teams/{team_id}/run"
        payload = {"org_id": org_id, "team_id": team_id}
        if self._http is not None:
            r = self._http.post(url, headers=self._headers(raw_token), json=payload)
        else:
            with httpx.Client(timeout=30.0) as c:
                r = c.post(url, headers=self._headers(raw_token), json=payload)
        r.raise_for_status()
        return dict(r.json())


class AgentApiClient:
    def __init__(
        self, *, base_url: str, http_client: Optional[httpx.Client] = None
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._http = http_client

    def run_agent(
        self,
        *,
        team_token: str,
        agent_name: str,
        message: str,
        context: Optional[dict[str, Any]] = None,
        timeout: Optional[int] = None,
        max_turns: Optional[int] = None,
        correlation_id: Optional[str] = None,
        agent_base_url: Optional[str] = None,  # Override for dedicated deployments
        output_destinations: Optional[
            list[dict[str, Any]]
        ] = None,  # Multi-destination output
        slack_context: Optional[
            dict[str, Any]
        ] = None,  # DEPRECATED: use output_destinations
        trigger_source: Optional[str] = None,  # Source that triggered this run
    ) -> dict[str, Any]:
        base = agent_base_url.rstrip("/") if agent_base_url else self.base_url
        url = f"{base}/agents/{agent_name}/run"
        headers = {"X-IncidentFox-Team-Token": team_token}
        if correlation_id:
            headers["X-Correlation-ID"] = correlation_id
        payload: dict[str, Any] = {"message": message}
        if context is not None:
            payload["context"] = context
        if timeout is not None:
            payload["timeout"] = timeout
        if max_turns is not None:
            payload["max_turns"] = max_turns
        if output_destinations is not None:
            payload["output_destinations"] = output_destinations
        elif slack_context is not None:
            # DEPRECATED: backwards compatibility
            payload["slack_context"] = slack_context
        if trigger_source is not None:
            payload["trigger_source"] = trigger_source
        if self._http is not None:
            r = self._http.post(url, headers=headers, json=payload)
        else:
            # HTTP timeout should be >= agent timeout. Add a small buffer for network overhead.
            request_timeout = 30.0
            try:
                if timeout is not None:
                    request_timeout = max(30.0, float(timeout) + 10.0)
            except Exception:
                request_timeout = 30.0
            with httpx.Client(timeout=request_timeout) as c:
                r = c.post(url, headers=headers, json=payload)
        r.raise_for_status()
        return dict(r.json())


class AuditApiClient:
    """Client for recording audit events to config service."""

    def __init__(
        self,
        *,
        base_url: str,
        internal_token: str,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.internal_token = internal_token
        self._http = http_client

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.internal_token}"}

    def create_agent_run(
        self,
        *,
        run_id: str,
        org_id: str,
        team_node_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        trigger_source: str,
        trigger_actor: Optional[str] = None,
        trigger_message: Optional[str] = None,
        trigger_channel_id: Optional[str] = None,
        agent_name: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Record agent run start."""
        url = f"{self.base_url}/api/v1/admin/orgs/{org_id}/unified-audit/agent-runs"
        payload = {
            "run_id": run_id,
            "org_id": org_id,
            "team_node_id": team_node_id,
            "correlation_id": correlation_id,
            "trigger_source": trigger_source,
            "trigger_actor": trigger_actor,
            "trigger_message": trigger_message,
            "trigger_channel_id": trigger_channel_id,
            "agent_name": agent_name,
            "metadata": metadata or {},
        }
        try:
            if self._http is not None:
                r = self._http.post(url, headers=self._headers(), json=payload)
            else:
                with httpx.Client(timeout=10.0) as c:
                    r = c.post(url, headers=self._headers(), json=payload)
            r.raise_for_status()
            return dict(r.json())
        except Exception:
            return None  # Don't fail agent runs if audit fails

    def complete_agent_run(
        self,
        *,
        org_id: str,
        run_id: str,
        status: str,
        tool_calls_count: Optional[int] = None,
        output_summary: Optional[str] = None,
        output_json: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        confidence: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """Record agent run completion."""
        url = f"{self.base_url}/api/v1/admin/orgs/{org_id}/unified-audit/agent-runs/{run_id}"
        payload = {
            "run_id": run_id,
            "status": status,
            "tool_calls_count": tool_calls_count,
            "output_summary": output_summary,
            "output_json": output_json,
            "error_message": error_message,
            "confidence": confidence,
        }
        try:
            if self._http is not None:
                r = self._http.patch(url, headers=self._headers(), json=payload)
            else:
                with httpx.Client(timeout=10.0) as c:
                    r = c.patch(url, headers=self._headers(), json=payload)
            r.raise_for_status()
            return dict(r.json())
        except Exception:
            return None  # Don't fail agent runs if audit fails

    def record_feedback(
        self,
        *,
        run_id: str,
        correlation_id: Optional[str] = None,
        feedback: str,
        user_id: Optional[str] = None,
        source: str = "unknown",
    ) -> Optional[Dict[str, Any]]:
        """
        Record user feedback on an agent run.

        Args:
            run_id: The agent run ID this feedback is for
            correlation_id: Optional correlation ID for tracing
            feedback: The feedback type (e.g., "positive", "negative")
            user_id: The user who provided feedback
            source: Where the feedback came from (e.g., "slack", "web")

        Returns:
            The created feedback record, or None if recording failed
        """
        # Use internal audit endpoint for feedback
        url = f"{self.base_url}/api/v1/internal/feedback"
        payload = {
            "run_id": run_id,
            "correlation_id": correlation_id,
            "feedback": feedback,
            "user_id": user_id,
            "source": source,
        }
        try:
            if self._http is not None:
                r = self._http.post(url, headers=self._headers(), json=payload)
            else:
                with httpx.Client(timeout=10.0) as c:
                    r = c.post(url, headers=self._headers(), json=payload)
            r.raise_for_status()
            return dict(r.json())
        except Exception:
            return None  # Don't fail if feedback recording fails


class TelemetryCollectorClient:
    """Client for telemetry collector sidecar (license queries)."""

    def __init__(
        self, *, base_url: str, http_client: Optional[httpx.Client] = None
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._http = http_client

    def get_license(self) -> Dict[str, Any]:
        """
        Get license information from telemetry collector.

        Returns: {
            valid: bool,
            customer_name: str,
            entitlements: {max_teams, max_runs_per_month, features},
            expires_at: str,
            warnings: list[str],
            cached: bool
        }
        """
        url = f"{self.base_url}/internal/license"
        if self._http is not None:
            r = self._http.get(url)
        else:
            with httpx.Client(timeout=10.0) as c:
                r = c.get(url)
        r.raise_for_status()
        return dict(r.json())

    def refresh_license(self) -> Dict[str, Any]:
        """
        Force refresh license cache in telemetry collector.

        Returns: {ok: bool, license: {...}, error: str}
        """
        url = f"{self.base_url}/internal/license/refresh"
        if self._http is not None:
            r = self._http.post(url)
        else:
            with httpx.Client(timeout=10.0) as c:
                r = c.post(url)
        r.raise_for_status()
        return dict(r.json())


class CorrelationServiceClient:
    """Client for alert correlation service.

    Correlates alerts using temporal, topology, and semantic analysis
    to identify related incidents and potential root causes.
    """

    def __init__(
        self, *, base_url: str, http_client: Optional[httpx.Client] = None
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._http = http_client

    def correlate_alerts(
        self,
        *,
        alerts: List[Dict[str, Any]],
        team_id: str,
        temporal_window_seconds: int = 300,
        semantic_threshold: float = 0.75,
    ) -> Dict[str, Any]:
        """
        Correlate a list of alerts into incidents.

        Args:
            alerts: List of alert objects to correlate
            team_id: Team identifier for topology correlation
            temporal_window_seconds: Time window for temporal correlation
            semantic_threshold: Similarity threshold for semantic correlation

        Returns: {
            incidents: List of correlated incidents,
            correlation_metadata: {
                total_alerts: int,
                incidents_created: int,
                correlation_sources: list[str]
            }
        }
        """
        url = f"{self.base_url}/api/v1/correlate"
        payload = {
            "alerts": alerts,
            "team_id": team_id,
            "config": {
                "temporal_window_seconds": temporal_window_seconds,
                "semantic_threshold": semantic_threshold,
            },
        }
        if self._http is not None:
            r = self._http.post(url, json=payload)
        else:
            with httpx.Client(timeout=30.0) as c:
                r = c.post(url, json=payload)
        r.raise_for_status()
        return dict(r.json())

    def find_correlated_alerts(
        self,
        *,
        alert: Dict[str, Any],
        team_id: str,
        lookback_minutes: int = 30,
    ) -> Dict[str, Any]:
        """
        Find alerts correlated to a single incoming alert.

        Used when processing a new alert to find existing related alerts.

        Args:
            alert: The incoming alert to find correlations for
            team_id: Team identifier for topology correlation
            lookback_minutes: How far back to look for correlated alerts

        Returns: {
            correlated_alerts: List of related alerts,
            correlation_signals: List of correlation signals (temporal, topology, semantic),
            incident_id: Optional existing incident ID if alert belongs to one
        }
        """
        url = f"{self.base_url}/api/v1/correlate/find"
        payload = {
            "alert": alert,
            "team_id": team_id,
            "lookback_minutes": lookback_minutes,
        }
        if self._http is not None:
            r = self._http.post(url, json=payload)
        else:
            with httpx.Client(timeout=15.0) as c:
                r = c.post(url, json=payload)
        r.raise_for_status()
        return dict(r.json())

    def health(self) -> Dict[str, Any]:
        """Check correlation service health."""
        url = f"{self.base_url}/health"
        if self._http is not None:
            r = self._http.get(url)
        else:
            with httpx.Client(timeout=5.0) as c:
                r = c.get(url)
        r.raise_for_status()
        return dict(r.json())

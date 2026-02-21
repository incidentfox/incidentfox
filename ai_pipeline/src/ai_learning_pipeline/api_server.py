"""
AI Pipeline API Server.

Exposes HTTP endpoints for triggering pipeline tasks on-demand,
including the onboarding scan triggered by the Slack bot.
"""

import asyncio
import json
import os
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(
    title="AI Learning Pipeline API",
    description="API for triggering AI pipeline tasks",
    version="1.0.0",
)


def _log(event: str, **fields) -> None:
    payload = {
        "timestamp": datetime.utcnow().isoformat(),
        "service": "ai-learning-pipeline",
        "module": "api_server",
        "event": event,
        **fields,
    }
    print(json.dumps(payload, default=str))


# ---------------------------------------------------------------------------
# Request/Response Models
# ---------------------------------------------------------------------------


class ScanTriggerRequest(BaseModel):
    """Request to trigger an onboarding scan."""

    org_id: str = Field(..., description="Organization ID (e.g., slack-T12345)")
    team_node_id: str = Field(
        default="default", description="Team node ID within the org"
    )
    trigger: str = Field(
        ...,
        description="Trigger type: 'initial', 'team_joined', 'team_created', or 'integration'",
    )
    slack_team_id: Optional[str] = Field(
        None, description="Slack team ID (for initial scan, to fetch bot token)"
    )
    integration_id: Optional[str] = Field(
        None, description="Integration ID (for integration trigger)"
    )
    channel_ids: Optional[List[str]] = Field(
        None,
        description="Slack channel IDs to scan (team-scoped). None = scan all channels.",
    )


class ScanTriggerResponse(BaseModel):
    """Response for scan trigger."""

    status: str
    scan_type: str
    message: str


# ---------------------------------------------------------------------------
# Background task runner
# ---------------------------------------------------------------------------


async def _run_initial_scan(
    org_id: str,
    team_node_id: str,
    slack_team_id: str,
    channel_ids: Optional[List[str]] = None,
):
    """Run initial onboarding scan in background."""
    from .tasks.onboarding_scan import OnboardingScanTask

    _log("background_initial_scan_started", org_id=org_id, slack_team_id=slack_team_id)

    try:
        # Fetch bot token from config service
        bot_token = await _get_bot_token(org_id, slack_team_id)
        if not bot_token:
            _log("bot_token_not_found", org_id=org_id)
            return

        task = OnboardingScanTask(
            org_id=org_id, team_node_id=team_node_id, channel_ids=channel_ids
        )
        result = await task.run_initial_scan(slack_bot_token=bot_token)

        # If recommendations were generated, notify via Slack DM
        recommendations = result.get("recommendations", [])
        if recommendations:
            await _notify_scan_results(
                org_id=org_id,
                slack_team_id=slack_team_id,
                recommendations=recommendations,
            )

        _log(
            "background_initial_scan_completed",
            org_id=org_id,
            recommendations=len(recommendations),
        )

    except Exception as e:
        _log("background_initial_scan_failed", org_id=org_id, error=str(e))


async def _run_integration_scan(org_id: str, team_node_id: str, integration_id: str):
    """Run integration-specific scan in background."""
    from .tasks.onboarding_scan import OnboardingScanTask

    _log(
        "background_integration_scan_started",
        org_id=org_id,
        integration_id=integration_id,
    )

    try:
        task = OnboardingScanTask(org_id=org_id, team_node_id=team_node_id)
        result = await task.run_integration_scan(integration_id=integration_id)

        _log(
            "background_integration_scan_completed",
            org_id=org_id,
            integration_id=integration_id,
            status=result.get("status"),
        )

    except Exception as e:
        _log(
            "background_integration_scan_failed",
            org_id=org_id,
            integration_id=integration_id,
            error=str(e),
        )


async def _get_bot_token(org_id: str, slack_team_id: str) -> Optional[str]:
    """Fetch bot token from config service's Slack installation data."""
    import httpx

    config_url = os.getenv("CONFIG_SERVICE_URL", "http://config-service:8080")
    internal_headers = {"X-Internal-Service": "ai_pipeline"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Look up installation by Slack team_id
            response = await client.get(
                f"{config_url}/api/v1/internal/slack/installations/find",
                params={"team_id": slack_team_id},
                headers=internal_headers,
            )
            if response.status_code == 200:
                data = response.json()
                if data:
                    token = data.get("bot_token")
                    if token:
                        _log(
                            "bot_token_found",
                            org_id=org_id,
                            slack_team_id=slack_team_id,
                        )
                        return token

            _log(
                "bot_token_installation_lookup_failed",
                org_id=org_id,
                slack_team_id=slack_team_id,
                status=response.status_code,
            )

    except Exception as e:
        _log("get_bot_token_failed", error=str(e))

    return None


async def _notify_scan_results(org_id: str, slack_team_id: str, recommendations: list):
    """Notify scan results — placeholder for Slack DM notification."""
    # This will be handled by the slackbot polling pending changes
    # or via a callback. For now, just log.
    _log(
        "scan_results_ready",
        org_id=org_id,
        recommendations_count=len(recommendations),
    )


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ai-learning-pipeline"}


@app.post("/api/v1/scan/trigger", response_model=ScanTriggerResponse)
async def trigger_scan(request: ScanTriggerRequest):
    """
    Trigger an onboarding environment scan.

    Called by the Slack bot after:
    - OAuth installation (trigger=initial)
    - Integration configuration save (trigger=integration)

    Uses asyncio.create_task() instead of BackgroundTasks to fully decouple
    scans from the ASGI connection lifecycle, preventing GIL contention from
    long-running scans from starving health check responses.
    """
    if request.trigger in ("initial", "team_joined", "team_created"):
        if not request.slack_team_id:
            return ScanTriggerResponse(
                status="error",
                scan_type=request.trigger,
                message="slack_team_id is required for initial/team scan",
            )

        asyncio.create_task(
            _run_initial_scan(
                org_id=request.org_id,
                team_node_id=request.team_node_id,
                slack_team_id=request.slack_team_id,
                channel_ids=request.channel_ids,
            )
        )

        _log(
            "scan_triggered",
            trigger=request.trigger,
            org_id=request.org_id,
            team_node_id=request.team_node_id,
        )

        return ScanTriggerResponse(
            status="scheduled",
            scan_type=request.trigger,
            message=f"{request.trigger} environment scan scheduled",
        )

    elif request.trigger == "integration":
        if not request.integration_id:
            return ScanTriggerResponse(
                status="error",
                scan_type="integration",
                message="integration_id is required for integration scan",
            )

        asyncio.create_task(
            _run_integration_scan(
                org_id=request.org_id,
                team_node_id=request.team_node_id,
                integration_id=request.integration_id,
            )
        )

        _log(
            "scan_triggered",
            trigger="integration",
            org_id=request.org_id,
            integration_id=request.integration_id,
        )

        return ScanTriggerResponse(
            status="scheduled",
            scan_type="integration",
            message=f"Integration scan for {request.integration_id} scheduled",
        )

    else:
        return ScanTriggerResponse(
            status="error",
            scan_type=request.trigger,
            message=f"Unknown trigger type: {request.trigger}",
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_server():
    """Run the API server."""
    import uvicorn

    port = int(os.getenv("PIPELINE_API_PORT", "8085"))
    _log("server_starting", port=port)
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    run_server()

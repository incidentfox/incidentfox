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
        # Fetch installation data (bot token + installer user_id)
        installation = await _get_slack_installation(org_id, slack_team_id)
        if not installation:
            _log("bot_token_not_found", org_id=org_id)
            return

        bot_token = installation["bot_token"]
        installer_user_id = installation.get("user_id")

        task = OnboardingScanTask(
            org_id=org_id, team_node_id=team_node_id, channel_ids=channel_ids
        )
        result = await task.run_initial_scan(slack_bot_token=bot_token)

        # Notify the installer via Slack DM with scan results
        recommendations = result.get("recommendations", [])
        rag_result = result.get("rag_ingestion", {})
        knowledge_items = (
            rag_result.get("items_extracted", 0) if isinstance(rag_result, dict) else 0
        )
        channels_scanned = result.get("channels_scanned", 0)

        await _notify_scan_results(
            bot_token=bot_token,
            user_id=installer_user_id,
            org_id=org_id,
            recommendations=recommendations,
            knowledge_items=knowledge_items,
            channels_scanned=channels_scanned,
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


async def _get_slack_installation(org_id: str, slack_team_id: str) -> Optional[dict]:
    """Fetch Slack installation data from config service.

    Returns the full installation dict (bot_token, user_id, etc.)
    or None if not found.
    """
    import httpx

    config_url = os.getenv("CONFIG_SERVICE_URL", "http://config-service:8080")
    internal_headers = {"X-Internal-Service": "ai_pipeline"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{config_url}/api/v1/internal/slack/installations/find",
                params={"team_id": slack_team_id},
                headers=internal_headers,
            )
            if response.status_code == 200:
                data = response.json()
                if data and data.get("bot_token"):
                    _log(
                        "bot_token_found",
                        org_id=org_id,
                        slack_team_id=slack_team_id,
                    )
                    return data

            _log(
                "bot_token_installation_lookup_failed",
                org_id=org_id,
                slack_team_id=slack_team_id,
                status=response.status_code,
            )

    except Exception as e:
        _log("get_bot_token_failed", error=str(e))

    return None


async def _notify_scan_results(
    bot_token: str,
    user_id: Optional[str],
    org_id: str,
    recommendations: list,
    knowledge_items: int = 0,
    channels_scanned: int = 0,
):
    """Send a Slack DM to the installer with scan results summary."""
    import httpx

    if not user_id:
        _log("scan_notification_skipped", reason="no_user_id", org_id=org_id)
        return

    # Build a concise summary message
    parts = [":white_check_mark: *Environment scan complete*\n"]

    if channels_scanned:
        parts.append(f"Scanned *{channels_scanned}* channels.")

    if knowledge_items:
        parts.append(
            f"Extracted *{knowledge_items}* knowledge items into your team's knowledge base."
        )

    if recommendations:
        names = [
            r.get("integration_name", r.get("integration_id", "?"))
            for r in recommendations
        ]
        parts.append(
            f"\n:bulb: Found *{len(recommendations)}* integration recommendation(s): "
            + ", ".join(f"*{n}*" for n in names)
            + ".\nReview them in *Pending Changes* on the web dashboard."
        )

    if not recommendations and not knowledge_items:
        parts.append("No new recommendations or knowledge items found this time.")

    text = "\n".join(parts)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Open a DM conversation with the installer
            dm_resp = await client.post(
                "https://slack.com/api/conversations.open",
                headers={"Authorization": f"Bearer {bot_token}"},
                json={"users": user_id},
            )
            dm_data = dm_resp.json()
            if not dm_data.get("ok"):
                _log(
                    "scan_notification_dm_open_failed",
                    error=dm_data.get("error"),
                    user_id=user_id,
                )
                return

            channel_id = dm_data["channel"]["id"]

            # Post the message
            msg_resp = await client.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {bot_token}"},
                json={
                    "channel": channel_id,
                    "text": text,
                    "unfurl_links": False,
                },
            )
            msg_data = msg_resp.json()
            if msg_data.get("ok"):
                _log("scan_notification_sent", user_id=user_id, org_id=org_id)
            else:
                _log(
                    "scan_notification_send_failed",
                    error=msg_data.get("error"),
                    user_id=user_id,
                )

    except Exception as e:
        _log("scan_notification_error", error=str(e), org_id=org_id)


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

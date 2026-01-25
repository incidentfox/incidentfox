#!/usr/bin/env python3
"""
Realistic test that mimics the production webhook pattern.

Tests if passing Request object to background tasks causes issues.

Run with:
    source /tmp/playground_venv/bin/activate
    python tests/background_task_realistic.py
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Optional

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def _log(event: str, **fields: Any) -> None:
    """Structured logging like production."""
    try:
        payload = {"service": "test", "event": event, **fields}
        print(json.dumps(payload, default=str))
    except Exception:
        print(f"{event} {fields}")


app = FastAPI()


# Simulate app.state like production
class ConfigServiceClient:
    def lookup_routing(self, **kwargs):
        return {"found": True, "org_id": "test-org", "team_node_id": "test-team"}


class AgentApiClient:
    def run_agent(self, **kwargs):
        time.sleep(1)  # Simulate agent run
        return {"success": True}


@app.on_event("startup")
async def startup():
    app.state.config_service = ConfigServiceClient()
    app.state.agent_api = AgentApiClient()
    logger.info("App state configured")


# =============================================================================
# This mimics the production _process_incidentio_webhook function
# =============================================================================
async def _process_webhook_with_request(
    request: Request,
    alert_data: dict,
    event_type: str,
    alert_source_id: str,
) -> None:
    """Process webhook asynchronously - USES REQUEST OBJECT."""
    # First line - should always appear if task runs
    _log(
        "webhook_task_started",
        alert_source_id=alert_source_id,
        event_type=event_type,
    )

    try:
        # Access app.state via request (like production)
        cfg = request.app.state.config_service
        agent_api = request.app.state.agent_api

        # Lookup routing (like production)
        routing = cfg.lookup_routing(
            internal_service_name="orchestrator",
            identifiers={"incidentio_alert_source_id": alert_source_id},
        )

        _log("webhook_routing_found", routing=routing)

        if not routing.get("found"):
            _log("webhook_no_routing")
            return

        # Simulate agent run
        _log("webhook_calling_agent")
        result = agent_api.run_agent(message="test")
        _log("webhook_agent_completed", result=result)

        _log("webhook_task_completed")

    except Exception as e:
        _log("webhook_task_failed", error=str(e))


# =============================================================================
# Alternative: Pass app directly instead of request
# =============================================================================
async def _process_webhook_with_app(
    app_instance: FastAPI,
    alert_data: dict,
    event_type: str,
    alert_source_id: str,
) -> None:
    """Process webhook asynchronously - USES APP DIRECTLY."""
    _log(
        "webhook_task_started_v2",
        alert_source_id=alert_source_id,
        event_type=event_type,
    )

    try:
        cfg = app_instance.state.config_service
        agent_api = app_instance.state.agent_api

        routing = cfg.lookup_routing(
            internal_service_name="orchestrator",
            identifiers={"incidentio_alert_source_id": alert_source_id},
        )

        _log("webhook_routing_found_v2", routing=routing)

        if not routing.get("found"):
            return

        _log("webhook_calling_agent_v2")
        result = agent_api.run_agent(message="test")
        _log("webhook_agent_completed_v2", result=result)

        _log("webhook_task_completed_v2")

    except Exception as e:
        _log("webhook_task_failed_v2", error=str(e))


# =============================================================================
# Webhook Endpoint (mimics production pattern)
# =============================================================================
@app.post("/webhook-request")
async def webhook_with_request(request: Request, background: BackgroundTasks):
    """Uses Request object in background task (production pattern)."""
    alert_data = {"title": "Test Alert"}
    alert_source_id = "test-alert-source"
    event_type = "public_alert.alert_created_v1"

    _log("webhook_adding_task_request_pattern", alert_source_id=alert_source_id)

    background.add_task(
        _process_webhook_with_request,
        request=request,
        alert_data=alert_data,
        event_type=event_type,
        alert_source_id=alert_source_id,
    )

    _log("webhook_task_added_request_pattern", tasks_count=len(background.tasks))

    return JSONResponse(content={"ok": True, "pattern": "request"})


@app.post("/webhook-app")
async def webhook_with_app(request: Request, background: BackgroundTasks):
    """Uses app directly in background task (alternative pattern)."""
    alert_data = {"title": "Test Alert"}
    alert_source_id = "test-alert-source"
    event_type = "public_alert.alert_created_v1"

    _log("webhook_adding_task_app_pattern", alert_source_id=alert_source_id)

    background.add_task(
        _process_webhook_with_app,
        app_instance=request.app,
        alert_data=alert_data,
        event_type=event_type,
        alert_source_id=alert_source_id,
    )

    _log("webhook_task_added_app_pattern", tasks_count=len(background.tasks))

    return JSONResponse(content={"ok": True, "pattern": "app"})


@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("TESTING BACKGROUND TASKS WITH REQUEST VS APP PATTERN")
    logger.info("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8091, log_level="info")

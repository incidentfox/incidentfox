from __future__ import annotations

import json
from typing import Any, Callable, Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field


def make_stub_pipeline_app() -> FastAPI:
    app = FastAPI(title="Stub AI Pipeline API", version="0.0.0")

    @app.post("/api/v1/teams/{team_id}/bootstrap")
    def bootstrap(team_id: str, authorization: str = Header(default="")):
        # Minimal shape compatible with orchestrator PipelineApiClient.
        if not authorization:
            raise HTTPException(status_code=401, detail="missing_auth")
        return {"run_id": f"bootstrap:{team_id}", "status": "queued"}

    return app


class InvestigateReq(BaseModel):
    prompt: str = Field(min_length=1)
    thread_id: Optional[str] = None
    tenant_id: Optional[str] = None
    team_id: Optional[str] = None
    team_token: Optional[str] = None


def make_stub_agent_app(
    *, get_effective_config: Callable[[str], dict[str, Any]]
) -> FastAPI:
    """
    Minimal agent runtime stub serving /investigate (SSE streaming).
    """

    app = FastAPI(title="Stub Agent", version="0.0.0")

    @app.post("/investigate")
    def investigate(body: InvestigateReq):
        if not body.team_token:
            raise HTTPException(status_code=401, detail="missing_team_token")
        try:
            cfg = get_effective_config(body.team_token)
        except Exception as e:
            raise HTTPException(
                status_code=502, detail=f"config_service_error:{e}"
            ) from e

        thread_id = body.thread_id or "test-thread"

        def stream():
            # Emit a result event matching the SSE protocol
            event = {
                "type": "result",
                "data": {
                    "text": f"echo: {body.prompt}",
                    "success": True,
                },
                "thread_id": thread_id,
            }
            yield f"data: {json.dumps(event)}\n\n"

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"X-Thread-ID": thread_id},
        )

    return app

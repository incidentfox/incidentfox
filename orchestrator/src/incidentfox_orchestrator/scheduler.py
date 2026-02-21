"""Scheduled jobs executor.

Polls config-service for due jobs and executes them via the agent API.
Started as a background asyncio task in the orchestrator's FastAPI lifespan.
"""

import asyncio
import json
import os
import traceback
import uuid

import httpx

# How often to poll for due jobs (seconds)
POLL_INTERVAL = int(os.getenv("SCHEDULER_POLL_INTERVAL", "30"))

# Service identifier for claim tracking
SERVICE_ID = f"orchestrator-{uuid.uuid4().hex[:8]}"


def _log(event: str, **fields) -> None:
    """Structured JSON logging matching orchestrator convention."""
    try:
        payload = {"service": "scheduler", "event": event, **fields}
        print(json.dumps(payload, default=str))
    except Exception:
        print(f"{event} {fields}")


async def scheduler_loop(app) -> None:
    """Main scheduler loop. Polls for due jobs and dispatches them."""
    _log("scheduler_started", poll_interval=POLL_INTERVAL, service_id=SERVICE_ID)

    # Wait a bit on startup to let other services initialize
    await asyncio.sleep(5)

    while True:
        try:
            due_jobs = await _fetch_due_jobs(app)
            if due_jobs:
                _log("scheduler_found_due_jobs", count=len(due_jobs))
                for job in due_jobs:
                    # Fire and forget — each job runs independently
                    asyncio.create_task(_execute_job(app, job))
        except asyncio.CancelledError:
            _log("scheduler_cancelled")
            return
        except Exception:
            _log("scheduler_poll_error", error=traceback.format_exc())

        await asyncio.sleep(POLL_INTERVAL)


async def _fetch_due_jobs(app) -> list[dict]:
    """Poll config-service for jobs that are due for execution."""
    config_service = app.state.config_service
    base_url = config_service.base_url.rstrip("/")
    url = f"{base_url}/api/v1/internal/scheduled-jobs/due"

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            url,
            params={"limit": 10},
            headers={"X-Internal-Service": SERVICE_ID},
        )
        if resp.status_code != 200:
            _log(
                "scheduler_fetch_failed",
                status=resp.status_code,
                body=resp.text[:200],
            )
            return []
        data = resp.json()
        return data.get("jobs", [])


async def _execute_job(app, job: dict) -> None:
    """Execute a single scheduled job."""
    job_id = job["id"]
    job_type = job["job_type"]
    org_id = job["org_id"]
    team_node_id = job["team_node_id"]
    job_name = job.get("name")

    _log(
        "scheduled_job_executing",
        job_id=job_id,
        job_type=job_type,
        org_id=org_id,
        team_node_id=team_node_id,
        job_name=job_name,
    )

    try:
        if job_type == "agent_run":
            result = await _execute_agent_run(app, job)
            status = "success" if result.get("success") else "error"
            error = (
                None if status == "success" else result.get("result", "Unknown error")
            )
        else:
            _log("scheduled_job_unknown_type", job_id=job_id, job_type=job_type)
            status = "error"
            error = f"Unknown job type: {job_type}"

        _log("scheduled_job_completed", job_id=job_id, status=status)

    except Exception as e:
        _log(
            "scheduled_job_failed",
            job_id=job_id,
            error=str(e),
            traceback=traceback.format_exc(),
        )
        status = "error"
        error = str(e)

    # Report completion to config-service
    await _report_completion(app, job_id, status, error)


async def _execute_agent_run(app, job: dict) -> dict:
    """Execute an agent_run job by calling sre-agent /investigate."""
    config = job.get("config", {})
    prompt = config.get("prompt", "")
    if not prompt:
        raise ValueError("Job config missing 'prompt'")

    agent_name = config.get("agent_name", "planner")
    max_turns = config.get("max_turns", 15)
    output_destinations = config.get("output_destinations", [])

    # Get team token from config-service for auth
    team_token = await _get_team_token(app, job["org_id"], job["team_node_id"])

    # run_agent is synchronous (httpx.Client) — run in thread
    agent_api = app.state.agent_api
    result = await asyncio.to_thread(
        agent_api.run_agent,
        team_token=team_token or "",
        agent_name=agent_name,
        message=prompt,
        output_destinations=output_destinations,
        trigger_source="scheduled",
        tenant_id=job["org_id"],
        team_id=job["team_node_id"],
        max_turns=max_turns,
        correlation_id=f"scheduled-{job['id']}",
    )

    # Deliver output to configured destinations (Slack, etc.)
    if result.get("success") and result.get("result"):
        await _deliver_output(app, output_destinations, result["result"], job)

    return result


async def _deliver_output(app, destinations: list[dict], text: str, job: dict) -> None:
    """Post agent result to output destinations (Slack channels, etc.)."""
    for dest in destinations:
        dest_type = dest.get("type", "")
        if dest_type == "slack":
            await _deliver_to_slack(app, dest, text, job)
        else:
            _log(
                "scheduler_output_unsupported_type",
                dest_type=dest_type,
                job_id=job["id"],
            )


async def _deliver_to_slack(app, dest: dict, text: str, job: dict) -> None:
    """Post result to a Slack channel."""
    channel_id = dest.get("channel_id")
    if not channel_id:
        _log("scheduler_slack_no_channel", job_id=job["id"])
        return

    # Resolve bot token with multiple fallback strategies
    bot_token = dest.get("bot_token", "")

    # 1. Try team config integrations.slack.bot_token
    if not bot_token:
        try:
            admin_token = os.getenv("ORCHESTRATOR_INTERNAL_ADMIN_TOKEN", "")
            if admin_token:
                config_service = app.state.config_service
                team_config = config_service.get_effective_config_for_node(
                    admin_token,
                    job["org_id"],
                    job["team_node_id"],
                )
                bot_token = (
                    team_config.get("integrations", {})
                    .get("slack", {})
                    .get("bot_token", "")
                )
        except Exception:
            pass

    # 2. Try Slack installation from config-service internal API
    if not bot_token:
        bot_token = await _get_slack_bot_token(app, dest.get("slack_team_id"))

    # 3. Fall back to env var (legacy single-tenant)
    if not bot_token:
        bot_token = os.getenv("SLACK_BOT_TOKEN", "")

    if not bot_token:
        _log(
            "scheduler_slack_no_token",
            job_id=job["id"],
            channel_id=channel_id,
        )
        return

    channel_name = dest.get("channel_name", channel_id)

    # Clean up agent output: strip narration before the report title.
    # The agent accumulates all assistant text blocks, so early "I'll check..."
    # narration gets prepended to the actual report. Strip it.
    cleaned = text
    title_marker = "*IncidentFox Automatic Status Report*"
    idx = cleaned.find(title_marker)
    if idx > 0:
        cleaned = cleaned[idx:]

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://slack.com/api/chat.postMessage",
                headers={
                    "Authorization": f"Bearer {bot_token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json={
                    "channel": channel_id,
                    "text": cleaned,
                    "unfurl_links": False,
                },
            )
            data = resp.json()
            if data.get("ok"):
                _log(
                    "scheduler_slack_posted",
                    job_id=job["id"],
                    channel=channel_name,
                )
            else:
                _log(
                    "scheduler_slack_error",
                    job_id=job["id"],
                    error=data.get("error", "unknown"),
                    channel=channel_name,
                )
    except Exception as e:
        _log(
            "scheduler_slack_failed",
            job_id=job["id"],
            error=str(e),
        )


async def _get_slack_bot_token(app, slack_team_id: str | None = None) -> str:
    """Fetch a Slack bot token from config-service's installation store."""
    config_service = app.state.config_service
    base_url = config_service.base_url.rstrip("/")
    url = f"{base_url}/api/v1/internal/slack/installations/find"

    # If no specific team_id, try to find any installation for the default app
    params: dict[str, str] = {"slack_app_slug": "incidentfox"}
    if slack_team_id:
        params["team_id"] = slack_team_id
    else:
        # Query the first available installation
        params["team_id"] = ""  # Will need to list instead

    try:
        # Try finding installation by team_id if available
        if slack_team_id:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    url,
                    params={"team_id": slack_team_id, "slack_app_slug": "incidentfox"},
                    headers={"X-Internal-Service": SERVICE_ID},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data and data.get("bot_token"):
                        return data["bot_token"]
    except Exception:
        pass
    return ""


async def _get_team_token(app, org_id: str, team_node_id: str) -> str | None:
    """Fetch team token from config-service internal API."""
    config_service = app.state.config_service
    base_url = config_service.base_url.rstrip("/")
    url = f"{base_url}/api/v1/internal/impersonate-team"

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            url,
            json={"org_id": org_id, "team_node_id": team_node_id},
            headers={"X-Internal-Service": SERVICE_ID},
        )
        if resp.status_code == 200:
            return resp.json().get("token")
        _log(
            "scheduler_token_fetch_failed",
            org_id=org_id,
            team_node_id=team_node_id,
            status=resp.status_code,
        )
        return None


async def _report_completion(app, job_id: str, status: str, error: str | None) -> None:
    """Report job completion to config-service."""
    config_service = app.state.config_service
    base_url = config_service.base_url.rstrip("/")
    url = f"{base_url}/api/v1/internal/scheduled-jobs/{job_id}/complete"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                json={"status": status, "error": error},
                headers={"X-Internal-Service": SERVICE_ID},
            )
            if resp.status_code != 200:
                _log(
                    "scheduler_completion_report_failed",
                    job_id=job_id,
                    status_code=resp.status_code,
                )
    except Exception:
        _log(
            "scheduler_completion_report_error",
            job_id=job_id,
            error=traceback.format_exc(),
        )

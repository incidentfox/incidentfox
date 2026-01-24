"""
Webhook router for IncidentFox Orchestrator.

Handles all external webhook endpoints:
- /webhooks/slack/events - Slack Events API (via Slack Bolt SDK)
- /webhooks/slack/interactions - Slack Interactivity & Actions (via Slack Bolt SDK)
- /webhooks/github - GitHub webhooks
- /webhooks/pagerduty - PagerDuty webhooks
- /webhooks/incidentio - Incident.io webhooks

Slack endpoints use Slack Bolt SDK for:
- Automatic signature verification
- URL verification challenge handling
- Event and interaction parsing

Other endpoints use manual signature verification.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any, Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from incidentfox_orchestrator.clients import CorrelationServiceClient
from incidentfox_orchestrator.context_enrichment import (
    build_enriched_message,
    fetch_github_pr_comments,
    format_github_pr_context,
)
from incidentfox_orchestrator.webhooks.signatures import (
    SignatureVerificationError,
    verify_circleback_signature,
    verify_github_signature,
    verify_incidentio_signature,
    verify_pagerduty_signature,
)

if TYPE_CHECKING:
    from incidentfox_orchestrator.webhooks.slack_bolt_app import SlackBoltIntegration


def _log(event: str, **fields: Any) -> None:
    """Structured logging."""
    try:
        payload = {"service": "orchestrator", "event": event, **fields}
        print(json.dumps(payload, default=str))
    except Exception:
        print(f"{event} {fields}")


router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# ============================================================================
# Slack Events API (via Slack Bolt SDK)
# ============================================================================


@router.post("/slack/events")
async def slack_events(request: Request):
    """
    Handle Slack Events API webhooks via Slack Bolt SDK.

    Bolt automatically handles:
    - Signature verification using SLACK_SIGNING_SECRET
    - URL verification challenges
    - Event parsing and routing to registered handlers

    The actual event processing is in slack_handlers.py.
    """
    bolt_integration: Optional[SlackBoltIntegration] = getattr(
        request.app.state, "slack_bolt", None
    )
    if bolt_integration is None:
        _log("slack_bolt_not_initialized")
        raise HTTPException(status_code=503, detail="Slack integration not initialized")

    return await bolt_integration.handler.handle(request)


# ============================================================================
# Slack Interactions (via Slack Bolt SDK)
# ============================================================================


@router.post("/slack/interactions")
async def slack_interactions(request: Request):
    """
    Handle Slack Interactivity & Shortcuts via Slack Bolt SDK.

    Bolt automatically handles:
    - Signature verification
    - Form-encoded payload parsing
    - Routing to registered action handlers (feedback buttons, etc.)

    The actual interaction handlers are in slack_handlers.py.
    """
    bolt_integration: Optional[SlackBoltIntegration] = getattr(
        request.app.state, "slack_bolt", None
    )
    if bolt_integration is None:
        _log("slack_bolt_not_initialized")
        raise HTTPException(status_code=503, detail="Slack integration not initialized")

    return await bolt_integration.handler.handle(request)


# ============================================================================
# GitHub Webhooks
# ============================================================================


@router.post("/github")
async def github_webhook(
    request: Request,
    background: BackgroundTasks,
    x_hub_signature_256: str = Header(default="", alias="X-Hub-Signature-256"),
    x_github_event: str = Header(default="", alias="X-GitHub-Event"),
    x_github_delivery: str = Header(default="", alias="X-GitHub-Delivery"),
):
    """
    Handle GitHub webhooks.

    Supports: push, pull_request, issues, issue_comment, etc.
    """
    webhook_secret = (os.getenv("GITHUB_WEBHOOK_SECRET") or "").strip()

    raw_body = (await request.body()).decode("utf-8")

    # Verify signature
    try:
        verify_github_signature(
            webhook_secret=webhook_secret,
            signature=x_hub_signature_256 or None,
            raw_body=raw_body,
        )
    except SignatureVerificationError as e:
        _log("github_webhook_signature_failed", reason=e.reason)
        raise HTTPException(
            status_code=401, detail=f"signature_verification_failed: {e.reason}"
        )

    # Parse payload
    try:
        payload = json.loads(raw_body) if raw_body else {}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid_json")

    _log(
        "github_webhook_received",
        github_event=x_github_event,
        delivery_id=x_github_delivery,
    )

    # Extract repository for routing
    repo = payload.get("repository", {})
    repo_full_name = repo.get("full_name", "")  # e.g., "org/repo"

    if repo_full_name:
        background.add_task(
            _process_github_webhook,
            request=request,
            event_type=x_github_event,
            delivery_id=x_github_delivery,
            repo_full_name=repo_full_name,
            payload=payload,
        )

    return JSONResponse(content={"ok": True})


async def _process_github_webhook(
    request: Request,
    event_type: str,
    delivery_id: str,
    repo_full_name: str,
    payload: dict,
) -> None:
    """Process GitHub webhook asynchronously."""
    from incidentfox_orchestrator.clients import (
        AgentApiClient,
        AuditApiClient,
        ConfigServiceClient,
    )

    correlation_id = delivery_id or __import__("uuid").uuid4().hex

    _log(
        "github_webhook_processing",
        correlation_id=correlation_id,
        event_type=event_type,
        repo=repo_full_name,
    )

    # Track whether agent run was created so we can mark it failed on exception
    agent_run_created = False
    run_id = None
    org_id = None
    audit_api = None

    try:
        cfg: ConfigServiceClient = request.app.state.config_service
        agent_api: AgentApiClient = request.app.state.agent_api
        audit_api: Optional[AuditApiClient] = getattr(
            request.app.state, "audit_api", None
        )

        # Look up team via routing
        routing = cfg.lookup_routing(
            internal_service_name="orchestrator",
            identifiers={"github_repo": repo_full_name},
        )

        if not routing.get("found"):
            _log(
                "github_webhook_no_routing",
                correlation_id=correlation_id,
                repo=repo_full_name,
            )
            return

        org_id = routing["org_id"]
        team_node_id = routing["team_node_id"]

        # Get impersonation token
        admin_token = (os.getenv("ORCHESTRATOR_INTERNAL_ADMIN_TOKEN") or "").strip()
        if not admin_token:
            return

        imp = cfg.issue_team_impersonation_token(
            admin_token, org_id=org_id, team_node_id=team_node_id
        )
        team_token = str(imp.get("token") or "")
        if not team_token:
            return

        # Get team config to determine entrance agent and dedicated URL
        entrance_agent_name = "planner"  # Default fallback
        dedicated_agent_url: Optional[str] = None
        try:
            effective_config = cfg.get_effective_config(team_token=team_token)
            entrance_agent_name = effective_config.get("entrance_agent", "planner")
            dedicated_agent_url = effective_config.get("agent", {}).get(
                "dedicated_service_url"
            )
        except Exception:
            pass  # Fall back to shared agent

        run_id = __import__("uuid").uuid4().hex

        # Construct message based on event type
        message = _build_github_message(event_type, payload)

        # Extract PR/issue number from payload
        pr_number = None
        issue_number = None
        if event_type == "pull_request":
            pr_number = payload.get("pull_request", {}).get("number")
        elif event_type in ("issues", "issue_comment"):
            issue_number = payload.get("issue", {}).get("number")
            # Check if this is a comment on a PR (GitHub issues API includes PRs)
            if issue_number and payload.get("issue", {}).get("pull_request"):
                pr_number = issue_number
                issue_number = None

        # Resolve output destinations
        from incidentfox_orchestrator.output_resolver import resolve_output_destinations

        trigger_payload = {
            "repo": repo_full_name,
            "pr_number": pr_number,
            "issue_number": issue_number,
            "event_type": event_type,
        }

        # Get team config for notification settings
        team_notifications_config = {}
        try:
            team_notifications_config = effective_config
        except Exception:
            pass

        output_destinations = resolve_output_destinations(
            trigger_source="github",
            trigger_payload=trigger_payload,
            team_config=team_notifications_config,
        )

        # Enrich message with PR comment context if this is a PR-related event
        enriched_message = message
        if pr_number:
            try:
                # Get GitHub token from team config
                github_config = effective_config.get("integrations", {}).get(
                    "github", {}
                )
                github_token = github_config.get("token") or github_config.get(
                    "app_private_key"
                )

                # For GitHub Apps, we might need to use installation token from payload
                installation_id = payload.get("installation", {}).get("id")

                if github_token or installation_id:
                    # Use installation token if available (for GitHub Apps)
                    token_to_use = github_token
                    if not token_to_use and installation_id:
                        # TODO: Generate installation token from app credentials
                        # For now, skip enrichment if no token available
                        pass

                    if token_to_use:
                        pr_comments = await fetch_github_pr_comments(
                            token=token_to_use,
                            repo=repo_full_name,
                            pr_number=pr_number,
                            limit=30,
                        )

                        if pr_comments:
                            # Get bot username from config if available
                            bot_username = github_config.get("app_name", "incidentfox")
                            context_str = format_github_pr_context(
                                comments=pr_comments,
                                bot_username=bot_username,
                            )

                            if context_str:
                                enriched_message = build_enriched_message(
                                    context_str, message
                                )
                                _log(
                                    "github_webhook_context_enriched",
                                    correlation_id=correlation_id,
                                    pr_comment_count=len(pr_comments),
                                    context_length=len(context_str),
                                )
            except Exception as e:
                _log(
                    "github_webhook_context_enrichment_failed",
                    correlation_id=correlation_id,
                    error=str(e),
                )
                # Continue with original message if enrichment fails

        if audit_api:
            audit_api.create_agent_run(
                run_id=run_id,
                org_id=org_id,
                team_node_id=team_node_id,
                correlation_id=correlation_id,
                trigger_source="github",
                trigger_actor=payload.get("sender", {}).get("login"),
                trigger_message=enriched_message[:500],
                agent_name=entrance_agent_name,
                metadata={
                    "event_type": event_type,
                    "repo": repo_full_name,
                    "pr_number": pr_number,
                    "issue_number": issue_number,
                    "is_pr": bool(pr_number),
                },
            )
            agent_run_created = True

        # Run agent with session resumption
        # OpenAIConversationsSession uses pr_number as conversation_id
        result = agent_api.run_agent(
            team_token=team_token,
            agent_name=entrance_agent_name,
            message=enriched_message,
            context={
                "metadata": {
                    "github": {
                        "event_type": event_type,
                        "repo": repo_full_name,
                        "delivery_id": delivery_id,
                        "pr_number": pr_number,  # Used for conversation_id
                        "issue_number": issue_number,
                    },
                    "trigger": "github",
                },
            },
            timeout=int(os.getenv("ORCHESTRATOR_GITHUB_AGENT_TIMEOUT_SECONDS", "180")),
            max_turns=int(os.getenv("ORCHESTRATOR_GITHUB_AGENT_MAX_TURNS", "30")),
            correlation_id=correlation_id,
            agent_base_url=dedicated_agent_url,
            output_destinations=output_destinations,
        )

        if audit_api:
            status = "completed" if result.get("success", True) else "failed"
            audit_api.complete_agent_run(
                org_id=org_id,
                run_id=run_id,
                status=status,
                tool_calls_count=result.get("tool_calls_count"),
            )

        _log(
            "github_webhook_completed",
            correlation_id=correlation_id,
            event_type=event_type,
            repo=repo_full_name,
        )

    except Exception as e:
        _log(
            "github_webhook_failed",
            correlation_id=correlation_id,
            event_type=event_type,
            error=str(e),
        )
        # Mark agent run as failed if it was created
        if agent_run_created and audit_api and run_id and org_id:
            try:
                audit_api.complete_agent_run(
                    org_id=org_id,
                    run_id=run_id,
                    status="failed",
                    error_message=str(e)[:500],
                )
            except Exception as completion_err:
                _log(
                    "github_webhook_failed_completion_error",
                    correlation_id=correlation_id,
                    run_id=run_id,
                    error=str(completion_err),
                )


def _build_github_message(event_type: str, payload: dict) -> str:
    """Build a human-readable message from GitHub webhook payload."""
    repo = payload.get("repository", {}).get("full_name", "unknown")
    action = payload.get("action", "")

    if event_type == "push":
        pusher = payload.get("pusher", {}).get("name", "unknown")
        ref = payload.get("ref", "")
        commits = payload.get("commits", [])
        return f"GitHub push to {repo} on {ref} by {pusher}: {len(commits)} commit(s)"

    elif event_type == "pull_request":
        pr = payload.get("pull_request", {})
        title = pr.get("title", "")
        number = pr.get("number", "")
        user = pr.get("user", {}).get("login", "unknown")
        return f"GitHub PR #{number} {action} in {repo} by {user}: {title}"

    elif event_type == "issues":
        issue = payload.get("issue", {})
        title = issue.get("title", "")
        number = issue.get("number", "")
        user = issue.get("user", {}).get("login", "unknown")
        return f"GitHub issue #{number} {action} in {repo} by {user}: {title}"

    elif event_type == "issue_comment":
        issue = payload.get("issue", {})
        comment = payload.get("comment", {})
        number = issue.get("number", "")
        user = comment.get("user", {}).get("login", "unknown")
        body = comment.get("body", "")[:200]
        return f"GitHub comment on #{number} in {repo} by {user}: {body}"

    else:
        return f"GitHub {event_type} event in {repo} (action: {action})"


# ============================================================================
# PagerDuty Webhooks
# ============================================================================


@router.post("/pagerduty")
async def pagerduty_webhook(
    request: Request,
    background: BackgroundTasks,
    x_pagerduty_signature: str = Header(default="", alias="X-PagerDuty-Signature"),
):
    """
    Handle PagerDuty webhooks (v3 format).
    """
    webhook_secret = (os.getenv("PAGERDUTY_WEBHOOK_SECRET") or "").strip()

    raw_body = (await request.body()).decode("utf-8")

    # Verify signature
    try:
        verify_pagerduty_signature(
            webhook_secret=webhook_secret,
            signature=x_pagerduty_signature or None,
            raw_body=raw_body,
        )
    except SignatureVerificationError as e:
        _log("pagerduty_webhook_signature_failed", reason=e.reason)
        raise HTTPException(
            status_code=401, detail=f"signature_verification_failed: {e.reason}"
        )

    # Parse payload
    try:
        payload = json.loads(raw_body) if raw_body else {}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid_json")

    _log("pagerduty_webhook_received")

    # Extract service ID for routing
    messages = payload.get("messages", [])
    for msg in messages:
        event = msg.get("event", {})
        service = event.get("data", {}).get("service", {})
        service_id = service.get("id", "")

        if service_id:
            background.add_task(
                _process_pagerduty_webhook,
                request=request,
                service_id=service_id,
                event=event,
            )

    return JSONResponse(content={"ok": True})


async def _process_pagerduty_webhook(
    request: Request,
    service_id: str,
    event: dict,
) -> None:
    """Process PagerDuty webhook asynchronously."""
    from incidentfox_orchestrator.clients import (
        AgentApiClient,
        AuditApiClient,
        ConfigServiceClient,
    )

    correlation_id = __import__("uuid").uuid4().hex

    _log(
        "pagerduty_webhook_processing",
        correlation_id=correlation_id,
        service_id=service_id,
    )

    # Track whether agent run was created so we can mark it failed on exception
    agent_run_created = False
    run_id = None
    org_id = None
    audit_api = None

    try:
        cfg: ConfigServiceClient = request.app.state.config_service
        agent_api: AgentApiClient = request.app.state.agent_api
        audit_api = getattr(request.app.state, "audit_api", None)
        correlation_service: Optional[CorrelationServiceClient] = getattr(
            request.app.state, "correlation_service", None
        )

        # Look up team via routing
        routing = cfg.lookup_routing(
            internal_service_name="orchestrator",
            identifiers={"pagerduty_service_id": service_id},
        )

        if not routing.get("found"):
            _log(
                "pagerduty_webhook_no_routing",
                correlation_id=correlation_id,
                service_id=service_id,
            )
            return

        org_id = routing["org_id"]
        team_node_id = routing["team_node_id"]

        admin_token = (os.getenv("ORCHESTRATOR_INTERNAL_ADMIN_TOKEN") or "").strip()
        if not admin_token:
            return

        imp = cfg.issue_team_impersonation_token(
            admin_token, org_id=org_id, team_node_id=team_node_id
        )
        team_token = str(imp.get("token") or "")
        if not team_token:
            return

        # Get team config to determine entrance agent and dedicated URL
        entrance_agent_name = "planner"  # Default fallback
        dedicated_agent_url: Optional[str] = None
        effective_config: dict = {}
        try:
            effective_config = cfg.get_effective_config(team_token=team_token)
            entrance_agent_name = effective_config.get("entrance_agent", "planner")
            dedicated_agent_url = effective_config.get("agent", {}).get(
                "dedicated_service_url"
            )
        except Exception:
            pass  # Fall back to shared agent

        run_id = __import__("uuid").uuid4().hex

        # Build message
        event_type = event.get("event_type", "")
        data = event.get("data", {})
        title = data.get("title", "")
        urgency = data.get("urgency", "")
        incident_id = data.get("id", "")
        message = f"PagerDuty {event_type}: {title} (urgency: {urgency})"

        # ─────────────────────────────────────────────────────────────────────
        # Alert Correlation (feature-flagged)
        # ─────────────────────────────────────────────────────────────────────
        correlation_context: Optional[dict] = None
        correlation_config = effective_config.get("correlation", {})
        correlation_enabled = correlation_config.get("enabled", False)

        if correlation_enabled and correlation_service:
            try:
                # Build alert object for correlation
                alert_for_correlation = {
                    "id": incident_id,
                    "service": service_id,
                    "title": title,
                    "severity": urgency,
                    "timestamp": data.get("created_at"),
                    "source": "pagerduty",
                    "metadata": data,
                }

                # Find correlated alerts
                correlation_result = correlation_service.find_correlated_alerts(
                    alert=alert_for_correlation,
                    team_id=team_node_id,
                    lookback_minutes=int(
                        correlation_config.get("temporal_window_seconds", 300) / 60
                    ),
                )

                correlated_alerts = correlation_result.get("correlated_alerts", [])
                correlation_signals = correlation_result.get("correlation_signals", [])

                if correlated_alerts:
                    correlation_context = {
                        "correlated_alerts_count": len(correlated_alerts),
                        "correlated_alerts": correlated_alerts[:5],  # Limit to top 5
                        "correlation_signals": correlation_signals,
                        "existing_incident_id": correlation_result.get("incident_id"),
                    }

                    # Enrich message with correlation context
                    alert_summary = ", ".join(
                        [a.get("title", "Unknown")[:50] for a in correlated_alerts[:3]]
                    )
                    message = (
                        f"{message}\n\n"
                        f"[Correlated with {len(correlated_alerts)} related alert(s): {alert_summary}]"
                    )

                    _log(
                        "pagerduty_webhook_correlation_found",
                        correlation_id=correlation_id,
                        correlated_count=len(correlated_alerts),
                        signals=[s.get("type") for s in correlation_signals],
                    )
            except Exception as e:
                _log(
                    "pagerduty_webhook_correlation_failed",
                    correlation_id=correlation_id,
                    error=str(e),
                )
                # Continue without correlation - don't block alert processing

        # Resolve output destinations
        from incidentfox_orchestrator.output_resolver import resolve_output_destinations

        trigger_payload = {
            "service_id": service_id,
            "incident_id": incident_id,
            "event_type": event_type,
        }

        # Get team config for notification settings
        team_notifications_config = {}
        try:
            team_notifications_config = effective_config
        except Exception:
            pass

        output_destinations = resolve_output_destinations(
            trigger_source="pagerduty",
            trigger_payload=trigger_payload,
            team_config=team_notifications_config,
        )

        if audit_api:
            audit_api.create_agent_run(
                run_id=run_id,
                org_id=org_id,
                team_node_id=team_node_id,
                correlation_id=correlation_id,
                trigger_source="pagerduty",
                trigger_message=message[:500],
                agent_name=entrance_agent_name,
                metadata={
                    "event_type": event_type,
                    "service_id": service_id,
                    "correlation": correlation_context,
                },
            )
            agent_run_created = True

        # Build context with optional correlation data
        agent_context: dict = {
            "metadata": {
                "pagerduty": {
                    "event_type": event_type,
                    "service_id": service_id,
                    "incident_data": data,
                },
                "trigger": "pagerduty",
            },
        }
        if correlation_context:
            agent_context["metadata"]["correlation"] = correlation_context

        result = agent_api.run_agent(
            team_token=team_token,
            agent_name=entrance_agent_name,
            message=message,
            context=agent_context,
            timeout=int(
                os.getenv("ORCHESTRATOR_PAGERDUTY_AGENT_TIMEOUT_SECONDS", "300")
            ),
            max_turns=int(os.getenv("ORCHESTRATOR_PAGERDUTY_AGENT_MAX_TURNS", "50")),
            correlation_id=correlation_id,
            agent_base_url=dedicated_agent_url,
            output_destinations=output_destinations,
        )

        if audit_api:
            status = "completed" if result.get("success", True) else "failed"
            audit_api.complete_agent_run(
                org_id=org_id,
                run_id=run_id,
                status=status,
                tool_calls_count=result.get("tool_calls_count"),
            )

        _log(
            "pagerduty_webhook_completed",
            correlation_id=correlation_id,
            service_id=service_id,
            correlation_enabled=correlation_enabled,
        )

    except Exception as e:
        _log(
            "pagerduty_webhook_failed",
            correlation_id=correlation_id,
            error=str(e),
        )
        # Mark agent run as failed if it was created
        if agent_run_created and audit_api and run_id and org_id:
            try:
                audit_api.complete_agent_run(
                    org_id=org_id,
                    run_id=run_id,
                    status="failed",
                    error_message=str(e)[:500],
                )
            except Exception as completion_err:
                _log(
                    "pagerduty_webhook_failed_completion_error",
                    correlation_id=correlation_id,
                    run_id=run_id,
                    error=str(completion_err),
                )


# ============================================================================
# Incident.io Webhooks
# ============================================================================


@router.post("/incidentio")
async def incidentio_webhook(
    request: Request,
    background: BackgroundTasks,
    webhook_id: str = Header(default="", alias="webhook-id"),
    webhook_timestamp: str = Header(default="", alias="webhook-timestamp"),
    webhook_signature: str = Header(default="", alias="webhook-signature"),
):
    """
    Handle Incident.io webhooks using Standard Webhooks format.

    Incident.io uses Standard Webhooks (https://www.standardwebhooks.com/) with:
    - webhook-id: Unique message ID
    - webhook-timestamp: Unix timestamp
    - webhook-signature: v1,{base64_hmac_sha256}
    """
    webhook_secret = (os.getenv("INCIDENTIO_WEBHOOK_SECRET") or "").strip()

    raw_body = (await request.body()).decode("utf-8")

    # Verify signature using Standard Webhooks format
    try:
        verify_incidentio_signature(
            webhook_secret=webhook_secret,
            webhook_id=webhook_id or None,
            signature=webhook_signature or None,
            timestamp=webhook_timestamp or None,
            raw_body=raw_body,
        )
    except SignatureVerificationError as e:
        _log("incidentio_webhook_signature_failed", reason=e.reason)
        raise HTTPException(
            status_code=401, detail=f"signature_verification_failed: {e.reason}"
        )

    # Parse payload
    try:
        payload = json.loads(raw_body) if raw_body else {}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid_json")

    event_type = payload.get("event_type", "")

    # Handle different payload structures:
    # - Public alerts: payload[event_type].alert contains alert info
    # - Incidents: payload.incident contains incident info
    incident = payload.get("incident", {})

    # Extract alert data and alert_source_id for public alerts
    # Incident.io public alert payloads have structure:
    # {
    #   "event_type": "public_alert.alert_created_v1",
    #   "public_alert.alert_created_v1": {
    #     "alert_source_id": "01KEGMSPPCKFPYHT2ZSNQ7WY3J",
    #     "title": "...",
    #     "status": "firing",
    #     ...
    #   }
    # }
    alert_source_id = ""
    alert_data = {}
    if event_type.startswith("public_alert."):
        event_data = payload.get(event_type, {})
        alert_data = event_data  # The event_data IS the alert data
        alert_source_id = event_data.get("alert_source_id", "")

    _log(
        "incidentio_webhook_received",
        event_type=event_type,
        alert_source_id=alert_source_id,
    )

    # For public alerts, use alert_data; for incidents, use incident
    is_public_alert = event_type.startswith("public_alert.")

    if is_public_alert and alert_source_id:
        _log(
            "incidentio_webhook_adding_task",
            alert_source_id=alert_source_id,
            event_type=event_type,
            task_type="public_alert",
        )
        background.add_task(
            _process_incidentio_webhook,
            request=request,
            incident=alert_data,  # Pass alert data as "incident" for processing
            event_type=event_type,
            payload=payload,
            alert_source_id=alert_source_id,
        )
        _log(
            "incidentio_webhook_task_added",
            alert_source_id=alert_source_id,
            tasks_count=len(background.tasks),
        )
    elif incident.get("id"):
        # Traditional incident webhook
        _log(
            "incidentio_webhook_adding_task",
            incident_id=incident.get("id"),
            event_type=event_type,
            task_type="incident",
        )
        background.add_task(
            _process_incidentio_webhook,
            request=request,
            incident=incident,
            event_type=event_type,
            payload=payload,
            alert_source_id="",
        )
        _log(
            "incidentio_webhook_task_added",
            incident_id=incident.get("id"),
            tasks_count=len(background.tasks),
        )
    else:
        _log(
            "incidentio_webhook_no_task_added",
            is_public_alert=is_public_alert,
            alert_source_id=alert_source_id,
            has_incident_id=bool(incident.get("id")),
        )

    return JSONResponse(content={"ok": True})


async def _process_incidentio_webhook(
    request: Request,
    incident: dict,
    event_type: str,
    payload: dict,
    alert_source_id: str = "",
) -> None:
    """Process Incident.io webhook asynchronously."""
    # Add initial logging to debug background task execution
    _log(
        "incidentio_webhook_task_started",
        alert_source_id=alert_source_id,
        event_type=event_type,
    )

    from incidentfox_orchestrator.clients import (
        AgentApiClient,
        AuditApiClient,
        ConfigServiceClient,
    )

    correlation_id = __import__("uuid").uuid4().hex
    incident_id = incident.get("id", "")
    is_public_alert = event_type.startswith("public_alert.")

    _log(
        "incidentio_webhook_processing",
        correlation_id=correlation_id,
        incident_id=incident_id,
        alert_source_id=alert_source_id,
        event_type=event_type,
    )

    # Track whether agent run was created so we can mark it failed on exception
    agent_run_created = False
    run_id = None
    org_id = None
    audit_api = None

    try:
        cfg: ConfigServiceClient = request.app.state.config_service
        agent_api: AgentApiClient = request.app.state.agent_api
        audit_api = getattr(request.app.state, "audit_api", None)
        correlation_service: Optional[CorrelationServiceClient] = getattr(
            request.app.state, "correlation_service", None
        )

        # Route by alert_source_id for public alerts, or incident_id for incidents
        if is_public_alert and alert_source_id:
            routing = cfg.lookup_routing(
                internal_service_name="orchestrator",
                identifiers={"incidentio_alert_source_id": alert_source_id},
            )
        else:
            routing = cfg.lookup_routing(
                internal_service_name="orchestrator",
                identifiers={"incidentio_team_id": incident_id},
            )

        if not routing.get("found"):
            _log(
                "incidentio_webhook_no_routing",
                correlation_id=correlation_id,
                incident_id=incident_id,
                alert_source_id=alert_source_id,
            )
            return

        org_id = routing["org_id"]
        team_node_id = routing["team_node_id"]

        admin_token = (os.getenv("ORCHESTRATOR_INTERNAL_ADMIN_TOKEN") or "").strip()
        if not admin_token:
            return

        imp = cfg.issue_team_impersonation_token(
            admin_token, org_id=org_id, team_node_id=team_node_id
        )
        team_token = str(imp.get("token") or "")
        if not team_token:
            return

        # Get team config to determine entrance agent and dedicated URL
        entrance_agent_name = "planner"  # Default fallback
        dedicated_agent_url: Optional[str] = None
        effective_config: dict = {}
        try:
            effective_config = cfg.get_effective_config(team_token=team_token)
            entrance_agent_name = effective_config.get("entrance_agent", "planner")
            dedicated_agent_url = effective_config.get("agent", {}).get(
                "dedicated_service_url"
            )
        except Exception:
            pass  # Fall back to shared agent

        run_id = __import__("uuid").uuid4().hex

        # Build message - handle both public alerts and incidents
        if is_public_alert:
            # Public alerts have title, status, priority directly
            name = incident.get("title", "") or incident.get("name", "")
            status = incident.get("status", "unknown")
            severity = incident.get("priority", "") or incident.get(
                "severity", "unknown"
            )
            message = f"Incident.io {event_type}: {name} (status: {status}, priority: {severity})"
        else:
            # Traditional incidents have nested structures
            name = incident.get("name", "")
            severity = incident.get("severity", {}).get("name", "unknown")
            status = incident.get("incident_status", {}).get("name", "unknown")
            message = (
                f"Incident.io {event_type}: [{severity}] {name} (status: {status})"
            )

        # ─────────────────────────────────────────────────────────────────────
        # Alert Correlation (feature-flagged)
        # ─────────────────────────────────────────────────────────────────────
        correlation_context: Optional[dict] = None
        correlation_config = effective_config.get("correlation", {})
        correlation_enabled = correlation_config.get("enabled", False)

        if correlation_enabled and correlation_service:
            try:
                # Build alert object for correlation
                alert_for_correlation = {
                    "id": incident_id,
                    "service": incident.get("affected_resources", [{}])[0].get(
                        "id", "unknown"
                    ),
                    "title": name,
                    "severity": severity,
                    "timestamp": incident.get("created_at"),
                    "source": "incidentio",
                    "metadata": incident,
                }

                # Find correlated alerts
                correlation_result = correlation_service.find_correlated_alerts(
                    alert=alert_for_correlation,
                    team_id=team_node_id,
                    lookback_minutes=int(
                        correlation_config.get("temporal_window_seconds", 300) / 60
                    ),
                )

                correlated_alerts = correlation_result.get("correlated_alerts", [])
                correlation_signals = correlation_result.get("correlation_signals", [])

                if correlated_alerts:
                    correlation_context = {
                        "correlated_alerts_count": len(correlated_alerts),
                        "correlated_alerts": correlated_alerts[:5],  # Limit to top 5
                        "correlation_signals": correlation_signals,
                        "existing_incident_id": correlation_result.get("incident_id"),
                    }

                    # Enrich message with correlation context
                    alert_summary = ", ".join(
                        [a.get("title", "Unknown")[:50] for a in correlated_alerts[:3]]
                    )
                    message = (
                        f"{message}\n\n"
                        f"[Correlated with {len(correlated_alerts)} related alert(s): {alert_summary}]"
                    )

                    _log(
                        "incidentio_webhook_correlation_found",
                        correlation_id=correlation_id,
                        correlated_count=len(correlated_alerts),
                        signals=[s.get("type") for s in correlation_signals],
                    )
            except Exception as e:
                _log(
                    "incidentio_webhook_correlation_failed",
                    correlation_id=correlation_id,
                    error=str(e),
                )
                # Continue without correlation - don't block alert processing

        # Resolve output destinations
        from incidentfox_orchestrator.output_resolver import resolve_output_destinations

        trigger_payload = {
            "incident_id": incident_id,
            "event_type": event_type,
        }

        # Get team config for notification settings
        team_notifications_config = {}
        try:
            team_notifications_config = effective_config
        except Exception:
            pass

        output_destinations = resolve_output_destinations(
            trigger_source="incidentio",
            trigger_payload=trigger_payload,
            team_config=team_notifications_config,
        )

        if audit_api:
            audit_api.create_agent_run(
                run_id=run_id,
                org_id=org_id,
                team_node_id=team_node_id,
                correlation_id=correlation_id,
                trigger_source="incidentio",
                trigger_message=message[:500],
                agent_name=entrance_agent_name,
                metadata={
                    "event_type": event_type,
                    "incident_id": incident_id,
                    "correlation": correlation_context,
                },
            )
            agent_run_created = True

        # Build context with optional correlation data
        agent_context: dict = {
            "metadata": {
                "incidentio": {
                    "event_type": event_type,
                    "incident": incident,
                },
                "trigger": "incidentio",
            },
        }
        if correlation_context:
            agent_context["metadata"]["correlation"] = correlation_context

        result = agent_api.run_agent(
            team_token=team_token,
            agent_name=entrance_agent_name,
            message=message,
            context=agent_context,
            timeout=int(
                os.getenv("ORCHESTRATOR_INCIDENTIO_AGENT_TIMEOUT_SECONDS", "300")
            ),
            max_turns=int(os.getenv("ORCHESTRATOR_INCIDENTIO_AGENT_MAX_TURNS", "50")),
            correlation_id=correlation_id,
            agent_base_url=dedicated_agent_url,
            output_destinations=output_destinations,
        )

        if audit_api:
            run_status = "completed" if result.get("success", True) else "failed"
            audit_api.complete_agent_run(
                org_id=org_id,
                run_id=run_id,
                status=run_status,
                tool_calls_count=result.get("tool_calls_count"),
            )

        _log(
            "incidentio_webhook_completed",
            correlation_id=correlation_id,
            incident_id=incident_id,
            correlation_enabled=correlation_enabled,
        )

    except Exception as e:
        _log(
            "incidentio_webhook_failed",
            correlation_id=correlation_id,
            error=str(e),
        )
        # Mark agent run as failed if it was created
        if agent_run_created and audit_api and run_id and org_id:
            try:
                audit_api.complete_agent_run(
                    org_id=org_id,
                    run_id=run_id,
                    status="failed",
                    error_message=str(e)[:500],
                )
            except Exception as completion_err:
                _log(
                    "incidentio_webhook_failed_completion_error",
                    correlation_id=correlation_id,
                    run_id=run_id,
                    error=str(completion_err),
                )


# ============================================================================
# Circleback Webhooks (Meeting Transcription)
# ============================================================================


@router.post("/circleback")
async def circleback_webhook(
    request: Request,
    background: BackgroundTasks,
    x_signature: str = Header(default="", alias="x-signature"),
):
    """
    Handle Circleback webhooks for meeting transcription data.

    Circleback sends meeting data (transcripts, notes, action items) via webhook
    after each meeting. This data is stored locally and can be queried by agents
    during incident investigation.

    Docs: https://circleback.ai/docs/webhook-integration
    """
    signing_secret = (os.getenv("CIRCLEBACK_SIGNING_SECRET") or "").strip()

    raw_body = (await request.body()).decode("utf-8")

    # Verify signature (optional - skip if no secret configured)
    if signing_secret:
        try:
            verify_circleback_signature(
                signing_secret=signing_secret,
                signature=x_signature or None,
                raw_body=raw_body,
            )
        except SignatureVerificationError as e:
            _log("circleback_webhook_signature_failed", reason=e.reason)
            raise HTTPException(
                status_code=401, detail=f"signature_verification_failed: {e.reason}"
            )

    # Parse payload
    try:
        payload = json.loads(raw_body) if raw_body else {}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid_json")

    meeting_id = payload.get("id", "")
    meeting_name = payload.get("name", "")

    _log(
        "circleback_webhook_received",
        meeting_id=meeting_id,
        meeting_name=meeting_name,
    )

    # Process in background
    if meeting_id:
        background.add_task(
            _process_circleback_webhook,
            request=request,
            payload=payload,
        )

    return JSONResponse(content={"ok": True})


async def _process_circleback_webhook(
    request: Request,
    payload: dict,
) -> None:
    """
    Process Circleback webhook asynchronously.

    Stores meeting data in config_service for later querying by agents.
    """
    from incidentfox_orchestrator.clients import ConfigServiceClient

    correlation_id = __import__("uuid").uuid4().hex
    meeting_id = payload.get("id", "")
    meeting_name = payload.get("name", "")

    _log(
        "circleback_webhook_processing",
        correlation_id=correlation_id,
        meeting_id=meeting_id,
    )

    try:
        cfg: ConfigServiceClient = request.app.state.config_service

        # Extract attendees to find which team this meeting belongs to
        attendees = payload.get("attendees", [])
        attendee_emails = [a.get("email", "") for a in attendees if a.get("email")]

        # Try to route based on attendee emails
        # This allows meeting data to be associated with the right team
        routing = None
        for email in attendee_emails:
            domain = email.split("@")[-1] if "@" in email else ""
            if domain:
                routing = cfg.lookup_routing(
                    internal_service_name="orchestrator",
                    identifiers={"email_domain": domain},
                )
                if routing.get("found"):
                    break

        if not routing or not routing.get("found"):
            _log(
                "circleback_webhook_no_routing",
                correlation_id=correlation_id,
                meeting_id=meeting_id,
                attendee_emails=attendee_emails[:3],  # Log first 3 for debugging
            )
            # Still store the meeting data with a default org if configured
            # For now, just log and skip
            return

        org_id = routing["org_id"]
        team_node_id = routing["team_node_id"]

        # Get admin token to store meeting data
        admin_token = (os.getenv("ORCHESTRATOR_INTERNAL_ADMIN_TOKEN") or "").strip()
        if not admin_token:
            _log(
                "circleback_webhook_no_admin_token",
                correlation_id=correlation_id,
            )
            return

        # Store meeting data via config service
        # The config service should have an endpoint for storing meeting data
        try:
            cfg.store_meeting_data(
                admin_token=admin_token,
                org_id=org_id,
                team_node_id=team_node_id,
                meeting_id=meeting_id,
                meeting_data={
                    "id": meeting_id,
                    "name": meeting_name,
                    "createdAt": payload.get("createdAt"),
                    "duration": payload.get("duration"),
                    "meetingUrl": payload.get("meetingUrl"),
                    "attendees": attendees,
                    "notes": payload.get("notes"),
                    "transcript": payload.get("transcript", []),
                    "action_items": payload.get("action_items", []),
                    "insights": payload.get("insights", []),
                    "provider": "circleback",
                },
            )

            _log(
                "circleback_webhook_stored",
                correlation_id=correlation_id,
                meeting_id=meeting_id,
                org_id=org_id,
                team_node_id=team_node_id,
                transcript_segments=len(payload.get("transcript", [])),
            )

        except Exception as store_error:
            _log(
                "circleback_webhook_store_failed",
                correlation_id=correlation_id,
                meeting_id=meeting_id,
                error=str(store_error),
            )

    except Exception as e:
        _log(
            "circleback_webhook_failed",
            correlation_id=correlation_id,
            meeting_id=meeting_id,
            error=str(e),
        )

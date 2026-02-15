"""
Webhook router for IncidentFox Orchestrator.

Handles all external webhook endpoints:
- /webhooks/slack/events - Slack Events API (via Slack Bolt SDK)
- /webhooks/slack/interactions - Slack Interactivity & Actions (via Slack Bolt SDK)
- /webhooks/github - GitHub webhooks
- /webhooks/pagerduty - PagerDuty webhooks
- /webhooks/incidentio - Incident.io webhooks
- /webhooks/blameless - Blameless webhooks
- /webhooks/firehydrant - FireHydrant webhooks
- /webhooks/google-chat - Google Chat App webhooks
- /webhooks/teams - MS Teams Bot Framework webhooks

Slack endpoints use Slack Bolt SDK for:
- Automatic signature verification
- URL verification challenge handling
- Event and interaction parsing

Other endpoints use manual signature verification.
"""

from __future__ import annotations

import asyncio
import json
import os
from functools import partial
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
    verify_blameless_signature,
    verify_circleback_signature,
    verify_firehydrant_signature,
    verify_github_signature,
    verify_google_chat_bearer_token,
    verify_incidentio_signature,
    verify_pagerduty_signature,
    verify_recall_signature,
)

if TYPE_CHECKING:
    from incidentfox_orchestrator.webhooks.google_chat_app import GoogleChatIntegration
    from incidentfox_orchestrator.webhooks.slack_bolt_app import SlackBoltIntegration
    from incidentfox_orchestrator.webhooks.teams_bot import TeamsIntegration


def _log(event: str, **fields: Any) -> None:
    """Structured logging."""
    try:
        payload = {"service": "orchestrator", "event": event, **fields}
        print(json.dumps(payload, default=str))
    except Exception:
        print(f"{event} {fields}")


import re

# Pattern to extract run_id from GitHub comment body
_INCIDENTFOX_RUN_ID_PATTERN = re.compile(
    r"<!--\s*incidentfox:run_id=([a-zA-Z0-9]+)\s*-->"
)


def _extract_run_id_from_comment(comment_body: str) -> str | None:
    """Extract run_id from a GitHub comment body if it contains our marker."""
    if not comment_body:
        return None
    match = _INCIDENTFOX_RUN_ID_PATTERN.search(comment_body)
    return match.group(1) if match else None


async def _check_github_reactions_and_record_feedback(
    comment_id: int,
    run_id: str,
    repo_full_name: str,
    github_token: str,
    audit_api: Any,
) -> None:
    """
    Check reactions on a GitHub comment and record feedback.

    GitHub reactions:
    - +1 (👍) -> positive feedback
    - -1 (👎) -> negative feedback
    """
    import httpx

    url = f"https://api.github.com/repos/{repo_full_name}/issues/comments/{comment_id}/reactions"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                url,
                headers={
                    "Authorization": f"Bearer {github_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            resp.raise_for_status()
            reactions = resp.json()

        # Track which users have given feedback to avoid duplicates
        # (In a full implementation, we'd store which reactions we've already processed)
        for reaction in reactions:
            content = reaction.get("content")
            user = reaction.get("user", {})
            user_id = user.get("login", "")

            if content == "+1":
                feedback_type = "positive"
            elif content == "-1":
                feedback_type = "negative"
            else:
                continue  # Ignore other reactions

            _log(
                "github_reaction_feedback",
                run_id=run_id,
                feedback_type=feedback_type,
                user_id=user_id,
                comment_id=comment_id,
            )

            # Record feedback via audit API
            if audit_api:
                await asyncio.to_thread(
                    audit_api.record_feedback,
                    run_id=run_id,
                    feedback=feedback_type,
                    user_id=user_id,
                    source="github",
                )

    except Exception as e:
        _log("github_reactions_fetch_failed", error=str(e), comment_id=comment_id)


router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# ============================================================================
# Slack Events API (via Slack Bolt SDK)
# ============================================================================


@router.post("/slack/{slug}/events")
async def slack_events_for_app(request: Request, slug: str):
    """
    Handle Slack Events API webhooks for a specific app (by slug).

    Each app has its own signing_secret for signature verification.
    """
    bolt_integration: Optional[SlackBoltIntegration] = getattr(
        request.app.state, "slack_bolt", None
    )
    if bolt_integration is None:
        _log("slack_bolt_not_initialized")
        raise HTTPException(status_code=503, detail="Slack integration not initialized")

    handler = bolt_integration.get_handler(slug)
    if handler is None:
        raise HTTPException(status_code=404, detail=f"Unknown Slack app: {slug}")

    return await handler.handle(request)


@router.post("/slack/{slug}/interactions")
async def slack_interactions_for_app(request: Request, slug: str):
    """
    Handle Slack Interactivity for a specific app (by slug).
    """
    bolt_integration: Optional[SlackBoltIntegration] = getattr(
        request.app.state, "slack_bolt", None
    )
    if bolt_integration is None:
        _log("slack_bolt_not_initialized")
        raise HTTPException(status_code=503, detail="Slack integration not initialized")

    handler = bolt_integration.get_handler(slug)
    if handler is None:
        raise HTTPException(status_code=404, detail=f"Unknown Slack app: {slug}")

    return await handler.handle(request)


# Legacy routes (backward compat - forward to default app's handler)


@router.post("/slack/events")
async def slack_events(request: Request):
    """Legacy: Handle Slack events for default app."""
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
    """Legacy: Handle Slack interactions for default app."""
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

    # Handle GitHub App lifecycle events (installation, installation_repositories)
    # These don't require repo-based routing - they're about the app installation itself
    if x_github_event in ("installation", "installation_repositories"):
        background.add_task(
            _process_github_app_lifecycle_webhook,
            request=request,
            event_type=x_github_event,
            delivery_id=x_github_delivery,
            payload=payload,
        )
        return JSONResponse(content={"ok": True})

    # Only process actionable event types — ignore noisy CI/CD events
    # (workflow_run, check_suite, check_run, status, deployment_status, etc.)
    _ACTIONABLE_GITHUB_EVENTS = {
        "pull_request",
        "push",
        "issues",
        "issue_comment",
    }
    if x_github_event not in _ACTIONABLE_GITHUB_EVENTS:
        _log(
            "github_webhook_skipped",
            event_type=x_github_event,
            delivery_id=x_github_delivery,
            reason="non_actionable_event_type",
        )
        return JSONResponse(content={"ok": True})

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
        # Use asyncio.to_thread() for sync HTTP calls to avoid blocking the event loop
        routing = await asyncio.to_thread(
            cfg.lookup_routing,
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

        # Run sync HTTP call in thread pool to avoid blocking event loop
        imp = await asyncio.to_thread(
            cfg.issue_team_impersonation_token,
            admin_token,
            org_id=org_id,
            team_node_id=team_node_id,
        )
        team_token = str(imp.get("token") or "")
        if not team_token:
            return

        # Get team config to determine entrance agent and dedicated URL
        entrance_agent_name = "planner"  # Default fallback
        dedicated_agent_url: Optional[str] = None
        try:
            # Run sync HTTP call in thread pool to avoid blocking event loop
            effective_config = await asyncio.to_thread(
                cfg.get_effective_config, team_token=team_token
            )
            entrance_agent_name = effective_config.get("entrance_agent", "planner")
            dedicated_agent_url = effective_config.get("agent", {}).get(
                "dedicated_service_url"
            )
        except Exception:
            pass  # Fall back to shared agent

        # Check for GitHub reactions on issue_comment events
        # If the comment contains our marker, check reactions and record feedback
        if event_type == "issue_comment":
            comment = payload.get("comment", {})
            comment_body = comment.get("body", "")
            comment_id = comment.get("id")

            marker_run_id = _extract_run_id_from_comment(comment_body)
            if marker_run_id and comment_id:
                # This comment was posted by IncidentFox - check reactions
                _log(
                    "github_comment_with_marker_detected",
                    correlation_id=correlation_id,
                    comment_id=comment_id,
                    marker_run_id=marker_run_id,
                )

                # Get GitHub token from team config
                github_config = effective_config.get("integrations", {}).get(
                    "github", {}
                )
                github_token = github_config.get("token") or github_config.get(
                    "app_private_key"
                )

                if github_token and audit_api:
                    await _check_github_reactions_and_record_feedback(
                        comment_id=comment_id,
                        run_id=marker_run_id,
                        repo_full_name=repo_full_name,
                        github_token=github_token,
                        audit_api=audit_api,
                    )

                # Don't trigger agent for comments on our own posts
                # (unless it's a new comment from a user, not an edit/reaction)
                action = payload.get("action", "")
                if action in ("edited", "deleted"):
                    _log(
                        "github_comment_skipped_own_comment",
                        correlation_id=correlation_id,
                        action=action,
                    )
                    return

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

        # Log resolved output destinations for debugging
        _log(
            "github_webhook_output_destinations_resolved",
            correlation_id=correlation_id,
            destination_count=len(output_destinations),
            destination_types=[d.get("type") for d in output_destinations],
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

        # Note: Agent service now handles agent run creation.
        # We pass trigger_source to ensure proper attribution.

        # Run agent with session resumption
        # OpenAIConversationsSession uses pr_number as conversation_id
        # CRITICAL: Run agent in thread pool to avoid blocking the event loop.
        result = await asyncio.to_thread(
            partial(
                agent_api.run_agent,
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
                timeout=int(
                    os.getenv("ORCHESTRATOR_GITHUB_AGENT_TIMEOUT_SECONDS", "180")
                ),
                max_turns=int(os.getenv("ORCHESTRATOR_GITHUB_AGENT_MAX_TURNS", "30")),
                correlation_id=correlation_id,
                agent_base_url=dedicated_agent_url,
                output_destinations=output_destinations,
                trigger_source="github",
                tenant_id=org_id,
                team_id=team_node_id,
            )
        )

        # Note: Agent service handles run completion recording

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
        # Note: Agent service handles run failure recording if the run was started


async def _process_github_app_lifecycle_webhook(
    request: Request,
    event_type: str,
    delivery_id: str,
    payload: dict,
) -> None:
    """
    Process GitHub App lifecycle webhooks (installation, installation_repositories).

    These events are sent when:
    - installation/created: App installed on an org/user
    - installation/deleted: App uninstalled
    - installation/suspend: App suspended
    - installation/unsuspend: App unsuspended
    - installation_repositories/added: Repos added to installation
    - installation_repositories/removed: Repos removed from installation

    We forward these to the config service to store/update the installation.
    """
    import httpx

    correlation_id = delivery_id or __import__("uuid").uuid4().hex
    action = payload.get("action", "")
    installation = payload.get("installation", {})
    installation_id = installation.get("id")

    _log(
        "github_app_lifecycle_webhook",
        correlation_id=correlation_id,
        event_type=event_type,
        action=action,
        installation_id=installation_id,
    )

    if not installation_id:
        _log(
            "github_app_lifecycle_no_installation_id",
            correlation_id=correlation_id,
        )
        return

    # Get config service URL from app state
    from incidentfox_orchestrator.clients import ConfigServiceClient

    cfg: ConfigServiceClient = request.app.state.config_service
    config_service_url = cfg.base_url

    internal_service_header = {"X-Internal-Service": "orchestrator"}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if event_type == "installation":
                if action == "created":
                    # New installation - store it
                    account = installation.get("account", {})
                    install_data = {
                        "installation_id": installation_id,
                        "app_id": installation.get("app_id"),
                        "account_id": account.get("id"),
                        "account_login": account.get("login", ""),
                        "account_type": account.get("type", "User"),
                        "account_avatar_url": account.get("avatar_url"),
                        "permissions": installation.get("permissions"),
                        "repository_selection": installation.get(
                            "repository_selection"
                        ),
                        "status": "active",
                        "raw_data": payload,
                    }

                    # If repository_selection is "selected", extract repos
                    if payload.get("repositories"):
                        install_data["repositories"] = [
                            r.get("full_name")
                            for r in payload.get("repositories", [])
                            if r.get("full_name")
                        ]

                    response = await client.post(
                        f"{config_service_url}/api/v1/internal/github/installations",
                        json=install_data,
                        headers=internal_service_header,
                    )
                    response.raise_for_status()

                    _log(
                        "github_installation_created",
                        correlation_id=correlation_id,
                        installation_id=installation_id,
                        account_login=account.get("login"),
                    )

                elif action == "deleted":
                    # Installation deleted - remove it
                    response = await client.delete(
                        f"{config_service_url}/api/v1/internal/github/installations/{installation_id}",
                        headers=internal_service_header,
                    )
                    # 404 is okay - installation might not exist
                    if response.status_code not in (200, 404):
                        response.raise_for_status()

                    _log(
                        "github_installation_deleted",
                        correlation_id=correlation_id,
                        installation_id=installation_id,
                    )

                elif action in ("suspend", "suspended"):
                    # Installation suspended
                    sender = payload.get("sender", {})
                    response = await client.patch(
                        f"{config_service_url}/api/v1/internal/github/installations/{installation_id}/status",
                        params={
                            "status": "suspended",
                            "suspended_by": sender.get("login"),
                        },
                        headers=internal_service_header,
                    )
                    if response.status_code != 404:
                        response.raise_for_status()

                    _log(
                        "github_installation_suspended",
                        correlation_id=correlation_id,
                        installation_id=installation_id,
                    )

                elif action in ("unsuspend", "unsuspended"):
                    # Installation unsuspended
                    response = await client.patch(
                        f"{config_service_url}/api/v1/internal/github/installations/{installation_id}/status",
                        params={"status": "active"},
                        headers=internal_service_header,
                    )
                    if response.status_code != 404:
                        response.raise_for_status()

                    _log(
                        "github_installation_unsuspended",
                        correlation_id=correlation_id,
                        installation_id=installation_id,
                    )

            elif event_type == "installation_repositories":
                # Repositories added or removed from installation
                # Update the installation's repository list
                repos_added = payload.get("repositories_added", [])
                repos_removed = payload.get("repositories_removed", [])

                _log(
                    "github_installation_repos_changed",
                    correlation_id=correlation_id,
                    installation_id=installation_id,
                    added_count=len(repos_added),
                    removed_count=len(repos_removed),
                )

                # Get current installation
                response = await client.get(
                    f"{config_service_url}/api/v1/internal/github/installations/{installation_id}",
                    headers=internal_service_header,
                )

                if response.status_code == 200:
                    current = response.json()
                    current_repos = set(current.get("repositories") or [])

                    # Add new repos
                    for repo in repos_added:
                        if repo.get("full_name"):
                            current_repos.add(repo["full_name"])

                    # Remove repos
                    for repo in repos_removed:
                        if repo.get("full_name"):
                            current_repos.discard(repo["full_name"])

                    # Update installation
                    update_data = {
                        "installation_id": installation_id,
                        "app_id": current.get("app_id"),
                        "account_id": current.get("account_id"),
                        "account_login": current.get("account_login"),
                        "account_type": current.get("account_type"),
                        "repositories": list(current_repos),
                        "repository_selection": installation.get(
                            "repository_selection", current.get("repository_selection")
                        ),
                    }

                    response = await client.post(
                        f"{config_service_url}/api/v1/internal/github/installations",
                        json=update_data,
                        headers=internal_service_header,
                    )
                    response.raise_for_status()

    except httpx.HTTPError as e:
        _log(
            "github_app_lifecycle_webhook_failed",
            correlation_id=correlation_id,
            event_type=event_type,
            action=action,
            error=str(e),
        )
    except Exception as e:
        _log(
            "github_app_lifecycle_webhook_error",
            correlation_id=correlation_id,
            event_type=event_type,
            action=action,
            error=str(e),
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

        # Log resolved output destinations for debugging
        _log(
            "pagerduty_webhook_output_destinations_resolved",
            correlation_id=correlation_id,
            destination_count=len(output_destinations),
            destination_types=[d.get("type") for d in output_destinations],
            has_notifications_config=bool(
                team_notifications_config.get("notifications")
            ),
            pagerduty_output_channel=team_notifications_config.get("notifications", {})
            .get("pagerduty_output", {})
            .get("slack_channel_id"),
            default_slack_channel=team_notifications_config.get(
                "notifications", {}
            ).get("default_slack_channel_id"),
        )

        # Note: Agent service now handles agent run creation.
        # We pass trigger_source to ensure proper attribution.

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
            trigger_source="pagerduty",
            tenant_id=org_id,
            team_id=team_node_id,
        )

        # Note: Agent service handles run completion recording

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
        # Note: Agent service handles run failure recording if the run was started


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
        # Use asyncio.to_thread() for sync HTTP calls to avoid blocking the event loop
        # This prevents liveness probe failures during long-running operations
        if is_public_alert and alert_source_id:
            routing = await asyncio.to_thread(
                cfg.lookup_routing,
                internal_service_name="orchestrator",
                identifiers={"incidentio_alert_source_id": alert_source_id},
            )
        else:
            routing = await asyncio.to_thread(
                cfg.lookup_routing,
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

        # Run sync HTTP call in thread pool to avoid blocking event loop
        imp = await asyncio.to_thread(
            cfg.issue_team_impersonation_token,
            admin_token,
            org_id=org_id,
            team_node_id=team_node_id,
        )
        team_token = str(imp.get("token") or "")
        if not team_token:
            return

        # Get team config to determine entrance agent and dedicated URL
        entrance_agent_name = "planner"  # Default fallback
        dedicated_agent_url: Optional[str] = None
        effective_config: dict = {}
        try:
            # Run sync HTTP call in thread pool to avoid blocking event loop
            effective_config = await asyncio.to_thread(
                cfg.get_effective_config, team_token=team_token
            )
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

        # Log resolved output destinations for debugging
        _log(
            "incidentio_webhook_output_destinations_resolved",
            correlation_id=correlation_id,
            destination_count=len(output_destinations),
            destination_types=[d.get("type") for d in output_destinations],
            has_notifications_config=bool(
                team_notifications_config.get("notifications")
            ),
            incidentio_output_channel=team_notifications_config.get("notifications", {})
            .get("incidentio_output", {})
            .get("slack_channel_id"),
            default_slack_channel=team_notifications_config.get(
                "notifications", {}
            ).get("default_slack_channel_id"),
        )

        # Note: Agent service now handles agent run creation.
        # We pass trigger_source to ensure proper attribution.

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

        # CRITICAL: Run agent in thread pool to avoid blocking the event loop.
        # agent_api.run_agent() uses sync httpx and can take several minutes.
        # Without this, the event loop blocks and health checks fail, causing
        # the pod to be killed by the liveness probe.
        result = await asyncio.to_thread(
            partial(
                agent_api.run_agent,
                team_token=team_token,
                agent_name=entrance_agent_name,
                message=message,
                context=agent_context,
                timeout=int(
                    os.getenv("ORCHESTRATOR_INCIDENTIO_AGENT_TIMEOUT_SECONDS", "300")
                ),
                max_turns=int(
                    os.getenv("ORCHESTRATOR_INCIDENTIO_AGENT_MAX_TURNS", "50")
                ),
                correlation_id=correlation_id,
                agent_base_url=dedicated_agent_url,
                output_destinations=output_destinations,
                trigger_source="incidentio",
                tenant_id=org_id,
                team_id=team_node_id,
            )
        )

        # Note: Agent service handles run completion recording

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
        # Note: Agent service handles run failure recording if the run was started


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


# ============================================================================
# Recall.ai Webhooks (Real-time Meeting Transcription)
# ============================================================================


@router.post("/recall")
async def recall_webhook(
    request: Request,
    background: BackgroundTasks,
    x_recall_signature: str = Header(default="", alias="x-recall-signature"),
):
    """
    Handle Recall.ai webhooks for real-time meeting transcription.

    Recall.ai sends real-time transcript events as meetings progress:
    - bot.status_change: Bot joined, left, or status changed
    - transcript.data: Finalized transcript utterance
    - transcript.partial_data: Low-latency partial transcript (optional)

    These events are processed in real-time and fed to the AI agent
    investigating the associated incident.

    Docs: https://docs.recall.ai/docs/bot-real-time-transcription
    """
    webhook_secret = (os.getenv("RECALL_WEBHOOK_SECRET") or "").strip()

    raw_body = (await request.body()).decode("utf-8")

    # Verify signature
    if webhook_secret:
        try:
            verify_recall_signature(
                webhook_secret=webhook_secret,
                signature=x_recall_signature or None,
                raw_body=raw_body,
            )
        except SignatureVerificationError as e:
            _log("recall_webhook_signature_failed", reason=e.reason)
            raise HTTPException(
                status_code=401, detail=f"signature_verification_failed: {e.reason}"
            )

    # Parse payload
    try:
        payload = json.loads(raw_body) if raw_body else {}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid_json")

    event_type = payload.get("event", "")
    bot_id = payload.get("data", {}).get("bot_id", "") or payload.get("bot_id", "")

    _log(
        "recall_webhook_received",
        event_type=event_type,
        bot_id=bot_id,
    )

    # Process in background
    if event_type and bot_id:
        background.add_task(
            _process_recall_webhook,
            request=request,
            event_type=event_type,
            bot_id=bot_id,
            payload=payload,
        )

    return JSONResponse(content={"ok": True})


async def _process_recall_webhook(
    request: Request,
    event_type: str,
    bot_id: str,
    payload: dict,
) -> None:
    """
    Process Recall.ai webhook asynchronously.

    Routes transcript data to the appropriate incident investigation
    and updates bot status in the database.
    """
    from incidentfox_orchestrator.clients import ConfigServiceClient

    correlation_id = __import__("uuid").uuid4().hex

    _log(
        "recall_webhook_processing",
        correlation_id=correlation_id,
        event_type=event_type,
        bot_id=bot_id,
    )

    try:
        cfg: ConfigServiceClient = request.app.state.config_service

        # Get admin token for database operations
        admin_token = (os.getenv("ORCHESTRATOR_INTERNAL_ADMIN_TOKEN") or "").strip()
        if not admin_token:
            _log(
                "recall_webhook_no_admin_token",
                correlation_id=correlation_id,
            )
            return

        # Handle different event types
        if event_type == "bot.status_change":
            await _handle_recall_bot_status_change(
                cfg=cfg,
                admin_token=admin_token,
                bot_id=bot_id,
                payload=payload,
                correlation_id=correlation_id,
            )

        elif event_type in ("transcript.data", "transcript.partial_data"):
            await _handle_recall_transcript_data(
                request=request,
                cfg=cfg,
                admin_token=admin_token,
                bot_id=bot_id,
                payload=payload,
                event_type=event_type,
                correlation_id=correlation_id,
            )

        else:
            _log(
                "recall_webhook_unknown_event",
                correlation_id=correlation_id,
                event_type=event_type,
            )

    except Exception as e:
        _log(
            "recall_webhook_failed",
            correlation_id=correlation_id,
            event_type=event_type,
            bot_id=bot_id,
            error=str(e),
        )


async def _handle_recall_bot_status_change(
    cfg: Any,
    admin_token: str,
    bot_id: str,
    payload: dict,
    correlation_id: str,
) -> None:
    """Handle bot status change events from Recall.ai."""
    data = payload.get("data", {})
    status = data.get("status", {})
    status_code = status.get("code", "unknown")
    status_message = status.get("message", "")

    _log(
        "recall_bot_status_change",
        correlation_id=correlation_id,
        bot_id=bot_id,
        status_code=status_code,
        status_message=status_message,
    )

    # Map Recall.ai status codes to our internal status
    # Recall statuses: ready, joining, in_waiting_room, in_call_not_recording,
    #                  in_call_recording, call_ended, done, fatal
    status_mapping = {
        "ready": "requested",
        "joining": "joining",
        "in_waiting_room": "joining",
        "in_call_not_recording": "in_call",
        "in_call_recording": "recording",
        "call_ended": "done",
        "done": "done",
        "fatal": "error",
    }
    internal_status = status_mapping.get(status_code, status_code)

    # Update bot status in database
    try:
        await asyncio.to_thread(
            cfg.update_recall_bot_status,
            admin_token=admin_token,
            recall_bot_id=bot_id,
            status=internal_status,
            status_message=status_message,
            joined_at=(
                data.get("joined_at")
                if status_code in ("in_call_not_recording", "in_call_recording")
                else None
            ),
            left_at=(
                data.get("left_at") if status_code in ("call_ended", "done") else None
            ),
        )
        _log(
            "recall_bot_status_updated",
            correlation_id=correlation_id,
            bot_id=bot_id,
            internal_status=internal_status,
        )
    except Exception as e:
        _log(
            "recall_bot_status_update_failed",
            correlation_id=correlation_id,
            bot_id=bot_id,
            error=str(e),
        )


async def _handle_recall_transcript_data(
    request: Request,
    cfg: Any,
    admin_token: str,
    bot_id: str,
    payload: dict,
    event_type: str,
    correlation_id: str,
) -> None:
    """
    Handle transcript data events from Recall.ai.

    This is the core real-time transcription handler that:
    1. Stores the transcript segment
    2. Looks up the associated incident
    3. Feeds the transcript to the active investigation
    """
    from incidentfox_orchestrator.clients import AgentApiClient

    data = payload.get("data", {})
    transcript = data.get("transcript", {})

    speaker = transcript.get("speaker", "Unknown")
    text = transcript.get("text", "")
    timestamp_ms = transcript.get("timestamp_ms")
    is_partial = event_type == "transcript.partial_data"

    if not text.strip():
        return  # Skip empty transcripts

    _log(
        "recall_transcript_received",
        correlation_id=correlation_id,
        bot_id=bot_id,
        speaker=speaker,
        text_length=len(text),
        is_partial=is_partial,
    )

    try:
        # Look up the bot to find the associated incident
        bot_info = await asyncio.to_thread(
            cfg.get_recall_bot,
            admin_token=admin_token,
            recall_bot_id=bot_id,
        )

        if not bot_info:
            _log(
                "recall_transcript_bot_not_found",
                correlation_id=correlation_id,
                bot_id=bot_id,
            )
            return

        org_id = bot_info.get("org_id")
        team_node_id = bot_info.get("team_node_id")
        incident_id = bot_info.get("incident_id")

        # Store transcript segment
        segment_id = __import__("uuid").uuid4().hex
        await asyncio.to_thread(
            cfg.store_recall_transcript_segment,
            admin_token=admin_token,
            segment_id=segment_id,
            recall_bot_id=bot_id,
            org_id=org_id,
            incident_id=incident_id,
            speaker=speaker,
            text=text,
            timestamp_ms=timestamp_ms,
            is_partial=is_partial,
            raw_event=payload,
        )

        # Update bot transcript count
        await asyncio.to_thread(
            cfg.increment_recall_bot_transcript_count,
            admin_token=admin_token,
            recall_bot_id=bot_id,
        )

        # If this is a partial transcript, don't feed to agent or update Slack (too noisy)
        if is_partial:
            return

        # Post/update transcript summary to Slack thread (if configured)
        if bot_info.get("slack_channel_id") and bot_info.get("slack_thread_ts"):
            try:
                from incidentfox_orchestrator.recall_summary import (
                    post_transcript_summary,
                )

                await post_transcript_summary(
                    config_service_client=cfg,
                    admin_token=admin_token,
                    recall_bot_id=bot_id,
                    bot_info=bot_info,
                )
            except Exception as slack_error:
                _log(
                    "recall_transcript_slack_summary_failed",
                    correlation_id=correlation_id,
                    bot_id=bot_id,
                    error=str(slack_error),
                )

        # Feed transcript to active investigation if there's an associated incident
        if incident_id and team_node_id:
            # Get impersonation token for the team
            imp = await asyncio.to_thread(
                cfg.issue_team_impersonation_token,
                admin_token,
                org_id=org_id,
                team_node_id=team_node_id,
            )
            team_token = str(imp.get("token") or "")

            if team_token:
                agent_api: AgentApiClient = request.app.state.agent_api

                # Format transcript for agent context
                transcript_context = f"[Meeting Transcript] {speaker}: {text}"

                # Send to agent as context update (non-blocking)
                try:
                    await asyncio.to_thread(
                        agent_api.add_investigation_context,
                        team_token=team_token,
                        incident_id=incident_id,
                        context_type="meeting_transcript",
                        content=transcript_context,
                        metadata={
                            "speaker": speaker,
                            "timestamp_ms": timestamp_ms,
                            "bot_id": bot_id,
                        },
                    )
                    _log(
                        "recall_transcript_sent_to_agent",
                        correlation_id=correlation_id,
                        incident_id=incident_id,
                        speaker=speaker,
                    )
                except Exception as agent_error:
                    _log(
                        "recall_transcript_agent_send_failed",
                        correlation_id=correlation_id,
                        incident_id=incident_id,
                        error=str(agent_error),
                    )

    except Exception as e:
        _log(
            "recall_transcript_processing_failed",
            correlation_id=correlation_id,
            bot_id=bot_id,
            error=str(e),
        )


# ============================================================================
# Google Chat App Webhooks
# ============================================================================


@router.post("/google-chat")
async def google_chat_webhook(
    request: Request,
    authorization: str = Header(default="", alias="Authorization"),
):
    """
    Handle Google Chat App webhooks.

    Google Chat sends:
    - MESSAGE: User messages mentioning the bot
    - ADDED_TO_SPACE: Bot added to a space
    - REMOVED_FROM_SPACE: Bot removed
    - CARD_CLICKED: Interactive card button clicks

    Auth: Bearer token (JWT from chat@system.gserviceaccount.com)
    """
    gchat_integration: Optional["GoogleChatIntegration"] = getattr(
        request.app.state, "google_chat", None
    )
    if gchat_integration is None:
        _log("google_chat_not_initialized")
        raise HTTPException(
            status_code=503, detail="Google Chat integration not initialized"
        )

    # Verify JWT
    # Google Chat HTTP endpoints use the webhook URL as the JWT audience.
    # Behind TLS-terminating LB, request.url is http:// but the token uses https://
    url = str(request.url)
    if request.headers.get("x-forwarded-proto") == "https" and url.startswith(
        "http://"
    ):
        url = "https://" + url[len("http://") :]
    expected_audience = os.getenv("GOOGLE_CHAT_AUDIENCE", "").strip() or url
    try:
        verify_google_chat_bearer_token(
            authorization=authorization or None,
            expected_audience=expected_audience,
        )
    except SignatureVerificationError as e:
        _log("google_chat_auth_failed", reason=e.reason)
        raise HTTPException(status_code=401, detail=f"auth_failed: {e.reason}")

    # Parse event
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid_json")

    # Google Chat sends different payload formats:
    # - Legacy/Chat app: {"type": "MESSAGE", "message": {...}, "space": {...}}
    # - Workspace Add-on: {"commonEventObject": {...}, "chat": {
    #       "messagePayload": {"message": {...}, "space": {...}},
    #       "user": {...}, "eventTime": "..."
    #   }}
    # Normalize to legacy format for downstream handlers
    chat_data = payload.get("chat", {}) or {}
    event_type = payload.get("type", "") or payload.get("eventType", "")

    if not event_type and chat_data:
        # Workspace Add-on format — infer event type from payload keys
        if "messagePayload" in chat_data:
            event_type = "MESSAGE"
            # Unwrap: chat.messagePayload contains {message, space}
            msg_payload = chat_data["messagePayload"]
            event_data = {
                "type": "MESSAGE",
                "message": msg_payload.get("message", {}),
                "space": msg_payload.get("space", {}),
                "user": chat_data.get("user", {}),
                "eventTime": chat_data.get("eventTime", ""),
            }
        elif "addedToSpacePayload" in chat_data:
            event_type = "ADDED_TO_SPACE"
            space_payload = chat_data["addedToSpacePayload"]
            event_data = {
                "type": "ADDED_TO_SPACE",
                "space": space_payload.get("space", {}),
                "user": chat_data.get("user", {}),
            }
        elif "removedFromSpacePayload" in chat_data:
            event_type = "REMOVED_FROM_SPACE"
            space_payload = chat_data["removedFromSpacePayload"]
            event_data = {
                "type": "REMOVED_FROM_SPACE",
                "space": space_payload.get("space", {}),
                "user": chat_data.get("user", {}),
            }
        else:
            event_data = payload
    else:
        event_data = payload

    correlation_id = __import__("uuid").uuid4().hex

    _log(
        "google_chat_webhook_received",
        event_type=event_type,
        correlation_id=correlation_id,
    )

    # Handle event and return response
    is_addon_format = bool(chat_data)
    response = await gchat_integration.handle_event(
        event_type=event_type,
        event_data=event_data,
        correlation_id=correlation_id,
    )

    # Workspace Add-on format requires wrapping the response
    if is_addon_format and response.get("text"):
        response = {
            "hostAppDataAction": {
                "chatDataAction": {
                    "createMessageAction": {
                        "message": response,
                    }
                }
            }
        }

    return JSONResponse(content=response)


# ============================================================================
# MS Teams Bot Framework Webhooks
# ============================================================================


@router.post("/teams")
async def teams_webhook(
    request: Request,
    authorization: str = Header(default="", alias="Authorization"),
):
    """
    Handle MS Teams Bot Framework webhooks.

    Teams sends Activity objects for:
    - message: User messages
    - conversationUpdate: Bot added/removed
    - invoke: Adaptive Card actions

    Auth: JWT validated by BotFrameworkAdapter against Azure AD
    """
    teams_integration: Optional["TeamsIntegration"] = getattr(
        request.app.state, "teams_bot", None
    )
    if teams_integration is None:
        _log("teams_not_initialized")
        raise HTTPException(status_code=503, detail="Teams integration not initialized")

    raw_body = await request.body()

    _log("teams_webhook_received")

    try:
        # BotFrameworkAdapter handles auth internally
        await teams_integration.process_activity(raw_body, authorization or "")
        return JSONResponse(content={"ok": True}, status_code=200)
    except Exception as e:
        import traceback

        _log("teams_webhook_failed", error=str(e), traceback=traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Blameless Webhooks
# ============================================================================


@router.post("/blameless")
async def blameless_webhook(
    request: Request,
    background: BackgroundTasks,
    x_blameless_signature: str = Header(default="", alias="X-Blameless-Signature"),
):
    """
    Handle Blameless webhooks.

    Blameless sends webhooks for incident lifecycle events:
    - incident.created
    - incident.updated
    - incident.resolved
    - retrospective.completed
    """
    webhook_secret = (os.getenv("BLAMELESS_WEBHOOK_SECRET") or "").strip()

    raw_body = (await request.body()).decode("utf-8")

    # Verify signature
    try:
        verify_blameless_signature(
            webhook_secret=webhook_secret,
            signature=x_blameless_signature or None,
            raw_body=raw_body,
        )
    except SignatureVerificationError as e:
        _log("blameless_webhook_signature_failed", reason=e.reason)
        raise HTTPException(
            status_code=401, detail=f"signature_verification_failed: {e.reason}"
        )

    # Parse payload
    try:
        payload = json.loads(raw_body) if raw_body else {}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid_json")

    _log("blameless_webhook_received")

    # Extract team/incident info for routing
    event_type = payload.get("event_type", payload.get("type", ""))
    incident = payload.get("incident", payload.get("data", {}))
    incident_id = incident.get("id", "")
    team_id = incident.get("team_id", incident.get("team", {}).get("id", ""))

    if incident_id:
        background.add_task(
            _process_blameless_webhook,
            request=request,
            team_id=team_id,
            incident_id=incident_id,
            event_type=event_type,
            incident_data=incident,
        )

    return JSONResponse(content={"ok": True})


async def _process_blameless_webhook(
    request: Request,
    team_id: str,
    incident_id: str,
    event_type: str,
    incident_data: dict,
) -> None:
    """Process Blameless webhook asynchronously."""
    from incidentfox_orchestrator.clients import (
        AgentApiClient,
        ConfigServiceClient,
    )

    correlation_id = __import__("uuid").uuid4().hex

    _log(
        "blameless_webhook_processing",
        correlation_id=correlation_id,
        team_id=team_id,
        incident_id=incident_id,
    )

    try:
        cfg: ConfigServiceClient = request.app.state.config_service
        agent_api: AgentApiClient = request.app.state.agent_api

        # Look up team via routing
        routing = cfg.lookup_routing(
            internal_service_name="orchestrator",
            identifiers={"blameless_team_id": team_id},
        )

        if not routing.get("found"):
            _log(
                "blameless_webhook_no_routing",
                correlation_id=correlation_id,
                team_id=team_id,
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

        # Get team config
        entrance_agent_name = "planner"
        dedicated_agent_url: Optional[str] = None
        effective_config: dict = {}
        try:
            effective_config = cfg.get_effective_config(team_token=team_token)
            entrance_agent_name = effective_config.get("entrance_agent", "planner")
            dedicated_agent_url = effective_config.get("agent", {}).get(
                "dedicated_service_url"
            )
        except Exception:
            pass

        # Build message
        title = incident_data.get("title") or incident_data.get("name", "")
        severity = incident_data.get("severity", "")
        message = f"Blameless {event_type}: {title} (severity: {severity})"

        # Resolve output destinations
        from incidentfox_orchestrator.output_resolver import resolve_output_destinations

        trigger_payload = {
            "team_id": team_id,
            "incident_id": incident_id,
            "event_type": event_type,
        }

        output_destinations = resolve_output_destinations(
            trigger_source="blameless",
            trigger_payload=trigger_payload,
            team_config=effective_config,
        )

        agent_context: dict = {
            "metadata": {
                "blameless": {
                    "event_type": event_type,
                    "team_id": team_id,
                    "incident_data": incident_data,
                },
                "trigger": "blameless",
            },
        }

        result = agent_api.run_agent(
            team_token=team_token,
            agent_name=entrance_agent_name,
            message=message,
            context=agent_context,
            timeout=int(
                os.getenv("ORCHESTRATOR_BLAMELESS_AGENT_TIMEOUT_SECONDS", "300")
            ),
            max_turns=int(os.getenv("ORCHESTRATOR_BLAMELESS_AGENT_MAX_TURNS", "50")),
            correlation_id=correlation_id,
            agent_base_url=dedicated_agent_url,
            output_destinations=output_destinations,
            trigger_source="blameless",
            tenant_id=org_id,
            team_id=team_node_id,
        )

        _log(
            "blameless_webhook_completed",
            correlation_id=correlation_id,
            team_id=team_id,
        )

    except Exception as e:
        _log(
            "blameless_webhook_failed",
            correlation_id=correlation_id,
            error=str(e),
        )


# ============================================================================
# FireHydrant Webhooks
# ============================================================================


@router.post("/firehydrant")
async def firehydrant_webhook(
    request: Request,
    background: BackgroundTasks,
    x_firehydrant_signature: str = Header(default="", alias="X-FireHydrant-Signature"),
):
    """
    Handle FireHydrant webhooks.

    FireHydrant sends webhooks for incident lifecycle events:
    - incident.opened
    - incident.updated
    - incident.resolved
    - incident.closed
    - alert.created
    """
    webhook_secret = (os.getenv("FIREHYDRANT_WEBHOOK_SECRET") or "").strip()

    raw_body = (await request.body()).decode("utf-8")

    # Verify signature
    try:
        verify_firehydrant_signature(
            webhook_secret=webhook_secret,
            signature=x_firehydrant_signature or None,
            raw_body=raw_body,
        )
    except SignatureVerificationError as e:
        _log("firehydrant_webhook_signature_failed", reason=e.reason)
        raise HTTPException(
            status_code=401, detail=f"signature_verification_failed: {e.reason}"
        )

    # Parse payload
    try:
        payload = json.loads(raw_body) if raw_body else {}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid_json")

    _log("firehydrant_webhook_received")

    # Extract incident info for routing
    event_type = payload.get("type", payload.get("event_type", ""))
    data = payload.get("data", payload)
    incident = data.get("incident", data)
    incident_id = incident.get("id", "")

    # Extract team ID from services or teams in the incident
    team_id = ""
    services = incident.get("services", [])
    if services and isinstance(services[0], dict):
        team_id = services[0].get("id", "")

    if incident_id:
        background.add_task(
            _process_firehydrant_webhook,
            request=request,
            team_id=team_id,
            incident_id=incident_id,
            event_type=event_type,
            incident_data=incident,
        )

    return JSONResponse(content={"ok": True})


async def _process_firehydrant_webhook(
    request: Request,
    team_id: str,
    incident_id: str,
    event_type: str,
    incident_data: dict,
) -> None:
    """Process FireHydrant webhook asynchronously."""
    from incidentfox_orchestrator.clients import (
        AgentApiClient,
        ConfigServiceClient,
    )

    correlation_id = __import__("uuid").uuid4().hex

    _log(
        "firehydrant_webhook_processing",
        correlation_id=correlation_id,
        team_id=team_id,
        incident_id=incident_id,
    )

    try:
        cfg: ConfigServiceClient = request.app.state.config_service
        agent_api: AgentApiClient = request.app.state.agent_api

        # Look up team via routing
        routing = cfg.lookup_routing(
            internal_service_name="orchestrator",
            identifiers={"firehydrant_team_id": team_id},
        )

        if not routing.get("found"):
            _log(
                "firehydrant_webhook_no_routing",
                correlation_id=correlation_id,
                team_id=team_id,
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

        # Get team config
        entrance_agent_name = "planner"
        dedicated_agent_url: Optional[str] = None
        effective_config: dict = {}
        try:
            effective_config = cfg.get_effective_config(team_token=team_token)
            entrance_agent_name = effective_config.get("entrance_agent", "planner")
            dedicated_agent_url = effective_config.get("agent", {}).get(
                "dedicated_service_url"
            )
        except Exception:
            pass

        # Build message
        name = incident_data.get("name", "")
        severity = incident_data.get("severity", "")
        message = f"FireHydrant {event_type}: {name} (severity: {severity})"

        # Resolve output destinations
        from incidentfox_orchestrator.output_resolver import resolve_output_destinations

        trigger_payload = {
            "team_id": team_id,
            "incident_id": incident_id,
            "event_type": event_type,
        }

        output_destinations = resolve_output_destinations(
            trigger_source="firehydrant",
            trigger_payload=trigger_payload,
            team_config=effective_config,
        )

        agent_context: dict = {
            "metadata": {
                "firehydrant": {
                    "event_type": event_type,
                    "team_id": team_id,
                    "incident_data": incident_data,
                },
                "trigger": "firehydrant",
            },
        }

        result = agent_api.run_agent(
            team_token=team_token,
            agent_name=entrance_agent_name,
            message=message,
            context=agent_context,
            timeout=int(
                os.getenv("ORCHESTRATOR_FIREHYDRANT_AGENT_TIMEOUT_SECONDS", "300")
            ),
            max_turns=int(os.getenv("ORCHESTRATOR_FIREHYDRANT_AGENT_MAX_TURNS", "50")),
            correlation_id=correlation_id,
            agent_base_url=dedicated_agent_url,
            output_destinations=output_destinations,
            trigger_source="firehydrant",
            tenant_id=org_id,
            team_id=team_node_id,
        )

        _log(
            "firehydrant_webhook_completed",
            correlation_id=correlation_id,
            team_id=team_id,
        )

    except Exception as e:
        _log(
            "firehydrant_webhook_failed",
            correlation_id=correlation_id,
            error=str(e),
        )

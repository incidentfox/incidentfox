from __future__ import annotations

import hashlib
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy import text as sql_text

from incidentfox_orchestrator.clients import (
    AgentApiClient,
    AuditApiClient,
    ConfigServiceClient,
    CorrelationServiceClient,
    PipelineApiClient,
    TelemetryCollectorClient,
    _extract_token,
)
from incidentfox_orchestrator.config import load_settings
from incidentfox_orchestrator.db import db_session, get_engine, init_engine
from incidentfox_orchestrator.k8s import (
    create_dedicated_agent_deployment,
    create_dependency_discovery_cronjob,
    create_pipeline_cronjob,
    delete_dependency_discovery_cronjob,
    delete_pipeline_cronjob,
)
from incidentfox_orchestrator.models import Base, ProvisioningRun

# TeamSlackChannel is deprecated - routing is now handled by Config Service
from incidentfox_orchestrator.webhooks.router import router as webhook_router


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_request_id() -> str:
    return __import__("uuid").uuid4().hex


def _lock_key(*parts: str) -> str:
    joined = "|".join([p.strip() for p in parts if p is not None])
    return joined[:512]


class _AdminCache:
    """Tiny TTL cache to reduce config_service /auth/me pressure."""

    def __init__(self) -> None:
        self._items: dict[str, tuple[float, dict[str, Any]]] = {}

    def _k(self, raw: str) -> str:
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, raw: str) -> Optional[dict[str, Any]]:
        now = __import__("time").time()
        k = self._k(raw)
        item = self._items.get(k)
        if not item:
            return None
        exp, data = item
        if exp <= now:
            self._items.pop(k, None)
            return None
        return data

    def set(self, raw: str, data: dict[str, Any], ttl_seconds: int) -> None:
        now = __import__("time").time()
        k = self._k(raw)
        self._items[k] = (now + max(1, int(ttl_seconds)), data)


def _log(event: str, **fields: Any) -> None:
    # Minimal structured logging without adding dependencies.
    try:
        payload = {
            "service": "orchestrator",
            "event": event,
            **fields,
        }
        print(__import__("json").dumps(payload, default=str))
    except Exception:
        # fall back to best-effort
        print(f"{event} {fields}")


# Metrics (Prometheus)
try:
    from prometheus_client import Counter, Histogram, generate_latest  # type: ignore
    from prometheus_client.exposition import CONTENT_TYPE_LATEST  # type: ignore

    _METRICS_ENABLED = True
    HTTP_REQUESTS_TOTAL = Counter(
        "incidentfox_orchestrator_http_requests_total",
        "Total HTTP requests",
        ["method", "path", "status_code"],
    )
    HTTP_REQUEST_DURATION_SECONDS = Histogram(
        "incidentfox_orchestrator_http_request_duration_seconds",
        "HTTP request duration in seconds",
        ["method", "path"],
    )
except Exception:
    _METRICS_ENABLED = False
    HTTP_REQUESTS_TOTAL = None  # type: ignore
    HTTP_REQUEST_DURATION_SECONDS = None  # type: ignore


class ProvisionRequest(BaseModel):
    org_id: str = Field(min_length=1, max_length=128)
    team_node_id: str = Field(min_length=1, max_length=128)
    slack_channel_ids: list[str] = Field(default_factory=list)
    idempotency_key: Optional[str] = Field(default=None, max_length=128)

    # K8s operations (optional)
    pipeline_schedule: Optional[str] = Field(
        default=None,
        description="Cron schedule for AI Pipeline (e.g., '0 2 * * *'). If set, creates a CronJob.",
    )
    deployment_mode: Optional[str] = Field(
        default="shared",
        description="Agent deployment mode: 'shared' (default) or 'dedicated' (enterprise)",
    )

    # K8s operations (optional)
    pipeline_schedule: Optional[str] = Field(
        default=None,
        description="Cron schedule for AI Pipeline (e.g., '0 2 * * *'). If set, creates a CronJob.",
    )
    deployment_mode: Optional[str] = Field(
        default="shared",
        description="Agent deployment mode: 'shared' (default) or 'dedicated' (enterprise)",
    )


class ProvisionResponse(BaseModel):
    provisioning_run_id: str
    status: str
    team_node_id: str
    org_id: str
    team_id: str
    team_token: Optional[str] = None
    pipeline_bootstrap: Optional[dict[str, Any]] = None
    pipeline_cronjob: Optional[dict[str, Any]] = None
    dedicated_deployment: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class ProvisionRunStatus(BaseModel):
    provisioning_run_id: str
    status: str
    steps: dict[str, Any]
    error: Optional[str] = None


class AgentRunRequest(BaseModel):
    org_id: str = Field(min_length=1, max_length=128)
    team_node_id: str = Field(min_length=1, max_length=128)
    agent_name: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=20_000)
    context: dict[str, Any] = Field(default_factory=dict)
    timeout: Optional[int] = None
    max_turns: Optional[int] = None


class AgentRunResponse(BaseModel):
    team_node_id: str
    agent_name: str
    agent_result: dict[str, Any]


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app_: FastAPI):
        # Enterprise default: do NOT silently mutate schema on startup.
        # For local dev you may set ORCHESTRATOR_AUTO_CREATE_TABLES=1.
        s = load_settings()
        init_engine(s.db_url)
        if (os.getenv("ORCHESTRATOR_AUTO_CREATE_TABLES", "0") or "0") == "1":
            Base.metadata.create_all(bind=get_engine())
        app_.state.config_service = ConfigServiceClient(base_url=s.config_service_url)
        app_.state.pipeline_api = PipelineApiClient(base_url=s.ai_pipeline_api_url)
        app_.state.agent_api = AgentApiClient(base_url=s.agent_api_url)
        app_.state.admin_cache = _AdminCache()
        # Audit client for recording agent runs
        internal_admin = (os.getenv("ORCHESTRATOR_INTERNAL_ADMIN_TOKEN") or "").strip()
        app_.state.audit_api = (
            AuditApiClient(base_url=s.config_service_url, internal_token=internal_admin)
            if internal_admin
            else None
        )

        # Telemetry collector client for license queries (optional)
        if s.telemetry_collector_url:
            app_.state.telemetry_collector = TelemetryCollectorClient(
                base_url=s.telemetry_collector_url
            )
            _log("telemetry_collector_configured", url=s.telemetry_collector_url)
        else:
            app_.state.telemetry_collector = None
            _log("telemetry_collector_not_configured")

        # Correlation service client for alert correlation (optional, feature-flagged)
        if s.correlation_service_url:
            app_.state.correlation_service = CorrelationServiceClient(
                base_url=s.correlation_service_url
            )
            _log("correlation_service_configured", url=s.correlation_service_url)
        else:
            app_.state.correlation_service = None
            _log("correlation_service_not_configured")

        # Slack Bolt integration for Slack webhooks
        slack_signing_secret = (os.getenv("SLACK_SIGNING_SECRET") or "").strip()
        if slack_signing_secret:
            from incidentfox_orchestrator.webhooks.slack_bolt_app import (
                SlackBoltIntegration,
            )

            app_.state.slack_bolt = SlackBoltIntegration(
                config_service=app_.state.config_service,
                agent_api=app_.state.agent_api,
                audit_api=app_.state.audit_api,
            )
            _log("slack_bolt_initialized")
        else:
            app_.state.slack_bolt = None
            _log("slack_bolt_not_configured", reason="SLACK_SIGNING_SECRET not set")

        yield

    app = FastAPI(title="IncidentFox Orchestrator", version="0.1.0", lifespan=lifespan)

    # Register webhook router (all external webhooks: Slack, GitHub, PagerDuty, Incident.io)
    app.include_router(webhook_router)

    # Pure ASGI middleware for request ID and logging.
    # NOTE: We use pure ASGI middleware instead of @app.middleware("http") because
    # BaseHTTPMiddleware breaks BackgroundTasks - it intercepts the response and
    # creates a new one that doesn't preserve background tasks.
    # See: https://github.com/encode/starlette/issues/919
    class RequestIdMiddleware:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return

            # Extract or generate request ID
            headers = dict(scope.get("headers", []))
            rid = (headers.get(b"x-request-id") or b"").decode(
                "utf-8"
            ) or _new_request_id()

            # Store in scope for access by route handlers
            scope["state"] = scope.get("state", {})
            scope["state"]["request_id"] = rid

            method = scope.get("method", "")
            path = scope.get("path", "")
            start = __import__("time").time()
            status_code = 500  # Default to 500 if we don't get a response

            async def send_wrapper(message):
                nonlocal status_code
                if message["type"] == "http.response.start":
                    status_code = message.get("status", 500)
                    # Add request ID to response headers
                    headers = list(message.get("headers", []))
                    headers.append((b"x-request-id", rid.encode("utf-8")))
                    message = {**message, "headers": headers}
                await send(message)

            try:
                await self.app(scope, receive, send_wrapper)
                # Log successful request after response is sent
                try:
                    if _METRICS_ENABLED:
                        HTTP_REQUESTS_TOTAL.labels(method, path, str(status_code)).inc()  # type: ignore[union-attr]
                        HTTP_REQUEST_DURATION_SECONDS.labels(method, path).observe(__import__("time").time() - start)  # type: ignore[union-attr]
                except Exception:
                    pass
                _log(
                    "http_request",
                    request_id=rid,
                    method=method,
                    path=path,
                    status_code=status_code,
                    duration_ms=int((__import__("time").time() - start) * 1000),
                )
            except Exception as e:
                try:
                    if _METRICS_ENABLED:
                        HTTP_REQUESTS_TOTAL.labels(method, path, "500").inc()  # type: ignore[union-attr]
                        HTTP_REQUEST_DURATION_SECONDS.labels(method, path).observe(__import__("time").time() - start)  # type: ignore[union-attr]
                except Exception:
                    pass
                _log(
                    "http_request_failed",
                    request_id=rid,
                    method=method,
                    path=path,
                    error=str(e),
                    duration_ms=int((__import__("time").time() - start) * 1000),
                )
                raise

    app.add_middleware(RequestIdMiddleware)

    @app.get("/health")
    def health():
        # DB health
        with db_session() as s:
            s.execute(sql_text("SELECT 1"))

        response = {"status": "ok"}

        # Include license info if telemetry collector is configured
        telemetry_collector: Optional[TelemetryCollectorClient] = getattr(
            app.state, "telemetry_collector", None
        )
        if telemetry_collector:
            try:
                license_info = telemetry_collector.get_license()
                response["license"] = {
                    "max_teams": license_info.get("entitlements", {}).get(
                        "max_teams", -1
                    ),
                    "max_runs_per_month": license_info.get("entitlements", {}).get(
                        "max_runs_per_month", -1
                    ),
                    "features": license_info.get("entitlements", {}).get(
                        "features", []
                    ),
                    "warnings": license_info.get("warnings", []),
                    "cached": license_info.get("cached", False),
                }
            except Exception:
                response["license"] = {"error": "telemetry_collector_unavailable"}

        return response

    @app.get("/metrics")
    def metrics():
        if not _METRICS_ENABLED:
            raise HTTPException(status_code=404, detail="metrics_disabled")
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)  # type: ignore[name-defined]

    def _require_admin(raw: str) -> dict[str, Any]:
        cfg: ConfigServiceClient = app.state.config_service
        cache: _AdminCache = app.state.admin_cache
        cached = cache.get(raw)
        if cached is not None:
            return cached
        data = cfg.auth_me_admin(raw)
        perms = data.get("permissions") or []
        if isinstance(perms, str):
            perms = [perms]
        require_admin_star = (
            os.getenv("ORCHESTRATOR_REQUIRE_ADMIN_STAR", "1") or "1"
        ).strip() == "1"
        if require_admin_star and ("admin:*" not in set(perms or [])):
            raise PermissionError("admin permissions required")
        ttl = int(os.getenv("ORCHESTRATOR_ADMIN_AUTH_CACHE_TTL_SECONDS", "15") or "15")
        cache.set(raw, data, ttl_seconds=ttl)
        return data

    def _require_admin_permission(principal: dict[str, Any], required: str) -> None:
        """
        Enforce a scoped permission while still allowing admin:*.

        Example required values:
        - admin:provision
        - admin:agent:run
        """
        perms = principal.get("permissions") or []
        if isinstance(perms, str):
            perms = [perms]
        s = set(perms or [])
        if "admin:*" in s:
            return
        if required in s:
            return
        raise HTTPException(status_code=403, detail="insufficient_permissions")

    def _acquire_team_lock(*, org_id: str, team_node_id: str):
        """
        Session-level advisory lock held across the full request.

        This prevents concurrent provisioning races across multiple replicas.
        """
        engine = get_engine()
        conn = engine.connect()
        # Only supported on Postgres.
        if (
            os.getenv("ORCHESTRATOR_DISABLE_ADVISORY_LOCKS", "0") or "0"
        ).strip() == "1":
            return conn, None
        if getattr(engine.dialect, "name", "") != "postgresql":
            return conn, None
        key = _lock_key("provision", org_id, team_node_id)
        conn.execute(sql_text("SELECT pg_advisory_lock(hashtext(:k))"), {"k": key})
        return conn, key

    @app.post("/api/v1/admin/provision/team", response_model=ProvisionResponse)
    def provision_team(
        body: ProvisionRequest,
        request: Request,
        authorization: str = Header(default=""),
        # Accept standard header: X-Admin-Token
        x_admin_token: str = Header(default="", alias="X-Admin-Token"),
    ):
        cfg: ConfigServiceClient = app.state.config_service
        pipeline: PipelineApiClient = app.state.pipeline_api
        raw = _extract_token(authorization, x_admin_token)
        if not raw:
            raise HTTPException(status_code=401, detail="Missing admin token")

        # Validate admin via config_service
        try:
            principal = _require_admin(raw)
            required_perm = (
                os.getenv("ORCHESTRATOR_REQUIRED_PERMISSION_PROVISION_TEAM")
                or "admin:provision"
            ).strip()
            if required_perm:
                _require_admin_permission(principal, required_perm)
        except PermissionError:
            raise HTTPException(status_code=403, detail="Admin role required")
        except httpx.HTTPError as e:
            raise HTTPException(
                status_code=502, detail=f"config_service_unavailable: {e}"
            ) from e

        # Check license quota if telemetry collector is configured
        telemetry_collector: Optional[TelemetryCollectorClient] = getattr(
            app.state, "telemetry_collector", None
        )
        if telemetry_collector:
            try:
                license_info = telemetry_collector.get_license()
                entitlements = license_info.get("entitlements", {})
                max_teams = entitlements.get("max_teams", -1)

                if max_teams != -1:  # -1 = unlimited
                    # Count currently provisioned teams
                    with db_session() as s:
                        current_teams = s.execute(sql_text("""
                                SELECT COUNT(DISTINCT concat(org_id, '/', team_node_id))
                                FROM provisioning_runs
                                WHERE status = 'completed'
                            """)).scalar() or 0

                    if current_teams >= max_teams:
                        _log(
                            "quota_exceeded_teams",
                            current_teams=current_teams,
                            max_teams=max_teams,
                            org_id=body.org_id,
                            team_node_id=body.team_node_id,
                        )
                        raise HTTPException(
                            status_code=403,
                            detail=f"Team limit reached: {current_teams}/{max_teams} teams. "
                            "Cannot provision new teams. Contact sales@incidentfox.ai to upgrade.",
                        )
            except HTTPException:
                raise
            except Exception as e:
                # Log but don't fail provisioning if license check fails
                _log("license_check_failed", error=str(e))

        # Check license quota if telemetry collector is configured
        telemetry_collector: Optional[TelemetryCollectorClient] = getattr(
            app.state, "telemetry_collector", None
        )
        if telemetry_collector:
            try:
                license_info = telemetry_collector.get_license()
                entitlements = license_info.get("entitlements", {})
                max_teams = entitlements.get("max_teams", -1)

                if max_teams != -1:  # -1 = unlimited
                    # Count currently provisioned teams
                    with db_session() as s:
                        current_teams = s.execute(sql_text("""
                                SELECT COUNT(DISTINCT concat(org_id, '/', team_node_id))
                                FROM provisioning_runs
                                WHERE status = 'completed'
                            """)).scalar() or 0

                    if current_teams >= max_teams:
                        _log(
                            "quota_exceeded_teams",
                            current_teams=current_teams,
                            max_teams=max_teams,
                            org_id=body.org_id,
                            team_node_id=body.team_node_id,
                        )
                        raise HTTPException(
                            status_code=403,
                            detail=f"Team limit reached: {current_teams}/{max_teams} teams. "
                            "Cannot provision new teams. Contact sales@incidentfox.ai to upgrade.",
                        )
            except HTTPException:
                raise
            except Exception as e:
                # Log but don't fail provisioning if license check fails
                _log("license_check_failed", error=str(e))

        team_id = body.team_node_id  # MVP decision: team_id == team_node_id

        # Serialize provisioning for this team to avoid races across replicas.
        lock_conn, lock_key = _acquire_team_lock(
            org_id=body.org_id, team_node_id=body.team_node_id
        )
        try:
            # Idempotency: if key is provided and a run already exists, return it.
            if body.idempotency_key:
                with db_session() as s:
                    existing_run = s.execute(
                        select(ProvisioningRun).where(
                            ProvisioningRun.org_id == body.org_id,
                            ProvisioningRun.team_node_id == body.team_node_id,
                            ProvisioningRun.idempotency_key == body.idempotency_key,
                        )
                    ).scalar_one_or_none()
                    if existing_run is not None:
                        return ProvisionResponse(
                            provisioning_run_id=str(existing_run.id),
                            status=str(existing_run.status),
                            team_node_id=body.team_node_id,
                            org_id=body.org_id,
                            team_id=team_id,
                            team_token=None,
                            pipeline_bootstrap=(existing_run.steps or {}).get(
                                "bootstrap"
                            ),
                            error=existing_run.error,
                        )

            # Create provisioning run record
            run = ProvisioningRun(
                org_id=body.org_id,
                team_node_id=body.team_node_id,
                idempotency_key=body.idempotency_key,
                status="running",
                steps={},
            )
            with db_session() as s:
                s.add(run)
                s.flush()
                run_id = run.id

            steps: dict[str, Any] = {}
            token: Optional[str] = None
            pipeline_bootstrap: Optional[dict[str, Any]] = None
            _log(
                "provision_start",
                request_id=getattr(request.state, "request_id", None),
                org_id=body.org_id,
                team_node_id=body.team_node_id,
                idempotency_key=body.idempotency_key,
                actor=principal.get("email") or principal.get("subject"),
                provisioning_run_id=str(run_id),
            )

            # 1) Patch team node config with routing + pipeline hints (self-describing).
            patch = {
                "routing": {
                    "slack_channel_ids": body.slack_channel_ids,
                    "team_id": team_id,
                },
                "ai_pipeline": {
                    "team_id": team_id,
                },
            }
            cfg.patch_node_config(
                raw, org_id=body.org_id, node_id=body.team_node_id, patch=patch
            )
            steps["config_patch"] = {"ok": True}

            # 2) Slack channel mapping is now handled by Config Service routing
            # The patch above sets routing.slack_channel_ids which Config Service indexes for lookup
            # No local table write needed - Config Service is the single source of truth
            steps["slack_channel_map"] = {
                "ok": True,
                "count": len(body.slack_channel_ids),
                "source": "config_service",
            }

            # 3) Team token (enterprise default: do not mint new tokens repeatedly).
            # If a non-revoked token exists, don't rotate implicitly; return no secret.
            existing = cfg.list_team_tokens(
                raw, org_id=body.org_id, team_node_id=body.team_node_id
            )
            has_active = any((row.get("revoked_at") is None) for row in existing)
            if has_active:
                token = None
                steps["team_token"] = {
                    "ok": True,
                    "created": False,
                    "existing_tokens": len(existing),
                }
            else:
                token = cfg.issue_team_token(
                    raw, org_id=body.org_id, team_node_id=body.team_node_id
                )
                steps["team_token"] = {"ok": True, "created": True}

            # 4) Trigger async bootstrap via pipeline API
            pipeline_bootstrap = pipeline.bootstrap(raw, team_id=team_id)
            steps["bootstrap"] = {"ok": True, "run": pipeline_bootstrap}

            # 5) Create AI Pipeline CronJob if schedule provided
            pipeline_cronjob_result: Optional[dict[str, Any]] = None
            if body.pipeline_schedule:
                try:
                    pipeline_cronjob_result = create_pipeline_cronjob(
                        org_id=body.org_id,
                        team_node_id=body.team_node_id,
                        schedule=body.pipeline_schedule,
                    )
                    if pipeline_cronjob_result.get("error"):
                        steps["pipeline_cronjob"] = {
                            "ok": False,
                            "error": pipeline_cronjob_result.get("error"),
                        }
                    else:
                        steps["pipeline_cronjob"] = {
                            "ok": True,
                            "result": pipeline_cronjob_result,
                        }
                except Exception as e:
                    _log(
                        "pipeline_cronjob_create_failed",
                        error=str(e),
                        org_id=body.org_id,
                        team_node_id=body.team_node_id,
                    )
                    steps["pipeline_cronjob"] = {"ok": False, "error": str(e)}

            # 6) Create dedicated agent Deployment if requested (enterprise feature)
            dedicated_deployment_result: Optional[dict[str, Any]] = None
            if body.deployment_mode == "dedicated":
                try:
                    dedicated_deployment_result = create_dedicated_agent_deployment(
                        org_id=body.org_id,
                        team_node_id=body.team_node_id,
                    )
                    if dedicated_deployment_result.get("error"):
                        steps["dedicated_deployment"] = {
                            "ok": False,
                            "error": dedicated_deployment_result.get("error"),
                        }
                    else:
                        steps["dedicated_deployment"] = {
                            "ok": True,
                            "result": dedicated_deployment_result,
                        }
                        # Store the service URL in config for routing
                        service_url = dedicated_deployment_result.get("service_url")
                        if service_url:
                            cfg.patch_node_config(
                                raw,
                                org_id=body.org_id,
                                node_id=body.team_node_id,
                                patch={"agent": {"dedicated_service_url": service_url}},
                            )
                except Exception as e:
                    _log(
                        "dedicated_deployment_create_failed",
                        error=str(e),
                        org_id=body.org_id,
                        team_node_id=body.team_node_id,
                    )
                    steps["dedicated_deployment"] = {"ok": False, "error": str(e)}

            # 5) Create AI Pipeline CronJob if schedule provided
            pipeline_cronjob_result: Optional[dict[str, Any]] = None
            if body.pipeline_schedule:
                try:
                    pipeline_cronjob_result = create_pipeline_cronjob(
                        org_id=body.org_id,
                        team_node_id=body.team_node_id,
                        schedule=body.pipeline_schedule,
                    )
                    if pipeline_cronjob_result.get("error"):
                        steps["pipeline_cronjob"] = {
                            "ok": False,
                            "error": pipeline_cronjob_result.get("error"),
                        }
                    else:
                        steps["pipeline_cronjob"] = {
                            "ok": True,
                            "result": pipeline_cronjob_result,
                        }
                except Exception as e:
                    _log(
                        "pipeline_cronjob_create_failed",
                        error=str(e),
                        org_id=body.org_id,
                        team_node_id=body.team_node_id,
                    )
                    steps["pipeline_cronjob"] = {"ok": False, "error": str(e)}

            # 6) Create dedicated agent Deployment if requested (enterprise feature)
            dedicated_deployment_result: Optional[dict[str, Any]] = None
            if body.deployment_mode == "dedicated":
                try:
                    dedicated_deployment_result = create_dedicated_agent_deployment(
                        org_id=body.org_id,
                        team_node_id=body.team_node_id,
                    )
                    if dedicated_deployment_result.get("error"):
                        steps["dedicated_deployment"] = {
                            "ok": False,
                            "error": dedicated_deployment_result.get("error"),
                        }
                    else:
                        steps["dedicated_deployment"] = {
                            "ok": True,
                            "result": dedicated_deployment_result,
                        }
                        # Store the service URL in config for routing
                        service_url = dedicated_deployment_result.get("service_url")
                        if service_url:
                            cfg.patch_node_config(
                                raw,
                                org_id=body.org_id,
                                node_id=body.team_node_id,
                                patch={"agent": {"dedicated_service_url": service_url}},
                            )
                except Exception as e:
                    _log(
                        "dedicated_deployment_create_failed",
                        error=str(e),
                        org_id=body.org_id,
                        team_node_id=body.team_node_id,
                    )
                    steps["dedicated_deployment"] = {"ok": False, "error": str(e)}

            with db_session() as s:
                r = s.get(ProvisioningRun, run_id)
                if r is not None:
                    r.status = "succeeded"
                    r.steps = steps
                    r.updated_at = _now()

            return ProvisionResponse(
                provisioning_run_id=str(run_id),
                status="succeeded",
                team_node_id=body.team_node_id,
                org_id=body.org_id,
                team_id=team_id,
                team_token=token,
                pipeline_bootstrap=pipeline_bootstrap,
                pipeline_cronjob=pipeline_cronjob_result,
                dedicated_deployment=dedicated_deployment_result,
            )

        except HTTPException as e:
            steps["error"] = str(e.detail)
            with db_session() as s:
                r = s.get(ProvisioningRun, run_id)
                if r is not None:
                    r.status = "failed"
                    r.steps = steps
                    r.error = str(e.detail)
                    r.updated_at = _now()
            payload = ProvisionResponse(
                provisioning_run_id=str(run_id),
                status="failed",
                team_node_id=body.team_node_id,
                org_id=body.org_id,
                team_id=team_id,
                team_token=None,
                pipeline_bootstrap=pipeline_bootstrap,
                error=str(e.detail),
            ).model_dump()
            return JSONResponse(
                status_code=int(e.status_code),
                content=payload,
                headers={"X-IncidentFox-Provisioning-Run-Id": str(run_id)},
            )
        except httpx.HTTPError as e:
            steps["error"] = f"upstream_error:{e}"
            with db_session() as s:
                r = s.get(ProvisioningRun, run_id)
                if r is not None:
                    r.status = "failed"
                    r.steps = steps
                    r.error = "upstream_error"
                    r.updated_at = _now()
            payload = ProvisionResponse(
                provisioning_run_id=str(run_id),
                status="failed",
                team_node_id=body.team_node_id,
                org_id=body.org_id,
                team_id=team_id,
                team_token=None,
                pipeline_bootstrap=pipeline_bootstrap,
                error="upstream_error",
            ).model_dump()
            return JSONResponse(
                status_code=502,
                content=payload,
                headers={"X-IncidentFox-Provisioning-Run-Id": str(run_id)},
            )
        except Exception:
            steps["error"] = "internal_error"
            with db_session() as s:
                r = s.get(ProvisioningRun, run_id)
                if r is not None:
                    r.status = "failed"
                    r.steps = steps
                    r.error = "internal_error"
                    r.updated_at = _now()
            payload = ProvisionResponse(
                provisioning_run_id=str(run_id),
                status="failed",
                team_node_id=body.team_node_id,
                org_id=body.org_id,
                team_id=team_id,
                team_token=None,
                pipeline_bootstrap=pipeline_bootstrap,
                error="internal_error",
            ).model_dump()
            return JSONResponse(
                status_code=500,
                content=payload,
                headers={"X-IncidentFox-Provisioning-Run-Id": str(run_id)},
            )
        finally:
            try:
                if lock_key is not None:
                    lock_conn.execute(
                        sql_text("SELECT pg_advisory_unlock(hashtext(:k))"),
                        {"k": lock_key},
                    )
            finally:
                lock_conn.close()

    @app.get(
        "/api/v1/admin/provision/runs/{provisioning_run_id}",
        response_model=ProvisionRunStatus,
    )
    def get_provision_run(
        provisioning_run_id: str,
        authorization: str = Header(default=""),
        x_admin_token: str = Header(default="", alias="X-Admin-Token"),
    ):
        cfg: ConfigServiceClient = app.state.config_service
        raw = _extract_token(authorization, x_admin_token)
        if not raw:
            raise HTTPException(status_code=401, detail="Missing admin token")
        try:
            principal = _require_admin(raw)
            required_perm = (
                os.getenv("ORCHESTRATOR_REQUIRED_PERMISSION_PROVISION_READ")
                or "admin:provision:read"
            ).strip()
            if required_perm:
                _require_admin_permission(principal, required_perm)
        except PermissionError:
            raise HTTPException(status_code=403, detail="Admin role required")
        except httpx.HTTPError as e:
            raise HTTPException(
                status_code=502, detail=f"config_service_unavailable: {e}"
            ) from e

        rid = UUID(provisioning_run_id)
        with db_session() as s:
            r = s.get(ProvisioningRun, rid)
            if r is None:
                raise HTTPException(status_code=404, detail="run_not_found")
            return ProvisionRunStatus(
                provisioning_run_id=str(r.id),
                status=r.status,
                steps=r.steps or {},
                error=r.error,
            )

    @app.post("/api/v1/admin/agents/run", response_model=AgentRunResponse)
    def run_agent_for_team(
        body: AgentRunRequest,
        authorization: str = Header(default=""),
        x_admin_token: str = Header(default="", alias="X-Admin-Token"),
    ):
        """
        Server-to-server agent run proxy.

        Enterprise contract: web_ui (or any admin tool) should call orchestrator, not the agent directly,
        so that team tokens never need to reach browsers/clients.
        """
        cfg: ConfigServiceClient = app.state.config_service
        agent_api: AgentApiClient = app.state.agent_api
        audit_api: Optional[AuditApiClient] = getattr(app.state, "audit_api", None)

        raw = _extract_token(authorization, x_admin_token)
        if not raw:
            raise HTTPException(status_code=401, detail="Missing admin token")
        try:
            principal = _require_admin(raw)
            required_perm = (
                os.getenv("ORCHESTRATOR_REQUIRED_PERMISSION_AGENT_RUN")
                or "admin:agent:run"
            ).strip()
            if required_perm:
                _require_admin_permission(principal, required_perm)
        except PermissionError:
            raise HTTPException(status_code=403, detail="Admin role required")
        except httpx.HTTPError as e:
            raise HTTPException(
                status_code=502, detail=f"config_service_unavailable: {e}"
            ) from e

        team_id = body.team_node_id
        run_id = __import__("uuid").uuid4().hex
        correlation_id = run_id

        # Mint a short-lived impersonation token (preferred over issuing long-lived team tokens).
        imp = cfg.issue_team_impersonation_token(
            raw, org_id=body.org_id, team_node_id=body.team_node_id
        )
        team_token = str(imp.get("token") or "")
        if not team_token:
            raise HTTPException(
                status_code=502, detail="config_service_impersonation_token_missing"
            )

        # Record agent run start
        if audit_api:
            audit_api.create_agent_run(
                run_id=run_id,
                org_id=body.org_id,
                team_node_id=body.team_node_id,
                correlation_id=correlation_id,
                trigger_source="api",
                trigger_actor="admin",
                trigger_message=body.message,
                agent_name=body.agent_name,
                metadata={"context": body.context or {}},
            )

        try:
            result = agent_api.run_agent(
                team_token=team_token,
                agent_name=body.agent_name,
                message=body.message,
                context=body.context,
                timeout=body.timeout,
                max_turns=body.max_turns,
                correlation_id=correlation_id,
            )

            # Record agent run completion
            if audit_api:
                out = result.get("output") or result.get("final_output")
                output_summary = None
                confidence = None
                if isinstance(out, dict):
                    output_summary = out.get("summary") or out.get("root_cause")
                    confidence = out.get("confidence")
                    if output_summary and len(output_summary) > 200:
                        output_summary = output_summary[:200] + "..."
                elif isinstance(out, str):
                    output_summary = out[:200] + "..." if len(out) > 200 else out

                status = "completed" if result.get("success", True) else "failed"
                audit_api.complete_agent_run(
                    org_id=body.org_id,
                    run_id=run_id,
                    status=status,
                    tool_calls_count=result.get("tool_calls_count"),
                    output_summary=output_summary,
                    output_json=result.get("output"),
                    confidence=confidence,
                )

        except httpx.HTTPError as e:
            # Record failed run
            if audit_api:
                audit_api.complete_agent_run(
                    org_id=body.org_id,
                    run_id=run_id,
                    status="failed",
                    error_message=str(e),
                )
            raise HTTPException(
                status_code=502, detail=f"agent_upstream_error: {e}"
            ) from e

        return AgentRunResponse(
            team_node_id=team_id, agent_name=body.agent_name, agent_result=result
        )

    # ═══════════════════════════════════════════════════════════════════════════
    # AI Pipeline Orchestration (C2)
    # ═══════════════════════════════════════════════════════════════════════════

    class PipelineTriggerRequest(BaseModel):
        org_id: str
        team_node_id: str

    class PipelineTriggerResponse(BaseModel):
        ok: bool
        job_name: Optional[str] = None
        message: str = ""

    @app.post("/api/v1/admin/pipeline/trigger", response_model=PipelineTriggerResponse)
    def trigger_pipeline_run(
        body: PipelineTriggerRequest,
        authorization: str = Header(default=""),
        x_admin_token: str = Header(default="", alias="X-Admin-Token"),
    ):
        """
        Manually trigger an AI Pipeline run for a team.

        This creates a one-off Kubernetes Job (not a CronJob) that runs the pipeline
        immediately for the specified team.
        """
        from incidentfox_orchestrator.k8s.cronjobs import K8S_AVAILABLE

        raw = _extract_token(authorization, x_admin_token)
        if not raw:
            raise HTTPException(status_code=401, detail="Missing admin token")
        try:
            principal = _require_admin(raw)
            _require_admin_permission(principal, "admin:pipeline:trigger")
        except PermissionError:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        except httpx.HTTPError as e:
            raise HTTPException(
                status_code=502, detail=f"config_service_unavailable: {e}"
            ) from e

        if not K8S_AVAILABLE:
            raise HTTPException(status_code=503, detail="kubernetes_not_available")

        # Trigger via Pipeline API (which creates a K8s Job)
        pipeline: PipelineApiClient = app.state.pipeline_api
        try:
            result = pipeline.trigger_run(
                raw, team_id=body.team_node_id, org_id=body.org_id
            )
            _log(
                "pipeline_manual_trigger",
                org_id=body.org_id,
                team_node_id=body.team_node_id,
                result=result,
            )
            return PipelineTriggerResponse(
                ok=True,
                job_name=result.get("job_name") or result.get("run_id"),
                message="Pipeline run triggered",
            )
        except Exception as e:
            _log("pipeline_manual_trigger_failed", error=str(e))
            return PipelineTriggerResponse(ok=False, message=str(e))

    # ═══════════════════════════════════════════════════════════════════════════
    # Dependency Discovery CronJob Management
    # ═══════════════════════════════════════════════════════════════════════════

    class SyncCronJobsRequest(BaseModel):
        org_id: str
        team_node_id: str

    class SyncCronJobsResponse(BaseModel):
        ok: bool
        ai_pipeline: Optional[dict[str, Any]] = None
        dependency_discovery: Optional[dict[str, Any]] = None
        message: str = ""

    @app.post("/api/v1/admin/teams/sync-cronjobs", response_model=SyncCronJobsResponse)
    def sync_team_cronjobs(
        body: SyncCronJobsRequest,
        authorization: str = Header(default=""),
        x_admin_token: str = Header(default="", alias="X-Admin-Token"),
    ):
        """
        Sync CronJobs based on team configuration.

        Reads the team's effective config from Config Service and creates/updates/deletes
        CronJobs accordingly. Call this after updating team config to apply changes.

        Handles:
        - AI Pipeline CronJob (based on ai_pipeline.enabled)
        - Dependency Discovery CronJob (based on dependency_discovery.enabled)
        """
        from incidentfox_orchestrator.k8s.cronjobs import K8S_AVAILABLE

        raw = _extract_token(authorization, x_admin_token)
        if not raw:
            raise HTTPException(status_code=401, detail="Missing admin token")
        try:
            principal = _require_admin(raw)
            _require_admin_permission(principal, "admin:cronjobs:sync")
        except PermissionError:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        except httpx.HTTPError as e:
            raise HTTPException(
                status_code=502, detail=f"config_service_unavailable: {e}"
            ) from e

        if not K8S_AVAILABLE:
            return SyncCronJobsResponse(ok=False, message="kubernetes_not_available")

        # Fetch team's effective config
        cfg: ConfigServiceClient = app.state.config_service
        try:
            team_config = cfg.get_effective_config_for_node(
                raw, org_id=body.org_id, node_id=body.team_node_id
            )
        except Exception as e:
            _log(
                "sync_cronjobs_config_fetch_failed",
                org_id=body.org_id,
                team_node_id=body.team_node_id,
                error=str(e),
            )
            return SyncCronJobsResponse(ok=False, message=f"config_fetch_failed: {e}")

        errors: list[str] = []
        pipeline_result: Optional[dict[str, Any]] = None
        dep_result: Optional[dict[str, Any]] = None

        # ─────────────────────────────────────────────────────────────────────
        # AI Pipeline CronJob
        # ─────────────────────────────────────────────────────────────────────
        pipeline_config = team_config.get("ai_pipeline", {})
        pipeline_enabled = pipeline_config.get("enabled", False)
        pipeline_schedule = pipeline_config.get("schedule", "0 2 * * *")

        if pipeline_enabled:
            try:
                pipeline_result = create_pipeline_cronjob(
                    org_id=body.org_id,
                    team_node_id=body.team_node_id,
                    schedule=pipeline_schedule,
                )
                if pipeline_result.get("error"):
                    errors.append(f"ai_pipeline: {pipeline_result.get('error')}")
                    _log(
                        "pipeline_cronjob_sync_failed",
                        org_id=body.org_id,
                        team_node_id=body.team_node_id,
                        error=pipeline_result.get("error"),
                    )
                else:
                    _log(
                        "pipeline_cronjob_synced",
                        org_id=body.org_id,
                        team_node_id=body.team_node_id,
                        schedule=pipeline_schedule,
                        action="created_or_updated",
                    )
            except Exception as e:
                errors.append(f"ai_pipeline: {e}")
                _log(
                    "pipeline_cronjob_sync_exception",
                    org_id=body.org_id,
                    team_node_id=body.team_node_id,
                    error=str(e),
                )
                pipeline_result = {"error": str(e)}
        else:
            try:
                pipeline_result = delete_pipeline_cronjob(
                    org_id=body.org_id,
                    team_node_id=body.team_node_id,
                )
                if pipeline_result.get("deleted"):
                    _log(
                        "pipeline_cronjob_synced",
                        org_id=body.org_id,
                        team_node_id=body.team_node_id,
                        action="deleted",
                    )
                elif pipeline_result.get("reason") == "not_found":
                    pipeline_result = {"skipped": True, "reason": "not_found"}
            except Exception as e:
                errors.append(f"ai_pipeline_delete: {e}")
                _log(
                    "pipeline_cronjob_delete_exception",
                    org_id=body.org_id,
                    team_node_id=body.team_node_id,
                    error=str(e),
                )
                pipeline_result = {"error": str(e)}

        # ─────────────────────────────────────────────────────────────────────
        # Dependency Discovery CronJob
        # ─────────────────────────────────────────────────────────────────────
        dep_config = team_config.get("dependency_discovery", {})
        dep_enabled = dep_config.get("enabled", False)
        dep_schedule = dep_config.get("schedule", "0 */2 * * *")

        if dep_enabled:
            try:
                dep_result = create_dependency_discovery_cronjob(
                    org_id=body.org_id,
                    team_node_id=body.team_node_id,
                    schedule=dep_schedule,
                )
                if dep_result.get("error"):
                    errors.append(f"dependency_discovery: {dep_result.get('error')}")
                    _log(
                        "dependency_cronjob_sync_failed",
                        org_id=body.org_id,
                        team_node_id=body.team_node_id,
                        error=dep_result.get("error"),
                    )
                else:
                    _log(
                        "dependency_cronjob_synced",
                        org_id=body.org_id,
                        team_node_id=body.team_node_id,
                        schedule=dep_schedule,
                        action="created_or_updated",
                    )
            except Exception as e:
                errors.append(f"dependency_discovery: {e}")
                _log(
                    "dependency_cronjob_sync_exception",
                    org_id=body.org_id,
                    team_node_id=body.team_node_id,
                    error=str(e),
                )
                dep_result = {"error": str(e)}
        else:
            try:
                dep_result = delete_dependency_discovery_cronjob(
                    org_id=body.org_id,
                    team_node_id=body.team_node_id,
                )
                if dep_result.get("deleted"):
                    _log(
                        "dependency_cronjob_synced",
                        org_id=body.org_id,
                        team_node_id=body.team_node_id,
                        action="deleted",
                    )
                elif dep_result.get("reason") == "not_found":
                    dep_result = {"skipped": True, "reason": "not_found"}
            except Exception as e:
                errors.append(f"dependency_discovery_delete: {e}")
                _log(
                    "dependency_cronjob_delete_exception",
                    org_id=body.org_id,
                    team_node_id=body.team_node_id,
                    error=str(e),
                )
                dep_result = {"error": str(e)}

        return SyncCronJobsResponse(
            ok=len(errors) == 0,
            ai_pipeline=pipeline_result,
            dependency_discovery=dep_result,
            message="CronJobs synced" if not errors else f"Errors: {', '.join(errors)}",
        )

    @app.post("/api/v1/teams/me/sync-cronjobs", response_model=SyncCronJobsResponse)
    def sync_my_team_cronjobs(
        authorization: str = Header(default=""),
        x_incidentfox_team_token: str = Header(
            default="", alias="X-IncidentFox-Team-Token"
        ),
    ):
        """
        Sync CronJobs for the authenticated team.

        Team-facing endpoint - allows team users to enable/disable scheduled features
        for their own team without requiring admin permissions.

        Handles:
        - AI Pipeline CronJob (based on ai_pipeline.enabled)
        - Dependency Discovery CronJob (based on dependency_discovery.enabled)
        """
        from incidentfox_orchestrator.k8s.cronjobs import K8S_AVAILABLE

        # Extract team token
        raw = _extract_token(authorization, x_incidentfox_team_token)
        if not raw:
            raise HTTPException(status_code=401, detail="Missing team token")

        # Validate team token and get identity
        cfg: ConfigServiceClient = app.state.config_service
        try:
            # Use the team token to get effective config (validates the token)
            team_config = cfg.get_effective_config(team_token=raw)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise HTTPException(status_code=401, detail="Invalid team token")
            raise HTTPException(
                status_code=502, detail=f"config_service_error: {e}"
            ) from e
        except Exception as e:
            _log("team_sync_cronjobs_config_fetch_failed", error=str(e))
            return SyncCronJobsResponse(ok=False, message=f"config_fetch_failed: {e}")

        # Extract org_id and team_node_id from the config response
        # The config service returns these in the response headers or we need to
        # call /auth/me to get them
        try:
            auth_url = f"{cfg.base_url}/api/v1/auth/me"
            with httpx.Client(timeout=10.0) as c:
                auth_res = c.get(auth_url, headers={"Authorization": f"Bearer {raw}"})
            auth_res.raise_for_status()
            auth_data = auth_res.json()
            org_id = auth_data.get("org_id")
            team_node_id = auth_data.get("team_node_id")
            if not org_id or not team_node_id:
                raise HTTPException(
                    status_code=400, detail="Cannot determine org_id/team_node_id"
                )
        except httpx.HTTPError as e:
            raise HTTPException(
                status_code=502, detail=f"auth_lookup_failed: {e}"
            ) from e

        if not K8S_AVAILABLE:
            return SyncCronJobsResponse(ok=False, message="kubernetes_not_available")

        errors: list[str] = []
        pipeline_result: Optional[dict[str, Any]] = None
        dep_result: Optional[dict[str, Any]] = None

        # ─────────────────────────────────────────────────────────────────────
        # AI Pipeline CronJob
        # ─────────────────────────────────────────────────────────────────────
        pipeline_config = team_config.get("ai_pipeline", {})
        pipeline_enabled = pipeline_config.get("enabled", False)
        pipeline_schedule = pipeline_config.get("schedule", "0 2 * * *")

        if pipeline_enabled:
            try:
                pipeline_result = create_pipeline_cronjob(
                    org_id=org_id,
                    team_node_id=team_node_id,
                    schedule=pipeline_schedule,
                )
                if pipeline_result.get("error"):
                    errors.append(f"ai_pipeline: {pipeline_result.get('error')}")
                else:
                    _log(
                        "team_pipeline_cronjob_synced",
                        org_id=org_id,
                        team_node_id=team_node_id,
                        schedule=pipeline_schedule,
                        action="created_or_updated",
                    )
            except Exception as e:
                errors.append(f"ai_pipeline: {e}")
                pipeline_result = {"error": str(e)}
        else:
            try:
                pipeline_result = delete_pipeline_cronjob(
                    org_id=org_id, team_node_id=team_node_id
                )
                if pipeline_result.get("deleted"):
                    _log(
                        "team_pipeline_cronjob_synced",
                        org_id=org_id,
                        team_node_id=team_node_id,
                        action="deleted",
                    )
                elif pipeline_result.get("reason") == "not_found":
                    pipeline_result = {"skipped": True, "reason": "not_found"}
            except Exception as e:
                errors.append(f"ai_pipeline_delete: {e}")
                pipeline_result = {"error": str(e)}

        # ─────────────────────────────────────────────────────────────────────
        # Dependency Discovery CronJob
        # ─────────────────────────────────────────────────────────────────────
        dep_config = team_config.get("dependency_discovery", {})
        dep_enabled = dep_config.get("enabled", False)
        dep_schedule = dep_config.get("schedule", "0 */2 * * *")

        if dep_enabled:
            try:
                dep_result = create_dependency_discovery_cronjob(
                    org_id=org_id,
                    team_node_id=team_node_id,
                    schedule=dep_schedule,
                )
                if dep_result.get("error"):
                    errors.append(f"dependency_discovery: {dep_result.get('error')}")
                else:
                    _log(
                        "team_dependency_cronjob_synced",
                        org_id=org_id,
                        team_node_id=team_node_id,
                        schedule=dep_schedule,
                        action="created_or_updated",
                    )
            except Exception as e:
                errors.append(f"dependency_discovery: {e}")
                dep_result = {"error": str(e)}
        else:
            try:
                dep_result = delete_dependency_discovery_cronjob(
                    org_id=org_id, team_node_id=team_node_id
                )
                if dep_result.get("deleted"):
                    _log(
                        "team_dependency_cronjob_synced",
                        org_id=org_id,
                        team_node_id=team_node_id,
                        action="deleted",
                    )
                elif dep_result.get("reason") == "not_found":
                    dep_result = {"skipped": True, "reason": "not_found"}
            except Exception as e:
                errors.append(f"dependency_discovery_delete: {e}")
                dep_result = {"error": str(e)}

        return SyncCronJobsResponse(
            ok=len(errors) == 0,
            ai_pipeline=pipeline_result,
            dependency_discovery=dep_result,
            message="CronJobs synced" if not errors else f"Errors: {', '.join(errors)}",
        )

    # ═══════════════════════════════════════════════════════════════════════════
    # Agent Deployment Management (C1)
    # ═══════════════════════════════════════════════════════════════════════════

    class DeploymentStatusResponse(BaseModel):
        name: Optional[str] = None
        namespace: Optional[str] = None
        mode: str = "shared"  # "shared" or "dedicated"
        replicas: Optional[int] = None
        ready_replicas: Optional[int] = None
        available_replicas: Optional[int] = None
        service_url: Optional[str] = None
        conditions: Optional[list] = None
        error: Optional[str] = None

    @app.get(
        "/api/v1/admin/teams/{org_id}/{team_node_id}/deployment",
        response_model=DeploymentStatusResponse,
    )
    def get_team_deployment_status(
        org_id: str,
        team_node_id: str,
        authorization: str = Header(default=""),
        x_admin_token: str = Header(default="", alias="X-Admin-Token"),
    ):
        """
        Get the agent deployment status for a team.

        Returns information about whether the team uses shared or dedicated agent deployment,
        and the current status of the deployment.
        """
        from incidentfox_orchestrator.k8s.deployments import (
            K8S_AVAILABLE,
            get_dedicated_agent_deployment,
        )

        raw = _extract_token(authorization, x_admin_token)
        if not raw:
            raise HTTPException(status_code=401, detail="Missing admin token")
        try:
            principal = _require_admin(raw)
            _require_admin_permission(principal, "admin:deployment:read")
        except PermissionError:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        except httpx.HTTPError as e:
            raise HTTPException(
                status_code=502, detail=f"config_service_unavailable: {e}"
            ) from e

        if not K8S_AVAILABLE:
            return DeploymentStatusResponse(
                mode="shared", error="kubernetes_not_available"
            )

        # Check if team has a dedicated deployment
        deployment_info = get_dedicated_agent_deployment(
            org_id=org_id, team_node_id=team_node_id
        )

        if deployment_info:
            return DeploymentStatusResponse(
                mode="dedicated",
                name=deployment_info.get("name"),
                namespace=deployment_info.get("namespace"),
                replicas=deployment_info.get("replicas"),
                ready_replicas=deployment_info.get("ready_replicas"),
                available_replicas=deployment_info.get("available_replicas"),
                service_url=deployment_info.get("service_url"),
                conditions=deployment_info.get("conditions"),
            )
        else:
            # Team uses shared deployment
            return DeploymentStatusResponse(mode="shared")

    @app.get(
        "/api/v1/admin/teams/{org_id}/{team_node_id}/pipeline", response_model=dict
    )
    def get_team_pipeline_status(
        org_id: str,
        team_node_id: str,
        authorization: str = Header(default=""),
        x_admin_token: str = Header(default="", alias="X-Admin-Token"),
    ):
        """
        Get the AI Pipeline CronJob status for a team.
        """
        from incidentfox_orchestrator.k8s.cronjobs import (
            K8S_AVAILABLE,
            get_pipeline_cronjob,
        )

        raw = _extract_token(authorization, x_admin_token)
        if not raw:
            raise HTTPException(status_code=401, detail="Missing admin token")
        try:
            principal = _require_admin(raw)
            _require_admin_permission(principal, "admin:pipeline:read")
        except PermissionError:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        except httpx.HTTPError as e:
            raise HTTPException(
                status_code=502, detail=f"config_service_unavailable: {e}"
            ) from e

        if not K8S_AVAILABLE:
            return {"configured": False, "error": "kubernetes_not_available"}

        cronjob_info = get_pipeline_cronjob(org_id=org_id, team_node_id=team_node_id)

        if cronjob_info:
            return {
                "configured": True,
                "name": cronjob_info.get("name"),
                "namespace": cronjob_info.get("namespace"),
                "schedule": cronjob_info.get("schedule"),
                "suspended": cronjob_info.get("suspended"),
                "last_schedule_time": cronjob_info.get("last_schedule_time"),
                "active_jobs": cronjob_info.get("active_jobs"),
            }
        else:
            return {"configured": False}

    # ═══════════════════════════════════════════════════════════════════════════
    # Team Deprovisioning
    # ═══════════════════════════════════════════════════════════════════════════

    class DeprovisionRequest(BaseModel):
        org_id: str
        team_node_id: str
        delete_k8s_resources: bool = True
        dry_run: bool = False

    class DeprovisionResponse(BaseModel):
        ok: bool
        dry_run: bool = False
        deleted: dict = {}
        errors: list = []

    @app.post("/api/v1/admin/deprovision/team", response_model=DeprovisionResponse)
    def deprovision_team(
        body: DeprovisionRequest,
        authorization: str = Header(default=""),
        x_admin_token: str = Header(default="", alias="X-Admin-Token"),
    ):
        """
        Deprovision a team - cleanup all K8s resources (deployment, cronjob).

        This does NOT delete config from Config Service, only infrastructure resources.
        """
        from incidentfox_orchestrator.k8s.cronjobs import delete_pipeline_cronjob
        from incidentfox_orchestrator.k8s.deployments import (
            K8S_AVAILABLE,
            delete_dedicated_agent_deployment,
        )

        raw = _extract_token(authorization, x_admin_token)
        if not raw:
            raise HTTPException(status_code=401, detail="Missing admin token")
        try:
            principal = _require_admin(raw)
            _require_admin_permission(principal, "admin:deprovision")
        except PermissionError:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        except httpx.HTTPError as e:
            raise HTTPException(
                status_code=502, detail=f"config_service_unavailable: {e}"
            ) from e

        deleted = {}
        errors = []

        if body.dry_run:
            _log(
                "deprovision_dry_run",
                org_id=body.org_id,
                team_node_id=body.team_node_id,
            )
            return DeprovisionResponse(ok=True, dry_run=True, deleted={}, errors=[])

        if not body.delete_k8s_resources:
            return DeprovisionResponse(ok=True, deleted={}, errors=[])

        if not K8S_AVAILABLE:
            return DeprovisionResponse(ok=False, errors=["kubernetes_not_available"])

        # Delete dedicated deployment (if exists)
        try:
            result = delete_dedicated_agent_deployment(
                org_id=body.org_id, team_node_id=body.team_node_id
            )
            if result.get("deployment_deleted") or result.get("service_deleted"):
                deleted["dedicated_deployment"] = result
            elif result.get("deployment_reason") == "not_found":
                deleted["dedicated_deployment"] = "not_found"
        except Exception as e:
            errors.append(f"deployment: {e}")

        # Delete pipeline cronjob (if exists)
        try:
            result = delete_pipeline_cronjob(
                org_id=body.org_id, team_node_id=body.team_node_id
            )
            if result.get("deleted"):
                deleted["pipeline_cronjob"] = result
            elif result.get("reason") == "not_found":
                deleted["pipeline_cronjob"] = "not_found"
        except Exception as e:
            errors.append(f"cronjob: {e}")

        # Delete dependency discovery cronjob (if exists)
        try:
            result = delete_dependency_discovery_cronjob(
                org_id=body.org_id, team_node_id=body.team_node_id
            )
            if result.get("deleted"):
                deleted["dependency_discovery_cronjob"] = result
            elif result.get("reason") == "not_found":
                deleted["dependency_discovery_cronjob"] = "not_found"
        except Exception as e:
            errors.append(f"dependency_cronjob: {e}")

        # Note: Slack channel mappings are in Config Service routing (not local table)
        # Deprovisioning routing data should be done via Config Service API if needed
        deleted["slack_channel_mappings"] = "handled_by_config_service"

        _log(
            "deprovision_complete",
            org_id=body.org_id,
            team_node_id=body.team_node_id,
            deleted=deleted,
            errors=errors,
        )

        return DeprovisionResponse(
            ok=len(errors) == 0,
            deleted=deleted,
            errors=errors,
        )

    return app


app = create_app()

from fastapi import FastAPI, Request
from fastapi.responses import Response

from src.api.routes.admin import router as admin_router
from src.api.routes.audit import router as audit_router
from src.api.routes.auth_me import router as auth_router
from src.api.routes.config_v2 import router as config_v2_router
from src.api.routes.dependencies import router as dependencies_router
from src.api.routes.github import router as github_router
from src.api.routes.health import router as health_router
from src.api.routes.integration_schemas import router as integration_schemas_router
from src.api.routes.internal import router as internal_router
from src.api.routes.k8s_clusters import admin_router as k8s_admin_router
from src.api.routes.k8s_clusters import internal_router as k8s_internal_router
from src.api.routes.k8s_clusters import router as k8s_clusters_router
from src.api.routes.metrics import router as metrics_router
from src.api.routes.remediation import router as remediation_router
from src.api.routes.scheduled_jobs import (
    internal_router as scheduled_jobs_internal_router,
)
from src.api.routes.scheduled_jobs import router as scheduled_jobs_router
from src.api.routes.security import router as security_router
from src.api.routes.sso import router as sso_router
from src.api.routes.teaching import router as teaching_router
from src.api.routes.team import router as team_router
from src.api.routes.templates import router as templates_router
from src.api.routes.tool_metadata import router as tool_metadata_router
from src.api.routes.ui import router as ui_router
from src.api.routes.visitor import router as visitor_router
from src.core.audit_log import app_logger, configure_logging, new_request_id
from src.core.metrics import HTTP_REQUEST_DURATION_SECONDS, HTTP_REQUESTS_TOTAL
from src.core.yaml_config import YAMLConfigManager, is_local_mode
from src.core.yaml_seeder import seed_from_yaml
from src.core.yaml_validator import validate_yaml_config
from src.core.yaml_watcher import start_yaml_watcher_background
from src.db.session import get_session_maker


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="IncidentFox Config Service", version="0.1.0")

    @app.on_event("startup")
    async def startup_event():
        """Seed configuration from YAML in local development mode."""
        if is_local_mode():
            logger = app_logger().bind(component="startup")
            logger.info("Running in local mode, seeding config from YAML...")

            # Validate YAML before seeding — warn-only at startup so a bad file
            # never prevents the service from coming up
            try:
                yaml_manager = YAMLConfigManager("config/local.yaml")
                resolved = yaml_manager.load_config()
                result = validate_yaml_config(resolved)
                if result.warnings:
                    for w in result.warnings:
                        logger.warning(f"⚠️  YAML warning: {w}")
                if not result.is_valid:
                    logger.warning(
                        "⚠️  local.yaml has validation errors (proceeding anyway):\n"
                        + result.format()
                    )
            except Exception as e:
                logger.warning(f"Could not validate local.yaml: {e}")

            # Create database session
            SessionLocal = get_session_maker()
            db = SessionLocal()
            try:
                # Use force=True to always update config from YAML in local mode
                seeded = seed_from_yaml(
                    db, config_file_path="config/local.yaml", force=True
                )
                if seeded:
                    logger.info("✅ Configuration seeded from local.yaml")
                else:
                    logger.info("ℹ️  Configuration already exists, skipping seed")
            except Exception as e:
                logger.error(f"Failed to seed config from YAML: {e}")
            finally:
                db.close()

            # Start file watcher for hot-reload
            try:
                start_yaml_watcher_background("config/local.yaml")
            except Exception as e:
                logger.error(f"Failed to start file watcher: {e}")

    app.include_router(ui_router)
    app.include_router(health_router)
    app.include_router(metrics_router)
    app.include_router(auth_router)
    app.include_router(admin_router)
    app.include_router(security_router)
    app.include_router(audit_router, prefix="/api/v1/admin/orgs/{org_id}")
    app.include_router(sso_router)
    app.include_router(team_router)
    app.include_router(remediation_router)
    app.include_router(teaching_router)
    app.include_router(config_v2_router)
    app.include_router(internal_router)
    app.include_router(templates_router)
    app.include_router(integration_schemas_router)
    app.include_router(tool_metadata_router)
    app.include_router(dependencies_router)
    app.include_router(visitor_router)
    app.include_router(k8s_clusters_router)
    app.include_router(k8s_internal_router)
    app.include_router(k8s_admin_router)
    app.include_router(github_router)
    app.include_router(scheduled_jobs_router)
    app.include_router(scheduled_jobs_internal_router)

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        rid = request.headers.get("x-request-id") or new_request_id()
        request.state.request_id = rid
        response: Response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        log = app_logger().bind(
            request_id=getattr(request.state, "request_id", None),
            method=request.method,
            path=str(request.url.path),
        )
        start = __import__("time").time()
        try:
            response: Response = await call_next(request)
            duration_ms = int((__import__("time").time() - start) * 1000)
            log.info(
                "http_request",
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
            # metrics
            path = str(request.url.path)
            HTTP_REQUESTS_TOTAL.labels(
                request.method, path, str(response.status_code)
            ).inc()
            HTTP_REQUEST_DURATION_SECONDS.labels(request.method, path).observe(
                (__import__("time").time() - start)
            )
            return response
        except Exception:
            duration_ms = int((__import__("time").time() - start) * 1000)
            log.exception("http_request_failed", duration_ms=duration_ms)
            path = str(request.url.path)
            HTTP_REQUESTS_TOTAL.labels(request.method, path, "500").inc()
            HTTP_REQUEST_DURATION_SECONDS.labels(request.method, path).observe(
                (__import__("time").time() - start)
            )
            raise

    return app


app = create_app()

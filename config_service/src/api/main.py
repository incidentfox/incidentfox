from fastapi import FastAPI, Request
from fastapi.responses import Response

from src.api.routes.admin import router as admin_router
from src.api.routes.audit import router as audit_router
from src.api.routes.auth_me import router as auth_router
from src.api.routes.config_v2 import router as config_v2_router
from src.api.routes.dependencies import router as dependencies_router
from src.api.routes.health import router as health_router
from src.api.routes.integration_schemas import router as integration_schemas_router
from src.api.routes.internal import router as internal_router
from src.api.routes.metrics import router as metrics_router
from src.api.routes.remediation import router as remediation_router
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


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="IncidentFox Config Service", version="0.1.0")
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

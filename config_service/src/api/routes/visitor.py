"""
Visitor Playground API Routes.

These endpoints handle visitor access to the public playground,
including login, session management, and heartbeat functionality.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.orm import Session

from src.db.session import db_session
from src.services.visitor_session_manager import VisitorSessionManager

router = APIRouter(prefix="/api/v1/visitor", tags=["visitor"])


def get_db():
    """Get database session."""
    with db_session() as session:
        yield session


# =============================================================================
# Request/Response Models
# =============================================================================


class VisitorLoginRequest(BaseModel):
    """Request body for visitor login."""

    email: EmailStr
    source: Optional[str] = None  # Optional attribution source

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        # Basic sanity check - EmailStr already validates format
        if len(v) > 256:
            raise ValueError("Email too long")
        return v.lower().strip()


class VisitorLoginResponse(BaseModel):
    """Response for visitor login."""

    session_id: str
    status: str  # "active" | "queued"
    queue_position: Optional[int] = None
    estimated_wait_seconds: Optional[int] = None
    token: Optional[str] = None  # JWT for authenticated requests


class SessionStatusResponse(BaseModel):
    """Response for session status/heartbeat."""

    status: str  # "active" | "warned" | "queued" | "expired"
    queue_position: Optional[int] = None
    warning_seconds_remaining: Optional[int] = None
    estimated_wait_seconds: Optional[int] = None
    reason: Optional[str] = None  # For expired status


class EndSessionResponse(BaseModel):
    """Response for ending a session."""

    status: str  # "ended" | "not_found"


# =============================================================================
# Endpoints
# =============================================================================


@router.post("/login", response_model=VisitorLoginResponse)
def visitor_login(
    body: VisitorLoginRequest,
    db: Session = Depends(get_db),
):
    """
    Start or queue a visitor session.

    If no one is currently using the playground, the visitor gets immediate access.
    Otherwise, they're added to a queue and must wait for their turn.

    The email is collected for marketing/outreach purposes.
    """
    manager = VisitorSessionManager()
    result = manager.try_login(db, body.email, source=body.source)

    return VisitorLoginResponse(
        session_id=result["session_id"],
        status=result["status"],
        queue_position=result.get("queue_position"),
        estimated_wait_seconds=result.get("estimated_wait_seconds"),
        token=result.get("token"),
    )


@router.post("/heartbeat", response_model=SessionStatusResponse)
def heartbeat(
    db: Session = Depends(get_db),
    authorization: str = Header(default=""),
):
    """
    Update session activity and get current status.

    Frontend should call this every 30 seconds while the tab is open.
    This keeps the session alive and returns the current status
    (active, warned if about to be kicked, queued, or expired).
    """
    # Extract session ID from the authorization token
    session_id = _extract_session_id(authorization)
    if not session_id:
        raise HTTPException(status_code=401, detail="Missing or invalid visitor token")

    manager = VisitorSessionManager()
    result = manager.heartbeat(db, session_id)

    return SessionStatusResponse(
        status=result["status"],
        queue_position=result.get("queue_position"),
        warning_seconds_remaining=result.get("warning_seconds_remaining"),
        estimated_wait_seconds=result.get("estimated_wait_seconds"),
        reason=result.get("reason"),
    )


@router.post("/end-session", response_model=EndSessionResponse)
def end_session(
    db: Session = Depends(get_db),
    authorization: str = Header(default=""),
):
    """
    Explicitly end a visitor session.

    Call this when the visitor logs out or closes the tab.
    This frees up the playground for the next person in queue.
    """
    session_id = _extract_session_id(authorization)
    if not session_id:
        raise HTTPException(status_code=401, detail="Missing or invalid visitor token")

    manager = VisitorSessionManager()
    result = manager.end_session(db, session_id)

    return EndSessionResponse(status=result["status"])


@router.get("/queue-status", response_model=SessionStatusResponse)
def get_queue_status(
    db: Session = Depends(get_db),
    authorization: str = Header(default=""),
):
    """
    Get current queue status without updating heartbeat.

    Useful for checking status without resetting the idle timer.
    """
    session_id = _extract_session_id(authorization)
    if not session_id:
        raise HTTPException(status_code=401, detail="Missing or invalid visitor token")

    manager = VisitorSessionManager()
    # Use heartbeat but don't update the timestamp for queued sessions
    result = manager.heartbeat(db, session_id)

    return SessionStatusResponse(
        status=result["status"],
        queue_position=result.get("queue_position"),
        warning_seconds_remaining=result.get("warning_seconds_remaining"),
        estimated_wait_seconds=result.get("estimated_wait_seconds"),
        reason=result.get("reason"),
    )


# =============================================================================
# Helper Functions
# =============================================================================


def _extract_session_id(authorization: str) -> Optional[str]:
    """
    Extract visitor session ID from the Authorization header.

    The authorization header should be: "Bearer <jwt_token>"
    We decode the JWT (without verification) to get the session ID.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        return None

    token = authorization.split(" ", 1)[1].strip()
    if not token:
        return None

    try:
        from src.core.impersonation import extract_visitor_session_id

        return extract_visitor_session_id(token)
    except Exception:
        return None

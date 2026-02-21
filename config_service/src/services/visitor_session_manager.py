"""
Visitor Session Manager for the public playground.

Manages visitor access to the playground with queue-based fairness:
- Only 1 active session at a time
- Others join a queue (FIFO)
- Active session timeout: 30 min idle when queue empty
- When queue exists: immediate 3 min countdown, then kicked
- Heartbeat: frontend calls every 30s while tab is open
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db.models import VisitorEmail, VisitorSession

logger = structlog.get_logger(__name__)


# Configuration constants
IDLE_TIMEOUT_NO_QUEUE = timedelta(minutes=30)
WARNING_DURATION = timedelta(minutes=3)
SESSION_CLEANUP_AGE = timedelta(hours=1)


def _utc_now() -> datetime:
    """Return current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)


# Playground configuration
PLAYGROUND_ORG_ID = "playground"
PLAYGROUND_TEAM_NODE_ID = "visitor-playground"


class VisitorSessionManager:
    """
    Manages visitor playground sessions with queue and timeout logic.

    Usage:
        manager = VisitorSessionManager()
        result = manager.try_login(db, "user@example.com")
        # result: {"session_id": "...", "status": "active"|"queued", ...}

        status = manager.heartbeat(db, "session_id")
        # status: {"status": "active"|"warned"|"expired", ...}
    """

    def try_login(self, db: Session, email: str, source: Optional[str] = None) -> dict:
        """
        Attempt to start or queue a visitor session.

        Args:
            db: Database session
            email: Visitor's email address
            source: Optional source attribution (e.g., "landing_page", "docs")

        Returns:
            {
                "session_id": "...",
                "status": "active" | "queued",
                "queue_position": 3,  # if queued
                "estimated_wait_seconds": 360,  # if queued
                "token": "...",  # JWT for API calls (only if active)
            }
        """
        logger.info("visitor_login_attempt", email=email, source=source)

        # 1. Record/update email for marketing
        self._record_email(db, email, source)

        # 2. Clean up stale sessions
        self._cleanup_expired_sessions(db)

        # 3. Check if this email already has an active/queued session
        existing = self._get_session_for_email(db, email)
        if existing:
            if existing.status in ("active", "warned"):
                logger.info(
                    "visitor_login_existing_active",
                    email=email,
                    session_id=existing.id,
                )
                return self._build_active_response(db, existing)
            elif existing.status == "queued":
                logger.info(
                    "visitor_login_existing_queued",
                    email=email,
                    session_id=existing.id,
                )
                return self._build_queued_response(db, existing)
            # If expired, we'll create a new session below

        # 4. Check current state
        active_session = self._get_active_session(db)

        # 5. If no active session, grant access
        if not active_session:
            return self._create_active_session(db, email)

        # 6. Otherwise, add to queue
        return self._create_queued_session(db, email)

    def heartbeat(self, db: Session, session_id: str) -> dict:
        """
        Called every 30s from frontend.
        Updates last_heartbeat_at and returns current session status.

        Args:
            db: Database session
            session_id: The visitor session ID

        Returns:
            {
                "status": "active" | "warned" | "queued" | "expired",
                "queue_position": 2,  # if queued
                "warning_seconds_remaining": 120,  # if warned
                "estimated_wait_seconds": 240,  # if queued
            }
        """
        session = db.query(VisitorSession).filter_by(id=session_id).first()
        if not session:
            logger.warning("heartbeat_session_not_found", session_id=session_id)
            return {"status": "expired", "reason": "session_not_found"}

        if session.status == "expired":
            logger.info("heartbeat_session_expired", session_id=session_id)
            return {"status": "expired", "reason": "session_expired"}

        # Update heartbeat for active/warned sessions
        if session.status in ("active", "warned"):
            session.last_heartbeat_at = _utc_now()
            logger.debug(
                "heartbeat_updated",
                session_id=session_id,
                status=session.status,
            )

        # Process timeouts (might promote queue, warn user, etc.)
        self._process_timeouts(db)

        db.commit()

        # Refresh session after potential changes
        db.refresh(session)

        # Return current state
        return self._get_session_status(db, session)

    def end_session(self, db: Session, session_id: str) -> dict:
        """
        Explicitly end a visitor session (e.g., user clicks logout).

        Args:
            db: Database session
            session_id: The visitor session ID

        Returns:
            {"status": "ended"}
        """
        session = db.query(VisitorSession).filter_by(id=session_id).first()
        if not session:
            return {"status": "not_found"}

        was_active = session.status in ("active", "warned")

        session.status = "expired"
        session.expired_at = _utc_now()

        # If this was the active session, promote next in queue
        if was_active:
            self._promote_next_in_queue(db)

        db.commit()

        logger.info(
            "visitor_session_ended",
            session_id=session_id,
            was_active=was_active,
        )

        return {"status": "ended"}

    # =========================================================================
    # Private methods
    # =========================================================================

    def _record_email(
        self, db: Session, email: str, source: Optional[str] = None
    ) -> None:
        """Record/update visitor email for marketing."""
        visitor = db.query(VisitorEmail).filter_by(email=email).first()
        if visitor:
            visitor.last_seen_at = _utc_now()
            visitor.visit_count += 1
            if source and not visitor.source:
                visitor.source = source
        else:
            visitor = VisitorEmail(
                email=email,
                first_seen_at=_utc_now(),
                last_seen_at=_utc_now(),
                visit_count=1,
                source=source,
            )
            db.add(visitor)
        db.flush()

    def _cleanup_expired_sessions(self, db: Session) -> int:
        """Remove old expired sessions."""
        cutoff = _utc_now() - SESSION_CLEANUP_AGE
        deleted = (
            db.query(VisitorSession)
            .filter(
                VisitorSession.status == "expired",
                VisitorSession.expired_at < cutoff,
            )
            .delete(synchronize_session=False)
        )
        if deleted:
            logger.info("cleaned_up_expired_sessions", count=deleted)
        return deleted

    def _get_session_for_email(
        self, db: Session, email: str
    ) -> Optional[VisitorSession]:
        """Get any non-expired session for this email."""
        return (
            db.query(VisitorSession)
            .filter(
                VisitorSession.email == email,
                VisitorSession.status.in_(["active", "warned", "queued"]),
            )
            .first()
        )

    def _get_active_session(self, db: Session) -> Optional[VisitorSession]:
        """Get the currently active session (if any)."""
        return (
            db.query(VisitorSession)
            .filter(VisitorSession.status.in_(["active", "warned"]))
            .first()
        )

    def _get_queue_count(self, db: Session) -> int:
        """Count sessions waiting in queue."""
        return (
            db.query(func.count(VisitorSession.id))
            .filter(VisitorSession.status == "queued")
            .scalar()
            or 0
        )

    def _get_queue_position(self, db: Session, session: VisitorSession) -> int:
        """Get the queue position for a queued session (1-indexed)."""
        if session.status != "queued":
            return 0

        position = (
            db.query(func.count(VisitorSession.id))
            .filter(
                VisitorSession.status == "queued",
                VisitorSession.created_at < session.created_at,
            )
            .scalar()
            or 0
        )
        return position + 1

    def _create_active_session(self, db: Session, email: str) -> dict:
        """Create a new active session."""
        session_id = str(uuid.uuid4())
        session = VisitorSession(
            id=session_id,
            email=email,
            status="active",
            created_at=_utc_now(),
            last_heartbeat_at=_utc_now(),
        )
        db.add(session)
        db.commit()

        logger.info(
            "visitor_session_created_active",
            session_id=session_id,
            email=email,
        )

        token = self._issue_visitor_token(session_id, email)

        return {
            "session_id": session_id,
            "status": "active",
            "token": token,
        }

    def _create_queued_session(self, db: Session, email: str) -> dict:
        """Create a new queued session."""
        session_id = str(uuid.uuid4())
        session = VisitorSession(
            id=session_id,
            email=email,
            status="queued",
            created_at=_utc_now(),
            last_heartbeat_at=_utc_now(),
        )
        db.add(session)
        db.commit()

        position = self._get_queue_position(db, session)

        logger.info(
            "visitor_session_created_queued",
            session_id=session_id,
            email=email,
            position=position,
        )

        # Issue a token even for queued users (they'll need it when promoted)
        token = self._issue_visitor_token(session_id, email)

        return {
            "session_id": session_id,
            "status": "queued",
            "queue_position": position,
            "estimated_wait_seconds": self._estimate_wait_time(position),
            "token": token,
        }

    def _build_active_response(self, db: Session, session: VisitorSession) -> dict:
        """Build response for an active/warned session."""
        session.last_heartbeat_at = _utc_now()
        db.commit()

        token = self._issue_visitor_token(session.id, session.email)

        response = {
            "session_id": session.id,
            "status": session.status,
            "token": token,
        }

        if session.status == "warned" and session.warned_at:
            elapsed = _utc_now() - session.warned_at
            remaining = WARNING_DURATION - elapsed
            response["warning_seconds_remaining"] = max(
                0, int(remaining.total_seconds())
            )

        return response

    def _build_queued_response(self, db: Session, session: VisitorSession) -> dict:
        """Build response for a queued session."""
        position = self._get_queue_position(db, session)
        token = self._issue_visitor_token(session.id, session.email)

        return {
            "session_id": session.id,
            "status": "queued",
            "queue_position": position,
            "estimated_wait_seconds": self._estimate_wait_time(position),
            "token": token,
        }

    def _get_session_status(self, db: Session, session: VisitorSession) -> dict:
        """Get current status for a session."""
        response = {"status": session.status}

        if session.status == "queued":
            position = self._get_queue_position(db, session)
            response["queue_position"] = position
            response["estimated_wait_seconds"] = self._estimate_wait_time(position)

        elif session.status == "warned" and session.warned_at:
            elapsed = _utc_now() - session.warned_at
            remaining = WARNING_DURATION - elapsed
            response["warning_seconds_remaining"] = max(
                0, int(remaining.total_seconds())
            )

        return response

    def _process_timeouts(self, db: Session) -> None:
        """Check for timeout conditions and handle them."""
        active = self._get_active_session(db)
        if not active:
            # No active session - promote from queue if available
            self._promote_next_in_queue(db)
            return

        queue_count = self._get_queue_count(db)
        idle_time = _utc_now() - active.last_heartbeat_at

        if queue_count == 0:
            # No queue - use lenient 30 min timeout
            if idle_time > IDLE_TIMEOUT_NO_QUEUE:
                logger.info(
                    "visitor_session_timeout_no_queue",
                    session_id=active.id,
                    idle_seconds=idle_time.total_seconds(),
                )
                self._expire_session(db, active)
        else:
            # Queue exists - start 3-minute countdown
            if active.status == "warned":
                # Check if warning period expired
                if active.warned_at:
                    warning_elapsed = _utc_now() - active.warned_at
                    if warning_elapsed > WARNING_DURATION:
                        logger.info(
                            "visitor_session_warning_expired",
                            session_id=active.id,
                            warning_seconds=warning_elapsed.total_seconds(),
                        )
                        self._expire_session(db, active)
                        self._promote_next_in_queue(db)
            else:
                # Start warning immediately when queue exists
                logger.info(
                    "visitor_session_warning_started",
                    session_id=active.id,
                    queue_count=queue_count,
                )
                active.status = "warned"
                active.warned_at = _utc_now()

    def _expire_session(self, db: Session, session: VisitorSession) -> None:
        """Mark a session as expired."""
        session.status = "expired"
        session.expired_at = _utc_now()
        logger.info("visitor_session_expired", session_id=session.id)

    def _promote_next_in_queue(self, db: Session) -> Optional[VisitorSession]:
        """Promote the next queued session to active."""
        next_session = (
            db.query(VisitorSession)
            .filter(VisitorSession.status == "queued")
            .order_by(VisitorSession.created_at.asc())
            .first()
        )

        if next_session:
            next_session.status = "active"
            next_session.last_heartbeat_at = _utc_now()
            logger.info(
                "visitor_session_promoted",
                session_id=next_session.id,
                email=next_session.email,
            )
            return next_session

        return None

    def _estimate_wait_time(self, position: int) -> int:
        """
        Estimate wait time in seconds based on queue position.

        Assumes each active session lasts ~3-5 minutes on average
        (either they finish or get kicked when warned).
        """
        # Rough estimate: 3 minutes per position
        return position * 180

    def _issue_visitor_token(self, session_id: str, email: str) -> str:
        """
        Issue a JWT token for the visitor session.

        This token identifies the visitor and grants them access to the
        playground team with limited permissions.
        """
        from ..core.impersonation import create_visitor_token

        return create_visitor_token(
            session_id=session_id,
            email=email,
            org_id=PLAYGROUND_ORG_ID,
            team_node_id=PLAYGROUND_TEAM_NODE_ID,
        )

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from src.core.security import generate_token, hash_token
from src.db.models import (
    AgentRun,
    ConversationMapping,
    ImpersonationJTI,
    OrgAdminToken,
    OrgNode,
    PendingConfigChange,
    SecurityPolicy,
    TeamToken,
    TokenAudit,
    TokenPermission,
)


@dataclass(frozen=True)
class Principal:
    org_id: str
    team_node_id: str


def record_impersonation_jti(
    session: Session,
    *,
    jti: str,
    org_id: str,
    team_node_id: str,
    subject: Optional[str],
    email: Optional[str],
    issued_at: datetime,
    expires_at: datetime,
) -> None:
    """
    Best-effort insert of an impersonation JWT's `jti` for auditing / allowlist verification.
    """
    row = ImpersonationJTI(
        jti=jti,
        org_id=org_id,
        team_node_id=team_node_id,
        subject=subject,
        email=email,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    session.add(row)
    # If this is a duplicate, let the caller decide whether to ignore/raise by catching.
    session.flush()


def impersonation_jti_exists(session: Session, *, jti: str) -> bool:
    row = session.execute(
        select(ImpersonationJTI.jti).where(ImpersonationJTI.jti == jti)
    ).first()
    return row is not None


def issue_team_token(
    session: Session,
    *,
    org_id: str,
    team_node_id: str,
    issued_by: Optional[str],
    pepper: str,
    expires_at: Optional[datetime] = None,
    permissions: Optional[List[str]] = None,
    label: Optional[str] = None,
) -> str:
    """Create and store a new opaque bearer token.

    Token format: <token_id>.<token_secret>
    - token_id is stored in DB and used for lookup
    - token_secret is only returned once; only its hash is stored
    """
    token_id = uuid4().hex
    token_secret = generate_token(32)
    token_hash = hash_token(token_secret, pepper=pepper)

    # Apply security policy expiration if not explicitly set
    if expires_at is None:
        policy = get_security_policy(session, org_id=org_id)
        if policy and policy.token_expiry_days:
            from datetime import timedelta

            expires_at = datetime.utcnow() + timedelta(days=policy.token_expiry_days)

    row = TeamToken(
        org_id=org_id,
        team_node_id=team_node_id,
        token_id=token_id,
        token_hash=token_hash,
        issued_at=datetime.utcnow(),
        issued_by=issued_by,
        revoked_at=None,
        expires_at=expires_at,
        permissions=permissions or TokenPermission.DEFAULT_TEAM,
        label=label,
    )
    session.add(row)
    session.flush()

    # Audit log
    record_token_audit(
        session,
        org_id=org_id,
        team_node_id=team_node_id,
        token_id=token_id,
        event_type="issued",
        actor=issued_by,
        details={
            "label": label,
            "permissions": permissions or TokenPermission.DEFAULT_TEAM,
        },
    )

    return f"{token_id}.{token_secret}"


def revoke_team_token(
    session: Session, *, token_id: str, revoked_by: Optional[str] = None
) -> None:
    row = session.execute(
        select(TeamToken).where(TeamToken.token_id == token_id)
    ).scalar_one_or_none()
    if row is None:
        return
    row.revoked_at = datetime.utcnow()
    session.flush()

    # Audit log
    record_token_audit(
        session,
        org_id=row.org_id,
        team_node_id=row.team_node_id,
        token_id=token_id,
        event_type="revoked",
        actor=revoked_by,
        details={},
    )


def revoke_team_token_scoped(
    session: Session,
    *,
    org_id: str,
    team_node_id: str,
    token_id: str,
    revoked_by: Optional[str] = None,
) -> None:
    row = session.execute(
        select(TeamToken).where(
            TeamToken.org_id == org_id,
            TeamToken.team_node_id == team_node_id,
            TeamToken.token_id == token_id,
        )
    ).scalar_one_or_none()
    if row is None:
        return
    row.revoked_at = datetime.utcnow()
    session.flush()

    # Audit log
    record_token_audit(
        session,
        org_id=org_id,
        team_node_id=team_node_id,
        token_id=token_id,
        event_type="revoked",
        actor=revoked_by,
        details={},
    )


def list_team_tokens(
    session: Session, *, org_id: str, team_node_id: str
) -> List[TeamToken]:
    return (
        session.execute(
            select(TeamToken)
            .where(TeamToken.org_id == org_id, TeamToken.team_node_id == team_node_id)
            .order_by(TeamToken.issued_at.desc())
        )
        .scalars()
        .all()
    )


def list_org_tokens(session: Session, *, org_id: str) -> List[TeamToken]:
    """List all tokens across all teams in an organization."""
    return (
        session.execute(
            select(TeamToken)
            .where(TeamToken.org_id == org_id)
            .order_by(TeamToken.issued_at.desc())
        )
        .scalars()
        .all()
    )


def get_token_by_id(session: Session, *, token_id: str) -> Optional[TeamToken]:
    """Get token details by token ID."""
    return session.execute(
        select(TeamToken).where(TeamToken.token_id == token_id)
    ).scalar_one_or_none()


def extend_token_expiration(
    session: Session,
    *,
    token_id: str,
    days: int,
    extended_by: Optional[str] = None,
) -> Optional[TeamToken]:
    """Extend token expiration by specified number of days."""
    token = session.execute(
        select(TeamToken).where(TeamToken.token_id == token_id)
    ).scalar_one_or_none()

    if token is None or token.revoked_at is not None:
        return None

    # Calculate new expiration
    if token.expires_at is None:
        # If token never expires, set expiration from now
        token.expires_at = datetime.utcnow() + timedelta(days=days)
    else:
        # Extend from current expiration
        token.expires_at = token.expires_at + timedelta(days=days)

    session.flush()

    # Audit log
    record_token_audit(
        session,
        org_id=token.org_id,
        team_node_id=token.team_node_id,
        token_id=token_id,
        event_type="extended",
        actor=extended_by,
        details={"extended_days": days, "new_expires_at": token.expires_at.isoformat()},
    )

    return token


def bulk_revoke_tokens(
    session: Session,
    *,
    token_ids: List[str],
    revoked_by: Optional[str] = None,
) -> int:
    """Bulk revoke multiple tokens. Returns count of revoked tokens."""
    count = 0
    for token_id in token_ids:
        token = session.execute(
            select(TeamToken).where(TeamToken.token_id == token_id)
        ).scalar_one_or_none()

        if token and token.revoked_at is None:
            token.revoked_at = datetime.utcnow()
            session.flush()

            # Audit log
            record_token_audit(
                session,
                org_id=token.org_id,
                team_node_id=token.team_node_id,
                token_id=token_id,
                event_type="revoked",
                actor=revoked_by,
                details={"bulk_revoke": True},
            )
            count += 1

    return count


# =============================================================================
# Org Admin Tokens (Per-Org Admin Authentication)
# =============================================================================


@dataclass(frozen=True)
class OrgAdminPrincipal:
    """Principal for org-scoped admin authentication."""

    org_id: str


def issue_org_admin_token(
    session: Session,
    *,
    org_id: str,
    issued_by: Optional[str],
    pepper: str,
    expires_at: Optional[datetime] = None,
    label: Optional[str] = None,
) -> str:
    """Create and store a new org admin token.

    Token format: <token_id>.<token_secret>
    - token_id is stored in DB and used for lookup
    - token_secret is only returned once; only its hash is stored
    """
    token_id = uuid4().hex
    token_secret = generate_token(32)
    token_hash = hash_token(token_secret, pepper=pepper)

    row = OrgAdminToken(
        org_id=org_id,
        token_id=token_id,
        token_hash=token_hash,
        issued_at=datetime.utcnow(),
        issued_by=issued_by,
        revoked_at=None,
        expires_at=expires_at,
        label=label,
    )
    session.add(row)
    session.flush()

    return f"{token_id}.{token_secret}"


def revoke_org_admin_token(
    session: Session,
    *,
    org_id: str,
    token_id: str,
    revoked_by: Optional[str] = None,
) -> None:
    """Revoke an org admin token."""
    row = session.execute(
        select(OrgAdminToken).where(
            OrgAdminToken.org_id == org_id,
            OrgAdminToken.token_id == token_id,
        )
    ).scalar_one_or_none()
    if row is None:
        return
    row.revoked_at = datetime.utcnow()
    session.flush()


def list_org_admin_tokens(session: Session, *, org_id: str) -> List[OrgAdminToken]:
    """List all admin tokens for an organization."""
    return (
        session.execute(
            select(OrgAdminToken)
            .where(OrgAdminToken.org_id == org_id)
            .order_by(OrgAdminToken.issued_at.desc())
        )
        .scalars()
        .all()
    )


def authenticate_org_admin_token(
    session: Session,
    *,
    bearer: str,
    pepper: str,
    update_last_used: bool = False,
) -> OrgAdminPrincipal:
    """Authenticate an org admin bearer token.

    Args:
        bearer: The full token string (token_id.secret)
        pepper: The token pepper for hashing
        update_last_used: Whether to update last_used_at timestamp

    Returns:
        OrgAdminPrincipal with org_id

    Raises:
        ValueError: If token is invalid, expired, or revoked
    """
    parts = bearer.split(".", 1)
    if len(parts) != 2:
        raise ValueError("Invalid token format")

    token_id, token_secret = parts
    expected_hash = hash_token(token_secret, pepper=pepper)

    row = session.execute(
        select(OrgAdminToken).where(OrgAdminToken.token_id == token_id)
    ).scalar_one_or_none()

    if row is None:
        raise ValueError("Token not found")

    if row.token_hash != expected_hash:
        raise ValueError("Invalid token")

    if row.revoked_at is not None:
        raise ValueError("Token has been revoked")

    if row.is_expired():
        raise ValueError("Token has expired")

    # Throttle last_used_at updates to reduce write contention (only update if older than 5 minutes)
    if update_last_used:
        now = datetime.utcnow()
        should_update = (
            row.last_used_at is None
            or (now - row.last_used_at.replace(tzinfo=None)).total_seconds() > 300
        )
        if should_update:
            row.last_used_at = now
            session.flush()

    return OrgAdminPrincipal(org_id=row.org_id)


def list_org_nodes(session: Session, *, org_id: str) -> List[OrgNode]:
    return (
        session.execute(
            select(OrgNode)
            .where(OrgNode.org_id == org_id)
            .order_by(OrgNode.node_id.asc())
        )
        .scalars()
        .all()
    )


def get_org_node(session: Session, *, org_id: str, node_id: str) -> OrgNode:
    node = session.execute(
        select(OrgNode).where(OrgNode.org_id == org_id, OrgNode.node_id == node_id)
    ).scalar_one_or_none()
    if node is None:
        raise ValueError(f"Node not found: {node_id}")
    return node


def list_node_config_audit(
    session: Session, *, org_id: str, node_id: str, limit: int = 50
) -> List["ConfigChangeHistory"]:
    """List configuration change history for a node. Now uses config_change_history table."""
    from .config_models import ConfigChangeHistory

    lim = max(1, min(int(limit), 200))
    return (
        session.execute(
            select(ConfigChangeHistory)
            .where(
                ConfigChangeHistory.org_id == org_id,
                ConfigChangeHistory.node_id == node_id,
            )
            .order_by(ConfigChangeHistory.changed_at.desc())
            .limit(lim)
        )
        .scalars()
        .all()
    )


def list_org_config_audit(
    session: Session,
    *,
    org_id: str,
    node_id: Optional[str] = None,
    changed_by: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: int = 200,
) -> List["ConfigChangeHistory"]:
    """List configuration change history for an org. Now uses config_change_history table."""
    from .config_models import ConfigChangeHistory

    lim = max(1, min(int(limit), 500))
    stmt = select(ConfigChangeHistory).where(ConfigChangeHistory.org_id == org_id)
    if node_id:
        stmt = stmt.where(ConfigChangeHistory.node_id == node_id)
    if changed_by:
        stmt = stmt.where(ConfigChangeHistory.changed_by == changed_by)
    if since is not None:
        stmt = stmt.where(ConfigChangeHistory.changed_at >= since)
    if until is not None:
        stmt = stmt.where(ConfigChangeHistory.changed_at <= until)
    stmt = stmt.order_by(ConfigChangeHistory.changed_at.desc()).limit(lim)
    return session.execute(stmt).scalars().all()


def create_org_node(
    session: Session,
    *,
    org_id: str,
    node_id: str,
    parent_id: Optional[str],
    node_type: Any,
    name: Optional[str],
) -> OrgNode:
    existing = session.execute(
        select(OrgNode).where(OrgNode.org_id == org_id, OrgNode.node_id == node_id)
    ).scalar_one_or_none()
    if existing is not None:
        raise ValueError(f"Node already exists: {node_id}")
    if parent_id is not None:
        parent = session.execute(
            select(OrgNode).where(
                OrgNode.org_id == org_id, OrgNode.node_id == parent_id
            )
        ).scalar_one_or_none()
        if parent is None:
            raise ValueError(f"Parent not found: {parent_id}")
    node = OrgNode(
        org_id=org_id,
        node_id=node_id,
        parent_id=parent_id,
        node_type=node_type,
        name=name,
    )
    session.add(node)
    session.flush()

    # Create corresponding node configuration entry
    from .config_repository import get_or_create_node_configuration

    get_or_create_node_configuration(
        session,
        org_id,
        node_id,
        node_type.value if hasattr(node_type, "value") else node_type,
    )

    return node


def update_org_node(
    session: Session,
    *,
    org_id: str,
    node_id: str,
    parent_id: Optional[str] = None,
    name: Optional[str] = None,
) -> OrgNode:
    node = session.execute(
        select(OrgNode).where(OrgNode.org_id == org_id, OrgNode.node_id == node_id)
    ).scalar_one_or_none()
    if node is None:
        raise ValueError(f"Node not found: {node_id}")

    if parent_id is not None:
        if parent_id == node_id:
            raise ValueError("parent_id cannot equal node_id")
        parent = session.execute(
            select(OrgNode).where(
                OrgNode.org_id == org_id, OrgNode.node_id == parent_id
            )
        ).scalar_one_or_none()
        if parent is None:
            raise ValueError(f"Parent not found: {parent_id}")
        # Prevent cycles: new parent cannot be a descendant of this node.
        lineage = get_lineage_nodes(session, org_id=org_id, node_id=parent_id)
        if any(n.node_id == node_id for n in lineage):
            raise ValueError("Reparent would create a cycle")
        node.parent_id = parent_id

    if name is not None:
        node.name = name

    session.flush()
    return node


def validate_against_locked_settings(
    session: Session,
    *,
    org_id: str,
    node_id: str,
    patch: Dict[str, Any],
) -> None:
    """Check if patch attempts to modify locked settings.

    Raises ValueError if trying to change a locked setting.
    """
    # Get security policy
    policy = get_security_policy(session, org_id=org_id)
    if not policy or not policy.locked_settings:
        return  # No locked settings

    # Get node to check if it's not root (root can change anything)
    node = session.execute(
        select(OrgNode).where(OrgNode.org_id == org_id, OrgNode.node_id == node_id)
    ).scalar_one_or_none()
    if node and node.parent_id is None:
        return  # Root node can change anything

    locked = set(policy.locked_settings)

    def check_path(obj: Any, path: str = "") -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                full_path = f"{path}.{k}" if path else k
                if full_path in locked:
                    raise ValueError(f"Cannot modify locked setting: {full_path}")
                check_path(v, full_path)

    check_path(patch)


def validate_against_max_values(
    session: Session,
    *,
    org_id: str,
    merged_config: Dict[str, Any],
) -> None:
    """Check if merged config violates max value constraints.

    Raises ValueError if any value exceeds max.
    """
    policy = get_security_policy(session, org_id=org_id)
    if not policy or not policy.max_values:
        return

    def get_nested(d: Dict[str, Any], path: str) -> Any:
        keys = path.split(".")
        for k in keys:
            if not isinstance(d, dict):
                return None
            d = d.get(k)
        return d

    for path, max_val in policy.max_values.items():
        current = get_nested(merged_config, path)
        if (
            current is not None
            and isinstance(current, (int, float))
            and isinstance(max_val, (int, float))
        ):
            if current > max_val:
                raise ValueError(
                    f"Value for {path} ({current}) exceeds maximum ({max_val})"
                )


@dataclass(frozen=True)
class AuthenticatedToken:
    """Extended principal with token metadata."""

    org_id: str
    team_node_id: str
    token_id: str
    permissions: List[str]
    expires_at: Optional[datetime]
    label: Optional[str]


def authenticate_bearer_token(
    session: Session,
    *,
    bearer: str,
    pepper: str,
    update_last_used: bool = True,
) -> Principal:
    """Authenticate an opaque bearer token against team_tokens.

    Raises ValueError if invalid or expired.
    """
    token_id, token_secret = _parse_bearer(bearer)
    row = session.execute(
        select(TeamToken).where(TeamToken.token_id == token_id)
    ).scalar_one_or_none()
    if row is None:
        raise ValueError("Invalid token")
    if row.revoked_at is not None:
        raise ValueError("Token revoked")
    if row.token_hash != hash_token(token_secret, pepper=pepper):
        raise ValueError("Invalid token")

    # Check expiration
    if row.expires_at is not None and datetime.utcnow() > row.expires_at.replace(
        tzinfo=None
    ):
        # Log expiration event
        record_token_audit(
            session,
            org_id=row.org_id,
            team_node_id=row.team_node_id,
            token_id=token_id,
            event_type="expired",
            actor="system",
            details={},
        )
        raise ValueError("Token expired")

    # Update last_used_at (throttled to reduce write contention - only update if older than 5 minutes)
    if update_last_used:
        now = datetime.utcnow()
        should_update = (
            row.last_used_at is None
            or (now - row.last_used_at.replace(tzinfo=None)).total_seconds() > 300
        )
        if should_update:
            row.last_used_at = now
            session.flush()

    return Principal(org_id=row.org_id, team_node_id=row.team_node_id)


def authenticate_bearer_token_extended(
    session: Session,
    *,
    bearer: str,
    pepper: str,
    required_permission: Optional[str] = None,
) -> AuthenticatedToken:
    """Authenticate and return extended token info with permission check.

    Raises ValueError if invalid, expired, or missing required permission.
    """
    token_id, token_secret = _parse_bearer(bearer)
    row = session.execute(
        select(TeamToken).where(TeamToken.token_id == token_id)
    ).scalar_one_or_none()
    if row is None:
        raise ValueError("Invalid token")
    if row.revoked_at is not None:
        raise ValueError("Token revoked")
    if row.token_hash != hash_token(token_secret, pepper=pepper):
        raise ValueError("Invalid token")

    # Check expiration
    if row.expires_at is not None and datetime.utcnow() > row.expires_at.replace(
        tzinfo=None
    ):
        record_token_audit(
            session,
            org_id=row.org_id,
            team_node_id=row.team_node_id,
            token_id=token_id,
            event_type="expired",
            actor="system",
            details={},
        )
        raise ValueError("Token expired")

    # Check permission
    permissions = row.permissions or []
    if required_permission and required_permission not in permissions:
        record_token_audit(
            session,
            org_id=row.org_id,
            team_node_id=row.team_node_id,
            token_id=token_id,
            event_type="permission_denied",
            actor="system",
            details={"required": required_permission, "has": permissions},
        )
        raise ValueError(f"Permission denied: {required_permission}")

    # Update last_used_at
    row.last_used_at = datetime.utcnow()
    session.flush()

    return AuthenticatedToken(
        org_id=row.org_id,
        team_node_id=row.team_node_id,
        token_id=token_id,
        permissions=permissions,
        expires_at=row.expires_at,
        label=row.label,
    )


def _parse_bearer(bearer: str) -> tuple[str, str]:
    if "." not in bearer:
        raise ValueError("Invalid token format")
    token_id, token_secret = bearer.split(".", 1)
    if not token_id or not token_secret:
        raise ValueError("Invalid token format")
    return token_id, token_secret


def get_lineage_nodes(
    session: Session, *, org_id: str, node_id: str, max_depth: int = 64
) -> List[OrgNode]:
    """Return lineage from root -> node_id inclusive by following parent_id pointers."""
    lineage: List[OrgNode] = []
    seen: set[str] = set()
    cur = node_id

    while True:
        if cur in seen:
            raise ValueError("Cycle detected in org graph")
        seen.add(cur)
        node = session.execute(
            select(OrgNode).where(OrgNode.org_id == org_id, OrgNode.node_id == cur)
        ).scalar_one_or_none()
        if node is None:
            raise ValueError(f"Node not found: {cur}")
        lineage.append(node)
        if node.parent_id is None:
            break
        if len(lineage) > max_depth:
            raise ValueError("Lineage depth exceeds safety limit")
        cur = node.parent_id

    lineage.reverse()
    return lineage


def get_node_configs(
    session: Session, *, org_id: str, node_ids: List[str]
) -> Dict[str, Dict[str, Any]]:
    """Get configuration for multiple nodes. Now uses node_configurations table."""
    if not node_ids:
        return {}
    from .config_models import NodeConfiguration

    rows = (
        session.execute(
            select(NodeConfiguration).where(
                NodeConfiguration.org_id == org_id,
                NodeConfiguration.node_id.in_(node_ids),
            )
        )
        .scalars()
        .all()
    )
    out: Dict[str, Dict[str, Any]] = {r.node_id: (r.config_json or {}) for r in rows}
    for nid in node_ids:
        out.setdefault(nid, {})
    return out


def upsert_team_overrides(
    session: Session,
    *,
    org_id: str,
    team_node_id: str,
    overrides: Dict[str, Any],
    updated_by: Optional[str],
) -> Dict[str, Any]:
    """Replace team config with provided overrides dict. Now uses node_configurations table."""
    from .config_models import ConfigChangeHistory, NodeConfiguration

    existing = session.execute(
        select(NodeConfiguration).where(
            NodeConfiguration.org_id == org_id,
            NodeConfiguration.node_id == team_node_id,
        )
    ).scalar_one_or_none()

    before = (
        existing.config_json
        if existing is not None and existing.config_json is not None
        else {}
    )

    if existing is None:
        # Create new config
        new = NodeConfiguration(
            id=f"cfg-{uuid.uuid4().hex[:12]}",
            org_id=org_id,
            node_id=team_node_id,
            node_type="team",  # This function is only called for teams
            config_json=overrides,
            version=1,
        )
        session.add(new)
        version = 1
    else:
        existing.config_json = overrides
        flag_modified(existing, "config_json")
        existing.version = int(existing.version) + 1
        version = existing.version

    diff = compute_diff(before, overrides)

    # Store in new audit table
    change = ConfigChangeHistory(
        id=f"chg-{uuid.uuid4().hex[:12]}",
        org_id=org_id,
        node_id=team_node_id,
        previous_config=before,
        new_config=overrides,
        change_diff=diff,
        changed_by=updated_by or "system",
        changed_at=datetime.utcnow(),
        change_reason="team_config_update",
        version=version,
    )
    session.add(change)
    session.flush()
    return overrides


def compute_diff(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    """Compute a minimal JSON diff (best-effort) for audit.

    Output format:
      { "changed": { "path.to.key": { "before": X, "after": Y }, ... } }
    """
    changed: Dict[str, Any] = {}

    def walk(b: Any, a: Any, path: str) -> None:
        if isinstance(b, dict) and isinstance(a, dict):
            keys = set(b.keys()) | set(a.keys())
            for k in keys:
                walk(b.get(k, None), a.get(k, None), f"{path}.{k}" if path else str(k))
            return
        if b != a:
            changed[path] = {"before": b, "after": a}

    walk(before or {}, after or {}, "")
    return {"changed": changed}


# =============================================================================
# Security Policy Functions
# =============================================================================


def get_security_policy(session: Session, *, org_id: str) -> Optional[SecurityPolicy]:
    """Get security policy for an org (or None if not set)."""
    return session.execute(
        select(SecurityPolicy).where(SecurityPolicy.org_id == org_id)
    ).scalar_one_or_none()


def upsert_security_policy(
    session: Session,
    *,
    org_id: str,
    updates: Dict[str, Any],
    updated_by: Optional[str],
) -> SecurityPolicy:
    """Create or update security policy for an org."""
    policy = get_security_policy(session, org_id=org_id)

    if policy is None:
        policy = SecurityPolicy(
            org_id=org_id,
            updated_at=datetime.utcnow(),
            updated_by=updated_by,
        )
        session.add(policy)

    for key, value in updates.items():
        if hasattr(policy, key):
            setattr(policy, key, value)

    policy.updated_at = datetime.utcnow()
    policy.updated_by = updated_by
    session.flush()

    return policy


# =============================================================================
# Token Audit Functions
# =============================================================================


def record_token_audit(
    session: Session,
    *,
    org_id: str,
    team_node_id: str,
    token_id: str,
    event_type: str,
    actor: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> TokenAudit:
    """Record a token audit event."""
    audit = TokenAudit(
        org_id=org_id,
        team_node_id=team_node_id,
        token_id=token_id,
        event_type=event_type,
        event_at=datetime.utcnow(),
        actor=actor,
        details=details or {},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    session.add(audit)
    session.flush()
    return audit


def list_token_audit(
    session: Session,
    *,
    org_id: str,
    team_node_id: Optional[str] = None,
    token_id: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[TokenAudit]:
    """List token audit events with optional filtering."""
    stmt = select(TokenAudit).where(TokenAudit.org_id == org_id)

    if team_node_id:
        stmt = stmt.where(TokenAudit.team_node_id == team_node_id)
    if token_id:
        stmt = stmt.where(TokenAudit.token_id == token_id)
    if event_type:
        stmt = stmt.where(TokenAudit.event_type == event_type)

    stmt = stmt.order_by(TokenAudit.event_at.desc())
    stmt = stmt.offset(offset).limit(min(limit, 1000))

    return list(session.execute(stmt).scalars().all())


# =============================================================================
# Agent Run Functions
# =============================================================================


def create_agent_run(
    session: Session,
    *,
    run_id: str,
    org_id: str,
    team_node_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    trigger_source: str,
    trigger_actor: Optional[str] = None,
    trigger_message: Optional[str] = None,
    trigger_channel_id: Optional[str] = None,
    agent_name: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> AgentRun:
    """Create a new agent run record (status=running)."""
    run = AgentRun(
        id=run_id,
        org_id=org_id,
        team_node_id=team_node_id,
        correlation_id=correlation_id,
        trigger_source=trigger_source,
        trigger_actor=trigger_actor,
        trigger_message=trigger_message,
        trigger_channel_id=trigger_channel_id,
        agent_name=agent_name,
        started_at=datetime.utcnow(),
        status="running",
        extra_metadata=metadata or {},
    )
    session.add(run)
    session.flush()
    return run


def complete_agent_run(
    session: Session,
    *,
    run_id: str,
    status: str,
    tool_calls_count: Optional[int] = None,
    output_summary: Optional[str] = None,
    output_json: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
    confidence: Optional[int] = None,
) -> Optional[AgentRun]:
    """Mark an agent run as completed/failed/timeout."""
    run = session.execute(
        select(AgentRun).where(AgentRun.id == run_id)
    ).scalar_one_or_none()

    if run is None:
        return None

    run.status = status
    from datetime import timezone

    run.completed_at = datetime.now(timezone.utc)
    run.tool_calls_count = tool_calls_count
    run.output_summary = output_summary
    run.output_json = output_json
    run.error_message = error_message
    run.confidence = confidence

    if run.started_at:
        # Handle timezone-aware vs naive datetime comparison
        completed = run.completed_at
        started = run.started_at
        if completed.tzinfo is not None and started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        elif completed.tzinfo is None and started.tzinfo is not None:
            completed = completed.replace(tzinfo=timezone.utc)
        run.duration_seconds = (completed - started).total_seconds()

    session.flush()
    return run


def get_agent_run(session: Session, *, run_id: str) -> Optional[AgentRun]:
    """Get a single agent run by ID."""
    return session.execute(
        select(AgentRun).where(AgentRun.id == run_id)
    ).scalar_one_or_none()


def list_agent_runs(
    session: Session,
    *,
    org_id: str,
    team_node_id: Optional[str] = None,
    status: Optional[str] = None,
    trigger_source: Optional[str] = None,
    agent_name: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[AgentRun]:
    """List agent runs with optional filtering."""
    stmt = select(AgentRun).where(AgentRun.org_id == org_id)

    if team_node_id:
        stmt = stmt.where(AgentRun.team_node_id == team_node_id)
    if status:
        stmt = stmt.where(AgentRun.status == status)
    if trigger_source:
        stmt = stmt.where(AgentRun.trigger_source == trigger_source)
    if agent_name:
        stmt = stmt.where(AgentRun.agent_name == agent_name)
    if since:
        stmt = stmt.where(AgentRun.started_at >= since)
    if until:
        stmt = stmt.where(AgentRun.started_at <= until)

    stmt = stmt.order_by(AgentRun.started_at.desc())
    stmt = stmt.offset(offset).limit(min(limit, 1000))

    return list(session.execute(stmt).scalars().all())


# =============================================================================
# Agent Tool Call Functions
# =============================================================================


def create_tool_call(
    session: Session,
    *,
    tool_call_id: str,
    run_id: str,
    tool_name: str,
    tool_input: Optional[Dict[str, Any]] = None,
    tool_output: Optional[str] = None,
    started_at: Optional[datetime] = None,
    duration_ms: Optional[int] = None,
    status: str = "success",
    error_message: Optional[str] = None,
    sequence_number: int = 0,
) -> "AgentToolCall":
    """Create a single tool call record."""
    from .models import AgentToolCall

    tool_call = AgentToolCall(
        id=tool_call_id,
        run_id=run_id,
        tool_name=tool_name,
        tool_input=tool_input,
        tool_output=tool_output[:5000] if tool_output else None,  # Truncate output
        started_at=started_at or datetime.utcnow(),
        duration_ms=duration_ms,
        status=status,
        error_message=error_message[:1000] if error_message else None,
        sequence_number=sequence_number,
    )
    session.add(tool_call)
    session.flush()
    return tool_call


def bulk_create_tool_calls(
    session: Session,
    *,
    run_id: str,
    tool_calls: List[Dict[str, Any]],
) -> int:
    """
    Bulk insert tool calls for a run.

    Args:
        run_id: The agent run ID
        tool_calls: List of dicts with keys:
            - id: Unique ID for the tool call
            - tool_name: Name of the tool
            - tool_input: Arguments passed to tool (dict)
            - tool_output: Result from tool (string, truncated)
            - started_at: When the call started (datetime)
            - duration_ms: How long it took (int)
            - status: success or error
            - error_message: Error details if failed
            - sequence_number: Order in the run

    Returns:
        Number of tool calls inserted
    """
    from .models import AgentToolCall

    if not tool_calls:
        return 0

    records = []
    for i, tc in enumerate(tool_calls):
        output = tc.get("tool_output")
        error = tc.get("error_message")
        records.append(
            AgentToolCall(
                id=tc.get("id", f"{run_id}_{i}"),
                run_id=run_id,
                agent_name=tc.get("agent_name"),
                parent_agent=tc.get("parent_agent"),
                tool_name=tc.get("tool_name", "unknown"),
                tool_input=tc.get("tool_input"),
                tool_output=output[:5000] if output else None,
                started_at=tc.get("started_at", datetime.utcnow()),
                duration_ms=tc.get("duration_ms"),
                status=tc.get("status", "success"),
                error_message=error[:1000] if error else None,
                sequence_number=tc.get("sequence_number", i),
            )
        )

    session.add_all(records)
    session.flush()
    return len(records)


def get_tool_calls_for_run(
    session: Session,
    *,
    run_id: str,
) -> List["AgentToolCall"]:
    """Get all tool calls for a specific agent run, ordered by sequence."""
    from .models import AgentToolCall

    stmt = (
        select(AgentToolCall)
        .where(AgentToolCall.run_id == run_id)
        .order_by(AgentToolCall.sequence_number)
    )
    return list(session.execute(stmt).scalars().all())


def list_tool_calls(
    session: Session,
    *,
    run_ids: Optional[List[str]] = None,
    tool_name: Optional[str] = None,
    status: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: int = 1000,
    offset: int = 0,
) -> List["AgentToolCall"]:
    """List tool calls with optional filtering."""
    from .models import AgentToolCall

    stmt = select(AgentToolCall)

    if run_ids:
        stmt = stmt.where(AgentToolCall.run_id.in_(run_ids))
    if tool_name:
        stmt = stmt.where(AgentToolCall.tool_name == tool_name)
    if status:
        stmt = stmt.where(AgentToolCall.status == status)
    if since:
        stmt = stmt.where(AgentToolCall.started_at >= since)
    if until:
        stmt = stmt.where(AgentToolCall.started_at <= until)

    stmt = stmt.order_by(AgentToolCall.started_at.desc())
    stmt = stmt.offset(offset).limit(min(limit, 5000))

    return list(session.execute(stmt).scalars().all())


# =============================================================================
# Unified Audit Functions
# =============================================================================


@dataclass
class UnifiedAuditEvent:
    """Normalized audit event for unified view."""

    id: str
    source: str  # token, config, agent
    event_type: str
    timestamp: datetime
    actor: Optional[str]
    team_node_id: Optional[str]
    summary: str
    details: Dict[str, Any]
    correlation_id: Optional[str] = None


def list_unified_audit(
    session: Session,
    *,
    org_id: str,
    sources: Optional[List[str]] = None,  # token, config, agent
    team_node_id: Optional[str] = None,
    event_types: Optional[List[str]] = None,
    actor: Optional[str] = None,
    search: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[List[UnifiedAuditEvent], int]:
    """
    Aggregate audit events from all sources into a unified timeline.

    Returns (events, total_count) for pagination.
    """
    all_sources = sources or ["token", "config", "agent"]
    events: List[UnifiedAuditEvent] = []

    # --- Token Audit ---
    if "token" in all_sources:
        stmt = select(TokenAudit).where(TokenAudit.org_id == org_id)
        if team_node_id:
            stmt = stmt.where(TokenAudit.team_node_id == team_node_id)
        if event_types:
            token_types = [
                et
                for et in event_types
                if et in ("issued", "revoked", "expired", "permission_denied", "used")
            ]
            if token_types:
                stmt = stmt.where(TokenAudit.event_type.in_(token_types))
        if actor:
            stmt = stmt.where(TokenAudit.actor.ilike(f"%{actor}%"))
        if since:
            stmt = stmt.where(TokenAudit.event_at >= since)
        if until:
            stmt = stmt.where(TokenAudit.event_at <= until)

        token_rows = session.execute(stmt).scalars().all()
        for row in token_rows:
            summary = f"Token {row.event_type}"
            if row.event_type == "issued":
                label = (row.details or {}).get("label", "")
                summary = f"Token issued{': ' + label if label else ''}"
            elif row.event_type == "revoked":
                summary = "Token revoked"
            elif row.event_type == "expired":
                summary = "Token expired"
            elif row.event_type == "permission_denied":
                summary = f"Permission denied: {(row.details or {}).get('required', 'unknown')}"

            events.append(
                UnifiedAuditEvent(
                    id=f"token_{row.id}",
                    source="token",
                    event_type=row.event_type,
                    timestamp=row.event_at,
                    actor=row.actor,
                    team_node_id=row.team_node_id,
                    summary=summary,
                    details={"token_id": row.token_id, **(row.details or {})},
                )
            )

    # --- Config Audit ---
    if "config" in all_sources:
        stmt = select(NodeConfigAudit).where(NodeConfigAudit.org_id == org_id)
        if team_node_id:
            stmt = stmt.where(NodeConfigAudit.node_id == team_node_id)
        if actor:
            stmt = stmt.where(NodeConfigAudit.changed_by.ilike(f"%{actor}%"))
        if since:
            stmt = stmt.where(NodeConfigAudit.changed_at >= since)
        if until:
            stmt = stmt.where(NodeConfigAudit.changed_at <= until)

        config_rows = session.execute(stmt).scalars().all()
        for row in config_rows:
            changed_keys = list((row.diff_json or {}).get("changed", {}).keys())
            summary = (
                f"Config updated: {', '.join(changed_keys[:3])}"
                if changed_keys
                else "Config updated"
            )
            if len(changed_keys) > 3:
                summary += f" (+{len(changed_keys) - 3} more)"

            events.append(
                UnifiedAuditEvent(
                    id=f"config_{row.org_id}_{row.node_id}_{row.version}",
                    source="config",
                    event_type="config_updated",
                    timestamp=row.changed_at,
                    actor=row.changed_by,
                    team_node_id=row.node_id,
                    summary=summary,
                    details={
                        "node_id": row.node_id,
                        "version": row.version,
                        "diff": row.diff_json,
                    },
                )
            )

    # --- Agent Runs ---
    if "agent" in all_sources:
        stmt = select(AgentRun).where(AgentRun.org_id == org_id)
        if team_node_id:
            stmt = stmt.where(AgentRun.team_node_id == team_node_id)
        if event_types:
            agent_types = [
                et
                for et in event_types
                if et in ("completed", "failed", "timeout", "running")
            ]
            if agent_types:
                stmt = stmt.where(AgentRun.status.in_(agent_types))
        if actor:
            stmt = stmt.where(AgentRun.trigger_actor.ilike(f"%{actor}%"))
        if since:
            stmt = stmt.where(AgentRun.started_at >= since)
        if until:
            stmt = stmt.where(AgentRun.started_at <= until)

        agent_rows = session.execute(stmt).scalars().all()
        for row in agent_rows:
            summary = f"Agent run {row.status}: {row.agent_name}"
            if row.output_summary:
                summary += f" - {row.output_summary[:100]}"
            if row.confidence:
                summary += f" ({row.confidence}% confidence)"

            events.append(
                UnifiedAuditEvent(
                    id=f"agent_{row.id}",
                    source="agent",
                    event_type=f"agent_{row.status}",
                    timestamp=row.started_at,
                    actor=row.trigger_actor,
                    team_node_id=row.team_node_id,
                    summary=summary,
                    details={
                        "agent_name": row.agent_name,
                        "trigger_source": row.trigger_source,
                        "trigger_message": row.trigger_message,
                        "status": row.status,
                        "tool_calls": row.tool_calls_count,
                        "duration_seconds": row.duration_seconds,
                        "confidence": row.confidence,
                        "error": row.error_message,
                    },
                    correlation_id=row.correlation_id,
                )
            )

    # --- Search filter ---
    if search:
        search_lower = search.lower()
        events = [
            e
            for e in events
            if search_lower in e.summary.lower()
            or search_lower in str(e.details).lower()
        ]

    # --- Sort by timestamp descending ---
    events.sort(key=lambda e: e.timestamp, reverse=True)

    total = len(events)

    # --- Paginate ---
    events = events[offset : offset + limit]

    return events, total


# =============================================================================
# Token Lifecycle Management
# =============================================================================


@dataclass
class TokenLifecycleResult:
    """Result of running token lifecycle checks."""

    tokens_expiring_soon: List[Dict[str, Any]]
    tokens_revoked: List[str]
    warnings_sent: int


def get_tokens_expiring_soon(
    session: Session,
    *,
    org_id: str,
    warn_before_days: int,
) -> List[TeamToken]:
    """Get tokens that will expire within warn_before_days."""
    from datetime import timedelta

    now = datetime.utcnow()
    warn_threshold = now + timedelta(days=warn_before_days)

    stmt = select(TeamToken).where(
        TeamToken.org_id == org_id,
        TeamToken.revoked_at.is_(None),
        TeamToken.expires_at.isnot(None),
        TeamToken.expires_at <= warn_threshold,
        TeamToken.expires_at > now,  # Not yet expired
    )
    return list(session.execute(stmt).scalars().all())


def get_inactive_tokens(
    session: Session,
    *,
    org_id: str,
    inactive_days: int,
) -> List[TeamToken]:
    """Get tokens not used in inactive_days."""
    from datetime import timedelta

    cutoff = datetime.utcnow() - timedelta(days=inactive_days)

    stmt = select(TeamToken).where(
        TeamToken.org_id == org_id,
        TeamToken.revoked_at.is_(None),
        # Consider both last_used_at and issued_at for tokens never used
        (
            (TeamToken.last_used_at.isnot(None) & (TeamToken.last_used_at < cutoff))
            | (TeamToken.last_used_at.is_(None) & (TeamToken.issued_at < cutoff))
        ),
    )
    return list(session.execute(stmt).scalars().all())


def process_token_lifecycle(
    session: Session,
    *,
    org_id: str,
) -> TokenLifecycleResult:
    """Run all token lifecycle checks for an org based on security policy.

    Returns summary of actions taken.
    """
    policy = get_security_policy(session, org_id=org_id)

    result = TokenLifecycleResult(
        tokens_expiring_soon=[],
        tokens_revoked=[],
        warnings_sent=0,
    )

    if not policy:
        return result

    # 1. Find tokens expiring soon
    if policy.token_warn_before_days:
        expiring = get_tokens_expiring_soon(
            session,
            org_id=org_id,
            warn_before_days=policy.token_warn_before_days,
        )
        for token in expiring:
            result.tokens_expiring_soon.append(
                {
                    "token_id": token.token_id,
                    "team_node_id": token.team_node_id,
                    "expires_at": (
                        token.expires_at.isoformat() if token.expires_at else None
                    ),
                    "label": token.label,
                    "issued_by": token.issued_by,
                }
            )
            # Record warning event (only once per day ideally)
            # Check if we already warned today
            existing_warning = session.execute(
                select(TokenAudit).where(
                    TokenAudit.token_id == token.token_id,
                    TokenAudit.event_type == "expiry_warning",
                    TokenAudit.event_at
                    >= datetime.utcnow().replace(hour=0, minute=0, second=0),
                )
            ).first()
            if not existing_warning:
                record_token_audit(
                    session,
                    org_id=org_id,
                    team_node_id=token.team_node_id,
                    token_id=token.token_id,
                    event_type="expiry_warning",
                    actor="system",
                    details={
                        "expires_at": (
                            token.expires_at.isoformat() if token.expires_at else None
                        ),
                        "days_remaining": (
                            (token.expires_at - datetime.utcnow()).days
                            if token.expires_at
                            else None
                        ),
                    },
                )
                result.warnings_sent += 1

    # 2. Auto-revoke inactive tokens
    if policy.token_revoke_inactive_days:
        inactive = get_inactive_tokens(
            session,
            org_id=org_id,
            inactive_days=policy.token_revoke_inactive_days,
        )
        for token in inactive:
            # Revoke it
            token.revoked_at = datetime.utcnow()
            record_token_audit(
                session,
                org_id=org_id,
                team_node_id=token.team_node_id,
                token_id=token.token_id,
                event_type="auto_revoked_inactive",
                actor="system",
                details={
                    "last_used_at": (
                        token.last_used_at.isoformat() if token.last_used_at else None
                    ),
                    "inactive_days": policy.token_revoke_inactive_days,
                },
            )
            result.tokens_revoked.append(token.token_id)

    session.flush()
    return result


# =============================================================================
# Approval Workflow Functions
# =============================================================================


def create_pending_change(
    session: Session,
    *,
    org_id: str,
    node_id: str,
    change_type: str,  # "prompt", "tools", "config"
    change_path: Optional[str] = None,
    proposed_value: Any,
    previous_value: Any,
    requested_by: str,
    reason: Optional[str] = None,
) -> PendingConfigChange:
    """Create a pending config change request."""
    from uuid import uuid4

    change = PendingConfigChange(
        id=uuid4().hex,
        org_id=org_id,
        node_id=node_id,
        change_type=change_type,
        change_path=change_path,
        proposed_value=proposed_value,
        previous_value=previous_value,
        requested_by=requested_by,
        requested_at=datetime.utcnow(),
        reason=reason,
        status="pending",
    )
    session.add(change)
    session.flush()
    return change


def list_pending_changes(
    session: Session,
    *,
    org_id: str,
    node_id: Optional[str] = None,
    status: Optional[str] = None,
    change_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[PendingConfigChange]:
    """List pending config changes."""
    stmt = select(PendingConfigChange).where(PendingConfigChange.org_id == org_id)

    if node_id:
        stmt = stmt.where(PendingConfigChange.node_id == node_id)
    if status:
        stmt = stmt.where(PendingConfigChange.status == status)
    if change_type:
        stmt = stmt.where(PendingConfigChange.change_type == change_type)

    stmt = stmt.order_by(PendingConfigChange.requested_at.desc())
    stmt = stmt.offset(offset).limit(min(limit, 1000))

    return list(session.execute(stmt).scalars().all())


def get_pending_change(
    session: Session, *, change_id: str
) -> Optional[PendingConfigChange]:
    """Get a pending change by ID."""
    return session.execute(
        select(PendingConfigChange).where(PendingConfigChange.id == change_id)
    ).scalar_one_or_none()


def approve_pending_change(
    session: Session,
    *,
    change_id: str,
    reviewed_by: str,
    review_comment: Optional[str] = None,
    apply_change: bool = True,
) -> Optional[PendingConfigChange]:
    """Approve a pending change and optionally apply it.

    If apply_change is True, the change will be applied to the node config.
    """
    change = get_pending_change(session, change_id=change_id)
    if not change:
        return None

    if change.status != "pending":
        raise ValueError(f"Change already {change.status}")

    change.status = "approved"
    change.reviewed_by = reviewed_by
    change.reviewed_at = datetime.utcnow()
    change.review_comment = review_comment

    if apply_change:
        # Apply the change to the node config
        # Build a patch from the change
        if change.change_path:
            # Nested path - build nested dict
            keys = change.change_path.split(".")
            patch = {}
            current = patch
            for i, key in enumerate(keys[:-1]):
                current[key] = {}
                current = current[key]
            current[keys[-1]] = change.proposed_value
        else:
            # Direct value
            patch = (
                change.proposed_value if isinstance(change.proposed_value, dict) else {}
            )

        if patch:
            # Lazy import to avoid circular dependency
            from src.db.config_repository import update_node_configuration

            update_node_configuration(
                session,
                org_id=change.org_id,
                node_id=change.node_id,
                config_patch=patch,
                updated_by=reviewed_by,
                skip_validation=True,  # Already approved
            )

    session.flush()
    return change


def reject_pending_change(
    session: Session,
    *,
    change_id: str,
    reviewed_by: str,
    review_comment: Optional[str] = None,
) -> Optional[PendingConfigChange]:
    """Reject a pending change."""
    change = get_pending_change(session, change_id=change_id)
    if not change:
        return None

    if change.status != "pending":
        raise ValueError(f"Change already {change.status}")

    change.status = "rejected"
    change.reviewed_by = reviewed_by
    change.reviewed_at = datetime.utcnow()
    change.review_comment = review_comment

    session.flush()
    return change


def requires_approval(
    session: Session,
    *,
    org_id: str,
    change_type: str,  # "prompt" or "tools"
) -> bool:
    """Check if a change type requires approval based on security policy."""
    policy = get_security_policy(session, org_id=org_id)
    if not policy:
        return False

    if change_type == "prompt":
        return policy.require_approval_for_prompts
    elif change_type == "tools":
        return policy.require_approval_for_tools

    return False


# =============================================================================
# Conversation Mapping Functions
# =============================================================================


def get_conversation_mapping(
    session: Session,
    *,
    session_id: str,
) -> Optional[ConversationMapping]:
    """Get conversation mapping by session_id."""
    stmt = select(ConversationMapping).where(
        ConversationMapping.session_id == session_id
    )
    return session.execute(stmt).scalar_one_or_none()


def create_conversation_mapping(
    session: Session,
    *,
    session_id: str,
    openai_conversation_id: str,
    session_type: str,
    org_id: Optional[str] = None,
    team_node_id: Optional[str] = None,
) -> ConversationMapping:
    """Create a new conversation mapping."""
    mapping = ConversationMapping(
        session_id=session_id,
        openai_conversation_id=openai_conversation_id,
        session_type=session_type,
        org_id=org_id,
        team_node_id=team_node_id,
    )
    session.add(mapping)
    session.flush()
    return mapping


def update_conversation_mapping_last_used(
    session: Session,
    *,
    session_id: str,
) -> Optional[ConversationMapping]:
    """Update the last_used_at timestamp for a conversation mapping."""
    mapping = get_conversation_mapping(session, session_id=session_id)
    if mapping:
        mapping.last_used_at = datetime.utcnow()
        session.flush()
    return mapping


def delete_conversation_mapping(
    session: Session,
    *,
    session_id: str,
) -> bool:
    """Delete a conversation mapping. Returns True if deleted, False if not found."""
    mapping = get_conversation_mapping(session, session_id=session_id)
    if mapping:
        session.delete(mapping)
        session.flush()
        return True
    return False

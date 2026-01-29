"""
Webhook signature verification utilities.

Each external service has its own signature scheme:
- Slack: HMAC-SHA256 with v0: prefix
- GitHub: HMAC-SHA256 with sha256= prefix
- PagerDuty: HMAC-SHA256 with v1= prefix
- Incident.io: HMAC-SHA256

All verifications use constant-time comparison to prevent timing attacks.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Optional


class SignatureVerificationError(Exception):
    """Raised when webhook signature verification fails."""

    def __init__(self, reason: str, service: str):
        self.reason = reason
        self.service = service
        super().__init__(f"{service} signature verification failed: {reason}")


def _constant_time_compare(a: str, b: str) -> bool:
    """Constant-time string comparison to prevent timing attacks."""
    if len(a) != len(b):
        return False
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def verify_slack_signature(
    *,
    signing_secret: str,
    timestamp: Optional[str],
    signature: Optional[str],
    raw_body: str,
    max_age_seconds: int = 300,
) -> None:
    """
    Verify Slack request signature.

    Slack uses HMAC-SHA256 with format:
    - Base string: v0:{timestamp}:{body}
    - Signature header: v0={hex_digest}

    Args:
        signing_secret: Slack app signing secret
        timestamp: X-Slack-Request-Timestamp header
        signature: X-Slack-Signature header
        raw_body: Raw request body as string
        max_age_seconds: Maximum age of request (default 5 minutes)

    Raises:
        SignatureVerificationError: If verification fails
    """
    if not signing_secret:
        raise SignatureVerificationError("missing_signing_secret", "slack")
    if not timestamp:
        raise SignatureVerificationError("missing_timestamp_header", "slack")
    if not signature:
        raise SignatureVerificationError("missing_signature_header", "slack")

    # Validate timestamp is numeric
    try:
        ts = int(timestamp)
    except (ValueError, TypeError):
        raise SignatureVerificationError("invalid_timestamp", "slack")

    # Replay protection
    age = abs(time.time() - ts)
    if age > max_age_seconds:
        raise SignatureVerificationError(
            f"stale_timestamp (age={int(age)}s, max={max_age_seconds}s)", "slack"
        )

    # Compute expected signature
    base_string = f"v0:{timestamp}:{raw_body}"
    digest = hmac.new(
        signing_secret.encode("utf-8"),
        base_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    expected = f"v0={digest}"

    if not _constant_time_compare(expected, signature):
        raise SignatureVerificationError("bad_signature", "slack")


def verify_github_signature(
    *,
    webhook_secret: str,
    signature: Optional[str],
    raw_body: str,
) -> None:
    """
    Verify GitHub webhook signature.

    GitHub uses HMAC-SHA256 with format:
    - Signature header (X-Hub-Signature-256): sha256={hex_digest}

    Args:
        webhook_secret: GitHub webhook secret
        signature: X-Hub-Signature-256 header
        raw_body: Raw request body as string

    Raises:
        SignatureVerificationError: If verification fails
    """
    if not webhook_secret:
        raise SignatureVerificationError("missing_webhook_secret", "github")
    if not signature:
        raise SignatureVerificationError("missing_signature_header", "github")

    # GitHub signature format: sha256=<hex>
    if not signature.startswith("sha256="):
        raise SignatureVerificationError("invalid_signature_format", "github")

    provided_digest = signature[7:]  # Remove "sha256=" prefix

    # Compute expected digest
    expected_digest = hmac.new(
        webhook_secret.encode("utf-8"),
        raw_body.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not _constant_time_compare(expected_digest, provided_digest):
        raise SignatureVerificationError("bad_signature", "github")


def verify_pagerduty_signature(
    *,
    webhook_secret: str,
    signature: Optional[str],
    raw_body: str,
) -> None:
    """
    Verify PagerDuty webhook signature.

    PagerDuty uses HMAC-SHA256 with format:
    - Signature header (X-PagerDuty-Signature): v1={hex_digest}

    Args:
        webhook_secret: PagerDuty webhook secret (integration key)
        signature: X-PagerDuty-Signature header
        raw_body: Raw request body as string

    Raises:
        SignatureVerificationError: If verification fails
    """
    if not webhook_secret:
        raise SignatureVerificationError("missing_webhook_secret", "pagerduty")
    if not signature:
        raise SignatureVerificationError("missing_signature_header", "pagerduty")

    # PagerDuty signature format: v1=<hex>
    if not signature.startswith("v1="):
        raise SignatureVerificationError("invalid_signature_format", "pagerduty")

    provided_digest = signature[3:]  # Remove "v1=" prefix

    # Compute expected digest
    expected_digest = hmac.new(
        webhook_secret.encode("utf-8"),
        raw_body.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not _constant_time_compare(expected_digest, provided_digest):
        raise SignatureVerificationError("bad_signature", "pagerduty")


def verify_incidentio_signature(
    *,
    webhook_secret: str,
    webhook_id: Optional[str],
    signature: Optional[str],
    timestamp: Optional[str],
    raw_body: str,
    max_age_seconds: int = 300,
) -> None:
    """
    Verify Incident.io webhook signature using Standard Webhooks format.

    Standard Webhooks uses:
    - Signed payload: {webhook-id}.{webhook-timestamp}.{body}
    - Signature header: v1,{base64_encoded_hmac_sha256}

    Args:
        webhook_secret: Incident.io webhook signing secret (starts with whsec_)
        webhook_id: webhook-id header
        signature: webhook-signature header (format: v1,{base64})
        timestamp: webhook-timestamp header (Unix timestamp)
        raw_body: Raw request body as string
        max_age_seconds: Maximum age of request (default 5 minutes)

    Raises:
        SignatureVerificationError: If verification fails
    """
    import base64

    if not webhook_secret:
        raise SignatureVerificationError("missing_webhook_secret", "incidentio")
    if not signature:
        raise SignatureVerificationError("missing_signature_header", "incidentio")
    if not timestamp:
        raise SignatureVerificationError("missing_timestamp_header", "incidentio")
    if not webhook_id:
        raise SignatureVerificationError("missing_webhook_id_header", "incidentio")

    # Validate timestamp
    try:
        ts = int(timestamp)
    except (ValueError, TypeError):
        raise SignatureVerificationError("invalid_timestamp", "incidentio")

    # Replay protection
    age = abs(time.time() - ts)
    if age > max_age_seconds:
        raise SignatureVerificationError(
            f"stale_timestamp (age={int(age)}s, max={max_age_seconds}s)", "incidentio"
        )

    # Standard Webhooks: signed payload is "{webhook_id}.{timestamp}.{body}"
    signed_payload = f"{webhook_id}.{timestamp}.{raw_body}"

    # Extract the secret key (remove whsec_ prefix if present)
    secret_key = webhook_secret
    if secret_key.startswith("whsec_"):
        secret_key = secret_key[6:]

    # Decode base64 secret (Standard Webhooks uses base64-encoded secrets)
    try:
        secret_bytes = base64.b64decode(secret_key)
    except Exception:
        # If not base64, use as-is (for backwards compatibility)
        secret_bytes = secret_key.encode("utf-8")

    # Compute expected signature
    expected_sig = hmac.new(
        secret_bytes,
        signed_payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    expected_b64 = base64.b64encode(expected_sig).decode("utf-8")

    # Parse signature header - can have multiple signatures (v1,sig1 v1,sig2)
    # We accept if any v1 signature matches
    signatures = signature.split(" ")
    for sig in signatures:
        if sig.startswith("v1,"):
            provided_b64 = sig[3:]  # Remove "v1," prefix
            if hmac.compare_digest(expected_b64, provided_b64):
                return  # Signature valid

    raise SignatureVerificationError("bad_signature", "incidentio")


def verify_circleback_signature(
    *,
    signing_secret: str,
    signature: Optional[str],
    raw_body: str,
) -> None:
    """
    Verify Circleback webhook signature.

    Circleback uses HMAC-SHA256:
    - Signature header (x-signature): hex_digest

    Args:
        signing_secret: Circleback webhook signing secret
        signature: x-signature header
        raw_body: Raw request body as string

    Raises:
        SignatureVerificationError: If verification fails
    """
    if not signing_secret:
        raise SignatureVerificationError("missing_signing_secret", "circleback")
    if not signature:
        raise SignatureVerificationError("missing_signature_header", "circleback")

    # Compute expected digest
    expected_digest = hmac.new(
        signing_secret.encode("utf-8"),
        raw_body.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not _constant_time_compare(expected_digest, signature):
        raise SignatureVerificationError("bad_signature", "circleback")


def verify_recall_signature(
    *,
    webhook_secret: str,
    signature: Optional[str],
    raw_body: str,
) -> None:
    """
    Verify Recall.ai webhook signature.

    Recall.ai uses HMAC-SHA256:
    - Signature header (x-recall-signature): sha256={hex_digest}

    Args:
        webhook_secret: Recall.ai webhook secret
        signature: x-recall-signature header
        raw_body: Raw request body as string

    Raises:
        SignatureVerificationError: If verification fails
    """
    if not webhook_secret:
        raise SignatureVerificationError("missing_webhook_secret", "recall")
    if not signature:
        raise SignatureVerificationError("missing_signature_header", "recall")

    # Recall signature format: sha256=<hex>
    if signature.startswith("sha256="):
        provided_digest = signature[7:]  # Remove "sha256=" prefix
    else:
        # Some versions may not have prefix
        provided_digest = signature

    # Compute expected digest
    expected_digest = hmac.new(
        webhook_secret.encode("utf-8"),
        raw_body.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not _constant_time_compare(expected_digest, provided_digest):
        raise SignatureVerificationError("bad_signature", "recall")

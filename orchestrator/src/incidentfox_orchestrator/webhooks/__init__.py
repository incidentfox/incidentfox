"""
Webhook handling utilities for IncidentFox Orchestrator.

This module provides signature verification and common utilities
for handling webhooks from external services (Slack, GitHub, PagerDuty, Incident.io,
Blameless, FireHydrant).
"""

from incidentfox_orchestrator.webhooks.signatures import (
    SignatureVerificationError,
    verify_blameless_signature,
    verify_firehydrant_signature,
    verify_github_signature,
    verify_incidentio_signature,
    verify_pagerduty_signature,
    verify_slack_signature,
)

__all__ = [
    "verify_slack_signature",
    "verify_github_signature",
    "verify_pagerduty_signature",
    "verify_incidentio_signature",
    "verify_blameless_signature",
    "verify_firehydrant_signature",
    "SignatureVerificationError",
]

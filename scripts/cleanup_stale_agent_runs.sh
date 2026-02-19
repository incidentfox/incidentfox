#!/bin/bash
#
# Cleanup Stale Agent Runs
#
# This script calls the config service to mark agent runs that have been stuck
# in 'running' status as 'timeout'. This handles edge cases like:
# - Process crash/OOM kill without graceful shutdown
# - Network partition during completion recording
# - Pod killed before shutdown handler completed
#
# Intended to be run as a Kubernetes CronJob every 5 minutes.
#
# Usage:
#   ./cleanup_stale_agent_runs.sh
#
# Environment Variables:
#   CONFIG_SERVICE_URL  - URL of the config service (required)
#   MAX_AGE_SECONDS     - Mark runs older than this as timeout (default: 600 = 10 min)
#   INTERNAL_SERVICE    - Service name for auth header (default: cleanup-job)
#

set -euo pipefail

# Configuration
CONFIG_SERVICE_URL="${CONFIG_SERVICE_URL:-http://incidentfox-config-service:8080}"
MAX_AGE_SECONDS="${MAX_AGE_SECONDS:-600}"
INTERNAL_SERVICE="${INTERNAL_SERVICE:-cleanup-job}"

echo "$(date -Iseconds) Starting stale agent runs cleanup"
echo "  Config Service: ${CONFIG_SERVICE_URL}"
echo "  Max Age: ${MAX_AGE_SECONDS} seconds"

# First, check how many stale runs there are (for logging/monitoring)
STALE_COUNT_RESPONSE=$(curl -sf \
  -H "X-Internal-Service: ${INTERNAL_SERVICE}" \
  "${CONFIG_SERVICE_URL}/api/v1/internal/agent-runs/stale-count?max_age_seconds=${MAX_AGE_SECONDS}" \
  || echo '{"error": "failed to get stale count"}')

echo "$(date -Iseconds) Stale count check: ${STALE_COUNT_RESPONSE}"

# Now perform the cleanup
CLEANUP_RESPONSE=$(curl -sf \
  -X POST \
  -H "Content-Type: application/json" \
  -H "X-Internal-Service: ${INTERNAL_SERVICE}" \
  -d "{\"max_age_seconds\": ${MAX_AGE_SECONDS}}" \
  "${CONFIG_SERVICE_URL}/api/v1/internal/agent-runs/cleanup-stale" \
  || echo '{"error": "cleanup request failed"}')

echo "$(date -Iseconds) Cleanup result: ${CLEANUP_RESPONSE}"

# Extract marked count for exit code determination
MARKED_COUNT=$(echo "${CLEANUP_RESPONSE}" | grep -o '"marked_count":[0-9]*' | grep -o '[0-9]*' || echo "0")

if [ "${MARKED_COUNT}" -gt 0 ]; then
  echo "$(date -Iseconds) WARNING: Marked ${MARKED_COUNT} stale runs as timeout"
else
  echo "$(date -Iseconds) No stale runs found"
fi

# Also clean up expired session cache entries (3-day TTL)
echo "$(date -Iseconds) Cleaning up expired session cache entries..."
SESSION_CLEANUP_RESPONSE=$(curl -sf \
  -X DELETE \
  -H "X-Internal-Service: ${INTERNAL_SERVICE}" \
  "${CONFIG_SERVICE_URL}/api/v1/internal/session-cache/expired?max_age_hours=72" \
  || echo '{"error": "session cache cleanup failed"}')

echo "$(date -Iseconds) Session cache cleanup result: ${SESSION_CLEANUP_RESPONSE}"

echo "$(date -Iseconds) Cleanup complete"

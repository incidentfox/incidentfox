#!/usr/bin/env bash
set -euo pipefail

echo "Running database migrations..."
alembic upgrade head

echo "Seeding local dev data..."
SEED_ORG_ID=local SEED_TEAM_NODE_ID=default SEED_TEAM_NAME="Local Development" python scripts/seed_demo_data.py

echo "Starting config-service..."
exec uvicorn src.api.main:app --host 0.0.0.0 --port 8080

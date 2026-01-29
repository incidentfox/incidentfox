#!/usr/bin/env bash
# Seed Recall.ai secrets to AWS Secrets Manager
#
# Usage:
#   RECALL_API_KEY=xxx RECALL_WEBHOOK_SECRET=xxx ./scripts/seed_recall_secrets.sh
#
# Prerequisites:
#   - AWS CLI configured with appropriate credentials
#   - Access to incidentfox AWS account
#   - RECALL_API_KEY and RECALL_WEBHOOK_SECRET environment variables set

set -euo pipefail

REGION="${AWS_REGION:-us-west-2}"
PROFILE="${AWS_PROFILE:-}"

if [[ -z "${RECALL_API_KEY:-}" ]]; then
    echo "Error: RECALL_API_KEY environment variable is required"
    exit 1
fi

if [[ -z "${RECALL_WEBHOOK_SECRET:-}" ]]; then
    echo "Error: RECALL_WEBHOOK_SECRET environment variable is required"
    exit 1
fi

echo "Seeding Recall.ai secrets to AWS Secrets Manager (region: $REGION)..."

python3 scripts/seed_aws_secrets.py --region "$REGION" ${PROFILE:+--profile "$PROFILE"} --from-stdin <<EOF
{
  "incidentfox/prod/recall_api_key": "${RECALL_API_KEY}",
  "incidentfox/prod/recall_webhook_secret": "${RECALL_WEBHOOK_SECRET}"
}
EOF

echo "Done! Recall.ai secrets have been seeded."
echo ""
echo "Next steps:"
echo "1. Enable Recall.ai in your Helm values:"
echo "   externalSecrets.contract.recall.enabled: true"
echo ""
echo "2. Add environment variables to orchestrator deployment:"
echo "   RECALL_API_KEY: from secret incidentfox-recall"
echo "   RECALL_WEBHOOK_SECRET: from secret incidentfox-recall"
echo "   RECALL_REGION: us-west-2"
echo "   RECALL_WEBHOOK_URL: https://orchestrator.incidentfox.ai/webhooks/recall"

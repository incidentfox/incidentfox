#!/usr/bin/env bash
# Seed Recall.ai secrets to AWS Secrets Manager
#
# Usage:
#   ./scripts/seed_recall_secrets.sh
#
# Prerequisites:
#   - AWS CLI configured with appropriate credentials
#   - Access to incidentfox AWS account

set -euo pipefail

REGION="${AWS_REGION:-us-west-2}"
PROFILE="${AWS_PROFILE:-}"

echo "Seeding Recall.ai secrets to AWS Secrets Manager (region: $REGION)..."

python3 scripts/seed_aws_secrets.py --region "$REGION" ${PROFILE:+--profile "$PROFILE"} --from-stdin <<'EOF'
{
  "incidentfox/prod/recall_api_key": "1dec1843c84426e0a840532efeed2b79d1208dfc",
  "incidentfox/prod/recall_webhook_secret": "whsec_VFMysQb1uuMEa4oKTfxfi89q8lcGWO5LjnwMiuJBYBhajjARyMQjUniD7cAUaOtd"
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

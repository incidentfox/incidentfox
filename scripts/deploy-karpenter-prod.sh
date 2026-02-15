#!/bin/bash
# Deploy Karpenter to the incidentfox-prod EKS cluster.
#
# The prod cluster was created with eksctl, so this script uses a standalone
# Terraform config (infra/terraform/envs/prod-karpenter/) for Karpenter IAM
# resources, and AWS CLI for subnet/SG tagging.
#
# This script handles:
#   1. Tag subnets + security groups for Karpenter discovery
#   2. Terraform init + plan + apply (creates IAM roles + SQS queue)
#   3. kubectl context switch to incidentfox-prod
#   4. Karpenter controller installation via setup-cluster-deps.sh
#
# Prerequisites:
#   - AWS CLI configured with 'incidentfox' profile
#   - terraform >= 1.5.0
#   - helm v3
#   - kubectl
#
# Usage:
#   ./scripts/deploy-karpenter-prod.sh           # Full deploy
#   ./scripts/deploy-karpenter-prod.sh --plan     # Plan only (no changes)
#   ./scripts/deploy-karpenter-prod.sh --skip-tf  # Skip Terraform, only install controller

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TF_DIR="$ROOT_DIR/infra/terraform/envs/prod-karpenter"

# Terraform state backend (shared bucket, separate key)
TF_STATE_BUCKET="incidentfox-tfstate-103002841599-us-east-1"
TF_STATE_KEY="incidentfox/prod-karpenter/terraform.tfstate"
TF_STATE_REGION="us-east-1"
TF_LOCK_TABLE="incidentfox-tflock"

# Cluster (eksctl-managed)
CLUSTER_NAME="incidentfox-prod"
AWS_REGION="us-west-2"

# AWS profile
export AWS_PROFILE="${AWS_PROFILE:-incidentfox}"

# Production cluster resources (from eksctl)
PRIVATE_SUBNETS=(
  "subnet-0369308e8e9955907"
  "subnet-00873819747ff89db"
  "subnet-05072ea753216a4a2"
)
NODE_SECURITY_GROUP="sg-06c0685d93169f97f"  # ClusterSharedNodeSecurityGroup

# Flags
PLAN_ONLY=false
SKIP_TF=false

for arg in "$@"; do
  case "$arg" in
    --plan) PLAN_ONLY=true ;;
    --skip-tf) SKIP_TF=true ;;
    *) echo "Unknown argument: $arg"; exit 1 ;;
  esac
done

echo "=== Deploy Karpenter to $CLUSTER_NAME ==="
echo "Region:  $AWS_REGION"
echo "Profile: $AWS_PROFILE"
echo ""

# ---------- Phase 1: Tag subnets + security groups ----------
echo "--- Phase 1: Tag AWS resources for Karpenter discovery ---"

echo "Tagging private subnets..."
for subnet in "${PRIVATE_SUBNETS[@]}"; do
  aws ec2 create-tags \
    --resources "$subnet" \
    --tags "Key=karpenter.sh/discovery,Value=$CLUSTER_NAME" \
    --region "$AWS_REGION"
  echo "  Tagged $subnet"
done

echo "Tagging node security group..."
aws ec2 create-tags \
  --resources "$NODE_SECURITY_GROUP" \
  --tags "Key=karpenter.sh/discovery,Value=$CLUSTER_NAME" \
  --region "$AWS_REGION"
echo "  Tagged $NODE_SECURITY_GROUP"
echo ""

# ---------- Phase 2: Terraform (IAM + SQS) ----------
if [ "$SKIP_TF" = false ]; then
  echo "--- Phase 2: Terraform (Karpenter IAM + SQS) ---"

  echo "Initializing Terraform..."
  terraform -chdir="$TF_DIR" init \
    -reconfigure \
    -backend-config="bucket=$TF_STATE_BUCKET" \
    -backend-config="key=$TF_STATE_KEY" \
    -backend-config="region=$TF_STATE_REGION" \
    -backend-config="dynamodb_table=$TF_LOCK_TABLE" \
    -backend-config="encrypt=true" \
    -backend-config="profile=${AWS_PROFILE}"

  echo ""
  echo "Planning Terraform changes..."
  terraform -chdir="$TF_DIR" plan -out=karpenter.tfplan

  if [ "$PLAN_ONLY" = true ]; then
    echo ""
    echo "Plan-only mode. Review the plan above."
    echo "Run without --plan to apply."
    rm -f "$TF_DIR/karpenter.tfplan"
    exit 0
  fi

  echo ""
  echo "Applying Terraform changes..."
  terraform -chdir="$TF_DIR" apply karpenter.tfplan

  rm -f "$TF_DIR/karpenter.tfplan"
else
  echo "--- Phase 2: Terraform (skipped) ---"
  echo "Reading existing outputs..."

  terraform -chdir="$TF_DIR" init \
    -reconfigure \
    -backend-config="bucket=$TF_STATE_BUCKET" \
    -backend-config="key=$TF_STATE_KEY" \
    -backend-config="region=$TF_STATE_REGION" \
    -backend-config="dynamodb_table=$TF_LOCK_TABLE" \
    -backend-config="encrypt=true" \
    -backend-config="profile=${AWS_PROFILE}" \
    > /dev/null 2>&1
fi

# Capture outputs
echo ""
echo "Capturing Terraform outputs..."
KARPENTER_ROLE_ARN=$(terraform -chdir="$TF_DIR" output -raw karpenter_irsa_role_arn 2>/dev/null || echo "")
KARPENTER_QUEUE_NAME=$(terraform -chdir="$TF_DIR" output -raw karpenter_queue_name 2>/dev/null || echo "")

echo "  KARPENTER_ROLE_ARN:   $KARPENTER_ROLE_ARN"
echo "  KARPENTER_QUEUE_NAME: $KARPENTER_QUEUE_NAME"

if [ -z "$KARPENTER_ROLE_ARN" ]; then
  echo "ERROR: karpenter_irsa_role_arn is empty. Terraform may not have created the Karpenter module."
  exit 1
fi
echo ""

# ---------- Phase 3: Switch kubectl to production ----------
echo "--- Phase 3: kubectl context ---"
echo "Updating kubeconfig for $CLUSTER_NAME..."
aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$AWS_REGION"

echo "Verifying cluster access..."
kubectl cluster-info | head -1
echo ""

# ---------- Phase 4: Install Karpenter controller ----------
echo "--- Phase 4: Karpenter controller ---"
export KARPENTER_ROLE_ARN
export KARPENTER_QUEUE_NAME
export CLUSTER_NAME

"$SCRIPT_DIR/setup-cluster-deps.sh"

# ---------- Phase 5: Verify ----------
echo "--- Phase 5: Verification ---"
echo ""
echo "Karpenter controller pods:"
kubectl get pods -n karpenter -l app.kubernetes.io/name=karpenter 2>/dev/null || echo "  (not found yet)"
echo ""
echo "Karpenter CRDs:"
kubectl get crd nodepools.karpenter.sh 2>/dev/null && echo "  NodePool CRD: OK" || echo "  NodePool CRD: MISSING"
kubectl get crd ec2nodeclasses.karpenter.k8s.aws 2>/dev/null && echo "  EC2NodeClass CRD: OK" || echo "  EC2NodeClass CRD: MISSING"
echo ""

echo "=== Karpenter infrastructure deployed ==="
echo ""
echo "Next steps:"
echo "  1. Trigger GHA deploy to create NodePool + EC2NodeClass:"
echo "     gh workflow run deploy-eks.yml -f environment=production -f services=all"
echo "  2. Verify NodePool:"
echo "     kubectl get nodepools"
echo "  3. Add secrets to GitHub for future GHA deploys:"
echo "     gh secret set KARPENTER_ROLE_ARN -b '$KARPENTER_ROLE_ARN'"
echo "     gh secret set KARPENTER_QUEUE_NAME -b '$KARPENTER_QUEUE_NAME'"

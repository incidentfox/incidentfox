#!/bin/bash
# Setup GitHub Secrets from .env file
# Usage: ./scripts/setup-github-secrets.sh

set -e

echo "🔐 Setting up GitHub Secrets"
echo "=============================="
echo ""

# Check if gh CLI is installed
if ! command -v gh &> /dev/null; then
    echo "❌ GitHub CLI (gh) not found"
    echo "   Install: brew install gh"
    exit 1
fi

# Check if authenticated
if ! gh auth status &> /dev/null; then
    echo "❌ Not authenticated with GitHub CLI"
    echo "   Run: gh auth login"
    exit 1
fi

# Find .env file (prefer root, fallback to local)
if [ -f "../.env" ]; then
    ENV_FILE="../.env"
    echo "✅ Found .env at repo root"
elif [ -f ".env" ]; then
    ENV_FILE=".env"
    echo "✅ Found .env in sre-agent/"
else
    echo "❌ .env file not found"
    exit 1
fi

# Source the .env file
source "$ENV_FILE"

# Multi-tenant architecture - GitHub secrets are for CI/CD pipeline only:
# - Platform secrets (JWT, Laminar) for deployment
# - AWS credentials for ECR/EKS access
# - Shared Anthropic key is in AWS Secrets Manager (set by setup-prod.sh)
# - Customer API keys are in config-service RDS (set by customers)

echo ""
echo "Setting required secrets..."

if [ -z "$AWS_ACCESS_KEY_ID" ]; then
    echo "⚠️  AWS_ACCESS_KEY_ID not set in .env"
else
    echo -n "$AWS_ACCESS_KEY_ID" | gh secret set AWS_ACCESS_KEY_ID
    echo "  ✅ AWS_ACCESS_KEY_ID"
fi

if [ -z "$AWS_SECRET_ACCESS_KEY" ]; then
    echo "⚠️  AWS_SECRET_ACCESS_KEY not set in .env"
else
    echo -n "$AWS_SECRET_ACCESS_KEY" | gh secret set AWS_SECRET_ACCESS_KEY
    echo "  ✅ AWS_SECRET_ACCESS_KEY"
fi

# Generate JWT_SECRET if not present
if [ -z "$JWT_SECRET" ]; then
    echo "⚠️  JWT_SECRET not set in .env, generating..."
    JWT_SECRET=$(openssl rand -hex 32)
    echo -n "$JWT_SECRET" | gh secret set JWT_SECRET
    echo "  ✅ JWT_SECRET (generated)"
    echo ""
    echo "💡 Add this to your .env file:"
    echo "   JWT_SECRET=$JWT_SECRET"
else
    echo -n "$JWT_SECRET" | gh secret set JWT_SECRET
    echo "  ✅ JWT_SECRET"
fi

if [ -z "$LMNR_PROJECT_API_KEY" ]; then
    echo "⚠️  LMNR_PROJECT_API_KEY not set in .env (required for telemetry)"
else
    echo -n "$LMNR_PROJECT_API_KEY" | gh secret set LMNR_PROJECT_API_KEY
    echo "  ✅ LMNR_PROJECT_API_KEY"
fi

echo ""
echo "✅ GitHub secrets configured!"
echo ""
echo "To verify, run:"
echo "  gh secret list"
echo ""
echo "To test deployment, run:"
echo "  gh workflow run deploy-eks.yml -f environment=staging -f services=all"
echo ""

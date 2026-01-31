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

# Required secrets
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

if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "⚠️  ANTHROPIC_API_KEY not set in .env"
else
    echo -n "$ANTHROPIC_API_KEY" | gh secret set ANTHROPIC_API_KEY
    echo "  ✅ ANTHROPIC_API_KEY"
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

# Optional secrets
echo ""
echo "Setting optional secrets..."

if [ -n "$LMNR_PROJECT_API_KEY" ]; then
    echo -n "$LMNR_PROJECT_API_KEY" | gh secret set LMNR_PROJECT_API_KEY
    echo "  ✅ LMNR_PROJECT_API_KEY"
else
    echo "  ⏭️  LMNR_PROJECT_API_KEY (skipped, not in .env)"
fi

if [ -n "$CORALOGIX_API_KEY" ]; then
    echo -n "$CORALOGIX_API_KEY" | gh secret set CORALOGIX_API_KEY
    echo "  ✅ CORALOGIX_API_KEY"
else
    echo "  ⏭️  CORALOGIX_API_KEY (skipped, not in .env)"
fi

if [ -n "$CORALOGIX_DOMAIN" ]; then
    echo -n "$CORALOGIX_DOMAIN" | gh secret set CORALOGIX_DOMAIN
    echo "  ✅ CORALOGIX_DOMAIN"
else
    echo "  ⏭️  CORALOGIX_DOMAIN (skipped, not in .env)"
fi

echo ""
echo "✅ GitHub secrets configured!"
echo ""
echo "To verify, run:"
echo "  gh secret list"
echo ""
echo "To test deployment, run:"
echo "  gh workflow run deploy-sre-agent-prod.yml"
echo ""

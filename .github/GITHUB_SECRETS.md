# GitHub Secrets Configuration

This document lists the required GitHub secrets for CI/CD workflows.

## Multi-Tenant Architecture

In the multi-tenant architecture, customer API keys are **NOT** stored in GitHub secrets or K8s secrets:

- **Customer API keys** (Anthropic BYOK, Coralogix, Datadog, etc.) → stored in config-service RDS
- **Shared Anthropic key** (for free trials) → stored in AWS Secrets Manager, accessed via IRSA
- **Platform secrets** (JWT, observability) → stored in GitHub secrets / K8s secrets

## Required Secrets for Production Deployment

Navigate to your GitHub repository → Settings → Secrets and variables → Actions → New repository secret

### AWS Credentials

- **`AWS_ACCESS_KEY_ID`** (Required)
  AWS access key with permissions to:
  - Push to ECR (Elastic Container Registry)
  - Update EKS cluster configuration
  - Manage EKS resources

- **`AWS_SECRET_ACCESS_KEY`** (Required)
  Corresponding AWS secret access key

### Platform Secrets

- **`JWT_SECRET`** (Required)
  Secret for JWT token signing between sre-agent and credential-resolver.
  Generate with: `openssl rand -hex 32`

- **`LMNR_PROJECT_API_KEY`** (Required)
  Laminar API key for **our** observability tracing (not customer's)

### Secrets NOT Needed Here

The following are stored elsewhere and do NOT need to be in GitHub secrets:

| Secret | Where It Lives | Why |
|--------|---------------|-----|
| `ANTHROPIC_API_KEY` | Config-service (BYOK) or AWS Secrets Manager (shared) | Per-tenant BYOK or shared key for free tier/non-BYOK customers |
| `CORALOGIX_API_KEY` | Config-service | Customer's observability integration |
| `CORALOGIX_DOMAIN` | Config-service | Customer's observability integration |
| `DATADOG_API_KEY` | Config-service | Customer's observability integration |

## AWS IAM Policy

The AWS credentials should have the following minimum permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken",
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage",
        "ecr:PutImage",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "eks:DescribeCluster",
        "eks:ListClusters"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "sts:GetCallerIdentity"
      ],
      "Resource": "*"
    }
  ]
}
```

## Setting Secrets via GitHub CLI

```bash
# Install GitHub CLI if needed
brew install gh

# Authenticate
gh auth login

# Set required secrets
gh secret set AWS_ACCESS_KEY_ID
gh secret set AWS_SECRET_ACCESS_KEY
gh secret set JWT_SECRET --body "$(openssl rand -hex 32)"
gh secret set LMNR_PROJECT_API_KEY
```

## Shared Anthropic Key Setup (AWS Secrets Manager)

For free tier and non-BYOK customers, the shared Anthropic key is stored in AWS Secrets Manager.
This is automatically configured when running `./scripts/setup-prod.sh`, but can be manually set:

```bash
# Create or update secret in AWS Secrets Manager
aws secretsmanager create-secret \
  --name "incidentfox/prod/anthropic" \
  --description "Shared Anthropic API key for free tier and non-BYOK customers" \
  --secret-string "sk-ant-..." \
  --region us-west-2

# Or update if it already exists:
aws secretsmanager update-secret \
  --secret-id "incidentfox/prod/anthropic" \
  --secret-string "sk-ant-..." \
  --region us-west-2

# The credential-resolver service accesses this via IRSA (IAM Roles for Service Accounts)
```

**Note**: This is the shared key used by customers who:
- Are in the free trial period
- Choose not to bring their own key (BYOK) after trial ends
- Get rate-limited features (canned responses, no auto-alert responses)

## Workflow Triggers

The deployment workflow requires **manual trigger only**:

- **Via GitHub UI**: Actions → Deploy SRE Agent to Production → Run workflow
- **Via CLI**: `gh workflow run deploy-sre-agent-prod.yml`

This ensures production deployments are intentional and controlled.

## Verifying Configuration

After setting up secrets:

1. Go to Actions tab in your GitHub repository
2. Find the "Deploy SRE Agent to Production" workflow
3. Click "Run workflow" to test manual deployment
4. Check the workflow logs for any authentication or permission issues

# GitHub Secrets Configuration

This document lists the required GitHub secrets for CI/CD workflows.

## Required Secrets for Production Deployment

Navigate to your GitHub repository → Settings → Secrets and variables → Actions → New repository secret

### AWS Credentials

- **`AWS_ACCESS_KEY_ID`**
  AWS access key with permissions to:
  - Push to ECR (Elastic Container Registry)
  - Update EKS cluster configuration
  - Manage EKS resources

- **`AWS_SECRET_ACCESS_KEY`**
  Corresponding AWS secret access key

### Application Secrets

- **`ANTHROPIC_API_KEY`** (Required)
  Your Anthropic API key for Claude access

- **`JWT_SECRET`** (Required)
  Secret for JWT token signing (generate with: `openssl rand -hex 32`)

- **`LMNR_PROJECT_API_KEY`** (Optional)
  Laminar API key for observability

- **`CORALOGIX_API_KEY`** (Optional)
  Coralogix API key for log aggregation

- **`CORALOGIX_DOMAIN`** (Optional)
  Coralogix domain (e.g., `cx498.coralogix.com`)

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

You can also set secrets using the GitHub CLI:

```bash
# Install GitHub CLI if needed
brew install gh

# Authenticate
gh auth login

# Set secrets
gh secret set AWS_ACCESS_KEY_ID
gh secret set AWS_SECRET_ACCESS_KEY
gh secret set ANTHROPIC_API_KEY
gh secret set JWT_SECRET --body "$(openssl rand -hex 32)"
gh secret set LMNR_PROJECT_API_KEY
gh secret set CORALOGIX_API_KEY
gh secret set CORALOGIX_DOMAIN
```

## Workflow Triggers

The deployment workflow requires **manual trigger only**:

- **Via GitHub UI**: Actions → Deploy SRE Agent to Production → Run workflow
- **Via CLI**: `gh workflow run deploy-sre-agent-prod.yml`

This ensures production deployments are intentional and controlled.

## Verifying Configuration

After setting up secrets, you can:

1. Go to Actions tab in your GitHub repository
2. Find the "Deploy SRE Agent to Production" workflow
3. Click "Run workflow" to test manual deployment
4. Check the workflow logs for any authentication or permission issues

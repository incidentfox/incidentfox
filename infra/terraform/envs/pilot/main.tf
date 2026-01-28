terraform {
  required_version = ">= 1.5.0"

  # Remote state is enterprise-default. `scripts/incidentfoxctl.py` passes backend config
  # (bucket/key/region/dynamodb_table) via `terraform init -backend-config=...`.
  backend "s3" {}

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.6"
    }
  }
}

provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile
}

locals {
  tags = merge(var.tags, { Environment = var.environment })
}

# Optional: create ECR repos (pilot helper).
module "ecr" {
  count  = var.create_ecr ? 1 : 0
  source = "../../modules/ecr"

  name_prefix  = "incidentfox-${var.environment}"
  repositories = var.ecr_repositories
  force_delete = var.ecr_force_delete
  tags         = local.tags
}

# Optional: create a VPC (pilot helper). Enterprises can BYO VPC/subnets instead.
module "vpc" {
  count  = var.create_vpc ? 1 : 0
  source = "../../modules/vpc"

  name               = "incidentfox-${var.environment}"
  cidr               = var.vpc_cidr
  azs                = var.vpc_azs
  public_subnets     = var.vpc_public_subnets
  private_subnets    = var.vpc_private_subnets
  single_nat_gateway = var.vpc_single_nat_gateway
  tags               = local.tags
}

locals {
  effective_vpc_id             = var.create_vpc ? module.vpc[0].vpc_id : var.vpc_id
  effective_private_subnet_ids = var.create_vpc ? module.vpc[0].private_subnet_ids : var.private_subnet_ids
}

# Optional: create an EKS cluster
module "eks" {
  count  = var.create_eks ? 1 : 0
  source = "../../modules/eks"

  cluster_name        = var.cluster_name
  cluster_version     = var.cluster_version
  cluster_endpoint_public_access       = var.cluster_endpoint_public_access
  cluster_endpoint_private_access      = var.cluster_endpoint_private_access
  cluster_endpoint_public_access_cidrs = var.cluster_endpoint_public_access_cidrs
  vpc_id              = local.effective_vpc_id
  private_subnet_ids  = local.effective_private_subnet_ids
  node_instance_types = var.node_instance_types
  node_ami_type       = var.node_ami_type
  node_min_size       = var.node_min_size
  node_max_size       = var.node_max_size
  node_desired_size   = var.node_desired_size

  # Memory-intensive node group for RAG workloads
  memory_intensive_nodegroup_enabled = var.memory_intensive_nodegroup_enabled
  memory_intensive_instance_types    = var.memory_intensive_instance_types
  memory_intensive_disk_size         = var.memory_intensive_disk_size
  memory_intensive_min_size          = var.memory_intensive_min_size
  memory_intensive_max_size          = var.memory_intensive_max_size
  memory_intensive_desired_size      = var.memory_intensive_desired_size

  tags                = local.tags
}

locals {
  oidc_provider_arn = var.create_eks ? module.eks[0].cluster_oidc_provider_arn : var.eks_oidc_provider_arn
  effective_node_sg = var.create_eks ? module.eks[0].node_security_group_id : var.eks_node_security_group_id
}

# IAM/IRSA for controllers
module "iam_irsa" {
  source              = "../../modules/iam_irsa"
  name_prefix         = "incidentfox-${var.environment}"
  oidc_provider_arn   = local.oidc_provider_arn
  secrets_manager_arns = var.eso_allowed_secret_arns
  tags                = local.tags
}

# IAM/IRSA for the IncidentFox agent (read-only AWS inspection tools)
data "aws_iam_openid_connect_provider" "eks" {
  arn = local.oidc_provider_arn
}

locals {
  agent_namespace            = "incidentfox"
  agent_service_account_name = "incidentfox-agent"
}

resource "aws_iam_role" "agent" {
  name = "incidentfox-${var.environment}-agent"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Principal = { Federated = local.oidc_provider_arn },
        Action = "sts:AssumeRoleWithWebIdentity",
        Condition = {
          StringEquals = {
            "${replace(data.aws_iam_openid_connect_provider.eks.url, "https://", "")}:sub" = "system:serviceaccount:${local.agent_namespace}:${local.agent_service_account_name}"
          }
        }
      }
    ]
  })
  tags = local.tags
}

resource "aws_iam_policy" "agent_readonly" {
  name = "incidentfox-${var.environment}-agent-readonly"
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = [
          "sts:GetCallerIdentity",

          "ec2:Describe*",
          "tag:GetResources",

          "rds:Describe*",
          "rds:ListTagsForResource",

          "logs:DescribeLogGroups",
          "logs:DescribeLogStreams",
          "logs:FilterLogEvents",
          "logs:StartQuery",
          "logs:GetQueryResults",

          "cloudwatch:GetMetricData",
          "cloudwatch:GetMetricStatistics",
          "cloudwatch:ListMetrics",
          "cloudwatch:DescribeAlarms",

          "lambda:GetFunction",
          "lambda:ListFunctions",

          "ecs:ListClusters",
          "ecs:DescribeClusters",
          "ecs:ListServices",
          "ecs:DescribeServices",
          "ecs:ListTasks",
          "ecs:DescribeTasks"
        ],
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "agent_readonly_attach" {
  role       = aws_iam_role.agent.name
  policy_arn = aws_iam_policy.agent_readonly.arn
}

# IAM/IRSA for CloudWatch Observability (logs + Container Insights metrics)
locals {
  cloudwatch_namespace = "amazon-cloudwatch"
}

resource "aws_iam_role" "cloudwatch_observability" {
  name = "incidentfox-${var.environment}-cloudwatch-observability"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Principal = { Federated = local.oidc_provider_arn },
        Action = "sts:AssumeRoleWithWebIdentity",
        Condition = {
          StringEquals = {
            "${replace(data.aws_iam_openid_connect_provider.eks.url, "https://", "")}:sub" = "system:serviceaccount:${local.cloudwatch_namespace}:cloudwatch-agent"
          }
        }
      },
      {
        Effect = "Allow",
        Principal = { Federated = local.oidc_provider_arn },
        Action = "sts:AssumeRoleWithWebIdentity",
        Condition = {
          StringEquals = {
            "${replace(data.aws_iam_openid_connect_provider.eks.url, "https://", "")}:sub" = "system:serviceaccount:${local.cloudwatch_namespace}:fluent-bit"
          }
        }
      }
    ]
  })
  tags = local.tags
}

resource "aws_iam_policy" "cloudwatch_observability" {
  name = "incidentfox-${var.environment}-cloudwatch-observability"
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = [
          # Logs
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:DescribeLogGroups",
          "logs:DescribeLogStreams",
          "logs:PutLogEvents",
          "logs:PutRetentionPolicy",

          # Metrics (Container Insights / custom PutMetricData)
          "cloudwatch:PutMetricData",

          # Needed for metadata enrichment
          "ec2:DescribeTags",
          "ec2:DescribeInstances",
          "ec2:DescribeRegions",

          # For cluster metadata
          "eks:DescribeCluster"
        ],
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "cloudwatch_observability_attach" {
  role       = aws_iam_role.cloudwatch_observability.name
  policy_arn = aws_iam_policy.cloudwatch_observability.arn
}

# Optional: create RDS
module "rds" {
  count  = var.create_rds ? 1 : 0
  source = "../../modules/rds"

  name                     = "incidentfox-${var.environment}"
  vpc_id                    = local.effective_vpc_id
  subnet_ids                = local.effective_private_subnet_ids
  allowed_security_group_id = local.effective_node_sg
  db_name                   = var.db_name
  db_username               = var.db_username
  db_password               = local.effective_db_password
  backup_retention_days     = var.rds_backup_retention_days
  deletion_protection       = var.rds_deletion_protection
  tags                      = local.tags
}

#
# Secrets (pilot): keep everything in AWS Secrets Manager and let ESO sync into the cluster.
# - We generate DB password + config_service internal secrets.
# - We intentionally DO NOT set the OpenAI key here; populate it once in Secrets Manager.
#

resource "random_password" "db_password" {
  length  = 32
  special = true
}

resource "random_password" "config_admin_token" {
  length  = 32
  special = false
}

resource "random_password" "token_pepper" {
  length  = 32
  special = true
}

resource "random_password" "impersonation_jwt_secret" {
  length  = 48
  special = true
}

locals {
  effective_db_password = length(trimspace(var.db_password)) > 0 ? var.db_password : random_password.db_password.result
  database_url = var.create_rds ? format(
    "postgresql+psycopg://%s:%s@%s:5432/%s",
    var.db_username,
    local.effective_db_password,
    module.rds[0].db_endpoint,
    var.db_name
  ) : ""
}

resource "aws_secretsmanager_secret" "database_url" {
  name = "incidentfox/pilot/database_url"
  tags = local.tags
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id     = aws_secretsmanager_secret.database_url.id
  secret_string = local.database_url
  depends_on    = [module.rds]
}

resource "aws_secretsmanager_secret" "config_service_admin_token" {
  name = "incidentfox/pilot/config_service_admin_token"
  tags = local.tags
}

resource "aws_secretsmanager_secret_version" "config_service_admin_token" {
  secret_id     = aws_secretsmanager_secret.config_service_admin_token.id
  secret_string = random_password.config_admin_token.result
}

resource "aws_secretsmanager_secret" "config_service_token_pepper" {
  name = "incidentfox/pilot/config_service_token_pepper"
  tags = local.tags
}

resource "aws_secretsmanager_secret_version" "config_service_token_pepper" {
  secret_id     = aws_secretsmanager_secret.config_service_token_pepper.id
  secret_string = random_password.token_pepper.result
}

resource "aws_secretsmanager_secret" "config_service_impersonation_jwt_secret" {
  name = "incidentfox/pilot/config_service_impersonation_jwt_secret"
  tags = local.tags
}

resource "aws_secretsmanager_secret_version" "config_service_impersonation_jwt_secret" {
  secret_id     = aws_secretsmanager_secret.config_service_impersonation_jwt_secret.id
  secret_string = random_password.impersonation_jwt_secret.result
}

resource "aws_secretsmanager_secret" "openai_api_key" {
  name = "incidentfox/pilot/openai_api_key"
  tags = local.tags
}

resource "aws_secretsmanager_secret_version" "openai_api_key" {
  secret_id     = aws_secretsmanager_secret.openai_api_key.id
  # Placeholder so ESO can sync a value. Replace via Secrets Manager before using the agent.
  secret_string = "REPLACE_ME"
}



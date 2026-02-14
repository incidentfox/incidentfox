# Karpenter IAM + SQS for the existing incidentfox-prod EKS cluster.
#
# This is a standalone config that targets an eksctl-managed cluster.
# It creates only the Karpenter-specific AWS resources (IAM roles, SQS queue).
# Subnet/SG tagging is handled by the deploy script via AWS CLI.
#
# Usage:
#   terraform init -backend-config=...
#   terraform apply

terraform {
  required_version = ">= 1.5.0"
  backend "s3" {}

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile
}

data "aws_eks_cluster" "prod" {
  name = var.cluster_name
}

# Look up the OIDC provider ARN from the cluster's identity
locals {
  oidc_issuer      = data.aws_eks_cluster.prod.identity[0].oidc[0].issuer
  oidc_provider_id = replace(local.oidc_issuer, "https://oidc.eks.${var.aws_region}.amazonaws.com/id/", "")
}

data "aws_iam_openid_connect_provider" "eks" {
  url = local.oidc_issuer
}

module "karpenter" {
  source  = "terraform-aws-modules/eks/aws//modules/karpenter"
  version = "~> 20.0"

  cluster_name = var.cluster_name

  enable_v1_permissions         = true
  enable_pod_identity           = false
  enable_irsa                   = true
  irsa_oidc_provider_arn        = data.aws_iam_openid_connect_provider.eks.arn
  node_iam_role_use_name_prefix = false
  node_iam_role_name            = "${var.cluster_name}-karpenter-node"

  tags = {
    Environment = "production"
    ManagedBy   = "terraform"
    Cluster     = var.cluster_name
  }
}

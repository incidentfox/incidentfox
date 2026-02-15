terraform {
  required_version = ">= 1.5.0"
}

# EKS module wrapper. Uses terraform-aws-modules/eks/aws.
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = var.cluster_name
  cluster_version = var.cluster_version

  vpc_id     = var.vpc_id
  subnet_ids = var.private_subnet_ids

  enable_irsa = true

  # For pilot/dev flows where kubectl/helm run from outside the VPC, we rely on
  # AWS IAM exec auth. Ensure the cluster creator (Terraform caller identity)
  # gets admin permissions via EKS Access Entries.
  enable_cluster_creator_admin_permissions = true

  cluster_endpoint_public_access       = var.cluster_endpoint_public_access
  cluster_endpoint_private_access      = var.cluster_endpoint_private_access
  cluster_endpoint_public_access_cidrs = var.cluster_endpoint_public_access_cidrs

  eks_managed_node_groups = merge(
    {
      default = {
        instance_types = var.node_instance_types
        ami_type       = var.node_ami_type
        min_size       = var.node_min_size
        max_size       = var.node_max_size
        desired_size   = var.node_desired_size
      }
    },
    var.memory_intensive_nodegroup_enabled ? {
      memory_intensive = {
        instance_types = var.memory_intensive_instance_types
        ami_type       = "AL2_x86_64" # x86 for AWS CLI compatibility
        disk_size      = var.memory_intensive_disk_size
        min_size       = var.memory_intensive_min_size
        max_size       = var.memory_intensive_max_size
        desired_size   = var.memory_intensive_desired_size
        labels = {
          "workload" = "memory-intensive"
        }
      }
    } : {}
  )

  # Tag node security group for Karpenter subnet/SG discovery
  node_security_group_tags = var.karpenter_enabled ? {
    "karpenter.sh/discovery" = var.cluster_name
  } : {}

  tags = var.tags
}

# Karpenter — dynamic node provisioning for burst workloads (production only)
module "karpenter" {
  count   = var.karpenter_enabled ? 1 : 0
  source  = "terraform-aws-modules/eks/aws//modules/karpenter"
  version = "~> 20.0"

  cluster_name = module.eks.cluster_name

  enable_v1_permissions         = true
  enable_pod_identity           = false
  enable_irsa                   = true
  irsa_oidc_provider_arn        = module.eks.oidc_provider_arn
  node_iam_role_use_name_prefix = false
  node_iam_role_name            = "${var.cluster_name}-karpenter-node"

  tags = var.tags
}

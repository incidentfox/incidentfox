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
        ami_type       = "AL2_x86_64"  # x86 for AWS CLI compatibility
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

  tags = var.tags
}



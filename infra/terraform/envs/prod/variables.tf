variable "environment" {
  type    = string
  default = "prod"
}

variable "aws_region" {
  type    = string
  default = "us-west-2"
}

variable "aws_profile" {
  type    = string
  default = ""
}

variable "tags" {
  type    = map(string)
  default = {}
}

# Optional: create ECR repos (pilot helper). Enterprises can use their own registry.
variable "create_ecr" {
  type    = bool
  default = true
}

variable "ecr_repositories" {
  type    = list(string)
  default = ["config-service", "orchestrator", "ai-pipeline-api", "agent", "web-ui"]
}

variable "ecr_force_delete" {
  type    = bool
  default = false
}

# Network (required in both BYO and create modes)
variable "vpc_id" {
  type    = string
  default = ""
}

variable "private_subnet_ids" {
  type    = list(string)
  default = []
}

# VPC mode (optional helper for pilot stacks)
variable "create_vpc" {
  type    = bool
  default = false
}

variable "vpc_cidr" {
  type    = string
  default = "10.42.0.0/16"
}

variable "vpc_azs" {
  type        = list(string)
  description = "Optional AZ list. If empty, module uses provider-available AZs."
  default     = []
}

variable "vpc_public_subnets" {
  type    = list(string)
  default = ["10.42.0.0/20", "10.42.16.0/20", "10.42.32.0/20"]
}

variable "vpc_private_subnets" {
  type    = list(string)
  default = ["10.42.128.0/20", "10.42.144.0/20", "10.42.160.0/20"]
}

variable "vpc_single_nat_gateway" {
  type    = bool
  default = true
}

# EKS mode
variable "create_eks" {
  type    = bool
  default = false
}

variable "cluster_name" {
  type    = string
  default = "incidentfox-prod"
}

variable "cluster_version" {
  type    = string
  default = "1.30"
}

variable "cluster_endpoint_public_access" {
  type    = bool
  default = false
}

variable "cluster_endpoint_private_access" {
  type    = bool
  default = true
}

variable "cluster_endpoint_public_access_cidrs" {
  type    = list(string)
  default = []
}

variable "eks_oidc_provider_arn" {
  type        = string
  default     = ""
  description = "If BYO EKS, provide OIDC provider ARN"
}

variable "node_instance_types" {
  type    = list(string)
  default = ["m7g.large"]
}

variable "node_ami_type" {
  type        = string
  description = "EKS managed node group AMI type"
  default     = "AL2023_ARM_64_STANDARD"
}

variable "node_min_size" {
  type    = number
  default = 1
}

variable "node_max_size" {
  type    = number
  default = 4
}

variable "node_desired_size" {
  type    = number
  default = 2
}

variable "eks_node_security_group_id" {
  type        = string
  default     = ""
  description = "Security group to allow DB ingress from (BYO EKS cluster SG or node SG)"
}

# Memory-intensive node group for RAG/knowledge-base workloads
variable "memory_intensive_nodegroup_enabled" {
  type        = bool
  default     = true
  description = "Enable memory-intensive node group for RAG workloads"
}

variable "memory_intensive_instance_types" {
  type        = list(string)
  default     = ["r6i.xlarge"]
  description = "Instance types for memory-intensive nodegroup (32GB RAM for RAG trees + rolling updates)"
}

variable "memory_intensive_disk_size" {
  type        = number
  default     = 50
  description = "Disk size in GB for memory-intensive nodes"
}

variable "memory_intensive_min_size" {
  type    = number
  default = 0
}

variable "memory_intensive_max_size" {
  type    = number
  default = 2
}

variable "memory_intensive_desired_size" {
  type    = number
  default = 1
}

# ESO permissions
variable "eso_allowed_secret_arns" {
  type        = list(string)
  default     = ["*"]
  description = "Secrets Manager ARNs ESO is allowed to read (restrict in real enterprise deployments)"
}

# RDS mode
variable "create_rds" {
  type    = bool
  default = false
}

variable "db_name" {
  type    = string
  default = "incidentfox"
}

variable "db_username" {
  type    = string
  default = "incidentfox"
}

variable "db_password" {
  type      = string
  default   = ""
  sensitive = true
}

variable "rds_backup_retention_days" {
  type    = number
  default = 7
}

variable "rds_deletion_protection" {
  type    = bool
  default = true
}

locals {
  _byo_network_ok = var.create_vpc || (length(trimspace(var.vpc_id)) > 0 && length(var.private_subnet_ids) > 0)
}

resource "terraform_data" "validate_inputs" {
  lifecycle {
    precondition {
      condition     = local._byo_network_ok
      error_message = "You must either set create_vpc=true OR provide vpc_id and private_subnet_ids."
    }
  }
}

terraform {
  required_version = ">= 1.5.0"
}

# If AZs are not provided, auto-select the first N AZs in the region where N is
# max(len(public_subnets), len(private_subnets)).
data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  subnet_count  = max(length(var.public_subnets), length(var.private_subnets))
  effective_azs = length(var.azs) > 0 ? var.azs : slice(data.aws_availability_zones.available.names, 0, local.subnet_count)
}

# VPC module wrapper. Uses terraform-aws-modules/vpc/aws.
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = var.name
  cidr = var.cidr

  azs             = local.effective_azs
  public_subnets  = var.public_subnets
  private_subnets = var.private_subnets

  enable_nat_gateway = true
  single_nat_gateway = var.single_nat_gateway

  enable_dns_hostnames = true
  enable_dns_support   = true

  private_subnet_tags = var.private_subnet_tags

  tags = var.tags
}



variable "name" {
  type        = string
  description = "Name prefix for the VPC"
}

variable "cidr" {
  type        = string
  description = "VPC CIDR block"
  default     = "10.42.0.0/16"
}

variable "azs" {
  type        = list(string)
  description = "Availability zones to use"
  default     = []
}

variable "public_subnets" {
  type        = list(string)
  description = "Public subnet CIDRs"
  default     = ["10.42.0.0/20", "10.42.16.0/20", "10.42.32.0/20"]
}

variable "private_subnets" {
  type        = list(string)
  description = "Private subnet CIDRs"
  default     = ["10.42.128.0/20", "10.42.144.0/20", "10.42.160.0/20"]
}

variable "single_nat_gateway" {
  type        = bool
  description = "Use a single NAT gateway (cheaper, less HA)"
  default     = true
}

variable "tags" {
  type        = map(string)
  description = "Tags applied to AWS resources"
  default     = {}
}

variable "private_subnet_tags" {
  type        = map(string)
  description = "Additional tags for private subnets (e.g. Karpenter discovery)"
  default     = {}
}

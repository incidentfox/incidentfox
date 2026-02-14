output "cluster_name" {
  value = module.eks.cluster_name
}

output "cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "cluster_oidc_provider_arn" {
  value = module.eks.oidc_provider_arn
}

output "cluster_oidc_provider" {
  value = module.eks.oidc_provider
}

output "node_security_group_id" {
  value = module.eks.node_security_group_id
}

# Karpenter outputs (null when disabled)
output "karpenter_irsa_role_arn" {
  value = try(module.karpenter[0].iam_role_arn, null)
}

output "karpenter_node_role_name" {
  value = try(module.karpenter[0].node_iam_role_name, null)
}

output "karpenter_queue_name" {
  value = try(module.karpenter[0].queue_name, null)
}

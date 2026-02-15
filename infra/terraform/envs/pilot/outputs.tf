output "alb_controller_role_arn" {
  value = module.iam_irsa.alb_controller_role_arn
}

output "external_secrets_role_arn" {
  value = module.iam_irsa.external_secrets_role_arn
}

output "agent_role_arn" {
  value = aws_iam_role.agent.arn
}

output "cloudwatch_observability_role_arn" {
  value = aws_iam_role.cloudwatch_observability.arn
}

output "alerts_sns_topic_arn" {
  value = aws_sns_topic.incidentfox_alerts.arn
}

output "ecr_repository_urls" {
  value = try(module.ecr[0].repository_urls, null)
}

output "eks_cluster_name" {
  value = try(module.eks[0].cluster_name, null)
}

output "eks_node_security_group_id" {
  value = try(module.eks[0].node_security_group_id, null)
}

output "vpc_id" {
  value = try(module.vpc[0].vpc_id, null)
}

output "private_subnet_ids" {
  value = try(module.vpc[0].private_subnet_ids, null)
}

output "rds_endpoint" {
  value = try(module.rds[0].db_endpoint, null)
}

# Karpenter outputs (null when disabled)
output "karpenter_irsa_role_arn" {
  value = try(module.eks[0].karpenter_irsa_role_arn, null)
}

output "karpenter_node_role_name" {
  value = try(module.eks[0].karpenter_node_role_name, null)
}

output "karpenter_queue_name" {
  value = try(module.eks[0].karpenter_queue_name, null)
}

output "pilot_secrets" {
  value = {
    database_url                            = "incidentfox/pilot/database_url"
    config_service_admin_token              = "incidentfox/pilot/config_service_admin_token"
    config_service_token_pepper             = "incidentfox/pilot/config_service_token_pepper"
    config_service_impersonation_jwt_secret = "incidentfox/pilot/config_service_impersonation_jwt_secret"
    openai_api_key                          = "incidentfox/pilot/openai_api_key"
  }
}



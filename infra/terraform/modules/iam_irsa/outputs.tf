output "alb_controller_role_arn" {
  value = aws_iam_role.alb_controller.arn
}

output "external_secrets_role_arn" {
  value = aws_iam_role.external_secrets.arn
}

output "knowledge_base_role_arn" {
  value       = var.knowledge_base_enabled ? aws_iam_role.knowledge_base[0].arn : ""
  description = "IAM role ARN for knowledge-base service account (IRSA)"
}



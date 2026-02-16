locals {
  cw_region        = var.aws_region
  cw_cluster_name  = var.cluster_name
  cw_alarm_prefix  = "${var.cluster_name}"
  cw_log_namespace = "IncidentFox"

  # Container Insights log group where app logs land (JSON logs from pods)
  cw_app_log_group = "/aws/containerinsights/${var.cluster_name}/application"

  # Optional: send alarm notifications to SNS (used by AWS Chatbot)
  cw_alarm_actions = var.enable_chatbot_slack ? [aws_sns_topic.incidentfox_alerts.arn] : []
}

#
# Inputs for infra-level alarm dimensions.
#
# We intentionally keep these as variables so the team can review/change and so
# Terraform doesn't need to “discover” k8s-managed resources.
#
variable "alb_load_balancer_dimension" {
  type        = string
  description = "CloudWatch dimension value for ALB alarms (the 'app/..../....' suffix, not the full ARN). Example: app/k8s-incident-incident-bb9f18348b/3e9b1a1acbca10a1"
  default     = ""
}

variable "rds_instance_identifier" {
  type        = string
  description = "RDS DBInstanceIdentifier for alarms."
  default     = "incidentfox-prod"
}

#
# -----------------
# ALB (Web UI) alarms
# -----------------
#
resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name          = "${local.cw_alarm_prefix}-alb-5xx"
  alarm_description   = "ALB 5xx detected"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_ELB_5XX_Count"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 5
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.cw_alarm_actions

  dimensions = {
    LoadBalancer = var.alb_load_balancer_dimension
  }
}

resource "aws_cloudwatch_metric_alarm" "alb_target_5xx" {
  alarm_name          = "${local.cw_alarm_prefix}-alb-target-5xx"
  alarm_description   = "Targets returning 5xx"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 5
  threshold           = 5
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.cw_alarm_actions

  dimensions = {
    LoadBalancer = var.alb_load_balancer_dimension
  }
}

resource "aws_cloudwatch_metric_alarm" "alb_p95_latency" {
  alarm_name          = "${local.cw_alarm_prefix}-alb-p95-latency"
  alarm_description   = "p95 target response time too high"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "TargetResponseTime"
  extended_statistic  = "p95"
  period              = 60
  evaluation_periods  = 5
  threshold           = 2
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.cw_alarm_actions

  dimensions = {
    LoadBalancer = var.alb_load_balancer_dimension
  }
}

resource "aws_cloudwatch_metric_alarm" "alb_unhealthy_targets" {
  alarm_name          = "${local.cw_alarm_prefix}-alb-unhealthy-targets"
  alarm_description   = "Unhealthy targets > 0"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "UnHealthyHostCount"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.cw_alarm_actions

  dimensions = {
    LoadBalancer = var.alb_load_balancer_dimension
  }
}

#
# -----------------
# RDS alarms
# -----------------
#
resource "aws_cloudwatch_metric_alarm" "rds_cpu_high" {
  alarm_name          = "${local.cw_alarm_prefix}-rds-cpu-high"
  alarm_description   = "RDS CPU > 80%"
  namespace           = "AWS/RDS"
  metric_name         = "CPUUtilization"
  statistic           = "Average"
  period              = 60
  evaluation_periods  = 10
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.cw_alarm_actions

  dimensions = {
    DBInstanceIdentifier = var.rds_instance_identifier
  }
}

resource "aws_cloudwatch_metric_alarm" "rds_free_storage_low" {
  alarm_name          = "${local.cw_alarm_prefix}-rds-free-storage-low"
  alarm_description   = "RDS free storage < 10GB"
  namespace           = "AWS/RDS"
  metric_name         = "FreeStorageSpace"
  statistic           = "Minimum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 10737418240 # 10GiB in bytes
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.cw_alarm_actions

  dimensions = {
    DBInstanceIdentifier = var.rds_instance_identifier
  }
}

resource "aws_cloudwatch_metric_alarm" "rds_free_mem_low" {
  alarm_name          = "${local.cw_alarm_prefix}-rds-free-mem-low"
  alarm_description   = "RDS freeable memory low (<512MiB)"
  namespace           = "AWS/RDS"
  metric_name         = "FreeableMemory"
  statistic           = "Minimum"
  period              = 60
  evaluation_periods  = 10
  threshold           = 536870912 # 512MiB
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.cw_alarm_actions

  dimensions = {
    DBInstanceIdentifier = var.rds_instance_identifier
  }
}

resource "aws_cloudwatch_metric_alarm" "rds_connections_high" {
  alarm_name          = "${local.cw_alarm_prefix}-rds-connections-high"
  alarm_description   = "RDS connections > 200"
  namespace           = "AWS/RDS"
  metric_name         = "DatabaseConnections"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 10
  threshold           = 200
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.cw_alarm_actions

  dimensions = {
    DBInstanceIdentifier = var.rds_instance_identifier
  }
}

resource "aws_cloudwatch_metric_alarm" "rds_write_latency_high" {
  alarm_name          = "${local.cw_alarm_prefix}-rds-latency-write"
  alarm_description   = "RDS write latency high (>50ms)"
  namespace           = "AWS/RDS"
  metric_name         = "WriteLatency"
  statistic           = "Average"
  period              = 60
  evaluation_periods  = 10
  threshold           = 0.05
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.cw_alarm_actions

  dimensions = {
    DBInstanceIdentifier = var.rds_instance_identifier
  }
}

resource "aws_cloudwatch_metric_alarm" "rds_read_latency_high" {
  alarm_name          = "${local.cw_alarm_prefix}-rds-latency-read"
  alarm_description   = "RDS read latency high (>50ms)"
  namespace           = "AWS/RDS"
  metric_name         = "ReadLatency"
  statistic           = "Average"
  period              = 60
  evaluation_periods  = 10
  threshold           = 0.05
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.cw_alarm_actions

  dimensions = {
    DBInstanceIdentifier = var.rds_instance_identifier
  }
}

#
# -----------------
# App-level alarms from log metric filters (JSON structured logs)
# -----------------
#
resource "aws_cloudwatch_log_metric_filter" "slack_trigger_failed" {
  name           = "${local.cw_alarm_prefix}-slack-trigger-failed"
  log_group_name = local.cw_app_log_group
  pattern        = "{ $.event = \"slack_trigger_run_failed\" }"

  metric_transformation {
    name          = "slack_trigger_failed"
    namespace     = local.cw_log_namespace
    value         = "1"
    default_value = 0
  }
}

resource "aws_cloudwatch_log_metric_filter" "slack_post_failed" {
  name           = "${local.cw_alarm_prefix}-slack-post-failed"
  log_group_name = local.cw_app_log_group
  pattern        = "{ $.event = \"slack_post_failed\" }"

  metric_transformation {
    name          = "slack_post_failed"
    namespace     = local.cw_log_namespace
    value         = "1"
    default_value = 0
  }
}

resource "aws_cloudwatch_log_metric_filter" "agent_upstream_error" {
  name           = "${local.cw_alarm_prefix}-agent-upstream-error"
  log_group_name = local.cw_app_log_group
  pattern        = "agent_upstream_error"

  metric_transformation {
    name          = "agent_upstream_error"
    namespace     = local.cw_log_namespace
    value         = "1"
    default_value = 0
  }
}

resource "aws_cloudwatch_metric_alarm" "slack_trigger_failed_alarm" {
  alarm_name          = "${local.cw_alarm_prefix}-slack-trigger-failed"
  alarm_description   = "Slack trigger runs failing"
  namespace           = local.cw_log_namespace
  metric_name         = aws_cloudwatch_log_metric_filter.slack_trigger_failed.metric_transformation[0].name
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 5
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.cw_alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "slack_post_failed_alarm" {
  alarm_name          = "${local.cw_alarm_prefix}-slack-post-failed"
  alarm_description   = "Slack postMessage failures"
  namespace           = local.cw_log_namespace
  metric_name         = aws_cloudwatch_log_metric_filter.slack_post_failed.metric_transformation[0].name
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 5
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.cw_alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "agent_upstream_error_alarm" {
  alarm_name          = "${local.cw_alarm_prefix}-agent-upstream-error"
  alarm_description   = "Orchestrator/agent upstream errors"
  namespace           = local.cw_log_namespace
  metric_name         = aws_cloudwatch_log_metric_filter.agent_upstream_error.metric_transformation[0].name
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 5
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.cw_alarm_actions
}

#
# -----------------
# Container Insights alarms (Kubernetes)
# -----------------
#
resource "aws_cloudwatch_metric_alarm" "k8s_pods_not_running" {
  alarm_name          = "${local.cw_alarm_prefix}-k8s-pods-not-running"
  alarm_description   = "Pods not running (namespace incidentfox)"
  namespace           = "ContainerInsights"
  metric_name         = "pod_container_status_running"
  statistic           = "Minimum"
  period              = 60
  evaluation_periods  = 5
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.cw_alarm_actions

  dimensions = {
    ClusterName = local.cw_cluster_name
    Namespace   = "incidentfox"
  }
}

resource "aws_cloudwatch_metric_alarm" "k8s_restarts" {
  alarm_name          = "${local.cw_alarm_prefix}-k8s-restarts"
  alarm_description   = "Container restarts detected (namespace incidentfox)"
  namespace           = "ContainerInsights"
  metric_name         = "pod_number_of_container_restarts"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.cw_alarm_actions

  dimensions = {
    ClusterName = local.cw_cluster_name
    Namespace   = "incidentfox"
  }
}



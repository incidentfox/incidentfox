#
# Slack paging via AWS Chatbot
#
# AWS Chatbot itself is free, but SNS + CloudWatch usage may incur small AWS charges depending on volume.
#

variable "enable_chatbot_slack" {
  type        = bool
  description = "If true, create an AWS Chatbot Slack channel configuration and wire alarms to SNS."
  default     = false
}

variable "slack_team_id" {
  type        = string
  description = "Slack workspace/team ID (starts with T...). Required when enable_chatbot_slack=true."
  default     = ""
}

variable "slack_channel_id" {
  type        = string
  description = "Slack channel ID (starts with C...). Required when enable_chatbot_slack=true."
  default     = ""
}

resource "aws_sns_topic" "incidentfox_alerts" {
  name = "${var.cluster_name}-alerts"
  tags = local.tags
}

# Allow CloudWatch Alarms to publish to the SNS topic
resource "aws_sns_topic_policy" "incidentfox_alerts" {
  arn = aws_sns_topic.incidentfox_alerts.arn
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Sid    = "AllowCloudWatchAlarmsPublish",
        Effect = "Allow",
        Principal = {
          Service = "cloudwatch.amazonaws.com"
        },
        Action   = "sns:Publish",
        Resource = aws_sns_topic.incidentfox_alerts.arn
      }
    ]
  })
}

# Chatbot needs an IAM role
resource "aws_iam_role" "chatbot" {
  count = var.enable_chatbot_slack ? 1 : 0
  name  = "incidentfox-${var.environment}-chatbot"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Principal = {
          Service = "chatbot.amazonaws.com"
        },
        Action = "sts:AssumeRole"
      }
    ]
  })
  tags = local.tags
}

resource "aws_iam_role_policy" "chatbot_inline" {
  count = var.enable_chatbot_slack ? 1 : 0
  name  = "incidentfox-${var.environment}-chatbot-inline"
  role  = aws_iam_role.chatbot[0].id

  # Minimal policy for SNS -> Slack notifications:
  # allow AWS Chatbot to manage subscriptions to the alerts topic.
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Sid    = "AllowSnsSubscribeToAlertsTopic",
        Effect = "Allow",
        Action = [
          "sns:GetTopicAttributes",
          "sns:ListSubscriptionsByTopic",
          "sns:Subscribe",
          "sns:Unsubscribe"
        ],
        Resource = aws_sns_topic.incidentfox_alerts.arn
      },
      # Optional read-only (useful if later you enable Chatbot AWS commands in Slack).
      {
        Sid    = "AllowReadOnlyCloudWatchForContext",
        Effect = "Allow",
        Action = [
          "cloudwatch:DescribeAlarms",
          "cloudwatch:DescribeAlarmHistory",
          "cloudwatch:GetMetricData",
          "cloudwatch:GetMetricStatistics",
          "cloudwatch:ListMetrics"
        ],
        Resource = "*"
      }
    ]
  })
}

resource "aws_chatbot_slack_channel_configuration" "incidentfox_alerts" {
  count = var.enable_chatbot_slack ? 1 : 0

  configuration_name = "${var.cluster_name}-alerts"
  iam_role_arn       = aws_iam_role.chatbot[0].arn

  # AWS provider uses slack_team_id for the workspace/team identifier.
  slack_team_id    = var.slack_team_id
  slack_channel_id   = var.slack_channel_id

  sns_topic_arns = [aws_sns_topic.incidentfox_alerts.arn]

  logging_level = "ERROR"

  lifecycle {
    precondition {
      condition     = length(trimspace(var.slack_team_id)) > 0 && length(trimspace(var.slack_channel_id)) > 0
      error_message = "When enable_chatbot_slack=true you must set slack_team_id (T...) and slack_channel_id (C...)."
    }
  }

  tags = local.tags
}



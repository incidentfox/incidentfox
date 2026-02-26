---
name: aws-infrastructure
description: AWS cloud infrastructure inspection. Use when investigating EC2 instances, ECS tasks/services, Lambda functions, CloudWatch logs/metrics, or AWS resource issues.
allowed-tools: Bash(python *)
---

# AWS Infrastructure

## Authentication

**IMPORTANT**: Credentials are fetched automatically from the credential resolver. Do NOT check for `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY` in environment variables — they won't be visible to you. Just run the scripts directly; authentication is handled transparently.

Configuration you CAN check (non-secret):
- `CONFIGURED_INTEGRATIONS` — JSON list, check if `aws` is present

---

## MANDATORY: Logs/Metrics-First Investigation

**Start with CloudWatch logs or metrics, then drill into resources.**

```
CLOUDWATCH LOGS/METRICS → IDENTIFY RESOURCE → DESCRIBE RESOURCE → CHECK ALARMS
```

## Available Scripts

All scripts are in `.claude/skills/infrastructure-aws/scripts/`

### get_cloudwatch_logs.py - CloudWatch Log Queries (START HERE for log investigation)
```bash
python .claude/skills/infrastructure-aws/scripts/get_cloudwatch_logs.py --log-group /aws/lambda/my-function --filter "ERROR" --hours 1
python .claude/skills/infrastructure-aws/scripts/get_cloudwatch_logs.py --log-group /ecs/my-service --filter "Exception" --hours 6 --limit 50
```

### get_cloudwatch_metrics.py - CloudWatch Metrics
```bash
python .claude/skills/infrastructure-aws/scripts/get_cloudwatch_metrics.py --namespace AWS/EC2 --metric CPUUtilization --dimension InstanceId=i-1234567890abcdef0 --hours 1
python .claude/skills/infrastructure-aws/scripts/get_cloudwatch_metrics.py --namespace AWS/ECS --metric CPUUtilization --dimension ClusterName=prod,ServiceName=api --hours 6 --period 300
```

### list_cloudwatch_alarms.py - CloudWatch Alarms
```bash
python .claude/skills/infrastructure-aws/scripts/list_cloudwatch_alarms.py
python .claude/skills/infrastructure-aws/scripts/list_cloudwatch_alarms.py --state ALARM
```

### list_ec2_instances.py - List EC2 Instances
```bash
python .claude/skills/infrastructure-aws/scripts/list_ec2_instances.py
python .claude/skills/infrastructure-aws/scripts/list_ec2_instances.py --filters "Name=tag:env,Values=production"
python .claude/skills/infrastructure-aws/scripts/list_ec2_instances.py --filters "Name=instance-state-name,Values=running"
```

### describe_ec2_instance.py - Detailed EC2 Instance Info
```bash
python .claude/skills/infrastructure-aws/scripts/describe_ec2_instance.py --instance-id i-1234567890abcdef0
```

### list_ecs_services.py - List ECS Services
```bash
python .claude/skills/infrastructure-aws/scripts/list_ecs_services.py --cluster prod-api
python .claude/skills/infrastructure-aws/scripts/list_ecs_services.py --cluster prod-api --json
```

### describe_ecs_service.py - ECS Service Details
```bash
python .claude/skills/infrastructure-aws/scripts/describe_ecs_service.py --cluster prod-api --service api-handler
```

### list_lambda_functions.py - List Lambda Functions
```bash
python .claude/skills/infrastructure-aws/scripts/list_lambda_functions.py
python .claude/skills/infrastructure-aws/scripts/list_lambda_functions.py --prefix api-
```

### get_lambda_logs.py - Lambda Invocation Logs
```bash
python .claude/skills/infrastructure-aws/scripts/get_lambda_logs.py --function-name api-handler --hours 1
python .claude/skills/infrastructure-aws/scripts/get_lambda_logs.py --function-name api-handler --filter "ERROR" --limit 20
```

---

## Investigation Workflows

### EC2 Instance Issue
```
1. list_ec2_instances.py --filters "Name=instance-state-name,Values=running"
2. describe_ec2_instance.py --instance-id <id>
3. get_cloudwatch_metrics.py --namespace AWS/EC2 --metric CPUUtilization --dimension InstanceId=<id>
4. list_cloudwatch_alarms.py --state ALARM
```

### ECS Task Failure
```
1. list_ecs_services.py --cluster <cluster>
2. describe_ecs_service.py --cluster <cluster> --service <service>
3. get_cloudwatch_logs.py --log-group /ecs/<service> --filter "ERROR" --hours 1
4. get_cloudwatch_metrics.py --namespace AWS/ECS --metric CPUUtilization --dimension ClusterName=<cluster>,ServiceName=<service>
```

### Lambda Error Investigation
```
1. list_lambda_functions.py
2. get_lambda_logs.py --function-name <function> --filter "ERROR" --hours 1
3. get_cloudwatch_metrics.py --namespace AWS/Lambda --metric Errors --dimension FunctionName=<function>
4. get_cloudwatch_metrics.py --namespace AWS/Lambda --metric Duration --dimension FunctionName=<function>
```

### Cost / Resource Audit
```
1. list_ec2_instances.py
2. list_ecs_services.py --cluster <cluster>
3. list_lambda_functions.py
4. get_cloudwatch_metrics.py (check utilization of resources)
```

## Output Format

When reporting findings, use this structure:

```
## AWS Analysis

**Service**: <EC2/ECS/Lambda/CloudWatch>
**Region**: <region>
**Resource**: <resource identifier>

### Findings
- [Finding with evidence]

### Root Cause Hypothesis
[Based on metrics and logs]

### Recommended Action
[Specific remediation step]
```

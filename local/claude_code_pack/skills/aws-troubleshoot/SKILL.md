---
name: aws-troubleshoot
description: AWS service troubleshooting patterns. Use for EC2, ECS, Lambda, CloudWatch, RDS issues.
---

# AWS Troubleshooting Expertise

## Investigation Methodology

1. **Identify the AWS resource/service involved**
2. **Check resource status** using describe functions
3. **Review CloudWatch logs** for errors
4. **Check CloudWatch metrics** for anomalies
5. **Analyze configuration** for misconfigurations
6. **Synthesize and recommend**

## CloudWatch Logs Strategy

### Partition First (CRITICAL)

**Never dump all logs.** Use aggregation queries first:

```
# Error rate over time
filter @message like /ERROR/
| stats count(*) as errors by bin(5m)

# Top error messages
filter @message like /Exception/
| stats count(*) by @message
| sort count desc
| limit 10

# Latency percentiles
stats pct(@duration, 50) as p50, pct(@duration, 99) as p99 by bin(5m)

# Unique error types
filter @message like /ERROR/
| parse @message /(?<error_type>[\w.]+Exception)/
| stats count(*) by error_type
```

### Query Flow

1. **Statistics first**: Get error counts, distributions
2. **Identify time windows**: Find when errors spiked
3. **Sample from spikes**: Get specific examples
4. **Compare to baseline**: Query same period yesterday/last week

## Service-Specific Patterns

### EC2 Issues

| Symptom | First Check | Typical Cause |
|---------|-------------|---------------|
| Unreachable | `describe_ec2_instance` | Security group, stopped, status check failed |
| Performance | `get_cloudwatch_metrics` (CPUUtilization) | CPU exhaustion, network saturation |
| Disk full | `get_cloudwatch_metrics` (DiskSpaceUtilization) | Logs, temp files |

**Key CloudWatch metrics for EC2**:
- CPUUtilization
- NetworkIn, NetworkOut
- DiskReadOps, DiskWriteOps
- StatusCheckFailed

### Lambda Issues

| Symptom | First Check | Typical Cause |
|---------|-------------|---------------|
| Timeout | CloudWatch logs | External call slow, cold start, insufficient memory |
| Permission denied | CloudWatch logs | IAM role missing permissions |
| Memory error | CloudWatch metrics | Memory allocation too low |
| Cold starts | CloudWatch logs + metrics | Provisioned concurrency needed |

**Key CloudWatch metrics for Lambda**:
- Invocations
- Duration
- Errors
- Throttles
- ConcurrentExecutions

**CloudWatch Insights for Lambda**:
```
# Cold start analysis
filter @type = "REPORT"
| stats avg(@initDuration) as avg_cold_start,
        count(@initDuration) as cold_starts,
        count(*) as total_invocations
        by bin(5m)

# Timeout analysis
filter @message like /Task timed out/
| stats count(*) by bin(5m)
```

### ECS/Fargate Issues

| Symptom | First Check | Typical Cause |
|---------|-------------|---------------|
| Task failed | `list_ecs_tasks` | Container crash, resource limits, image pull |
| Service unhealthy | `list_ecs_tasks` | Health check failing, target group issues |
| Slow scaling | CloudWatch metrics | Insufficient capacity, service limits |

**Investigation flow**:
1. `list_ecs_tasks` - See task status and health
2. Check stopped reason in task description
3. Review CloudWatch logs for the task
4. Check container insights metrics

### RDS Issues

| Symptom | First Check | Typical Cause |
|---------|-------------|---------------|
| Connection refused | `get_rds_instance_status` | Security group, stopped, maintenance |
| Slow queries | CloudWatch metrics | CPU, IOPS, connections |
| Storage full | CloudWatch metrics | Data growth, logs, snapshots |

**Key CloudWatch metrics for RDS**:
- CPUUtilization
- DatabaseConnections
- ReadIOPS, WriteIOPS
- FreeStorageSpace
- ReadLatency, WriteLatency

## Common AWS Errors

### Permission Errors
```
AccessDeniedException
UnauthorizedAccess
```
→ Check IAM role/policy attached to the service

### Throttling
```
Throttling
Rate exceeded
TooManyRequestsException
```
→ Implement exponential backoff, request limit increase

### Resource Not Found
```
ResourceNotFoundException
NoSuchEntity
```
→ Verify resource name, region, account

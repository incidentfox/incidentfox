"""AWS resource inspection and debugging tools."""

import json
from datetime import UTC
from typing import Any

import boto3
from agents import function_tool
from botocore.exceptions import ClientError, NoCredentialsError

from ..core.config_required import make_config_required_response
from ..core.execution_context import get_execution_context
from ..core.integration_errors import IntegrationNotConfiguredError
from ..core.logging import get_logger

logger = get_logger(__name__)


def _aws_config_required_response(tool_name: str) -> str:
    """Create config_required response for AWS tools."""
    return make_config_required_response(
        integration="aws",
        tool=tool_name,
        missing_config=["AWS credentials (access key, secret key, or IAM role)"],
    )


def _get_aws_session(region: str = "us-east-1"):
    """
    Get boto3 session with credentials from execution context or default chain.

    AWS credentials can come from:
    1. Execution context (for explicitly configured credentials)
    2. Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
    3. ~/.aws/credentials file
    4. IAM instance profile (for EC2)
    5. IAM task role (for ECS/Fargate)
    """
    # 1. Try execution context (explicit config)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("aws")
        if config and config.get("access_key_id") and config.get("secret_access_key"):
            return boto3.Session(
                aws_access_key_id=config["access_key_id"],
                aws_secret_access_key=config["secret_access_key"],
                region_name=config.get("region", region),
            )

    # 2. Use default boto3 credential chain (env vars, IAM roles, etc.)
    # This is the standard AWS approach and supports all AWS credential sources
    try:
        session = boto3.Session(region_name=region)
        # Test that credentials are available
        session.client("sts").get_caller_identity()
        return session
    except NoCredentialsError:
        # 3. Not configured - raise error
        raise IntegrationNotConfiguredError(
            integration_id="aws", tool_id="aws_tools", missing_fields=["credentials"]
        )


@function_tool(strict_mode=False)
def describe_ec2_instance(instance_id: str, region: str = "us-east-1") -> str:
    """
    Get details about an EC2 instance.

    Args:
        instance_id: EC2 instance ID
        region: AWS region

    Returns:
        Instance details as JSON string
    """
    try:
        session = _get_aws_session(region)
        ec2 = session.client("ec2")
        response = ec2.describe_instances(InstanceIds=[instance_id])

        if not response["Reservations"]:
            return json.dumps(
                {"error": "Instance not found", "instance_id": instance_id}
            )

        instance = response["Reservations"][0]["Instances"][0]

        result = {
            "instance_id": instance["InstanceId"],
            "state": instance["State"]["Name"],
            "instance_type": instance["InstanceType"],
            "availability_zone": instance["Placement"]["AvailabilityZone"],
            "private_ip": instance.get("PrivateIpAddress"),
            "public_ip": instance.get("PublicIpAddress"),
            "launch_time": str(instance["LaunchTime"]),
            "tags": {tag["Key"]: tag["Value"] for tag in instance.get("Tags", [])},
        }
        return json.dumps(result)

    except IntegrationNotConfiguredError:
        logger.warning("aws_not_configured", tool="describe_ec2_instance")
        return _aws_config_required_response("describe_ec2_instance")
    except ClientError as e:
        logger.error(
            "failed_to_describe_ec2_instance", error=str(e), instance_id=instance_id
        )
        return json.dumps({"error": str(e), "instance_id": instance_id})


@function_tool(strict_mode=False)
def get_cloudwatch_logs(
    log_group: str,
    log_stream: str | None = None,
    limit: int = 100,
    region: str = "us-east-1",
) -> str:
    """
    Get logs from CloudWatch.

    Args:
        log_group: CloudWatch log group name
        log_stream: Optional specific log stream
        limit: Number of log events to retrieve
        region: AWS region

    Returns:
        List of log messages as JSON string
    """
    try:
        session = _get_aws_session(region)
        logs = session.client("logs")

        if log_stream:
            response = logs.get_log_events(
                logGroupName=log_group,
                logStreamName=log_stream,
                limit=limit,
            )
            messages = [event["message"] for event in response["events"]]
        else:
            # Get latest log stream
            streams = logs.describe_log_streams(
                logGroupName=log_group,
                orderBy="LastEventTime",
                descending=True,
                limit=1,
            )

            if not streams["logStreams"]:
                return json.dumps(
                    {
                        "log_group": log_group,
                        "messages": [],
                        "error": "No log streams found",
                    }
                )

            stream_name = streams["logStreams"][0]["logStreamName"]
            response = logs.get_log_events(
                logGroupName=log_group,
                logStreamName=stream_name,
                limit=limit,
            )
            messages = [event["message"] for event in response["events"]]

        return json.dumps(
            {
                "log_group": log_group,
                "message_count": len(messages),
                "messages": messages,
            }
        )

    except IntegrationNotConfiguredError:
        logger.warning("aws_not_configured", tool="get_cloudwatch_logs")
        return _aws_config_required_response("get_cloudwatch_logs")
    except ClientError as e:
        logger.error("failed_to_get_cloudwatch_logs", error=str(e), log_group=log_group)
        return json.dumps({"error": str(e), "log_group": log_group})


@function_tool(strict_mode=False)
def describe_lambda_function(function_name: str, region: str = "us-east-1") -> str:
    """
    Get details about a Lambda function.

    Args:
        function_name: Lambda function name
        region: AWS region

    Returns:
        Function configuration as JSON string
    """
    try:
        session = _get_aws_session(region)
        lambda_client = session.client("lambda")
        response = lambda_client.get_function(FunctionName=function_name)

        config = response["Configuration"]

        result = {
            "function_name": config["FunctionName"],
            "runtime": config["Runtime"],
            "memory": config["MemorySize"],
            "timeout": config["Timeout"],
            "last_modified": config["LastModified"],
            "environment": config.get("Environment", {}).get("Variables", {}),
            "vpc_config": config.get("VpcConfig", {}),
        }
        return json.dumps(result)

    except IntegrationNotConfiguredError:
        logger.warning("aws_not_configured", tool="describe_lambda_function")
        return _aws_config_required_response("describe_lambda_function")
    except ClientError as e:
        logger.error("failed_to_describe_lambda", error=str(e), function=function_name)
        return json.dumps({"error": str(e), "function_name": function_name})


@function_tool(strict_mode=False)
def get_rds_instance_status(db_instance_id: str, region: str = "us-east-1") -> str:
    """
    Get RDS instance status.

    Args:
        db_instance_id: RDS instance identifier
        region: AWS region

    Returns:
        Instance status as JSON string
    """
    try:
        session = _get_aws_session(region)
        rds = session.client("rds")
        response = rds.describe_db_instances(DBInstanceIdentifier=db_instance_id)

        if not response["DBInstances"]:
            return json.dumps(
                {"error": "Instance not found", "db_instance_id": db_instance_id}
            )

        db = response["DBInstances"][0]

        result = {
            "db_instance_id": db["DBInstanceIdentifier"],
            "status": db["DBInstanceStatus"],
            "engine": db["Engine"],
            "engine_version": db["EngineVersion"],
            "instance_class": db["DBInstanceClass"],
            "availability_zone": db["AvailabilityZone"],
            "endpoint": db.get("Endpoint", {}).get("Address"),
            "port": db.get("Endpoint", {}).get("Port"),
        }
        return json.dumps(result)

    except IntegrationNotConfiguredError:
        logger.warning("aws_not_configured", tool="get_rds_instance_status")
        return _aws_config_required_response("get_rds_instance_status")
    except ClientError as e:
        logger.error(
            "failed_to_get_rds_status", error=str(e), db_instance=db_instance_id
        )
        return json.dumps({"error": str(e), "db_instance_id": db_instance_id})


@function_tool(strict_mode=False)
def query_cloudwatch_insights(
    log_group: str,
    query: str,
    start_time: int,
    end_time: int,
    region: str = "us-east-1",
) -> str:
    """
    Run a CloudWatch Logs Insights query.

    Args:
        log_group: CloudWatch log group name
        query: CloudWatch Insights query string
        start_time: Start time (Unix timestamp)
        end_time: End time (Unix timestamp)
        region: AWS region

    Returns:
        Query results as JSON string

    Example query:
        "fields @timestamp, @message | filter @message like /ERROR/ | sort @timestamp desc | limit 20"
    """
    try:
        session = _get_aws_session(region)
        logs = session.client("logs")

        # Start query
        response = logs.start_query(
            logGroupName=log_group,
            startTime=start_time,
            endTime=end_time,
            queryString=query,
        )

        query_id = response["queryId"]

        # Poll for results
        import time

        max_attempts = 30
        for _ in range(max_attempts):
            result = logs.get_query_results(queryId=query_id)
            status = result["status"]

            if status == "Complete":
                return json.dumps(
                    {
                        "log_group": log_group,
                        "query_id": query_id,
                        "results": result["results"],
                    }
                )
            elif status == "Failed" or status == "Cancelled":
                return json.dumps(
                    {
                        "error": f"Query {status.lower()}",
                        "query_id": query_id,
                        "log_group": log_group,
                    }
                )

            time.sleep(1)

        return json.dumps(
            {"error": "Query timeout", "query_id": query_id, "log_group": log_group}
        )

    except IntegrationNotConfiguredError:
        logger.warning("aws_not_configured", tool="query_cloudwatch_insights")
        return _aws_config_required_response("query_cloudwatch_insights")
    except ClientError as e:
        logger.error("failed_to_query_insights", error=str(e), log_group=log_group)
        return json.dumps({"error": str(e), "log_group": log_group})


@function_tool(strict_mode=False)
def get_cloudwatch_metrics(
    namespace: str,
    metric_name: str,
    dimensions: list[dict[str, str]] | None = None,
    start_time: int | None = None,
    end_time: int | None = None,
    period: int = 300,
    region: str = "us-east-1",
) -> str:
    """
    Get CloudWatch metric statistics.

    Args:
        namespace: CloudWatch namespace (e.g., "AWS/EC2")
        metric_name: Metric name (e.g., "CPUUtilization")
        dimensions: Optional metric dimensions
        start_time: Start time (Unix timestamp, defaults to 1 hour ago)
        end_time: End time (Unix timestamp, defaults to now)
        period: Period in seconds
        region: AWS region

    Returns:
        Metric statistics as JSON string
    """
    try:
        from datetime import datetime, timedelta

        session = _get_aws_session(region)
        cloudwatch = session.client("cloudwatch")

        if not start_time:
            start_time = int((datetime.utcnow() - timedelta(hours=1)).timestamp())
        if not end_time:
            end_time = int(datetime.utcnow().timestamp())

        response = cloudwatch.get_metric_statistics(
            Namespace=namespace,
            MetricName=metric_name,
            Dimensions=dimensions or [],
            StartTime=datetime.fromtimestamp(start_time),
            EndTime=datetime.fromtimestamp(end_time),
            Period=period,
            Statistics=["Average", "Maximum", "Minimum", "Sum"],
        )

        # Convert datetime objects in datapoints to strings
        datapoints = []
        for dp in response["Datapoints"]:
            datapoint = dict(dp)
            if "Timestamp" in datapoint:
                datapoint["Timestamp"] = str(datapoint["Timestamp"])
            datapoints.append(datapoint)

        result = {
            "metric": metric_name,
            "namespace": namespace,
            "datapoints": datapoints,
            "datapoint_count": len(datapoints),
        }
        return json.dumps(result)

    except IntegrationNotConfiguredError:
        logger.warning("aws_not_configured", tool="get_cloudwatch_metrics")
        return _aws_config_required_response("get_cloudwatch_metrics")
    except ClientError as e:
        logger.error("failed_to_get_metrics", error=str(e), metric=metric_name)
        return json.dumps(
            {"error": str(e), "metric": metric_name, "namespace": namespace}
        )


@function_tool(strict_mode=False)
def list_ecs_tasks(
    cluster: str, service: str | None = None, region: str = "us-east-1"
) -> str:
    """
    List ECS tasks in a cluster.

    Args:
        cluster: ECS cluster name
        service: Optional service name to filter
        region: AWS region

    Returns:
        List of tasks as JSON string
    """
    try:
        session = _get_aws_session(region)
        ecs = session.client("ecs")

        list_kwargs = {"cluster": cluster}
        if service:
            list_kwargs["serviceName"] = service

        task_arns = ecs.list_tasks(**list_kwargs)["taskArns"]

        if not task_arns:
            return json.dumps(
                {"cluster": cluster, "service": service, "task_count": 0, "tasks": []}
            )

        # Describe tasks
        tasks = ecs.describe_tasks(cluster=cluster, tasks=task_arns)["tasks"]

        task_list = [
            {
                "task_id": task["taskArn"].split("/")[-1],
                "task_definition": task["taskDefinitionArn"].split("/")[-1],
                "status": task["lastStatus"],
                "health": task.get("healthStatus", "UNKNOWN"),
                "started_at": str(task.get("startedAt", "")),
            }
            for task in tasks
        ]

        return json.dumps(
            {
                "cluster": cluster,
                "service": service,
                "task_count": len(task_list),
                "tasks": task_list,
            }
        )

    except IntegrationNotConfiguredError:
        logger.warning("aws_not_configured", tool="list_ecs_tasks")
        return _aws_config_required_response("list_ecs_tasks")
    except ClientError as e:
        logger.error("failed_to_list_ecs_tasks", error=str(e), cluster=cluster)
        return json.dumps({"error": str(e), "cluster": cluster, "service": service})


# =============================================================================
# AWS Cost Analysis Tools
# =============================================================================


@function_tool(strict_mode=False)
def aws_cost_explorer(
    time_period_start: str,
    time_period_end: str,
    granularity: str = "MONTHLY",
    metrics: list[str] | None = None,
    group_by: list[dict[str, str]] | None = None,
    region: str = "us-east-1",
) -> str:
    """
    Get cost and usage data from AWS Cost Explorer.

    Args:
        time_period_start: Start date in YYYY-MM-DD format
        time_period_end: End date in YYYY-MM-DD format
        granularity: DAILY, MONTHLY, or HOURLY
        metrics: Metrics to retrieve (defaults to ["UnblendedCost"])
        group_by: Optional grouping (e.g., [{"Type": "DIMENSION", "Key": "SERVICE"}])
        region: AWS region

    Returns:
        Cost and usage data as JSON string
    """
    try:
        session = _get_aws_session(region)
        ce = session.client("ce")

        if not metrics:
            metrics = ["UnblendedCost"]

        kwargs = {
            "TimePeriod": {"Start": time_period_start, "End": time_period_end},
            "Granularity": granularity,
            "Metrics": metrics,
        }

        if group_by:
            kwargs["GroupBy"] = group_by

        response = ce.get_cost_and_usage(**kwargs)

        results = response.get("ResultsByTime", [])
        total_cost = sum(
            float(period.get("Total", {}).get("UnblendedCost", {}).get("Amount", 0))
            for period in results
        )

        return json.dumps(
            {
                "time_period": {"start": time_period_start, "end": time_period_end},
                "granularity": granularity,
                "total_cost": round(total_cost, 2),
                "currency": (
                    results[0]
                    .get("Total", {})
                    .get("UnblendedCost", {})
                    .get("Unit", "USD")
                    if results
                    else "USD"
                ),
                "results": results,
            }
        )

    except IntegrationNotConfiguredError:
        logger.warning("aws_not_configured", tool="aws_cost_explorer")
        return _aws_config_required_response("aws_cost_explorer")
    except ClientError as e:
        logger.error("failed_to_get_cost_explorer", error=str(e))
        return json.dumps({"error": str(e)})


@function_tool(strict_mode=False)
def aws_trusted_advisor(region: str = "us-east-1") -> str:
    """
    Get AWS Trusted Advisor recommendations.

    Args:
        region: AWS region

    Returns:
        Trusted Advisor checks and recommendations as JSON string
    """
    try:
        session = _get_aws_session("us-east-1")
        support = session.client("support")  # Trusted Advisor is only in us-east-1

        # Get all checks
        checks_response = support.describe_trusted_advisor_checks(language="en")
        checks = checks_response["checks"]

        # Get check results (focus on cost optimization)
        cost_checks = [c for c in checks if c["category"] == "cost_optimizing"]

        results = []
        for check in cost_checks[:10]:  # Limit to 10 checks to avoid rate limits
            try:
                result = support.describe_trusted_advisor_check_result(
                    checkId=check["id"]
                )
                check_result = result["result"]

                results.append(
                    {
                        "check_name": check["name"],
                        "description": check["description"],
                        "category": check["category"],
                        "status": check_result["status"],
                        "flagged_resources": check_result.get("flaggedResources", []),
                        "resources_summary": check_result.get("resourcesSummary", {}),
                    }
                )
            except Exception as e:
                logger.warning(f"Could not get result for check {check['name']}: {e}")
                continue

        return json.dumps(
            {
                "total_cost_checks": len(cost_checks),
                "results_retrieved": len(results),
                "checks": results,
            }
        )

    except IntegrationNotConfiguredError:
        logger.warning("aws_not_configured", tool="aws_trusted_advisor")
        return _aws_config_required_response("aws_trusted_advisor")
    except ClientError as e:
        logger.error("failed_to_get_trusted_advisor", error=str(e))
        return json.dumps(
            {
                "error": str(e),
                "note": "Trusted Advisor requires Business or Enterprise support plan",
            }
        )


@function_tool(strict_mode=False)
def ec2_describe_instances(
    filters: list[dict[str, Any]] | None = None,
    max_results: int = 100,
    region: str = "us-east-1",
) -> str:
    """
    List EC2 instances with optional filters.

    Args:
        filters: EC2 filters (e.g., [{"Name": "instance-state-name", "Values": ["running"]}])
        max_results: Maximum number of instances to return
        region: AWS region

    Returns:
        List of EC2 instances as JSON string
    """
    try:
        session = _get_aws_session(region)
        ec2 = session.client("ec2")

        kwargs = {}
        if filters:
            kwargs["Filters"] = filters
        if max_results:
            kwargs["MaxResults"] = max_results

        response = ec2.describe_instances(**kwargs)

        instances = []
        for reservation in response.get("Reservations", []):
            for instance in reservation.get("Instances", []):
                instances.append(
                    {
                        "instance_id": instance["InstanceId"],
                        "instance_type": instance["InstanceType"],
                        "state": instance["State"]["Name"],
                        "launch_time": str(instance["LaunchTime"]),
                        "availability_zone": instance["Placement"]["AvailabilityZone"],
                        "private_ip": instance.get("PrivateIpAddress"),
                        "public_ip": instance.get("PublicIpAddress"),
                        "tags": {
                            tag["Key"]: tag["Value"] for tag in instance.get("Tags", [])
                        },
                        "platform": instance.get("Platform", "linux"),
                    }
                )

        return json.dumps(
            {
                "region": region,
                "instance_count": len(instances),
                "instances": instances,
            }
        )

    except IntegrationNotConfiguredError:
        logger.warning("aws_not_configured", tool="ec2_describe_instances")
        return _aws_config_required_response("ec2_describe_instances")
    except ClientError as e:
        logger.error("failed_to_describe_instances", error=str(e), region=region)
        return json.dumps({"error": str(e), "region": region})


@function_tool(strict_mode=False)
def ec2_describe_volumes(
    filters: list[dict[str, Any]] | None = None,
    max_results: int = 100,
    region: str = "us-east-1",
) -> str:
    """
    List EBS volumes with optional filters.

    Args:
        filters: EBS filters (e.g., [{"Name": "status", "Values": ["available"]}] for unattached)
        max_results: Maximum number of volumes to return
        region: AWS region

    Returns:
        List of EBS volumes as JSON string
    """
    try:
        session = _get_aws_session(region)
        ec2 = session.client("ec2")

        kwargs = {}
        if filters:
            kwargs["Filters"] = filters
        if max_results:
            kwargs["MaxResults"] = max_results

        response = ec2.describe_volumes(**kwargs)

        volumes = []
        for volume in response.get("Volumes", []):
            volumes.append(
                {
                    "volume_id": volume["VolumeId"],
                    "size_gb": volume["Size"],
                    "volume_type": volume["VolumeType"],
                    "state": volume["State"],
                    "create_time": str(volume["CreateTime"]),
                    "availability_zone": volume["AvailabilityZone"],
                    "attachments": volume.get("Attachments", []),
                    "is_attached": len(volume.get("Attachments", [])) > 0,
                    "tags": {
                        tag["Key"]: tag["Value"] for tag in volume.get("Tags", [])
                    },
                }
            )

        return json.dumps(
            {
                "region": region,
                "volume_count": len(volumes),
                "volumes": volumes,
            }
        )

    except IntegrationNotConfiguredError:
        logger.warning("aws_not_configured", tool="ec2_describe_volumes")
        return _aws_config_required_response("ec2_describe_volumes")
    except ClientError as e:
        logger.error("failed_to_describe_volumes", error=str(e), region=region)
        return json.dumps({"error": str(e), "region": region})


@function_tool(strict_mode=False)
def ec2_describe_snapshots(
    owner_ids: list[str] | None = None,
    max_results: int = 100,
    region: str = "us-east-1",
) -> str:
    """
    List EBS snapshots.

    Args:
        owner_ids: AWS account IDs to filter (defaults to "self")
        max_results: Maximum number of snapshots to return
        region: AWS region

    Returns:
        List of EBS snapshots as JSON string
    """
    try:
        session = _get_aws_session(region)
        ec2 = session.client("ec2")

        kwargs = {"OwnerIds": owner_ids or ["self"]}
        if max_results:
            kwargs["MaxResults"] = max_results

        response = ec2.describe_snapshots(**kwargs)

        from datetime import datetime

        now = datetime.now(UTC)

        snapshots = []
        for snapshot in response.get("Snapshots", []):
            start_time = snapshot["StartTime"]
            age_days = (now - start_time).days

            snapshots.append(
                {
                    "snapshot_id": snapshot["SnapshotId"],
                    "volume_id": snapshot.get("VolumeId"),
                    "size_gb": snapshot["VolumeSize"],
                    "state": snapshot["State"],
                    "start_time": str(start_time),
                    "age_days": age_days,
                    "description": snapshot.get("Description", ""),
                    "tags": {
                        tag["Key"]: tag["Value"] for tag in snapshot.get("Tags", [])
                    },
                }
            )

        return json.dumps(
            {
                "region": region,
                "snapshot_count": len(snapshots),
                "snapshots": snapshots,
            }
        )

    except IntegrationNotConfiguredError:
        logger.warning("aws_not_configured", tool="ec2_describe_snapshots")
        return _aws_config_required_response("ec2_describe_snapshots")
    except ClientError as e:
        logger.error("failed_to_describe_snapshots", error=str(e), region=region)
        return json.dumps({"error": str(e), "region": region})


@function_tool(strict_mode=False)
def ec2_rightsizing_recommendations(region: str = "us-east-1") -> str:
    """
    Get EC2 rightsizing recommendations from AWS Compute Optimizer.

    Args:
        region: AWS region

    Returns:
        Rightsizing recommendations as JSON string
    """
    try:
        session = _get_aws_session(region)
        compute_optimizer = session.client("compute-optimizer")

        response = compute_optimizer.get_ec2_instance_recommendations()

        recommendations = []
        for rec in response.get("instanceRecommendations", []):
            current_type = rec.get("currentInstanceType")
            recommended_options = rec.get("recommendationOptions", [])

            if recommended_options:
                best_option = recommended_options[0]
                recommendations.append(
                    {
                        "instance_id": rec.get("instanceArn", "").split("/")[-1],
                        "current_type": current_type,
                        "recommended_type": best_option.get("instanceType"),
                        "finding": rec.get("finding"),
                        "utilization_metrics": rec.get("utilizationMetrics", []),
                        "estimated_savings": best_option.get(
                            "estimatedMonthlySavings", {}
                        ),
                    }
                )

        return json.dumps(
            {
                "region": region,
                "recommendation_count": len(recommendations),
                "recommendations": recommendations,
            }
        )

    except IntegrationNotConfiguredError:
        logger.warning("aws_not_configured", tool="ec2_rightsizing_recommendations")
        return _aws_config_required_response("ec2_rightsizing_recommendations")
    except ClientError as e:
        logger.error("failed_to_get_rightsizing", error=str(e), region=region)
        return json.dumps(
            {
                "error": str(e),
                "region": region,
                "note": "Compute Optimizer requires opt-in",
            }
        )


@function_tool(strict_mode=False)
def rds_describe_db_instances(
    max_records: int = 100,
    region: str = "us-east-1",
) -> str:
    """
    List RDS database instances.

    Args:
        max_records: Maximum number of instances to return
        region: AWS region

    Returns:
        List of RDS instances as JSON string
    """
    try:
        session = _get_aws_session(region)
        rds = session.client("rds")

        response = rds.describe_db_instances(MaxRecords=max_records)

        instances = []
        for db in response.get("DBInstances", []):
            instances.append(
                {
                    "db_instance_id": db["DBInstanceIdentifier"],
                    "db_instance_class": db["DBInstanceClass"],
                    "engine": db["Engine"],
                    "engine_version": db["EngineVersion"],
                    "status": db["DBInstanceStatus"],
                    "allocated_storage_gb": db.get("AllocatedStorage"),
                    "storage_type": db.get("StorageType"),
                    "availability_zone": db.get("AvailabilityZone"),
                    "multi_az": db.get("MultiAZ", False),
                    "endpoint": db.get("Endpoint", {}).get("Address"),
                    "port": db.get("Endpoint", {}).get("Port"),
                    "backup_retention_days": db.get("BackupRetentionPeriod"),
                    "tags": {tag["Key"]: tag["Value"] for tag in db.get("TagList", [])},
                }
            )

        return json.dumps(
            {
                "region": region,
                "instance_count": len(instances),
                "instances": instances,
            }
        )

    except IntegrationNotConfiguredError:
        logger.warning("aws_not_configured", tool="rds_describe_db_instances")
        return _aws_config_required_response("rds_describe_db_instances")
    except ClientError as e:
        logger.error("failed_to_describe_rds_instances", error=str(e), region=region)
        return json.dumps({"error": str(e), "region": region})


@function_tool(strict_mode=False)
def rds_describe_db_snapshots(
    max_records: int = 100,
    region: str = "us-east-1",
) -> str:
    """
    List RDS database snapshots.

    Args:
        max_records: Maximum number of snapshots to return
        region: AWS region

    Returns:
        List of RDS snapshots as JSON string
    """
    try:
        session = _get_aws_session(region)
        rds = session.client("rds")

        response = rds.describe_db_snapshots(
            MaxRecords=max_records,
            SnapshotType="manual",  # Focus on manual snapshots
        )

        from datetime import datetime

        now = datetime.now(UTC)

        snapshots = []
        for snapshot in response.get("DBSnapshots", []):
            create_time = snapshot.get("SnapshotCreateTime")
            age_days = (now - create_time).days if create_time else None

            snapshots.append(
                {
                    "snapshot_id": snapshot["DBSnapshotIdentifier"],
                    "db_instance_id": snapshot.get("DBInstanceIdentifier"),
                    "engine": snapshot.get("Engine"),
                    "allocated_storage_gb": snapshot.get("AllocatedStorage"),
                    "status": snapshot.get("Status"),
                    "snapshot_type": snapshot.get("SnapshotType"),
                    "create_time": str(create_time) if create_time else None,
                    "age_days": age_days,
                }
            )

        return json.dumps(
            {
                "region": region,
                "snapshot_count": len(snapshots),
                "snapshots": snapshots,
            }
        )

    except IntegrationNotConfiguredError:
        logger.warning("aws_not_configured", tool="rds_describe_db_snapshots")
        return _aws_config_required_response("rds_describe_db_snapshots")
    except ClientError as e:
        logger.error("failed_to_describe_rds_snapshots", error=str(e), region=region)
        return json.dumps({"error": str(e), "region": region})


@function_tool(strict_mode=False)
def s3_list_buckets() -> str:
    """
    List all S3 buckets in the account.

    Returns:
        List of S3 buckets as JSON string
    """
    try:
        session = _get_aws_session()
        s3 = session.client("s3")

        response = s3.list_buckets()

        buckets = []
        for bucket in response.get("Buckets", []):
            bucket_name = bucket["Name"]
            creation_date = bucket.get("CreationDate")

            # Get bucket location
            try:
                location_response = s3.get_bucket_location(Bucket=bucket_name)
                region = location_response.get("LocationConstraint") or "us-east-1"
            except:
                region = "unknown"

            buckets.append(
                {
                    "bucket_name": bucket_name,
                    "creation_date": str(creation_date),
                    "region": region,
                }
            )

        return json.dumps(
            {
                "bucket_count": len(buckets),
                "buckets": buckets,
            }
        )

    except IntegrationNotConfiguredError:
        logger.warning("aws_not_configured", tool="s3_list_buckets")
        return _aws_config_required_response("s3_list_buckets")
    except ClientError as e:
        logger.error("failed_to_list_s3_buckets", error=str(e))
        return json.dumps({"error": str(e)})


@function_tool(strict_mode=False)
def s3_get_bucket_metrics(bucket_name: str) -> str:
    """
    Get storage metrics for an S3 bucket.

    Args:
        bucket_name: S3 bucket name

    Returns:
        Bucket storage metrics as JSON string
    """
    try:
        from datetime import datetime, timedelta

        session = _get_aws_session()
        cloudwatch = session.client("cloudwatch")
        s3 = session.client("s3")

        # Get bucket size from CloudWatch
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=2)

        response = cloudwatch.get_metric_statistics(
            Namespace="AWS/S3",
            MetricName="BucketSizeBytes",
            Dimensions=[
                {"Name": "BucketName", "Value": bucket_name},
                {"Name": "StorageType", "Value": "StandardStorage"},
            ],
            StartTime=start_time,
            EndTime=end_time,
            Period=86400,  # 1 day
            Statistics=["Average"],
        )

        size_bytes = 0
        if response["Datapoints"]:
            size_bytes = response["Datapoints"][0].get("Average", 0)

        # Get number of objects
        object_count_response = cloudwatch.get_metric_statistics(
            Namespace="AWS/S3",
            MetricName="NumberOfObjects",
            Dimensions=[
                {"Name": "BucketName", "Value": bucket_name},
                {"Name": "StorageType", "Value": "AllStorageTypes"},
            ],
            StartTime=start_time,
            EndTime=end_time,
            Period=86400,
            Statistics=["Average"],
        )

        object_count = 0
        if object_count_response["Datapoints"]:
            object_count = int(object_count_response["Datapoints"][0].get("Average", 0))

        # Try to get lifecycle configuration
        try:
            lifecycle = s3.get_bucket_lifecycle_configuration(Bucket=bucket_name)
            has_lifecycle = True
            lifecycle_rules = len(lifecycle.get("Rules", []))
        except:
            has_lifecycle = False
            lifecycle_rules = 0

        return json.dumps(
            {
                "bucket_name": bucket_name,
                "size_bytes": int(size_bytes),
                "size_gb": round(size_bytes / (1024**3), 2),
                "object_count": object_count,
                "has_lifecycle_policy": has_lifecycle,
                "lifecycle_rule_count": lifecycle_rules,
            }
        )

    except IntegrationNotConfiguredError:
        logger.warning("aws_not_configured", tool="s3_get_bucket_metrics")
        return _aws_config_required_response("s3_get_bucket_metrics")
    except ClientError as e:
        logger.error("failed_to_get_bucket_metrics", error=str(e), bucket=bucket_name)
        return json.dumps({"error": str(e), "bucket_name": bucket_name})


@function_tool(strict_mode=False)
def s3_storage_class_analysis(bucket_name: str, max_keys: int = 1000) -> str:
    """
    Analyze S3 object storage classes for optimization opportunities.

    Args:
        bucket_name: S3 bucket name
        max_keys: Maximum number of objects to analyze

    Returns:
        Storage class analysis as JSON string
    """
    try:
        session = _get_aws_session()
        s3 = session.client("s3")

        response = s3.list_objects_v2(Bucket=bucket_name, MaxKeys=max_keys)

        from collections import defaultdict
        from datetime import datetime

        storage_class_counts = defaultdict(int)
        storage_class_sizes = defaultdict(int)
        old_objects = []  # Objects not accessed recently (candidates for IA or Glacier)

        now = datetime.now(UTC)

        for obj in response.get("Contents", []):
            storage_class = obj.get("StorageClass", "STANDARD")
            size = obj.get("Size", 0)
            last_modified = obj.get("LastModified")

            storage_class_counts[storage_class] += 1
            storage_class_sizes[storage_class] += size

            # Check if object is old (>90 days) and still in STANDARD
            if storage_class == "STANDARD" and last_modified:
                age_days = (now - last_modified).days
                if age_days > 90:
                    old_objects.append(
                        {
                            "key": obj["Key"],
                            "size_bytes": size,
                            "age_days": age_days,
                            "last_modified": str(last_modified),
                        }
                    )

        return json.dumps(
            {
                "bucket_name": bucket_name,
                "objects_analyzed": len(response.get("Contents", [])),
                "storage_class_distribution": dict(storage_class_counts),
                "storage_class_sizes_gb": {
                    sc: round(size / (1024**3), 2)
                    for sc, size in storage_class_sizes.items()
                },
                "old_standard_objects_count": len(old_objects),
                "old_standard_objects": old_objects[:100],  # Limit to 100 examples
                "recommendation": (
                    "Consider moving old STANDARD objects to INTELLIGENT_TIERING or GLACIER"
                    if old_objects
                    else "Storage classes look optimized"
                ),
            }
        )

    except IntegrationNotConfiguredError:
        logger.warning("aws_not_configured", tool="s3_storage_class_analysis")
        return _aws_config_required_response("s3_storage_class_analysis")
    except ClientError as e:
        logger.error(
            "failed_to_analyze_storage_class", error=str(e), bucket=bucket_name
        )
        return json.dumps({"error": str(e), "bucket_name": bucket_name})


@function_tool(strict_mode=False)
def lambda_list_functions(
    max_items: int = 50,
    region: str = "us-east-1",
) -> str:
    """
    List Lambda functions.

    Args:
        max_items: Maximum number of functions to return
        region: AWS region

    Returns:
        List of Lambda functions as JSON string
    """
    try:
        session = _get_aws_session(region)
        lambda_client = session.client("lambda")

        response = lambda_client.list_functions(MaxItems=max_items)

        functions = []
        for func in response.get("Functions", []):
            functions.append(
                {
                    "function_name": func["FunctionName"],
                    "runtime": func.get("Runtime"),
                    "memory_mb": func.get("MemorySize"),
                    "timeout_seconds": func.get("Timeout"),
                    "code_size_bytes": func.get("CodeSize"),
                    "last_modified": func.get("LastModified"),
                    "description": func.get("Description", ""),
                }
            )

        return json.dumps(
            {
                "region": region,
                "function_count": len(functions),
                "functions": functions,
            }
        )

    except IntegrationNotConfiguredError:
        logger.warning("aws_not_configured", tool="lambda_list_functions")
        return _aws_config_required_response("lambda_list_functions")
    except ClientError as e:
        logger.error("failed_to_list_lambda_functions", error=str(e), region=region)
        return json.dumps({"error": str(e), "region": region})


@function_tool(strict_mode=False)
def lambda_cost_analysis(
    function_name: str,
    days: int = 7,
    region: str = "us-east-1",
) -> str:
    """
    Analyze Lambda function cost and usage.

    Args:
        function_name: Lambda function name
        days: Number of days to analyze
        region: AWS region

    Returns:
        Cost analysis as JSON string
    """
    try:
        from datetime import datetime, timedelta

        session = _get_aws_session(region)
        cloudwatch = session.client("cloudwatch")
        lambda_client = session.client("lambda")

        # Get function config
        func_config = lambda_client.get_function(FunctionName=function_name)[
            "Configuration"
        ]
        memory_mb = func_config["MemorySize"]

        # Get invocation metrics
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=days)

        invocations_response = cloudwatch.get_metric_statistics(
            Namespace="AWS/Lambda",
            MetricName="Invocations",
            Dimensions=[{"Name": "FunctionName", "Value": function_name}],
            StartTime=start_time,
            EndTime=end_time,
            Period=86400,
            Statistics=["Sum"],
        )

        duration_response = cloudwatch.get_metric_statistics(
            Namespace="AWS/Lambda",
            MetricName="Duration",
            Dimensions=[{"Name": "FunctionName", "Value": function_name}],
            StartTime=start_time,
            EndTime=end_time,
            Period=86400,
            Statistics=["Average"],
        )

        total_invocations = sum(
            dp.get("Sum", 0) for dp in invocations_response["Datapoints"]
        )
        avg_duration_ms = (
            sum(dp.get("Average", 0) for dp in duration_response["Datapoints"])
            / len(duration_response["Datapoints"])
            if duration_response["Datapoints"]
            else 0
        )

        # Estimate cost
        # Lambda pricing: $0.20 per 1M requests + $0.0000166667 per GB-second
        request_cost = (total_invocations / 1_000_000) * 0.20
        gb_seconds = (memory_mb / 1024) * (avg_duration_ms / 1000) * total_invocations
        compute_cost = gb_seconds * 0.0000166667
        estimated_monthly_cost = (request_cost + compute_cost) * (30 / days)

        return json.dumps(
            {
                "function_name": function_name,
                "memory_mb": memory_mb,
                "analysis_days": days,
                "total_invocations": int(total_invocations),
                "avg_duration_ms": round(avg_duration_ms, 2),
                "estimated_cost": {
                    "request_cost": round(request_cost, 4),
                    "compute_cost": round(compute_cost, 4),
                    "total_cost_period": round(request_cost + compute_cost, 4),
                    "estimated_monthly_cost": round(estimated_monthly_cost, 2),
                },
            }
        )

    except IntegrationNotConfiguredError:
        logger.warning("aws_not_configured", tool="lambda_cost_analysis")
        return _aws_config_required_response("lambda_cost_analysis")
    except ClientError as e:
        logger.error(
            "failed_to_analyze_lambda_cost", error=str(e), function=function_name
        )
        return json.dumps({"error": str(e), "function_name": function_name})


@function_tool(strict_mode=False)
def elasticache_describe_clusters(
    max_records: int = 100,
    region: str = "us-east-1",
) -> str:
    """
    List ElastiCache clusters.

    Args:
        max_records: Maximum number of clusters to return
        region: AWS region

    Returns:
        List of ElastiCache clusters as JSON string
    """
    try:
        session = _get_aws_session(region)
        elasticache = session.client("elasticache")

        response = elasticache.describe_cache_clusters(MaxRecords=max_records)

        clusters = []
        for cluster in response.get("CacheClusters", []):
            clusters.append(
                {
                    "cluster_id": cluster["CacheClusterId"],
                    "node_type": cluster.get("CacheNodeType"),
                    "engine": cluster.get("Engine"),
                    "engine_version": cluster.get("EngineVersion"),
                    "status": cluster.get("CacheClusterStatus"),
                    "num_nodes": cluster.get("NumCacheNodes"),
                    "availability_zone": cluster.get("PreferredAvailabilityZone"),
                }
            )

        return json.dumps(
            {
                "region": region,
                "cluster_count": len(clusters),
                "clusters": clusters,
            }
        )

    except IntegrationNotConfiguredError:
        logger.warning("aws_not_configured", tool="elasticache_describe_clusters")
        return _aws_config_required_response("elasticache_describe_clusters")
    except ClientError as e:
        logger.error("failed_to_describe_elasticache", error=str(e), region=region)
        return json.dumps({"error": str(e), "region": region})


# =============================================================================
# AWS Backup and Disaster Recovery Tools
# =============================================================================


@function_tool(strict_mode=False)
def aws_backup_describe_vaults(region: str = "us-east-1") -> str:
    """
    List AWS Backup vaults.

    Args:
        region: AWS region

    Returns:
        List of backup vaults as JSON string
    """
    try:
        session = _get_aws_session(region)
        backup = session.client("backup")

        response = backup.list_backup_vaults()

        vaults = []
        for vault in response.get("BackupVaultList", []):
            vaults.append(
                {
                    "vault_name": vault["BackupVaultName"],
                    "vault_arn": vault["BackupVaultArn"],
                    "creation_date": str(vault.get("CreationDate", "")),
                    "number_of_recovery_points": vault.get("NumberOfRecoveryPoints", 0),
                }
            )

        return json.dumps(
            {
                "region": region,
                "vault_count": len(vaults),
                "vaults": vaults,
            }
        )

    except IntegrationNotConfiguredError:
        logger.warning("aws_not_configured", tool="aws_backup_describe_vaults")
        return _aws_config_required_response("aws_backup_describe_vaults")
    except ClientError as e:
        logger.error("failed_to_describe_backup_vaults", error=str(e), region=region)
        return json.dumps({"error": str(e), "region": region})


@function_tool(strict_mode=False)
def aws_backup_get_recovery_point(
    backup_vault_name: str,
    recovery_point_arn: str,
    region: str = "us-east-1",
) -> str:
    """
    Get details of an AWS Backup recovery point.

    Args:
        backup_vault_name: Name of the backup vault
        recovery_point_arn: ARN of the recovery point
        region: AWS region

    Returns:
        Recovery point details as JSON string
    """
    try:
        session = _get_aws_session(region)
        backup = session.client("backup")

        response = backup.describe_recovery_point(
            BackupVaultName=backup_vault_name,
            RecoveryPointArn=recovery_point_arn,
        )

        from datetime import datetime

        now = datetime.now(UTC)
        creation_date = response.get("CreationDate")
        age_hours = (
            (now - creation_date).total_seconds() / 3600 if creation_date else None
        )

        return json.dumps(
            {
                "recovery_point_arn": response["RecoveryPointArn"],
                "backup_vault_name": response["BackupVaultName"],
                "resource_arn": response.get("ResourceArn"),
                "resource_type": response.get("ResourceType"),
                "status": response.get("Status"),
                "creation_date": str(creation_date),
                "age_hours": round(age_hours, 2) if age_hours else None,
                "backup_size_bytes": response.get("BackupSizeInBytes"),
                "backup_size_gb": round(
                    response.get("BackupSizeInBytes", 0) / (1024**3), 2
                ),
                "completion_date": str(response.get("CompletionDate", "")),
                "lifecycle": response.get("Lifecycle", {}),
            }
        )

    except IntegrationNotConfiguredError:
        logger.warning("aws_not_configured", tool="aws_backup_get_recovery_point")
        return _aws_config_required_response("aws_backup_get_recovery_point")
    except ClientError as e:
        logger.error(
            "failed_to_get_recovery_point",
            error=str(e),
            recovery_point=recovery_point_arn,
        )
        return json.dumps({"error": str(e), "recovery_point_arn": recovery_point_arn})


@function_tool(strict_mode=False)
def aws_backup_start_restore(
    recovery_point_arn: str,
    resource_type: str,
    iam_role_arn: str,
    metadata: dict[str, str],
    region: str = "us-east-1",
) -> str:
    """
    Start a restore job from an AWS Backup recovery point.

    Args:
        recovery_point_arn: ARN of the recovery point to restore
        resource_type: Type of resource (e.g., "EBS", "RDS", "DynamoDB")
        iam_role_arn: IAM role ARN for restore operation
        metadata: Resource-specific metadata (e.g., {"DBInstanceIdentifier": "test-restore"})
        region: AWS region

    Returns:
        Restore job details as JSON string
    """
    try:
        session = _get_aws_session(region)
        backup = session.client("backup")

        response = backup.start_restore_job(
            RecoveryPointArn=recovery_point_arn,
            IamRoleArn=iam_role_arn,
            Metadata=metadata,
        )

        logger.info("backup_restore_started", restore_job_id=response["RestoreJobId"])

        return json.dumps(
            {
                "restore_job_id": response["RestoreJobId"],
                "recovery_point_arn": recovery_point_arn,
                "resource_type": resource_type,
                "status": "CREATED",
                "note": "Restore job started. Use describe_restore_job to check status.",
            }
        )

    except IntegrationNotConfiguredError:
        logger.warning("aws_not_configured", tool="aws_backup_start_restore")
        return _aws_config_required_response("aws_backup_start_restore")
    except ClientError as e:
        logger.error(
            "failed_to_start_restore", error=str(e), recovery_point=recovery_point_arn
        )
        return json.dumps({"error": str(e), "recovery_point_arn": recovery_point_arn})


@function_tool(strict_mode=False)
def rds_restore_db_from_snapshot(
    db_instance_id: str,
    db_snapshot_id: str,
    db_instance_class: str | None = None,
    region: str = "us-east-1",
) -> str:
    """
    Restore an RDS database from a snapshot.

    Args:
        db_instance_id: Identifier for the restored DB instance
        db_snapshot_id: Snapshot identifier to restore from
        db_instance_class: Optional instance class (e.g., "db.t3.small")
        region: AWS region

    Returns:
        Restore operation details as JSON string
    """
    try:
        session = _get_aws_session(region)
        rds = session.client("rds")

        kwargs = {
            "DBInstanceIdentifier": db_instance_id,
            "DBSnapshotIdentifier": db_snapshot_id,
        }

        if db_instance_class:
            kwargs["DBInstanceClass"] = db_instance_class

        response = rds.restore_db_instance_from_db_snapshot(**kwargs)

        db_instance = response["DBInstance"]

        logger.info(
            "rds_restore_started",
            db_instance_id=db_instance_id,
            snapshot=db_snapshot_id,
        )

        return json.dumps(
            {
                "db_instance_id": db_instance["DBInstanceIdentifier"],
                "status": db_instance["DBInstanceStatus"],
                "engine": db_instance["Engine"],
                "db_instance_class": db_instance["DBInstanceClass"],
                "availability_zone": db_instance.get("AvailabilityZone"),
                "restore_time": str(db_instance.get("InstanceCreateTime", "")),
                "note": "Restore in progress. Use get_rds_instance_status to check progress.",
            }
        )

    except IntegrationNotConfiguredError:
        logger.warning("aws_not_configured", tool="rds_restore_db_from_snapshot")
        return _aws_config_required_response("rds_restore_db_from_snapshot")
    except ClientError as e:
        logger.error("failed_to_restore_rds", error=str(e), snapshot=db_snapshot_id)
        return json.dumps({"error": str(e), "db_snapshot_id": db_snapshot_id})


@function_tool(strict_mode=False)
def s3_list_bucket_versions(
    bucket_name: str,
    prefix: str | None = None,
    max_keys: int = 100,
) -> str:
    """
    List object versions in an S3 bucket (for versioned buckets).

    Args:
        bucket_name: S3 bucket name
        prefix: Optional key prefix to filter
        max_keys: Maximum number of versions to return

    Returns:
        List of object versions as JSON string
    """
    try:
        session = _get_aws_session()
        s3 = session.client("s3")

        kwargs = {"Bucket": bucket_name, "MaxKeys": max_keys}
        if prefix:
            kwargs["Prefix"] = prefix

        response = s3.list_object_versions(**kwargs)

        versions = []
        for version in response.get("Versions", []):
            versions.append(
                {
                    "key": version["Key"],
                    "version_id": version["VersionId"],
                    "is_latest": version.get("IsLatest", False),
                    "last_modified": str(version.get("LastModified", "")),
                    "size_bytes": version.get("Size"),
                    "storage_class": version.get("StorageClass"),
                }
            )

        return json.dumps(
            {
                "bucket_name": bucket_name,
                "version_count": len(versions),
                "versions": versions,
                "is_truncated": response.get("IsTruncated", False),
            }
        )

    except IntegrationNotConfiguredError:
        logger.warning("aws_not_configured", tool="s3_list_bucket_versions")
        return _aws_config_required_response("s3_list_bucket_versions")
    except ClientError as e:
        logger.error("failed_to_list_bucket_versions", error=str(e), bucket=bucket_name)
        return json.dumps({"error": str(e), "bucket_name": bucket_name})


@function_tool(strict_mode=False)
def s3_restore_object(
    bucket_name: str,
    object_key: str,
    version_id: str | None = None,
    days: int = 7,
    tier: str = "Standard",
) -> str:
    """
    Restore an object from S3 Glacier or delete a previous version.

    Args:
        bucket_name: S3 bucket name
        object_key: Object key to restore
        version_id: Optional version ID to restore
        days: Number of days to keep restored object (for Glacier)
        tier: Restore tier (Standard, Bulk, Expedited)

    Returns:
        Restore request details as JSON string
    """
    try:
        session = _get_aws_session()
        s3 = session.client("s3")

        # Check if object is in Glacier and needs restore
        head_kwargs = {"Bucket": bucket_name, "Key": object_key}
        if version_id:
            head_kwargs["VersionId"] = version_id

        head_response = s3.head_object(**head_kwargs)
        storage_class = head_response.get("StorageClass")

        if storage_class in ["GLACIER", "DEEP_ARCHIVE"]:
            # Restore from Glacier
            restore_kwargs = {
                "Bucket": bucket_name,
                "Key": object_key,
                "RestoreRequest": {
                    "Days": days,
                    "GlacierJobParameters": {"Tier": tier},
                },
            }
            if version_id:
                restore_kwargs["VersionId"] = version_id

            s3.restore_object(**restore_kwargs)

            logger.info("s3_restore_started", bucket=bucket_name, key=object_key)

            return json.dumps(
                {
                    "bucket_name": bucket_name,
                    "object_key": object_key,
                    "version_id": version_id,
                    "status": "RESTORE_INITIATED",
                    "storage_class": storage_class,
                    "restore_days": days,
                    "tier": tier,
                    "note": "Restore initiated. Time depends on tier: Expedited (1-5 min), Standard (3-5 hrs), Bulk (5-12 hrs)",
                }
            )
        else:
            return json.dumps(
                {
                    "bucket_name": bucket_name,
                    "object_key": object_key,
                    "status": "NO_RESTORE_NEEDED",
                    "storage_class": storage_class,
                    "note": "Object is not in Glacier and does not need restore",
                }
            )

    except IntegrationNotConfiguredError:
        logger.warning("aws_not_configured", tool="s3_restore_object")
        return _aws_config_required_response("s3_restore_object")
    except ClientError as e:
        logger.error(
            "failed_to_restore_s3_object",
            error=str(e),
            bucket=bucket_name,
            key=object_key,
        )
        return json.dumps(
            {"error": str(e), "bucket_name": bucket_name, "object_key": object_key}
        )


@function_tool(strict_mode=False)
def s3_get_bucket_replication(bucket_name: str) -> str:
    """
    Get S3 bucket replication configuration.

    Args:
        bucket_name: S3 bucket name

    Returns:
        Replication configuration as JSON string
    """
    try:
        session = _get_aws_session()
        s3 = session.client("s3")

        response = s3.get_bucket_replication(Bucket=bucket_name)

        replication_config = response.get("ReplicationConfiguration", {})
        rules = replication_config.get("Rules", [])

        replication_rules = []
        for rule in rules:
            replication_rules.append(
                {
                    "rule_id": rule.get("ID"),
                    "status": rule.get("Status"),
                    "priority": rule.get("Priority"),
                    "destination_bucket": rule.get("Destination", {}).get("Bucket"),
                    "destination_storage_class": rule.get("Destination", {}).get(
                        "StorageClass"
                    ),
                    "filter": rule.get("Filter", {}),
                }
            )

        return json.dumps(
            {
                "bucket_name": bucket_name,
                "replication_enabled": True,
                "role_arn": replication_config.get("Role"),
                "rule_count": len(replication_rules),
                "rules": replication_rules,
            }
        )

    except IntegrationNotConfiguredError:
        logger.warning("aws_not_configured", tool="s3_get_bucket_replication")
        return _aws_config_required_response("s3_get_bucket_replication")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ReplicationConfigurationNotFoundError":
            return json.dumps(
                {
                    "bucket_name": bucket_name,
                    "replication_enabled": False,
                    "note": "No replication configuration found",
                }
            )
        logger.error(
            "failed_to_get_bucket_replication", error=str(e), bucket=bucket_name
        )
        return json.dumps({"error": str(e), "bucket_name": bucket_name})


@function_tool(strict_mode=False)
def route53_get_health_check(health_check_id: str) -> str:
    """
    Get Route53 health check details.

    Args:
        health_check_id: Health check ID

    Returns:
        Health check configuration as JSON string
    """
    try:
        session = _get_aws_session()
        route53 = session.client("route53")

        response = route53.get_health_check(HealthCheckId=health_check_id)
        health_check = response["HealthCheck"]

        config = health_check["HealthCheckConfig"]

        # Get health check status
        status_response = route53.get_health_check_status(HealthCheckId=health_check_id)
        checkers = status_response.get("HealthCheckObservations", [])
        healthy_count = sum(
            1 for c in checkers if c.get("StatusReport", {}).get("Status") == "Success"
        )

        return json.dumps(
            {
                "health_check_id": health_check["Id"],
                "type": config["Type"],
                "resource_path": config.get("ResourcePath"),
                "fully_qualified_domain_name": config.get("FullyQualifiedDomainName"),
                "ip_address": config.get("IPAddress"),
                "port": config.get("Port"),
                "request_interval": config.get("RequestInterval"),
                "failure_threshold": config.get("FailureThreshold"),
                "measure_latency": config.get("MeasureLatency", False),
                "inverted": config.get("Inverted", False),
                "health_status": {
                    "total_checkers": len(checkers),
                    "healthy_checkers": healthy_count,
                    "is_healthy": healthy_count > (len(checkers) / 2),
                },
            }
        )

    except IntegrationNotConfiguredError:
        logger.warning("aws_not_configured", tool="route53_get_health_check")
        return _aws_config_required_response("route53_get_health_check")
    except ClientError as e:
        logger.error(
            "failed_to_get_health_check", error=str(e), health_check_id=health_check_id
        )
        return json.dumps({"error": str(e), "health_check_id": health_check_id})


@function_tool(strict_mode=False)
def route53_update_dns_records(
    hosted_zone_id: str,
    record_name: str,
    record_type: str,
    record_value: str,
    ttl: int = 300,
    action: str = "UPSERT",
) -> str:
    """
    Update Route53 DNS records (for failover testing).

    Args:
        hosted_zone_id: Route53 hosted zone ID
        record_name: DNS record name (e.g., "api.example.com")
        record_type: Record type (A, CNAME, TXT, etc.)
        record_value: New record value
        ttl: Time to live in seconds
        action: CREATE, DELETE, or UPSERT

    Returns:
        Change request details as JSON string
    """
    try:
        session = _get_aws_session()
        route53 = session.client("route53")

        change_batch = {
            "Changes": [
                {
                    "Action": action,
                    "ResourceRecordSet": {
                        "Name": record_name,
                        "Type": record_type,
                        "TTL": ttl,
                        "ResourceRecords": [{"Value": record_value}],
                    },
                }
            ]
        }

        response = route53.change_resource_record_sets(
            HostedZoneId=hosted_zone_id,
            ChangeBatch=change_batch,
        )

        change_info = response["ChangeInfo"]

        logger.info(
            "route53_record_updated",
            zone=hosted_zone_id,
            record=record_name,
            type=record_type,
        )

        return json.dumps(
            {
                "change_id": change_info["Id"],
                "status": change_info["Status"],
                "submitted_at": str(change_info["SubmittedAt"]),
                "hosted_zone_id": hosted_zone_id,
                "record_name": record_name,
                "record_type": record_type,
                "record_value": record_value,
                "action": action,
                "note": "Change is PENDING and will propagate within 60 seconds",
            }
        )

    except IntegrationNotConfiguredError:
        logger.warning("aws_not_configured", tool="route53_update_dns_records")
        return _aws_config_required_response("route53_update_dns_records")
    except ClientError as e:
        logger.error(
            "failed_to_update_dns_record",
            error=str(e),
            zone=hosted_zone_id,
            record=record_name,
        )
        return json.dumps(
            {
                "error": str(e),
                "hosted_zone_id": hosted_zone_id,
                "record_name": record_name,
            }
        )

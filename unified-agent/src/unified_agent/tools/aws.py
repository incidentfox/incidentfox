"""
AWS resource inspection and debugging tools.

Provides tools for EC2, CloudWatch, Lambda, ECS, and RDS operations.
"""

import json
import logging
from typing import Optional

from ..core.agent import function_tool
from . import register_tool

logger = logging.getLogger(__name__)


def _get_aws_session(region: str = "us-east-1"):
    """Get boto3 session with credentials from environment or IAM."""
    try:
        import boto3
        from botocore.exceptions import NoCredentialsError

        session = boto3.Session(region_name=region)
        # Test credentials
        session.client("sts").get_caller_identity()
        return session
    except NoCredentialsError:
        raise RuntimeError("AWS credentials not configured")
    except ImportError:
        raise RuntimeError("boto3 not installed: pip install boto3")


@function_tool
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

    except Exception as e:
        logger.error(f"describe_ec2_instance error: {e}")
        return json.dumps({"error": str(e), "instance_id": instance_id})


@function_tool
def get_cloudwatch_logs(
    log_group: str,
    log_stream: Optional[str] = None,
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

    except Exception as e:
        logger.error(f"get_cloudwatch_logs error: {e}")
        return json.dumps({"error": str(e), "log_group": log_group})


@function_tool
def get_cloudwatch_metrics(
    namespace: str,
    metric_name: str,
    dimensions: Optional[str] = None,
    period: int = 300,
    stat: str = "Average",
    region: str = "us-east-1",
) -> str:
    """
    Get CloudWatch metrics data.

    Args:
        namespace: CloudWatch namespace (e.g., AWS/EC2)
        metric_name: Metric name (e.g., CPUUtilization)
        dimensions: JSON string of dimensions (e.g., '[{"Name": "InstanceId", "Value": "i-xxx"}]')
        period: Period in seconds
        stat: Statistic (Average, Sum, Maximum, Minimum)
        region: AWS region

    Returns:
        Metric datapoints as JSON string
    """
    try:
        from datetime import datetime, timedelta

        session = _get_aws_session(region)
        cloudwatch = session.client("cloudwatch")

        dims = json.loads(dimensions) if dimensions else []

        response = cloudwatch.get_metric_statistics(
            Namespace=namespace,
            MetricName=metric_name,
            Dimensions=dims,
            StartTime=datetime.utcnow() - timedelta(hours=1),
            EndTime=datetime.utcnow(),
            Period=period,
            Statistics=[stat],
        )

        datapoints = sorted(
            response["Datapoints"],
            key=lambda x: x["Timestamp"],
        )

        return json.dumps(
            {
                "namespace": namespace,
                "metric_name": metric_name,
                "datapoints": [
                    {
                        "timestamp": str(dp["Timestamp"]),
                        "value": dp.get(stat),
                        "unit": dp.get("Unit"),
                    }
                    for dp in datapoints
                ],
            }
        )

    except Exception as e:
        logger.error(f"get_cloudwatch_metrics error: {e}")
        return json.dumps({"error": str(e), "metric_name": metric_name})


@function_tool
def list_ecs_tasks(
    cluster: str,
    service: Optional[str] = None,
    region: str = "us-east-1",
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

        params = {"cluster": cluster}
        if service:
            params["serviceName"] = service

        task_arns = ecs.list_tasks(**params)["taskArns"]

        if not task_arns:
            return json.dumps({"cluster": cluster, "tasks": []})

        tasks = ecs.describe_tasks(cluster=cluster, tasks=task_arns)["tasks"]

        result = {
            "cluster": cluster,
            "task_count": len(tasks),
            "tasks": [
                {
                    "task_arn": t["taskArn"],
                    "task_definition": t["taskDefinitionArn"].split("/")[-1],
                    "status": t["lastStatus"],
                    "desired_status": t["desiredStatus"],
                    "health": t.get("healthStatus"),
                    "started_at": str(t.get("startedAt", "")),
                }
                for t in tasks
            ],
        }
        return json.dumps(result)

    except Exception as e:
        logger.error(f"list_ecs_tasks error: {e}")
        return json.dumps({"error": str(e), "cluster": cluster})


@function_tool
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
            "runtime": config.get("Runtime"),
            "memory_size": config["MemorySize"],
            "timeout": config["Timeout"],
            "last_modified": config["LastModified"],
            "state": config.get("State"),
            "handler": config.get("Handler"),
        }
        return json.dumps(result)

    except Exception as e:
        logger.error(f"describe_lambda_function error: {e}")
        return json.dumps({"error": str(e), "function_name": function_name})


# Register tools
register_tool("describe_ec2_instance", describe_ec2_instance)
register_tool("get_cloudwatch_logs", get_cloudwatch_logs)
register_tool("get_cloudwatch_metrics", get_cloudwatch_metrics)
register_tool("list_ecs_tasks", list_ecs_tasks)
register_tool("describe_lambda_function", describe_lambda_function)

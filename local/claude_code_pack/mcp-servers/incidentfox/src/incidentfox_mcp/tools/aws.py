"""AWS resource inspection and debugging tools.

Provides tools for investigating AWS infrastructure:
- describe_ec2_instance: EC2 instance status and details
- get_cloudwatch_logs: CloudWatch log retrieval
- query_cloudwatch_insights: Advanced log queries
- get_cloudwatch_metrics: CloudWatch metrics
- list_ecs_tasks: ECS/Fargate task status
"""

import json
import time
from datetime import datetime, timedelta

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from mcp.server.fastmcp import FastMCP

from ..utils.config import get_env


class AWSConfigError(Exception):
    """Raised when AWS is not configured."""

    def __init__(self, message: str):
        super().__init__(message)


def _get_aws_session(region: str | None = None):
    """Get boto3 session using default credential chain.

    Supports:
    - Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
    - ~/.incidentfox/.env file
    - ~/.aws/credentials file
    - IAM instance profile (for EC2)
    - IAM task role (for ECS/Fargate)
    """
    region = (
        region or get_env("AWS_REGION") or get_env("AWS_DEFAULT_REGION") or "us-east-1"
    )

    try:
        session = boto3.Session(region_name=region)
        # Test that credentials are available
        session.client("sts").get_caller_identity()
        return session
    except NoCredentialsError:
        raise AWSConfigError(
            "AWS credentials not configured. Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY, "
            "configure ~/.aws/credentials, or run on EC2/ECS with an IAM role."
        )


def register_tools(mcp: FastMCP):
    """Register AWS tools with the MCP server."""

    @mcp.tool()
    def describe_ec2_instance(instance_id: str, region: str = "us-east-1") -> str:
        """Get details about an EC2 instance.

        Args:
            instance_id: EC2 instance ID (e.g., "i-1234567890abcdef0")
            region: AWS region (default: "us-east-1")

        Returns:
            JSON with instance state, type, IPs, tags
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
            return json.dumps(result, indent=2)

        except AWSConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except ClientError as e:
            return json.dumps({"error": str(e), "instance_id": instance_id})

    @mcp.tool()
    def get_cloudwatch_logs(
        log_group: str,
        log_stream: str | None = None,
        limit: int = 100,
        region: str = "us-east-1",
    ) -> str:
        """Get logs from CloudWatch.

        Args:
            log_group: CloudWatch log group name
            log_stream: Specific log stream (optional, uses latest if not specified)
            limit: Number of log events to retrieve (default: 100)
            region: AWS region (default: "us-east-1")

        Returns:
            JSON with log messages
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
                },
                indent=2,
            )

        except AWSConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except ClientError as e:
            return json.dumps({"error": str(e), "log_group": log_group})

    @mcp.tool()
    def query_cloudwatch_insights(
        log_group: str,
        query: str,
        hours_ago: int = 1,
        region: str = "us-east-1",
    ) -> str:
        """Run a CloudWatch Logs Insights query.

        This is the most powerful way to analyze CloudWatch logs.
        Use aggregation queries to understand patterns before diving into samples.

        Args:
            log_group: CloudWatch log group name
            query: CloudWatch Insights query string
            hours_ago: How many hours back to query (default: 1)
            region: AWS region (default: "us-east-1")

        Returns:
            JSON with query results

        Example queries:
            - Error count: "filter @message like /ERROR/ | stats count(*) by bin(5m)"
            - Top errors: "filter @message like /Exception/ | stats count(*) by @message | sort count desc | limit 10"
            - Latency p99: "stats pct(@duration, 99) as p99 by bin(5m)"
        """
        try:
            session = _get_aws_session(region)
            logs = session.client("logs")

            end_time = int(datetime.utcnow().timestamp())
            start_time = int(
                (datetime.utcnow() - timedelta(hours=hours_ago)).timestamp()
            )

            # Start query
            response = logs.start_query(
                logGroupName=log_group,
                startTime=start_time,
                endTime=end_time,
                queryString=query,
            )

            query_id = response["queryId"]

            # Poll for results
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
                        },
                        indent=2,
                    )
                elif status in ("Failed", "Cancelled"):
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

        except AWSConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except ClientError as e:
            return json.dumps({"error": str(e), "log_group": log_group})

    @mcp.tool()
    def get_cloudwatch_metrics(
        namespace: str,
        metric_name: str,
        dimensions: str | None = None,
        hours_ago: int = 1,
        period: int = 300,
        region: str = "us-east-1",
    ) -> str:
        """Get CloudWatch metric statistics.

        Args:
            namespace: CloudWatch namespace (e.g., "AWS/EC2", "AWS/Lambda")
            metric_name: Metric name (e.g., "CPUUtilization", "Duration")
            dimensions: JSON string of dimensions (e.g., '[{"Name": "InstanceId", "Value": "i-xxx"}]')
            hours_ago: How many hours back to query (default: 1)
            period: Period in seconds for aggregation (default: 300 = 5 minutes)
            region: AWS region (default: "us-east-1")

        Returns:
            JSON with metric statistics (Average, Max, Min, Sum)
        """
        try:
            session = _get_aws_session(region)
            cloudwatch = session.client("cloudwatch")

            end_time = datetime.utcnow()
            start_time = end_time - timedelta(hours=hours_ago)

            # Parse dimensions if provided
            dims = []
            if dimensions:
                dims = json.loads(dimensions)

            response = cloudwatch.get_metric_statistics(
                Namespace=namespace,
                MetricName=metric_name,
                Dimensions=dims,
                StartTime=start_time,
                EndTime=end_time,
                Period=period,
                Statistics=["Average", "Maximum", "Minimum", "Sum"],
            )

            # Convert datetime objects to strings
            datapoints = []
            for dp in response["Datapoints"]:
                datapoint = dict(dp)
                if "Timestamp" in datapoint:
                    datapoint["Timestamp"] = str(datapoint["Timestamp"])
                datapoints.append(datapoint)

            # Sort by timestamp
            datapoints.sort(key=lambda x: x.get("Timestamp", ""))

            result = {
                "metric": metric_name,
                "namespace": namespace,
                "datapoints": datapoints,
            }
            return json.dumps(result, indent=2)

        except AWSConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except ClientError as e:
            return json.dumps(
                {"error": str(e), "namespace": namespace, "metric": metric_name}
            )

    @mcp.tool()
    def list_ecs_tasks(
        cluster: str,
        service: str | None = None,
        region: str = "us-east-1",
    ) -> str:
        """List ECS/Fargate tasks in a cluster.

        Args:
            cluster: ECS cluster name
            service: Optional service name to filter tasks
            region: AWS region (default: "us-east-1")

        Returns:
            JSON with task IDs, status, health, and start times
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
                    {
                        "cluster": cluster,
                        "service": service,
                        "task_count": 0,
                        "tasks": [],
                    }
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
                },
                indent=2,
            )

        except AWSConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except ClientError as e:
            return json.dumps({"error": str(e), "cluster": cluster, "service": service})

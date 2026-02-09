"""AWS CodePipeline tools for deployment monitoring."""

import os
from typing import Any

import json
import logging

from ..core.agent import function_tool
from . import register_tool


logger = logging.getLogger(__name__)


def _get_codepipeline_config() -> str:
    """Get CodePipeline configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    # Credentials from environment variables
    # 2. Try environment variables (dev/testing fallback)
    if os.getenv("AWS_REGION") or os.getenv("CODEPIPELINE_REGION"):
        return {
            "region": os.getenv("CODEPIPELINE_REGION") or os.getenv("AWS_REGION"),
            "access_key_id": os.getenv("AWS_ACCESS_KEY_ID"),
            "secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
            "pipeline_names": (
                os.getenv("CODEPIPELINE_NAMES", "").split(",")
                if os.getenv("CODEPIPELINE_NAMES")
                else None
            ),
        }

    # 3. Not configured - raise error
    return {"error": "codepipeline not configured"}


def _get_codepipeline_client():
    """Get CodePipeline boto3 client."""
    try:
        import boto3

        config = _get_codepipeline_config()

        kwargs = {"region_name": config["region"]}

        if config.get("access_key_id") and config.get("secret_access_key"):
            kwargs["aws_access_key_id"] = config["access_key_id"]
            kwargs["aws_secret_access_key"] = config["secret_access_key"]

        return boto3.client("codepipeline", **kwargs)

    except ImportError:
        return json.dumps({"ok": False, "error": "Tool execution error"})
            "codepipeline", "boto3 not installed. Install with: pip install boto3"
        )


@function_tool
def codepipeline_list_pipelines() -> str:
    """
    List all CodePipeline pipelines.

    Returns:
        List of pipelines with metadata
    """
    try:
        client = _get_codepipeline_client()
        config = _get_codepipeline_config()

        response = client.list_pipelines()

        pipelines = []
        for pipeline in response.get("pipelines", []):
            # Filter by configured pipeline names if specified
            pipeline_names = config.get("pipeline_names")
            if pipeline_names and pipeline["name"] not in pipeline_names:
                continue

            pipelines.append(
                {
                    "name": pipeline["name"],
                    "version": pipeline.get("version"),
                    "created": str(pipeline.get("created")),
                    "updated": str(pipeline.get("updated")),
                }
            )

        logger.info("codepipeline_pipelines_listed", count=len(pipelines))
        return pipelines

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except Exception as e:
        logger.error("codepipeline_list_pipelines_failed", error=str(e))
        return json.dumps({"ok": False, "error": "codepipeline_list_pipelines"})


@function_tool
def codepipeline_get_pipeline_state(pipeline_name: str) -> str:
    """
    Get current state of a CodePipeline pipeline.

    Args:
        pipeline_name: Name of the pipeline

    Returns:
        Pipeline state including stage statuses
    """
    try:
        client = _get_codepipeline_client()

        response = client.get_pipeline_state(name=pipeline_name)

        stages = []
        for stage in response.get("stageStates", []):
            actions = []
            for action in stage.get("actionStates", []):
                actions.append(
                    {
                        "name": action["actionName"],
                        "status": action.get("latestExecution", {}).get("status"),
                        "last_status_change": (
                            str(
                                action.get("latestExecution", {}).get(
                                    "lastStatusChange"
                                )
                            )
                            if action.get("latestExecution")
                            else None
                        ),
                    }
                )

            stages.append(
                {
                    "name": stage["stageName"],
                    "status": (
                        stage.get("latestExecution", {}).get("status")
                        if stage.get("latestExecution")
                        else "N/A"
                    ),
                    "actions": actions,
                }
            )

        logger.info("codepipeline_state_retrieved", pipeline=pipeline_name)

        return {
            "pipeline_name": response["pipelineName"],
            "pipeline_version": response.get("pipelineVersion"),
            "stages": stages,
            "created": str(response.get("created")),
            "updated": str(response.get("updated")),
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except Exception as e:
        logger.error(
            "codepipeline_get_state_failed", error=str(e), pipeline=pipeline_name
        )
        return json.dumps({"ok": False, "error": "codepipeline_get_pipeline_state"})


@function_tool
def codepipeline_get_execution_history(
    pipeline_name: str, max_results: int = 10
) -> str:
    """
    Get execution history for a pipeline.

    Args:
        pipeline_name: Name of the pipeline
        max_results: Maximum executions to return

    Returns:
        List of pipeline executions
    """
    try:
        client = _get_codepipeline_client()

        response = client.list_pipeline_executions(
            pipelineName=pipeline_name, maxResults=max_results
        )

        executions = []
        for execution in response.get("pipelineExecutionSummaries", []):
            executions.append(
                {
                    "execution_id": execution["pipelineExecutionId"],
                    "status": execution["status"],
                    "start_time": str(execution.get("startTime")),
                    "last_update_time": str(execution.get("lastUpdateTime")),
                    "source_revisions": execution.get("sourceRevisions", []),
                }
            )

        logger.info(
            "codepipeline_history_retrieved",
            pipeline=pipeline_name,
            executions=len(executions),
        )
        return executions

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except Exception as e:
        logger.error(
            "codepipeline_get_history_failed", error=str(e), pipeline=pipeline_name
        )
        return json.dumps({"ok": False, "error": "codepipeline_get_execution_history"})


@function_tool
def codepipeline_start_execution(
    pipeline_name: str, client_request_token: str | None = None
) -> str:
    """
    Start a manual execution of a pipeline.

    Args:
        pipeline_name: Name of the pipeline
        client_request_token: Optional idempotency token

    Returns:
        Execution details
    """
    try:
        client = _get_codepipeline_client()

        kwargs = {"name": pipeline_name}
        if client_request_token:
            kwargs["clientRequestToken"] = client_request_token

        response = client.start_pipeline_execution(**kwargs)

        logger.info(
            "codepipeline_execution_started",
            pipeline=pipeline_name,
            execution_id=response["pipelineExecutionId"],
        )

        return {
            "pipeline_name": pipeline_name,
            "execution_id": response["pipelineExecutionId"],
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except Exception as e:
        logger.error(
            "codepipeline_start_execution_failed", error=str(e), pipeline=pipeline_name
        )
        return json.dumps({"ok": False, "error": "codepipeline_start_execution"})


@function_tool
def codepipeline_get_failed_actions(pipeline_name: str) -> str:
    """
    Get details of failed actions in the latest pipeline execution.

    Args:
        pipeline_name: Name of the pipeline

    Returns:
        List of failed actions with error details
    """
    try:
        client = _get_codepipeline_client()

        # Get latest execution
        executions = client.list_pipeline_executions(
            pipelineName=pipeline_name, maxResults=1
        )

        if not executions.get("pipelineExecutionSummaries"):
            return []

        execution_id = executions["pipelineExecutionSummaries"][0][
            "pipelineExecutionId"
        ]

        # Get pipeline state
        state = client.get_pipeline_state(name=pipeline_name)

        failed_actions = []
        for stage in state.get("stageStates", []):
            for action in stage.get("actionStates", []):
                latest_exec = action.get("latestExecution", {})
                if latest_exec.get("status") == "Failed":
                    failed_actions.append(
                        {
                            "stage": stage["stageName"],
                            "action": action["actionName"],
                            "error_code": latest_exec.get("errorDetails", {}).get(
                                "code"
                            ),
                            "error_message": latest_exec.get("errorDetails", {}).get(
                                "message"
                            ),
                            "last_status_change": str(
                                latest_exec.get("lastStatusChange")
                            ),
                        }
                    )

        logger.info(
            "codepipeline_failed_actions_retrieved",
            pipeline=pipeline_name,
            count=len(failed_actions),
        )
        return failed_actions

    except IntegrationNotConfiguredError as e:
        return json.dumps({"ok": False, "error": "integration not configured"})
    except Exception as e:
        logger.error(
            "codepipeline_get_failed_actions_failed",
            error=str(e),
            pipeline=pipeline_name,
        )
        return json.dumps({"ok": False, "error": "codepipeline_get_failed_actions"})


# List of all CodePipeline tools for registration
CODEPIPELINE_TOOLS = [
    codepipeline_list_pipelines,
    codepipeline_get_pipeline_state,
    codepipeline_get_execution_history,
    codepipeline_start_execution,
    codepipeline_get_failed_actions,
]


# Register tools
register_tool("codepipeline_list_pipelines", codepipeline_list_pipelines)
register_tool("codepipeline_get_pipeline_state", codepipeline_get_pipeline_state)
register_tool("codepipeline_get_execution_history", codepipeline_get_execution_history)
register_tool("codepipeline_start_execution", codepipeline_start_execution)
register_tool("codepipeline_get_failed_actions", codepipeline_get_failed_actions)

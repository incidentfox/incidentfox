"""K8s Agent entry point."""

import asyncio
import signal
import sys

import structlog

from .config import get_settings
from .connection import GatewayConnection
from .executor import K8sExecutor

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logger = structlog.get_logger(__name__)


async def main():
    """Main entry point for the K8s agent."""
    settings = get_settings()

    # Validate required settings
    if not settings.api_key:
        logger.error(
            "missing_api_key",
            message="INCIDENTFOX_API_KEY environment variable is required",
        )
        sys.exit(1)

    if not settings.cluster_name:
        logger.error(
            "missing_cluster_name",
            message="INCIDENTFOX_CLUSTER_NAME environment variable is required",
        )
        sys.exit(1)

    logger.info(
        "starting_k8s_agent",
        cluster_name=settings.cluster_name,
        gateway_url=settings.gateway_url,
        agent_version=settings.agent_version,
    )

    # Initialize K8s executor
    try:
        executor = K8sExecutor()
    except Exception as e:
        logger.error("failed_to_initialize_executor", error=str(e))
        sys.exit(1)

    # Create gateway connection
    connection = GatewayConnection(executor)

    # Set up signal handlers for graceful shutdown
    shutdown_event = asyncio.Event()

    def signal_handler():
        logger.info("received_shutdown_signal")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)

    # Start connection in background
    connection_task = asyncio.create_task(connection.start())

    # Wait for shutdown signal
    await shutdown_event.wait()

    # Graceful shutdown
    logger.info("shutting_down")
    await connection.stop()

    # Cancel connection task
    connection_task.cancel()
    try:
        await connection_task
    except asyncio.CancelledError:
        pass

    logger.info("shutdown_complete")


def run():
    """Run the agent."""
    asyncio.run(main())


if __name__ == "__main__":
    run()

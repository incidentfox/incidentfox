"""
Unified Agent - Main Entry Point

This is the unified agent consolidating agent/ and sre-agent/ into a single runtime.
"""

import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def run_sandbox_server():
    """Run the sandbox server (FastAPI on port 8888)."""
    from .sandbox.server import run_server

    run_server()


def run_cli():
    """Run in CLI mode for direct interaction."""
    import asyncio

    from .core.agent import Agent
    from .core.runner import Runner

    async def main():
        agent = Agent(
            name="Investigator",
            instructions="You are an expert SRE investigator. Help debug production issues.",
        )

        print("Unified Agent CLI - Type 'quit' to exit")
        print("-" * 50)

        while True:
            try:
                user_input = input("\nYou: ").strip()
                if user_input.lower() in ("quit", "exit", "q"):
                    break
                if not user_input:
                    continue

                result = await Runner.run(agent, user_input)
                print(f"\nAgent: {result.final_output}")

            except KeyboardInterrupt:
                print("\nExiting...")
                break
            except Exception as e:
                print(f"\nError: {e}")

    asyncio.run(main())


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="IncidentFox Unified Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  incidentfox-agent --mode server   # Run sandbox server (default)
  incidentfox-agent --mode cli      # Run interactive CLI
        """,
    )

    parser.add_argument(
        "--mode",
        choices=["server", "cli"],
        default="server",
        help="Run mode: server (FastAPI sandbox) or cli (interactive)",
    )

    parser.add_argument(
        "--port", type=int, default=8888, help="Port for server mode (default: 8888)"
    )

    args = parser.parse_args()

    if args.mode == "server":
        logger.info("Starting unified agent in server mode...")
        run_sandbox_server()
    elif args.mode == "cli":
        logger.info("Starting unified agent in CLI mode...")
        run_cli()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

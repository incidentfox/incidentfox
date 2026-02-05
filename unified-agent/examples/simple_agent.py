#!/usr/bin/env python3
"""
Simple example of using the Unified Agent.

This demonstrates:
1. Creating an agent with tools
2. Running it with the Runner
3. Using config-driven agent creation
"""

import asyncio
import os
import sys

# Add the src directory to path for local development
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from unified_agent import (
    Agent,
    ModelSettings,
    Runner,
    create_generic_agent_from_config,
    function_tool,
)


# Define a simple tool
@function_tool
def get_current_time() -> str:
    """Get the current UTC time."""
    from datetime import datetime

    return datetime.utcnow().isoformat()


@function_tool
def calculate(expression: str) -> str:
    """
    Safely evaluate a mathematical expression.

    Args:
        expression: Mathematical expression (e.g., "2 + 2", "10 * 5")

    Returns:
        Result of the calculation
    """
    import json

    # Only allow safe mathematical operations
    allowed = set("0123456789+-*/.() ")
    if not all(c in allowed for c in expression):
        return json.dumps({"error": "Invalid expression"})
    try:
        result = eval(expression)  # Safe due to character filtering
        return json.dumps({"expression": expression, "result": result})
    except Exception as e:
        return json.dumps({"error": str(e)})


async def example_basic():
    """Basic example: Create and run an agent directly."""
    print("\n=== Basic Agent Example ===\n")

    agent = Agent(
        name="Helper",
        instructions="You are a helpful assistant. Use your tools to answer questions.",
        model="sonnet",  # Alias for anthropic/claude-sonnet-4-20250514
        tools=[get_current_time, calculate],
        model_settings=ModelSettings(temperature=0.3),
    )

    result = await Runner.run(
        agent,
        "What is 42 * 17? Also, what time is it?",
        max_turns=10,
    )

    print(f"Status: {result.status}")
    print(f"Output: {result.final_output}")
    print(f"Tool calls made: {len(result.tool_calls)}")


async def example_config_driven():
    """Config-driven example: Create agent from JSON config."""
    print("\n=== Config-Driven Agent Example ===\n")

    # This is how agents are created from config service
    agent_config = {
        "name": "Math Helper",
        "prompt": "You are a math expert. Help users with calculations.",
        "model": "sonnet",
        "temperature": 0.2,
        "tools": ["calculate"],  # Tool names to enable
    }

    # Create agent from config
    agent = create_generic_agent_from_config(
        agent_config,
        available_tools={"calculate": calculate},
    )

    result = await Runner.run(
        agent,
        "What is the square root of 144 plus 5 squared?",
        max_turns=10,
    )

    print(f"Agent: {agent.name}")
    print(f"Model: {agent.model}")
    print(f"Output: {result.final_output}")


async def example_streaming():
    """Streaming example: Get real-time events during execution."""
    print("\n=== Streaming Agent Example ===\n")

    agent = Agent(
        name="Streaming Demo",
        instructions="You are a helpful assistant.",
        model="sonnet",
        tools=[calculate],
    )

    async for event in Runner.run_streaming(
        agent,
        "Calculate 100 divided by 4",
        max_turns=10,
    ):
        print(f"[{event.type}] {event.data}")


def main():
    """Run all examples."""
    print("Unified Agent Examples")
    print("=" * 50)

    # Check for API key
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("\nWarning: ANTHROPIC_API_KEY not set.")
        print("Set it to run these examples:")
        print("  export ANTHROPIC_API_KEY=sk-ant-...")
        return

    try:
        asyncio.run(example_basic())
        asyncio.run(example_config_driven())
        asyncio.run(example_streaming())
    except Exception as e:
        print(f"\nError: {e}")
        raise


if __name__ == "__main__":
    main()

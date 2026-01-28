#!/usr/bin/env python3
"""Quick local test script - run agent without K8s sandbox.

Usage:
    uv run python test_local.py "What services are in otel-demo?"
    uv run python test_local.py  # Interactive mode
"""

import asyncio
import os
import sys

# Load .env
from dotenv import load_dotenv

load_dotenv()


async def main():
    # Import after dotenv loads
    from agent import InteractiveAgentSession

    # Get prompt from args or interactive
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
    else:
        prompt = input("Enter prompt: ")

    print(f"\n🔍 Running: {prompt}\n")
    print("=" * 60)

    session = InteractiveAgentSession(thread_id="local-test")
    await session.start()

    try:
        async for event in session.execute(prompt):
            # StreamEvent is a dataclass with .type and .data attributes
            event_type = event.type
            data = event.data

            if event_type == "thought":
                text = data.get("content", "")[:200]
                if text:
                    print(f"💭 {text}...")
            elif event_type == "text":
                print(data.get("content", ""), end="", flush=True)
            elif event_type == "tool_start":
                print(f"\n🔧 Using: {data.get('name', 'unknown')}")
            elif event_type == "tool_end":
                success = "✅" if data.get("success") else "❌"
                name = data.get("name", "")
                print(f"   {success} {name}")
            elif event_type == "error":
                print(f"\n❌ Error: {data.get('message', 'unknown')}")
            elif event_type == "result":
                print("\n" + "-" * 60)
                print("📋 RESULT:")
                print(data.get("content", ""))
                print("=" * 60)
                print("✅ Complete")
                break
    except Exception as e:
        print(f"\n❌ Error: {e}")
    finally:
        try:
            await session.stop()
        except Exception:
            pass  # Ignore cleanup errors


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Interrupted")
    except Exception as e:
        print(f"\n❌ Fatal: {e}")

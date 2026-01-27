"""
Test cross-event-loop hook behavior.

This simulates the ACTUAL problem where:
1. Main event loop is running (API server)
2. SlackUpdateHooks is created IN the main event loop context
3. A subagent runs in a separate thread with a new event loop
4. The hooks are called from the subagent's event loop
5. asyncio.Lock() fails because it's bound to the main event loop

We test different solutions to make hooks work across event loops.
"""

import asyncio
import threading
import time
from dataclasses import dataclass

# ============================================================================
# PROBLEM: Current implementation with asyncio.Lock
# ============================================================================


class BrokenHooks:
    """
    This simulates the current SlackUpdateHooks implementation.
    It will fail when called from a different event loop.
    """

    def __init__(self):
        # This lock is created in the main event loop
        self._update_lock = asyncio.Lock()
        self._pending_task: asyncio.Task | None = None
        self._last_update_time = 0.0
        self._update_count = 0
        self._creation_loop = asyncio.get_running_loop()
        print(
            f"  [BrokenHooks] Created with lock bound to loop {id(self._creation_loop)}"
        )

    async def use_lock_in_main_loop(self):
        """Simulates the hook being used in main loop BEFORE subagent starts."""
        async with self._update_lock:
            self._last_update_time = time.time()
            self._update_count += 1
            print("  [BrokenHooks] Initial update in main loop (binds lock)")

    async def hold_lock_during_subagent(self, duration: float = 0.2):
        """Hold lock in main loop while subagent runs - creates contention."""
        print(
            f"  [BrokenHooks] Main loop acquiring lock (will hold for {duration}s)..."
        )
        async with self._update_lock:
            print("  [BrokenHooks] Main loop holding lock...")
            await asyncio.sleep(duration)
            print("  [BrokenHooks] Main loop releasing lock")

    async def on_tool_end(self, tool_name: str, result: str):
        """Called when a tool finishes - this will fail in different event loop."""
        try:
            await self._schedule_update(tool_name)
            return True
        except RuntimeError as e:
            print(f"  ERROR in on_tool_end: {e}")
            return False

    async def _schedule_update(self, tool_name: str):
        current_loop = asyncio.get_running_loop()
        print(f"  [BrokenHooks] _schedule_update called in loop {id(current_loop)}")

        async with self._update_lock:  # This fails in different event loop!
            now = time.time()
            if now - self._last_update_time >= 0.1:  # 100ms debounce
                self._last_update_time = now
                self._update_count += 1
                print(f"  [BrokenHooks] Update #{self._update_count}: {tool_name}")


# ============================================================================
# SOLUTION 1: Use threading.Lock with simple debounce (no deferred updates)
# ============================================================================


class ThreadSafeHooks:
    """
    Use threading.Lock for synchronization.
    Skip deferred updates - just send immediately if debounce passed.
    """

    def __init__(self):
        self._state_lock = threading.Lock()
        self._last_update_time = 0.0
        self._update_count = 0
        self._debounce_seconds = 0.1

    async def on_tool_end(self, tool_name: str, result: str):
        """Called when a tool finishes - works across event loops."""
        try:
            await self._schedule_update(tool_name)
            return True
        except Exception as e:
            print(f"  ERROR in on_tool_end: {e}")
            return False

    async def _schedule_update(self, tool_name: str):
        now = time.time()

        # Quick check with lock - only for state access
        with self._state_lock:
            time_since_last = now - self._last_update_time
            if time_since_last < self._debounce_seconds:
                # Too soon, skip this update
                print(f"  [ThreadSafeHooks] Skipped (debounce): {tool_name}")
                return
            self._last_update_time = now
            self._update_count += 1
            count = self._update_count

        # Send update outside lock (simulated)
        print(f"  [ThreadSafeHooks] Update #{count}: {tool_name}")


# ============================================================================
# SOLUTION 2: Event-loop aware locks (create new lock per loop)
# ============================================================================


class EventLoopAwareHooks:
    """
    Create a new asyncio.Lock for each event loop.
    This allows proper async coordination within each loop.
    """

    def __init__(self):
        self._locks: dict[int, asyncio.Lock] = {}  # loop id -> lock
        self._lock_creation_lock = threading.Lock()  # For creating new locks safely
        self._last_update_time = 0.0
        self._update_count = 0
        self._state_lock = threading.Lock()
        self._debounce_seconds = 0.1

    def _get_lock(self) -> asyncio.Lock:
        """Get or create a lock for the current event loop."""
        try:
            loop = asyncio.get_running_loop()
            loop_id = id(loop)
        except RuntimeError:
            # No running loop - shouldn't happen in async context
            raise

        with self._lock_creation_lock:
            if loop_id not in self._locks:
                self._locks[loop_id] = asyncio.Lock()
                print(f"  [EventLoopAwareHooks] Created new lock for loop {loop_id}")
            return self._locks[loop_id]

    async def on_tool_end(self, tool_name: str, result: str):
        """Called when a tool finishes - works across event loops."""
        try:
            await self._schedule_update(tool_name)
            return True
        except Exception as e:
            print(f"  ERROR in on_tool_end: {e}")
            return False

    async def _schedule_update(self, tool_name: str):
        lock = self._get_lock()

        async with lock:  # Now this works because lock is for current loop
            now = time.time()

            with self._state_lock:
                time_since_last = now - self._last_update_time
                if time_since_last < self._debounce_seconds:
                    print(f"  [EventLoopAwareHooks] Skipped (debounce): {tool_name}")
                    return
                self._last_update_time = now
                self._update_count += 1
                count = self._update_count

            print(f"  [EventLoopAwareHooks] Update #{count}: {tool_name}")


# ============================================================================
# Test runner - simulates the ACTUAL production scenario
# ============================================================================


def run_subagent_in_thread(hooks, tool_names: list[str], results: dict):
    """
    Simulates a subagent running in a separate thread with new event loop.
    This is what investigation_agent does with _run_agent_in_thread.
    """

    def run():
        # Create new event loop for this thread (like subagent does)
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        print(f"  [Subagent] Running in new loop {id(new_loop)}")

        async def run_tools():
            success_count = 0
            for tool_name in tool_names:
                # Simulate tool execution
                await asyncio.sleep(0.05)  # Tool takes 50ms

                # Call hook (this is where the problem occurs)
                success = await hooks.on_tool_end(tool_name, f"result of {tool_name}")
                if success:
                    success_count += 1

            return success_count

        try:
            success = new_loop.run_until_complete(run_tools())
            results["success"] = success
            results["error"] = None
        except Exception as e:
            results["success"] = 0
            results["error"] = str(e)
        finally:
            new_loop.close()

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(timeout=5)

    if thread.is_alive():
        results["error"] = "Thread timed out"
        results["success"] = 0


async def test_hooks_async(hooks_class, name: str):
    """
    Test a hooks implementation.
    Creates hooks in the CURRENT event loop (simulating main API server loop),
    then runs subagent in a separate thread.
    """
    print(f"\n{'='*60}")
    print(f"Testing: {name}")
    print(f"{'='*60}")

    main_loop = asyncio.get_running_loop()
    print(f"  [Main] Creating hooks in main loop {id(main_loop)}")

    # Create hooks in the main event loop context
    hooks = hooks_class()

    # For BrokenHooks, first use the lock in main loop to bind it
    # This simulates the real scenario where hooks are used before subagent starts
    if hasattr(hooks, "use_lock_in_main_loop"):
        await hooks.use_lock_in_main_loop()

    tool_names = ["list_pods", "describe_deployment", "get_pod_events"]
    results = {}

    print(f"\n  [Main] Running {len(tool_names)} tools in subagent thread...")

    # Run subagent in separate thread (like production)
    loop = asyncio.get_running_loop()

    # For BrokenHooks, create lock contention - main loop holds lock while subagent runs
    if hasattr(hooks, "hold_lock_during_subagent"):
        # Run both concurrently: main holds lock while subagent tries to acquire
        await asyncio.gather(
            hooks.hold_lock_during_subagent(0.15),
            loop.run_in_executor(
                None, lambda: run_subagent_in_thread(hooks, tool_names, results)
            ),
        )
    else:
        # Other hooks just run subagent
        await loop.run_in_executor(
            None, lambda: run_subagent_in_thread(hooks, tool_names, results)
        )

    print("\n  Results:")
    print(f"    Success count: {results.get('success', 0)}/{len(tool_names)}")
    if results.get("error"):
        print(f"    Error: {results['error']}")

    return results.get("success", 0) == len(tool_names)


async def main():
    print("Cross-Event-Loop Hooks Test")
    print("=" * 60)
    print("\nThis tests different approaches for making hooks work when")
    print("called from a subagent running in a different thread/event loop.")
    print("\nIMPORTANT: Hooks are created in the MAIN event loop,")
    print("then used from a SUBAGENT thread with a DIFFERENT event loop.")

    results = {}

    # Test 1: Broken (current implementation)
    results["BrokenHooks"] = await test_hooks_async(
        BrokenHooks, "BrokenHooks (current implementation)"
    )

    # Test 2: ThreadSafeHooks
    results["ThreadSafeHooks"] = await test_hooks_async(
        ThreadSafeHooks, "ThreadSafeHooks (threading.Lock)"
    )

    # Test 3: EventLoopAwareHooks
    results["EventLoopAwareHooks"] = await test_hooks_async(
        EventLoopAwareHooks, "EventLoopAwareHooks (per-loop locks)"
    )

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    for name, success in results.items():
        status = "PASS" if success else "FAIL"
        print(f"  {name}: {status}")

    print("\nRecommendation:")
    if not results["BrokenHooks"]:
        print("  BrokenHooks FAILS as expected (asyncio.Lock bound to wrong loop)")
    if results["ThreadSafeHooks"]:
        print("  ThreadSafeHooks WORKS - simplest solution using threading.Lock")
    if results["EventLoopAwareHooks"]:
        print("  EventLoopAwareHooks WORKS - creates per-loop asyncio.Lock")


if __name__ == "__main__":
    asyncio.run(main())

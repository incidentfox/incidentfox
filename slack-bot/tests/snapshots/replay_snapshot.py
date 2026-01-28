#!/usr/bin/env python3
"""
Replay investigation snapshots to test message/modal formatting.

Usage:
    python replay_snapshot.py <snapshot_file>
    python replay_snapshot.py data/investigation_20260121_120000_12345678.json

Output:
    - main_message.json - The main message blocks
    - modal.json - The modal view blocks
    - subagent_N.json - Detail modal for each subagent (if any)
"""

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Add parent directory to path to import production modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Import the builders
from message_builder import build_final_message
from modal_builder import build_session_modal, build_subagent_detail_modal

# Placeholder file IDs for testing (valid format for Block Kit Builder)
# Real Slack file IDs: F + 8+ uppercase alphanumeric chars
LOADING_FILE_ID = "F07TESTLOAD1"
DONE_FILE_ID = "F07TESTDONE1"


def replace_slack_files_with_urls(blocks):
    """
    Replace slack_file references with image_url for Block Kit Builder testing.
    This allows images to actually render during development/testing.
    """
    if isinstance(blocks, dict):
        # If this is an image element with slack_file, replace with image_url
        if blocks.get("type") == "image" and "slack_file" in blocks:
            file_id = blocks["slack_file"]["id"]
            # Use different placeholder images based on file ID
            if "LOAD" in file_id:
                url = "https://placehold.co/32x32/4A90E2/white?text=..."
            elif "DONE" in file_id:
                url = "https://placehold.co/32x32/7ED321/white?text=✓"
            else:
                url = "https://placehold.co/32x32/cccccc/333333?text=?"

            # Replace slack_file with image_url
            blocks_copy = blocks.copy()
            del blocks_copy["slack_file"]
            blocks_copy["image_url"] = url
            return blocks_copy
        else:
            # Recursively process dict values
            return {k: replace_slack_files_with_urls(v) for k, v in blocks.items()}
    elif isinstance(blocks, list):
        # Recursively process list items
        return [replace_slack_files_with_urls(item) for item in blocks]
    else:
        return blocks


@dataclass
class ThoughtSection:
    """A thought and its associated tool calls."""

    text: str
    tools: list = field(default_factory=list)
    completed: bool = False


@dataclass
class MessageState:
    """Tracks the state of a Slack message during investigation."""

    channel_id: str
    message_ts: str
    thread_ts: str
    thread_id: str
    thoughts: list = field(default_factory=list)
    current_tool: Optional[dict] = None
    final_result: Optional[str] = None
    error: Optional[str] = None
    timeline: list = field(default_factory=list)
    last_update_time: float = 0


def dict_to_state(data: dict) -> MessageState:
    """Convert dict back to MessageState."""
    # Convert thoughts - handle both dict and already-converted objects
    thoughts = []
    for t in data.get("thoughts", []):
        # If it's already a ThoughtSection, keep it
        if isinstance(t, ThoughtSection):
            thoughts.append(t)
        # If it's a dict or has dict-like structure
        elif isinstance(t, dict):
            thought = ThoughtSection(
                text=t.get("text", ""),
                tools=t.get("tools", []),
                completed=t.get("completed", False),
            )
            thoughts.append(thought)
        else:
            # Fallback for unexpected types
            print(f"Warning: unexpected thought type: {type(t)}")
            thought = ThoughtSection(text=str(t), tools=[], completed=False)
            thoughts.append(thought)

    return MessageState(
        channel_id=data.get("channel_id", ""),
        message_ts=data.get("message_ts", ""),
        thread_ts=data.get("thread_ts", ""),
        thread_id=data.get("thread_id", ""),
        thoughts=thoughts,
        current_tool=data.get("current_tool"),
        final_result=data.get("final_result"),
        error=data.get("error"),
        timeline=data.get("timeline", []),
        last_update_time=data.get("last_update_time", 0),
    )


def replay_snapshot(snapshot_file: str):
    """Load snapshot and generate message/modal blocks."""
    print(f"Loading snapshot: {snapshot_file}")

    # Load snapshot
    with open(snapshot_file, "r") as f:
        snapshot = json.load(f)

    print(f"Captured at: {snapshot['captured_at']}")
    print(f"Thread ID: {snapshot['thread_id']}")

    # Convert to MessageState
    state = dict_to_state(snapshot["state"])

    print("\nInvestigation summary:")
    print(f"  Thoughts: {len(state.thoughts)}")
    print(f"  Total tools: {sum(len(t.tools) for t in state.thoughts)}")
    print(f"  Final result: {bool(state.final_result)}")
    print(f"  Error: {state.error if state.error else 'None'}")

    # Generate main message blocks
    print("\nGenerating main message blocks...")
    main_blocks = build_final_message(
        result_text=state.final_result or "",
        thoughts=state.thoughts,
        success=not bool(state.error),
        error=state.error,
        done_file_id=DONE_FILE_ID,
        thread_id=state.thread_id,
    )

    # Generate modal blocks
    print("Generating modal blocks...")
    modal_view = build_session_modal(
        thread_id=state.thread_id,
        thoughts=state.thoughts,
        result=state.final_result,
        loading_file_id=LOADING_FILE_ID,
        done_file_id=DONE_FILE_ID,
    )

    # Generate subagent detail modals
    print("Generating subagent detail modals...")
    subagent_modals = []

    for thought_idx, thought in enumerate(state.thoughts):
        for task_idx, tool in enumerate(thought.tools):
            tool_name = tool.get("name", "")
            if tool_name == "Task":
                # This is a subagent - find all its children
                subagent_id = tool.get("tool_use_id")  # Use tool_use_id, not id
                children = []

                # Collect all tools that have this as parent (but exclude nested Task tools)
                for child_idx, child_tool in enumerate(thought.tools):
                    parent_id = child_tool.get("parent_tool_use_id")
                    child_name = child_tool.get("name", "")
                    # Only include if parent matches AND it's not another Task (subagent)
                    if parent_id == subagent_id and child_name != "Task":
                        children.append((child_idx, child_tool))

                # Generate the detail modal for this subagent
                subagent_modal = build_subagent_detail_modal(
                    thread_id=state.thread_id,
                    task_tool=tool,
                    children=children,
                    loading_file_id=LOADING_FILE_ID,
                    done_file_id=DONE_FILE_ID,
                    thought_idx=thought_idx,
                )

                # Store with metadata
                description = tool.get("input", {}).get("description", "Subagent")
                subagent_modals.append(
                    {
                        "thought_idx": thought_idx,
                        "task_idx": task_idx,
                        "description": description,
                        "modal": subagent_modal,
                    }
                )

                print(
                    f"  - Subagent {len(subagent_modals)}: {description} ({len(children)} tools)"
                )

    # Replace slack_file with image_url for Block Kit Builder testing
    main_blocks_for_builder = replace_slack_files_with_urls(main_blocks)
    modal_view_for_builder = replace_slack_files_with_urls(modal_view)
    subagent_modals_for_builder = [
        {**sa, "modal": replace_slack_files_with_urls(sa["modal"])}
        for sa in subagent_modals
    ]

    # Save outputs
    output_dir = Path(snapshot_file).parent

    main_output = output_dir / f"{Path(snapshot_file).stem}_main_message.json"
    modal_output = output_dir / f"{Path(snapshot_file).stem}_modal.json"

    with open(main_output, "w") as f:
        json.dump({"blocks": main_blocks_for_builder}, f, indent=2)

    with open(modal_output, "w") as f:
        json.dump(modal_view_for_builder, f, indent=2)

    # Save subagent modals
    subagent_outputs = []
    for idx, sa in enumerate(subagent_modals_for_builder):
        subagent_output = output_dir / f"{Path(snapshot_file).stem}_subagent_{idx}.json"
        with open(subagent_output, "w") as f:
            json.dump(sa["modal"], f, indent=2)
        subagent_outputs.append(subagent_output)

    print("\n✅ Output saved:")
    print(f"   Main message: {main_output}")
    print(f"   Modal: {modal_output}")
    if subagent_outputs:
        for idx, output in enumerate(subagent_outputs):
            desc = subagent_modals_for_builder[idx]["description"]
            print(f"   Subagent {idx}: {output} ({desc})")
    print("\n📋 Copy/paste to Slack Block Kit Builder:")
    print("   https://app.slack.com/block-kit-builder")

    # Print summary of blocks
    print("\n📊 Block counts:")
    print(f"   Main message: {len(main_blocks)} blocks")
    if "blocks" in modal_view:
        print(f"   Modal: {len(modal_view['blocks'])} blocks")
    for idx, sa in enumerate(subagent_modals_for_builder):
        if "blocks" in sa["modal"]:
            print(f"   Subagent {idx}: {len(sa['modal']['blocks'])} blocks")

    return main_output, modal_output, subagent_outputs


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python replay_snapshot.py <snapshot_file>")
        print("\nAvailable snapshots:")
        snapshots_dir = Path(__file__).parent / "data"
        if snapshots_dir.exists():
            snapshots = sorted(snapshots_dir.glob("investigation_*.json"))
            for s in snapshots:
                print(f"  - {s.name}")
        else:
            print("  (no snapshots found)")
        sys.exit(1)

    snapshot_file = sys.argv[1]
    if not os.path.exists(snapshot_file):
        print(f"Error: File not found: {snapshot_file}")
        sys.exit(1)

    replay_snapshot(snapshot_file)

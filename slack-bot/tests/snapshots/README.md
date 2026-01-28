# Test Snapshots - Fast Iteration Workflow

## Overview

Instead of running a full investigation every time you want to test message formatting changes, you can capture investigation snapshots and replay them locally.

## Workflow

### 1. **Capture** (Automatic)

When you run an investigation in Slack with snapshots enabled, the bot automatically saves a snapshot to `tests/snapshots/data/`:

```bash
# Enable snapshot recording in your .env file
ENABLE_SNAPSHOTS=true
```

```
tests/snapshots/data/
  investigation_20260121_120530_12345678.json
```

**Note:** Snapshot recording is **disabled by default** in production. Set `ENABLE_SNAPSHOTS=true` in your `.env` file for local development.

The snapshot contains:
- All thoughts and tool calls
- Tool inputs and outputs
- Final result
- Everything needed to rebuild the message

### 2. **Replay** (Manual)

Use the replay script to process a snapshot locally:

```bash
cd tests/snapshots
python replay_snapshot.py data/investigation_20260121_120530_12345678.json
```

This generates two files:
- `investigation_..._main_message.json` - Main message blocks
- `investigation_..._modal.json` - Modal view blocks

### 3. **Test** (Manual)

Copy/paste the generated JSON into Slack's Block Kit Builder:

🔗 **https://app.slack.com/block-kit-builder**

You'll see exactly how the message/modal looks without running a new investigation!

## Benefits

✅ **Fast iteration** - No need to run full investigations  
✅ **Consistent testing** - Same data every time  
✅ **Offline development** - Work without connecting to agents  
✅ **Version control** - Keep snapshots for regression testing  

## Example

```bash
# 1. Run investigation in Slack (snapshot auto-saved)
# 2. Replay it locally
cd tests/snapshots
python replay_snapshot.py data/investigation_20260121_120530_12345678.json

# Output:
📸 Loaded snapshot from 2026-01-21T12:05:30
   Thoughts: 3, Tools: 12, Final result: Yes

✅ Output saved:
   Main message: data/investigation_..._main_message.json
   Modal: data/investigation_..._modal.json

📋 Copy/paste to: https://app.slack.com/block-kit-builder

# 3. Open Block Kit Builder and paste the JSON
# 4. Make changes to message_builder.py or modal_builder.py
# 5. Replay again to see changes
```

## Snapshot Format

```json
{
  "captured_at": "2026-01-21T12:05:30",
  "thread_id": "slack-...",
  "state": {
    "thoughts": [
      {
        "text": "Let me search for files...",
        "tools": [
          {
            "name": "Glob",
            "input": {"pattern": "**/*.py"},
            "output": {"matches": [...], "count": 295},
            "success": true,
            "running": false
          }
        ],
        "completed": true
      }
    ],
    "final_result": "Here's what I found..."
  }
}
```

## Tips

1. **Keep useful snapshots** - Rename complex investigations for regression tests
2. **Compare outputs** - Use `diff` to compare before/after changes
3. **Test edge cases** - Capture snapshots with errors, long outputs, etc.
4. **Share with team** - Commit interesting snapshots for shared testing

## Cleanup

Snapshots are in `.gitignore` by default, but you can commit specific ones:

```bash
# Add a specific snapshot for regression testing
git add -f tests/snapshots/data/investigation_edge_case_long_output.json
```


#!/bin/bash
# Pre-commit observability gate
# Runs before git commit/push. Scans staged files for observability gaps.
# Blocks commit if critical gaps exist.

TOOL_INPUT=$(cat)
COMMAND=$(echo "$TOOL_INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)

# Only intercept git commit and git push
if ! echo "$COMMAND" | grep -qE 'git\s+(commit|push)'; then
    exit 0
fi

# Find the scanner
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCANNER="$SCRIPT_DIR/analyzers/scan.py"

if [ ! -f "$SCANNER" ]; then
    exit 0
fi

# Get staged/changed files
if echo "$COMMAND" | grep -q 'git push'; then
    # For push: scan files changed since main
    FILES=$(git diff --name-only main...HEAD 2>/dev/null | grep -E '\.(ts|tsx|js|jsx|py|go|java|rb|rs)$' | grep -viE '(test_|_test\.|\.test\.|\.spec\.)' | head -20)
else
    # For commit: scan staged files
    FILES=$(git diff --cached --name-only 2>/dev/null | grep -E '\.(ts|tsx|js|jsx|py|go|java|rb|rs)$' | grep -viE '(test_|_test\.|\.test\.|\.spec\.)' | head -20)
    # Also check unstaged if nothing is staged
    if [ -z "$FILES" ]; then
        FILES=$(git diff --name-only 2>/dev/null | grep -E '\.(ts|tsx|js|jsx|py|go|java|rb|rs)$' | grep -viE '(test_|_test\.|\.test\.|\.spec\.)' | head -20)
    fi
fi

if [ -z "$FILES" ]; then
    exit 0
fi

TOTAL_CRITICAL=0
TOTAL_HIGH=0
ALL_GAPS=""

for FILE in $FILES; do
    if [ ! -f "$FILE" ]; then
        continue
    fi

    RESULT=$(python3 "$SCANNER" "$FILE" --json 2>/dev/null)
    if [ $? -ne 0 ] || [ -z "$RESULT" ]; then
        continue
    fi

    CRITICAL=$(echo "$RESULT" | jq -r '.critical // 0' 2>/dev/null)
    HIGH=$(echo "$RESULT" | jq -r '.high // 0' 2>/dev/null)
    TOTAL_CRITICAL=$((TOTAL_CRITICAL + CRITICAL))
    TOTAL_HIGH=$((TOTAL_HIGH + HIGH))

    if [ "$((CRITICAL + HIGH))" -gt 0 ]; then
        GAPS=$(echo "$RESULT" | jq -r '
            [.files[].gaps[] | select(.severity == "critical" or .severity == "high")] |
            .[0:3][] |
            "  \(.file):\(.line) — \(.description)"
        ' 2>/dev/null)
        ALL_GAPS="$ALL_GAPS
$GAPS"
    fi
done

if [ "$TOTAL_CRITICAL" -eq 0 ] && [ "$TOTAL_HIGH" -eq 0 ]; then
    echo "━━━ Observability: All clear ━━━"
    exit 0
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  OBSERVABILITY CHECK (pre-commit)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  $TOTAL_CRITICAL critical, $TOTAL_HIGH high gaps in changed files"
echo ""
echo "$ALL_GAPS" | head -10
echo ""

if [ "$TOTAL_CRITICAL" -gt 0 ]; then
    echo "  BLOCKING: $TOTAL_CRITICAL critical gaps must be fixed."
    echo "  Add structured logging to silent error handlers before committing."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    # Exit non-zero to signal the issue (though Claude Code hooks don't block,
    # the message prompts Claude to fix before proceeding)
    exit 0
else
    echo "  Non-blocking: $TOTAL_HIGH suggestions to improve observability."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    exit 0
fi

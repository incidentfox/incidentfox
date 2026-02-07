#!/bin/bash
# Post-edit observability scanner
# Runs after every Write/Edit to a source file.
# Outputs actionable suggestions that Claude sees and can auto-fix.

TOOL_INPUT=$(cat)
FILE_PATH=$(echo "$TOOL_INPUT" | jq -r '.tool_input.file_path // .tool_input.filePath // empty' 2>/dev/null)

# Only scan source code files
if [ -z "$FILE_PATH" ] || ! echo "$FILE_PATH" | grep -qE '\.(ts|tsx|js|jsx|py|go|java|rb|rs)$'; then
    exit 0
fi

# Skip test files
if echo "$FILE_PATH" | grep -qiE '(test_|_test\.|\.test\.|\.spec\.|__tests__)'; then
    exit 0
fi

# Find the scanner relative to this hook
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCANNER="$SCRIPT_DIR/analyzers/scan.py"

if [ ! -f "$SCANNER" ]; then
    exit 0
fi

# Run scanner (JSON mode for parsing)
RESULT=$(python3 "$SCANNER" "$FILE_PATH" --json 2>/dev/null)
if [ $? -ne 0 ] || [ -z "$RESULT" ]; then
    exit 0
fi

CRITICAL=$(echo "$RESULT" | jq -r '.critical // 0' 2>/dev/null)
HIGH=$(echo "$RESULT" | jq -r '.high // 0' 2>/dev/null)
TOTAL=$((CRITICAL + HIGH))

if [ "$TOTAL" -eq 0 ]; then
    exit 0
fi

# Output suggestions that Claude will see
echo ""
echo "━━━ Observability Coverage ━━━"
echo "$CRITICAL critical, $HIGH high priority gaps in $(basename "$FILE_PATH")"

# Show the top 3 gaps with line numbers
echo "$RESULT" | jq -r '
    [.files[].gaps[] | select(.severity == "critical" or .severity == "high")] |
    sort_by(if .severity == "critical" then 0 else 1 end) |
    .[0:3][] |
    "  Line \(.line): \(.description)"
' 2>/dev/null

echo ""
echo "Fix these before moving on — add structured logging with context."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

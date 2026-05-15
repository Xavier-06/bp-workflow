#!/bin/bash
# cleanup_completed_tasks.sh - Clean up subagent sessions for completed tasks
# Checks tasks.md for ✅ completed tasks and removes their session files

SESSION_DIR="/Users/xavier/WorkBuddy/20260409155327/ir_runtime/sessions"
TASKS_FILE="/Users/xavier/WorkBuddy/20260409155327/ir_runtime/memory/tasks.md"

echo "🧹 Cleaning up sessions for completed tasks..."
echo ""

# Extract completed task IDs from tasks.md
# Looking for patterns like [TASK-20260329-001] ... ✅
COMPLETED_TASKS=$(grep -oE '\[TASK-[A-Z0-9-]+\].*✅' "$TASKS_FILE" | grep -oE 'TASK-[A-Z0-9-]+' | sort -u)

if [ -z "$COMPLETED_TASKS" ]; then
    echo "⚠️  No completed TASK-XXX tasks found in tasks.md"
    echo "✅ Nothing to clean up"
    exit 0
fi

echo "📋 Found completed tasks:"
echo "$COMPLETED_TASKS" | sed 's/^/   - /'
echo ""

# Count before cleanup
BEFORE=$(find "$SESSION_DIR" -name "*.jsonl" -type f | wc -l)
echo "📊 Sessions before: $BEFORE"

DELETED=0
KEPT=0

# Check each session file
for session_file in "$SESSION_DIR"/*.jsonl; do
    [ -f "$session_file" ] || continue
    
    # Extract label from session file (look for "label" in the JSONL)
    LABEL=$(grep -o '"label"[[:space:]]*:[[:space:]]*"[^"]*"' "$session_file" | head -1 | grep -oE 'TASK-[A-Z0-9-]+' || true)
    
    if [ -z "$LABEL" ]; then
        ((KEPT++))
        continue
    fi
    
    # Check if this task is in completed list
    if echo "$COMPLETED_TASKS" | grep -q "^${LABEL}$"; then
        rm "$session_file"
        # Also remove .meta.json if exists
        meta_file="${session_file%.jsonl}.meta.json"
        [ -f "$meta_file" ] && rm "$meta_file"
        echo "🗑️  Deleted: $(basename "$session_file") (${LABEL})"
        ((DELETED++))
    else
        ((KEPT++))
    fi
done

AFTER=$(find "$SESSION_DIR" -name "*.jsonl" -type f | wc -l)
echo ""
echo "🗑️  Deleted: $DELETED sessions"
echo "📦 Kept: $KEPT sessions (active/no task label)"
echo "📊 Sessions after: $AFTER"
echo ""
echo "✅ Cleanup complete!"

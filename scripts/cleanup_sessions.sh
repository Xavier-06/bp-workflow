#!/bin/bash
# cleanup_sessions.sh - Clean up old subagent session transcripts
# Keeps sessions from last N days, removes the rest

KEEP_DAYS=${1:-3}
SESSION_DIR="/Users/xavier/WorkBuddy/20260409155327/ir_runtime/sessions"

echo "🧹 Cleaning up session transcripts older than $KEEP_DAYS days..."
echo "📁 Session directory: $SESSION_DIR"
echo ""

# Count before cleanup
BEFORE=$(find "$SESSION_DIR" -name "*.jsonl" -type f | wc -l)
echo "📊 Before: $BEFORE session files"

# Find and remove old session files
DELETED=0
while IFS= read -r file; do
    rm "$file"
    # Also remove corresponding .meta.json if exists
    meta_file="${file%.jsonl}.meta.json"
    [ -f "$meta_file" ] && rm "$meta_file"
    ((DELETED++))
done < <(find "$SESSION_DIR" -name "*.jsonl" -type f -mtime +$KEEP_DAYS)

# Count after cleanup
AFTER=$(find "$SESSION_DIR" -name "*.jsonl" -type f | wc -l)
echo "🗑️  Deleted: $DELETED session files"
echo "📊 After: $AFTER session files"
echo ""
echo "✅ Cleanup complete!"

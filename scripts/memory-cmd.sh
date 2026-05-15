#!/bin/bash
# Unified memory command entrypoint
# Primary: memory_system (mem0-env)
# Fallback: memory_agent wrapper

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$SCRIPT_DIR/.."
BRIDGE="$SCRIPT_DIR/memory_bridge.py"
PRIMARY_PY="/Users/xavier/WorkBuddy/20260409155327/mem0-env/bin/python"
MEMORY_AGENT_DIR="$ROOT/memory_agent"
TOOL_SCRIPT="$ROOT/skills/memory-agent/scripts/tool.py"

if [ -x "$PRIMARY_PY" ] && [ -f "$BRIDGE" ]; then
  if "$PRIMARY_PY" "$BRIDGE" "$@"; then
    exit 0
  fi
fi

cd "$MEMORY_AGENT_DIR"
source venv/bin/activate
python3 "$TOOL_SCRIPT" "$@"

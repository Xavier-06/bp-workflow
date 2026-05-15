#!/usr/bin/env bash
# memory-decay — 每天 03:00 由 launchd 触发
# 输出通过 launchd 标准管道写入 logs/
set -euo pipefail
cd /Users/xavier/WorkBuddy/20260409155327/ir_runtime

PYTHON="/opt/homebrew/bin/python3"
TODAY=$(date +%Y-%m-%d)
SEVEN_DAYS_AGO=$(date -v-7d +%Y-%m-%d)

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === memory-decay start ==="

# 1. 30+ 天日志归档
"$PYTHON" scripts/memory_dedup.py decay --days 30

# 2. 7 天前日志去重
"$PYTHON" scripts/memory_dedup.py dedup --file "memory/${SEVEN_DAYS_AGO}.md" 2>/dev/null || \
  echo "⚠️ dedup ${SEVEN_DAYS_AGO}.md: 文件不存在或跳过"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === memory-decay done ==="

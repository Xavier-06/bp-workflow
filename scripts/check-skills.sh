#!/bin/bash
# 自动检查可用技能 - WorkBuddy 版

WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"

echo "🔌 IR Pipeline 模块:"
find "$WORKSPACE" -mindepth 1 -maxdepth 1 -type d | sort \
  | sed "s#^$WORKSPACE/##" \
  | sed 's/^/  - /'

echo ""
echo "🔌 已安装 WorkBuddy Skills:"
ls -1 ~/.workbuddy/skills/ 2>/dev/null | sed 's/^/  - /'

echo ""
echo "💡 IR 管线提示:"
echo "  - 搜索? DDG (免密钥) + Yahoo Finance Skill"
echo "  - 行情? Yahoo Skill (yahoo_quote.py / yahoo_brief.py)"
echo "  - 研报交付? 龙少微信推送 (longshao_notify.py)"
echo "  - 记忆? memory_agent + vector_memory"

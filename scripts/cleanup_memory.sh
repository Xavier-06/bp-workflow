#!/bin/bash
# 一次性清理：去重 + 30 天衰减

cd /Users/xavier/WorkBuddy/20260409155327/ir_runtime

echo "=== 当前状况 ==="
for f in memory/2026-03-{20,21,22,23,24,25}.md memory/2026-04-01.md; do
    if [ -f "$f" ]; then
        lines=$(wc -l < "$f")
        echo "$f: ${lines} lines"
    fi
done

echo ""
echo "=== 执行衰减（30 天 -> archives） ==="
/usr/bin/env python3 scripts/memory_dedup.py decay --days 30

echo ""
echo "=== 执行去重 ==="
for f in memory/2026-04-01.md; do
    echo "去重: $f"
    /usr/bin/env python3 scripts/memory_dedup.py dedup --file "$f"
done

echo ""
echo "=== 更新 daily_log.sh ==="
# daily_log.sh 改为用 memory_dedup.py 避免重复
cat > scripts/daily_log.sh << 'SCRIPT'
#!/bin/bash
# 每日日志自动创建（带去重检查）
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
cd /Users/xavier/WorkBuddy/20260409155327/ir_runtime
TODAY=$(date +%Y-%m-%d)
LOG_FILE="memory/${TODAY}.md"
if [ ! -f "$LOG_FILE" ]; then
    /usr/bin/env python3 scripts/memory_dedup.py add "日志文件已创建" --type "今日事项" --date "$TODAY"
    echo "$(date): 日志已创建（去重模式）" >> /Users/xavier/WorkBuddy/20260409155327/ir_runtime/logs/daily_log.log
fi
SCRIPT

echo ""
echo "=== 完成 ==="

#!/bin/bash
# 检查 brain.md 中的待办提醒，主动发消息

BRAIN="/Users/xavier/WorkBuddy/20260409155327/ir_runtime/brain.md"
TRACKER="/Users/xavier/WorkBuddy/20260409155327/ir_runtime/memory/proactive-reminders.json"

# 读取 brain.md 中的待办
# 格式: ### YYYY-MM-DD HH:MM - 提醒内容

NOW=$(date +%s)
FIVE_MINUTES=$((5 * 60))

# 提取待办并检查
grep -E "^### [0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}" "$BRAIN" | while read -r line; do
    # 解析日期和时间
    date_part=$(echo "$line" | grep -oE "[0-9]{4}-[0-9]{2}-[0-9]{2}")
    time_part=$(echo "$line" | grep -oE "[0-9]{2}:[0-9]{2}")
    
    if [[ -n "$date_part" && -n "$time_part" ]]; then
        reminder_datetime="${date_part} ${time_part}"
        reminder_ts=$(date -j -f "%Y-%m-%d %H:%M" "$reminder_datetime" +%s 2>/dev/null)
        
        if [[ -n "$reminder_ts" ]]; then
            diff=$((reminder_ts - NOW))
            # 如果在未来 5 分钟内
            if [[ $diff -gt 0 && $diff -le $FIVE_MINUTES ]]; then
                echo "REMINDER:$line"
            fi
        fi
    fi
done
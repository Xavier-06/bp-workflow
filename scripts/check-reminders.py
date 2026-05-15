#!/usr/bin/env python3
import json
import os
import subprocess
from datetime import datetime

BRAIN = "str(Path(__file__).resolve().parent.parent / 'brain.md')"
TRACKER = "str(Path(__file__).resolve().parent.parent / 'memory/proactive-reminders.json')"

def load_tracker():
    if os.path.exists(TRACKER):
        with open(TRACKER, 'r') as f:
            return json.load(f)
    return {"reminded": [], "last_check": None}

def save_tracker(tracker):
    with open(TRACKER, 'w') as f:
        json.dump(tracker, f, ensure_ascii=False, indent=2)

def get_reminders():
    """从 brain.md 提取待办提醒"""
    reminders = []
    with open(BRAIN, 'r') as f:
        content = f.read()
    
    # 查找 ### YYYY-MM-DD HH:MM 格式的行
    import re
    pattern = r'### (\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})'
    for match in re.finditer(pattern, content):
        date_str = match.group(1)
        time_str = match.group(2)
        dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        reminders.append({
            "datetime": f"{date_str} {time_str}",
            "timestamp": int(dt.timestamp()),
            "content": ""
        })
    
    # 提取内容（紧跟其后的列表项）
    for i, rem in enumerate(reminders):
        # 简单取下一行作为内容
        pass
    
    return reminders

def check_and_remind():
    tracker = load_tracker()
    now = int(datetime.now().timestamp())
    five_min = 5 * 60
    
    reminders = get_reminders()
    
    for rem in reminders:
        key = rem["datetime"]
        if key in tracker["reminded"]:
            continue  # 已提醒过
        
        diff = rem["timestamp"] - now
        if 0 < diff <= five_min:
            # 需要提醒
            content = f"📅 提醒: {rem['datetime']}"
            print(f"NEED_REMINDER:{content}")
            
            # 标记为已提醒
            tracker["reminded"].append(key)
            save_tracker(tracker)
            return content
    
    return None

if __name__ == "__main__":
    result = check_and_remind()
    if result:
        print(result)
    else:
        print("NO_REMINDER")
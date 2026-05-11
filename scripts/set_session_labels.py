#!/usr/bin/env python3
"""
set_session_labels.py - 给飞书会话设置友好的标题
"""

import json
from pathlib import Path

SESSIONS_JSON = Path(__file__).resolve().parent.parent / "data" / "sessions.json"

# 向量记忆库里的映射（2026-03-18 存储 + 2026-03-31 更新）
# 格式：短 ID 或完整 ID -> 名字
user_name_map = {
    # 周总（有两个 ID）
    "2f5ff2cf": "周总",
    "67210f80aae94b073c8f90f184b510d5": "周总",
    
    # 吉总
    "44e18a48": "吉总",
    
    # 罗姐
    "6beaf48c": "罗姐",
    
    # 睿仪
    "gd18d544": "睿仪",
    
    # Xavier
    "ad5gc112": "Xavier",
    "fc4728374aeed4fb302026963720c08c": "Xavier",
}

def extract_short_id(session_key):
    """从 session key 提取短 ID 或长 ID"""
    parts = session_key.split(':')
    for p in parts:
        # 匹配短 ID (8 位)
        if len(p) == 8 and p.isalnum():
            return p
        # 匹配长 ID (ou_xxx)
        if p.startswith('ou_'):
            return p[3:]  # 去掉 ou_
    return None

def main():
    if not SESSIONS_JSON.exists():
        print(f"❌ Sessions file not found: {SESSIONS_JSON}")
        return
    
    with open(SESSIONS_JSON, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    print("📋 当前飞书会话及设置的标题:")
    print()
    
    updated = 0
    for session_key in sorted(data.keys()):
        if 'feishu' not in session_key:
            continue
        
        session_info = data[session_key]
        short_id = extract_short_id(session_key)
        
        if not short_id:
            continue
        
        name = user_name_map.get(short_id)
        if not name:
            print(f"⚠️  未识别：{session_key} (ID: {short_id})")
            continue
        
        new_label = f"飞书-{name}"
        old_label = session_info.get('label', '')
        
        if old_label != new_label:
            session_info['label'] = new_label
            print(f"✅ {name}: {short_id}")
            print(f"   旧标签：{old_label or '(none)'} → 新标签：{new_label}")
            updated += 1
        else:
            print(f"✓  {name}: {short_id} (已是 {new_label})")
    
    with open(SESSIONS_JSON, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print()
    print(f"📝 已更新 {updated} 个会话标签")
    print("✅ 完成！")

if __name__ == "__main__":
    main()

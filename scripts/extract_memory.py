#!/usr/bin/env python3
"""
Auto Extract Memory — 从近期对话/日志中自动抽取记忆

借鉴 Claude Code 的 extractMemories 设计：
- 从近期日志中提取 durable memories
- 写入 memory_agent 向量库 + memory/topics 目录
- 四层分类：user / feedback / project / reference
- 失败和成功都记（不仅纠错，也记确认）

用法:
    python3 scripts/extract_memory.py
    python3 scripts/extract_memory.py --days 3
    python3 scripts/extract_memory.py --dry-run
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
MEMORY_DIR = ROOT / "memory"
AGENT_SKILL = ROOT / "skills" / "memory-agent" / "SKILL.md"
MEMORY_MD = ROOT / "MEMORY.md"

# ── 记忆类型定义 (Claude Code 四层分类) ──────────────────
MEMORY_TYPES = {
    "user": {
        "keywords": ["用户", "偏好", "喜欢", "讨厌", "习惯", "风格", "知道", "了解", "角色", "岗位", "负责"],
        "when": "学到用户的任何新信息时",
    },
    "feedback": {
        "keywords": ["纠正", "不对", "别这样", "不要", "对，", "完美", "继续", "正确", "修复", "错误", "教训", "改进"],
        "when": "用户纠正或确认工作方式时",
    },
    "project": {
        "keywords": ["项目", "目标", "决策", "确认", "采用", "改用", "放弃", "冻结", "合并", "发布", "交付"],
        "when": "学到谁在做什么/为什么/何时",
    },
    "reference": {
        "keywords": ["Linear", "Grafana", "Jira", "飞书", "文档", "看板", "追踪", "位置"],
        "when": "学到外部系统位置时",
    },
}

# 什么 NOT 存
SKIP_KEYWORDS = ["git log", "git blame", "commit", "grep", "ls ", "一次性", "临时", "待办", "TODO"]


def read_recent_logs(days: int = 3) -> list[dict]:
    """读取最近 N 天的 daily logs"""
    entries = []
    today = datetime.now()
    for i in range(days):
        date = today - timedelta(days=i)
        date_str = date.strftime("%Y-%m-%d")
        log_path = MEMORY_DIR / f"{date_str}.md"
        if log_path.exists():
            content = log_path.read_text(encoding="utf-8")
            # Strip frontmatter
            m = re.match(r"^---\n.*?\n---\n", content, re.DOTALL)
            body = content[m.end():] if m else content
            entries.append({"date": date_str, "content": body})
    return entries


def classify_memory(text: str) -> list[str]:
    """基于关键词判断记忆类型"""
    types = []
    lower = text.lower()
    for type_name, meta in MEMORY_TYPES.items():
        if any(kw.lower() in lower for kw in meta["keywords"]):
            types.append(type_name)
    return types or ["project"]  # default to project


def should_skip(text: str) -> bool:
    """检查是否应该跳过（基于 NOT 存规则）"""
    lower = text.lower()
    return any(kw.lower() in lower for kw in SKIP_KEYWORDS)


def extract_memories(logs: list[dict], dry_run: bool = False) -> list[dict]:
    """从日志中提取记忆"""
    memories = []

    for log in logs:
        lines = log["content"].split("\n")
        current_section = ""

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("## "):
                current_section = stripped[3:].strip()
                continue
            if not stripped or stripped.startswith("- ") and not any(kw in stripped for kw in MEMORY_TYPES):
                continue

            # 只处理有意义的行（至少20字符）
            if len(stripped) < 20:
                continue

            # 检查是否跳过
            if should_skip(stripped):
                continue

            # 分类
            memory_types = classify_memory(stripped)
            for mem_type in memory_types:
                memory = {
                    "date": log["date"],
                    "type": mem_type,
                    "section": current_section,
                    "content": stripped[:500],  # cap length
                    "source": log["date"],
                }
                memories.append(memory)

    return memories


def save_memory(memory: dict) -> None:
    """保存单条记忆"""
    try:
        # Import memory bridge if available
        sys.path.insert(0, str(ROOT / "memory"))
        from memory_bridge import add_memory

        result = add_memory(
            content=memory["content"],
            category=memory["type"],
            metadata={
                "source": memory["source"],
                "section": memory["section"],
                "date": memory["date"],
            },
        )
        print(f"  ✅ Saved ({memory['type']}): {memory['content'][:80]}...")
    except Exception as e:
        print(f"  ⚠ Failed to save: {e}")


def main():
    parser = argparse.ArgumentParser(description="Auto Extract Memory from recent logs")
    parser.add_argument("--days", type=int, default=3, help="Look back N days (default: 3)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be saved without saving")
    args = parser.parse_args()

    print(f"📖 Reading logs from last {args.days} days...")
    logs = read_recent_logs(args.days)

    if not logs:
        print("  No recent logs found.")
        return

    print(f"  Found {len(logs)} log entries")

    print(f"\n🔍 Extracting memories...")
    memories = extract_memories(logs, dry_run=args.dry_run)

    if not memories:
        print("  No new memories to extract.")
        return

    print(f"\n📋 Found {len(memories)} candidate memories:")
    for m in memories:
        print(f"  [{m['type']}] ({m['date']}) {m['content'][:100]}...")

    if args.dry_run:
        print("\n🔒 Dry run — no memories saved.")
        return

    print(f"\n💾 Saving memories...")
    for m in memories:
        save_memory(m)

    print(f"\n✅ Extraction complete: {len(memories)} memories processed.")


if __name__ == "__main__":
    main()

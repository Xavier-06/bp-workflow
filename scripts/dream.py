#!/usr/bin/env python3
"""
自动记忆蒸馏 (auto-dream)

借鉴 Claude Code 的 auto-dream 设计：
- 从近期 daily logs 中提取值得长期记忆的内容
- 按四类分类：user / feedback / project / reference
- 写入 memory/topics/ 主题文件 + memory/lessons/ + memory/decisions/
- 同时更新 MEMORY.md 索引

用法:
  python3 scripts/dream.py --days 3          # 蒸馏最近 3 天日志
  python3 scripts/dream.py --days 3 --dry-run  # 只查看不写入
  cron: 每天 00:30 自动运行
"""

import sys
import re
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
MEMORY_DIR = ROOT / "memory"
TOPICS_DIR = MEMORY_DIR / "topics"
LESSONS_DIR = MEMORY_DIR / "lessons"
DECISIONS_DIR = MEMORY_DIR / "decisions"
MEMORY_MD = ROOT / "MEMORY.md"

# ── 四层记忆类型定义 ───────────────────────────────────
MEMORY_TYPES = {
    "user": {
        "name": "user",
        "desc": "用户角色/偏好/知识。帮你更贴合他的需求。",
        "when": "学到用户任何新信息时",
    },
    "feedback": {
        "name": "feedback",
        "desc": "用户纠正或确认的工作方式。失败 AND 成功都记。",
        "when": "用户说'不对/别这样'或'对，继续'时",
        "body_structure": "规则 + **Why:** + **How to apply:**",
    },
    "project": {
        "name": "project",
        "desc": "项目目标/决策/冻结窗口。相对时间必须转绝对日期。",
        "when": "学到谁在做什么/为什么/何时",
        "body_structure": "事实/决策 + **Why:** + **How to apply:**",
    },
    "reference": {
        "name": "reference",
        "desc": "外部系统位置（Linear/Grafana/文档等）。",
        "when": "学到外部资源时",
    },
}

# 什么 NOT 存
NOT_SAVE_REASONS = [
    ("代码模式/架构/文件路径", "grep 可查"),
    ("git log / git blame", "有权威源"),
    ("调试方案/修复配方", "修复在代码里"),
    ("已在 AGENTS.md / TOOLS.md", "已记录"),
    ("进行中任务/临时状态", "会变"),
]


def read_recent_logs(days: int = 3) -> list[str]:
    """读取最近 N 天的 daily logs"""
    entries = []
    today = datetime.now()
    for i in range(days):
        date = today - timedelta(days=i)
        log_file = MEMORY_DIR / f"{date.strftime('%Y-%m-%d')}.md"
        if log_file.exists():
            entries.append(log_file.read_text(encoding="utf-8"))
    return entries


def classify_section(title: str, content: str) -> Optional[str]:
    """判断内容应该归到哪个主题"""
    text = f"{title}\n{content}".lower()

    mappings = [
        (["bp", "尽调", "dd", "pipeline"], "bp-pipeline"),
        (["研报", "ir", "valuation", "估值", "earnings"], "ir-research"),
        (["搜索", "searxng", "tavily", "ddg", "search"], "search-system"),
        (["记忆", "memory", "去重", "蒸馏"], "memory-system"),
        (["飞书", "feishu", "消息", "通知"], "feishu"),
        (["skills", "技能", "agent", "子代理", "架构"], "agent-skills"),
        (["credential", "凭证", "token", "security"], "security"),
    ]

    for keywords, topic in mappings:
        if any(kw in text for kw in keywords):
            return topic
    return None


def extract_memories(logs: list[str]) -> dict:
    """从日志中提取值得蒸馏的内容，分类到四类型"""
    result = {
        "topics": defaultdict(list),
        "lessons": [],
        "decisions": [],
    }

    lesson_kw = ["教训", "失败", "错误", "修复", "根因", "踩坑", "不能", "不要"]
    decision_kw = ["决策", "决定", "确认", "策略", "采用", "改用", "放弃"]

    for log in logs:
        # 解析 frontmatter
        m = re.match(r"---\n.*?\n---\n", log, re.DOTALL)
        body = log[m.end():] if m else log

        # 解析 sections
        sections = []
        current_title = ""
        current_content = []

        for line in body.split("\n"):
            if line.strip().startswith("## "):
                if current_title:
                    sections.append((current_title, "\n".join(current_content).strip()))
                current_title = line.strip()[3:]
                current_content = []
            elif current_title:
                current_content.append(line)

        if current_title:
            sections.append((current_title, "\n".join(current_content).strip()))

        # 分类每个 section
        for title, content in sections:
            if len(content) < 30:  # 忽略太短的
                continue

            topic = classify_section(title, content)
            if topic:
                result["topics"][topic].append({
                    "title": title,
                    "content": content,
                    "date": datetime.now().strftime("%Y-%m-%d"),
                })

            # 检查是否是教训
            if any(kw in content for kw in lesson_kw):
                result["lessons"].append({
                    "title": title,
                    "content": content,
                })

            # 检查是否是决策
            if any(kw in content for kw in decision_kw):
                result["decisions"].append({
                    "title": title,
                    "content": content,
                })

    return result


def update_topic_file(topic: str, entries: list[dict], dry_run: bool = False):
    """更新或创建主题文件"""
    topic_file = TOPICS_DIR / f"{topic}.md"

    # 读取已有内容
    existing = ""
    if topic_file.exists():
        existing = topic_file.read_text(encoding="utf-8")

    # 构建更新内容
    updates = []
    for entry in entries:
        updates.append(f"### {entry['title']} (*{entry['date']}*)\n\n{entry['content']}\n")

    if dry_run:
        print(f"\n  [DRY RUN] Would update {topic_file.name}:")
        for u in updates:
            print(f"    + {u.split()[0] if u else 'empty'}")
        return

    # 追加到文件
    with open(topic_file, "a", encoding="utf-8") as f:
        if updates:
            f.write("\n\n## " + datetime.now().strftime("%Y-%m-%d") + " 更新\n\n")
            for u in updates:
                f.write(u)
                f.write("\n")

    print(f"  ✅ Updated {topic_file.name} with {len(updates)} entries")


def update_lessons(entries: list[dict], dry_run: bool = False):
    """更新教训文件"""
    lessons_file = LESSONS_DIR / f"{datetime.now().strftime('%Y-%m')}.md"

    if dry_run:
        print(f"\n  [DRY RUN] Would update {lessons_file.name}")
        return

    with open(lessons_file, "a", encoding="utf-8") as f:
        for entry in entries:
            f.write(f"### {entry['title']}\n\n{entry['content']}\n\n")


def update_decisions(entries: list[dict], dry_run: bool = False):
    """更新决策文件"""
    decisions_file = DECISIONS_DIR / f"{datetime.now().strftime('%Y-%m')}.md"

    if dry_run:
        print(f"\n  [DRY RUN] Would update {decisions_file.name}")
        return

    with open(decisions_file, "a", encoding="utf-8") as f:
        for entry in entries:
            f.write(f"### {entry['title']}\n\n{entry['content']}\n\n")


def main():
    import argparse
    import sys
    sys.path.insert(0, str(MEMORY_DIR.parent / "scripts"))
    from dream_lock import acquire_dream_lock, release_dream_lock, hours_since_last_consolidation

    ap = argparse.ArgumentParser(description="自动记忆蒸馏")
    ap.add_argument("--days", type=int, default=3, help="读取最近 N 天日志")
    ap.add_argument("--from", dest="from_date", help="起始日期 YYYY-MM-DD")
    ap.add_argument("--to", dest="to_date", help="结束日期 YYYY-MM-DD")
    ap.add_argument("--dry-run", action="store_true", help="只查看，不写入")
    ap.add_argument("--force", action="store_true", help="跳过时间/锁 gate")
    args = ap.parse_args()

    # --- Gate control (borrowed from Claude Code autoDream.ts) ---
    if not args.dry_run and not args.force:
        hours = hours_since_last_consolidation()
        if hours < 24:
            print(f"⏳ 距上次蒸馏仅 {hours:.1f}小时，跳过（需 ≥24h）")
            return

        prior = acquire_dream_lock()
        if prior is None:
            print("⏳ 有其他进程正在蒸馏，跳过")
            return

    # 读取日志
    logs = read_recent_logs(args.days)
    if not logs:
        print(f"⚠️  最近 {args.days} 天无日志")
        return

    print(f"📖 读取了 {len(logs)} 份日志文件")

    # 提取记忆
    memories = extract_memories(logs)

    topic_count = sum(len(v) for v in memories["topics"].values())
    print(f"🔍 提取到 {topic_count} 个主题条目, {len(memories['lessons'])} 个教训, {len(memories['decisions'])} 个决策")

    # 更新主题文件
    for topic, entries in memories["topics"].items():
        update_topic_file(topic, entries, dry_run=args.dry_run)

    # 更新教训和决策
    if memories["lessons"]:
        update_lessons(memories["lessons"], dry_run=args.dry_run)
    if memories["decisions"]:
        update_decisions(memories["decisions"], dry_run=args.dry_run)

    # Release lock (or rollback if dry-run)
    if not args.dry_run and not args.force:
        release_dream_lock()  # delete lock — normal completion

    print("✅ 蒸馏完成")


if __name__ == "__main__":
    main()

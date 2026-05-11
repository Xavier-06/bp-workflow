#!/usr/bin/env python3
"""
Session Memory Extractor — post-session extraction

借鉴 Claude Code 的 extractMemories 设计：
- 从当前对话中提取 durable memories，写入 memory/topics/ + memory_agent
- 四层分类：user / feedback / project / reference
- 去重：写入前先查旧条目
- 写入时自动附加 **Why:** + **How to apply:**（feedback/project 类）

触发方式：
1. 在会话结束时自动运行（OpenClaw hook 或手动调用）
2. 也可以在 /extract 命令触发

用法:
  python3 scripts/session_memory_extract.py --session-log /path/to/session.log
  python3 scripts/session_memory_extract.py --last-session
  python3 scripts/session_memory_extract.py --dry-run
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEMORY_DIR = ROOT / "memory"
TOPICS_DIR = MEMORY_DIR / "topics"
MEMORY_AGENT_VENV = ROOT / "memory_agent" / "venv" / "bin" / "python3"

# ── 四层记忆类型定义 ──────────────────────────────────────
TYPES = {
    "user": {
        "desc": "用户角色/偏好/知识水平",
        "triggers": ["偏好", "习惯", "喜欢", "讨厌", "风格", "角色", "知道", "了解", "负责", "我是", "我的"],
    },
    "feedback": {
        "desc": "用户纠正或确认的工作方式（失败 AND 成功都记）",
        "triggers": ["纠正", "不对", "别", "不要", "不能", "禁止", "完美", "对，继续", "对，就", "错误", "教训",
                      "修复", "改进", "下次", "以后别", "不要再", "下次别"],
    },
    "project": {
        "desc": "项目目标、决策、冻结窗口",
        "triggers": ["决定", "确认", "采用", "改用", "放弃", "冻结", "合并", "发布", "交付", "策略", "方案",
                      "项目", "目标"],
    },
    "reference": {
        "desc": "外部系统位置",
        "triggers": ["Linear ", "Grafana ", "Jira", "在哪个", "哪里找", "资源", "文档", "看板"],
    },
}

# 什么 NOT 存
SKIP_PATTERNS = [
    r"git log", r"git blame", r"git status",
    r"grep ", r"ls ", r"cat ",
    r"临时", r"一次性", r"暂时", r"待会",
    r"进行中", r"in progress", r"WIP",
]


def classify(text: str) -> list[str]:
    """基于关键词判断记忆类型"""
    types = []
    lower = text.lower()
    for type_name, meta in TYPES.items():
        if any(kw.lower() in lower for kw in meta["triggers"]):
            types.append(type_name)
    return types or ["project"]  # default


def should_skip(text: str) -> bool:
    """检查是否应该跳过"""
    return any(re.search(p, text, re.IGNORECASE) for p in SKIP_PATTERNS)


def extract_candidates(session_text: str) -> list[dict]:
    """从对话文本中提取值得记忆的内容"""
    candidates = []
    lines = session_text.split("\n")

    current_context = ""
    for line in lines:
        stripped = line.strip()

        # Track section context
        if stripped.startswith(("## ", "### ", "# ")):
            current_context = stripped.lstrip("# ")
            continue

        # Skip empty / too short
        if len(stripped) < 30:
            continue

        # Skip known skip patterns
        if should_skip(stripped):
            continue

        # Check if it looks like a memory-worthy fact
        types = classify(stripped)
        if not types:
            continue

        # Dedup: skip if already in recent logs
        if is_duplicate(stripped):
            continue

        for t in types:
            candidates.append({
                "date": datetime.now().strftime("%Y-%m-%d"),
                "type": t,
                "content": stripped[:500],
                "context": current_context,
            })

    return candidates[:10]  # cap at 10 per session


def is_duplicate(content: str) -> bool:
    """简单去重：检查是否与最近 3 天日志重复"""
    today = datetime.now()
    for i in range(3):
        date = today
        log_path = MEMORY_DIR / f"{date.strftime('%Y-%m-%d')}.md"
        if not log_path.exists():
            continue
        content_lower = content.lower()[:50]
        if content_lower in log_path.read_text(encoding="utf-8").lower():
            return True
    return False


def format_feedback_memory(content: str) -> str:
    """格式化 feedback 类型记忆（带 Why: + How to apply:）"""
    return f"{content}\n\n  - **Why:** 用户在反馈中确认或纠正\n  - **How to apply:** 在未来相关工作中应用"


def format_project_memory(content: str) -> str:
    """格式化 project 类型记忆（带 Why: + How to apply:）"""
    return f"{content}\n\n  - **Why:** 项目决策\n  - **How to apply:** 在相关工作中遵循"


def save_to_memory(candidate: dict, dry_run: bool = False) -> bool:
    """保存单条记忆"""
    if dry_run:
        print(f"  [DRY RUN] [{candidate['type']}] {candidate['content'][:80]}...")
        return True

    content = candidate["content"]
    if candidate["type"] == "feedback":
        content = format_feedback_memory(content)
    elif candidate["type"] == "project":
        content = format_project_memory(content)

    # 1) 写入 memory_bridge (ChromaDB)
    try:
        sys.path.insert(0, str(ROOT / "memory"))
        from memory.memory_bridge import add_memory
        doc_id = add_memory(content, category=candidate["type"])
        if not doc_id:
            print(f"  ⏭️ Duplicate skipped: {content[:60]}...")
            return False
        print(f"  ✅ [{candidate['type']}] saved to ChromaDB: {content[:60]}...")
    except Exception as e:
        print(f"  ⚠ Failed to write to ChromaDB: {e}")
        return False

    return True


def main():
    parser = argparse.ArgumentParser(description="Session Memory Extractor")
    parser.add_argument("--session-log", help="会话日志文件路径")
    parser.add_argument("--last-session", action="store_true", help="使用最近的会话日志")
    parser.add_argument("--dry-run", action="store_true", help="只查看，不写入")
    args = parser.parse_args()

    # Get session text
    session_text = ""
    if args.session_log:
        path = Path(args.session_log)
        if path.exists():
            session_text = path.read_text(encoding="utf-8")
    elif args.last_session:
        # Find most recent session log in notes/open-loops or similar
        candidates = list(ROOT.glob("notes/**/*.md")) + list(ROOT.glob("memory/transcripts/*.md"))
        if candidates:
            candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            session_text = candidates[0].read_text(encoding="utf-8")
    else:
        # Fallback: read today's memory log
        today = datetime.now().strftime("%Y-%m-%d")
        log_path = MEMORY_DIR / f"{today}.md"
        if log_path.exists():
            session_text = log_path.read_text(encoding="utf-8")
        else:
            print("⚠️ No session log found. Use --session-log or --last-session")
            return

    if not session_text:
        print("⚠️ Empty session log")
        return

    print(f"📖 Processing session log ({len(session_text)} chars)")

    # Extract candidates
    candidates = extract_candidates(session_text)

    if not candidates:
        print("  No memory-worthy content found.")
        return

    print(f"\n🔍 Found {len(candidates)} candidate memories:")
    for c in candidates:
        print(f"  [{c['type']}] {c['content'][:80]}...")

    # Save memories
    if not args.dry_run:
        print(f"\n💾 Saving memories...")

    saved = 0
    for c in candidates:
        if save_to_memory(c, dry_run=args.dry_run):
            saved += 1
        time.sleep(0.3)  # rate limit

    if args.dry_run:
        print(f"\n🔒 Dry run complete — {saved} candidates shown")
    else:
        print(f"\n✅ Extraction complete: {saved} memories saved")


if __name__ == "__main__":
    main()

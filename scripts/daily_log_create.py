#!/usr/bin/env python3
"""
每日日志自动创建 — Python 版，替代 daily_log.sh

功能：
  1. 检查当天 memory/YYYY-MM-DD.md 是否存在
  2. 不存在则创建带标准模板的文件
  3. 幂等：已存在就不碰

运行：
  python3 scripts/daily_log_create.py
"""
from datetime import date
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
MEMORY_DIR = WORKSPACE / "memory"
TODAY = date.today().strftime("%Y-%m-%d")
LOG_FILE = MEMORY_DIR / f"{TODAY}.md"


def create_daily_log() -> Path:
    """创建当天日志，返回路径"""
    content = f"""# {TODAY}

## 今日事项

## 重要决定

## 学到的教训

## 待办

"""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text(content, encoding="utf-8")
    return LOG_FILE


def main():
    if LOG_FILE.exists():
        print(f"[{TODAY}] 日志已存在，跳过: {LOG_FILE}")
        return
    path = create_daily_log()
    print(f"[{TODAY}] ✅ 日志已创建: {path}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
记忆新鲜度 — 借鉴 Claude Code memoryAge.ts

计算记忆距今天数，自动加 freshness warning（>1 天的记忆）。
"""
from datetime import datetime
from typing import Optional


def memory_age_days(mtime_epoch_ms: Optional[int] = None) -> int:
    """
    记忆距今天数。Floor-rounded — 0 = 今天，1 = 昨天，2+ = 更早。
    负值（未来时间/时钟偏差）clamp 到 0。
    """
    if mtime_epoch_ms is None:
        mtime_epoch_ms = int(datetime.now().timestamp() * 1000)
    now_ms = int(datetime.now().timestamp() * 1000)
    return max(0, (now_ms - mtime_epoch_ms) // 86_400_000)


def memory_age_str(mtime_epoch_ms: Optional[int] = None) -> str:
    """人类可读的年龄字符串。
    模型不擅长日期算术——"47 天前" 比原始 ISO 时间戳更能触发"过期"推理。
    """
    d = memory_age_days(mtime_epoch_ms)
    if d == 0:
        return "今天"
    if d == 1:
        return "昨天"
    return f"{d} 天前"


def freshness_warning(mtime_epoch_ms: Optional[int] = None) -> str:
    """
    超过 1 天的记忆的过期警告。
    今天/昨天不返（噪音）。
    
    用法：在 prompt 中注入到旧的记忆条目旁边。
    """
    d = memory_age_days(mtime_epoch_ms)
    if d <= 1:
        return ""
    return (
        f"⚠️ 这条记忆是 {d} 天前的。"
        f"记忆是某个时间点的观察，不是实时状态——"
        f"关于代码行为/文件:行号的声称可能已过期。请在断言前验证当前状态。"
    )


if __name__ == "__main__":
    import time
    now = int(time.time() * 1000)
    yesterday = now - 86_400_000
    week_ago = now - 7 * 86_400_000
    month_ago = now - 30 * 86_400_000

    print("记忆新鲜度测试:")
    for label, ts in [("今天", now), ("昨天", yesterday), ("一周前", week_ago), ("一个月前", month_ago)]:
        days = memory_age_days(ts)
        age = memory_age_str(ts)
        warn = freshness_warning(ts)
        print(f"  {label}: {days} 天, {age}")
        if warn:
            print(f"    {warn[:80]}...")

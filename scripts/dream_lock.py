#!/usr/bin/env python3
"""
Dream Lock — 防止并发记忆蒸馏

借鉴 Claude Code consolidationLock.ts：
- Lock 文件 mtime = lastConsolidatedAt
- 获取锁：写入内容 = now 的 mtime，返回之前的 mtime（用于 rollback）
- 死锁恢复：检查锁文件是否 >60 分钟，或者持有者进程是否存在

用法:
  from scripts.dream_lock import acquire_dream_lock, release_dream_lock, read_last_consolidated_at
"""
import os
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
MEMORY_DIR = ROOT / "memory"
LOCK_FILE = MEMORY_DIR / ".dream_lock"
HOLDER_STALE_MS = 60 * 60 * 1000  # 1 hour


def read_last_consolidated_at() -> float:
    """返回上次蒸馏的时间戳。无锁文件返回 0。"""
    if LOCK_FILE.exists():
        return LOCK_FILE.stat().st_mtime
    return 0.0


def acquire_dream_lock() -> Optional[float]:
    """
    获取蒸馏锁。
    返回: 之前的 mtime(用于 rollback), None = 获取失败/有人在蒸馏
    """
    now = time.time()

    # Check existing lock
    if LOCK_FILE.exists():
        mtime = LOCK_FILE.stat().st_mtime
        age_ms = (now - mtime) * 1000

        # Check if holder is stale (lock exists but too old)
        if age_ms < HOLDER_STALE_MS:
            # Active lock — someone is consolidating
            return None
        # Lock is stale — we can reclaim it

    # Write new lock (PID as content, mtime as timestamp)
    try:
        LOCK_FILE.write_text(str(os.getpid()))
        # mtime is now — this IS our timestamp
        return now
    except Exception:
        return None


def release_dream_lock(prior_mtime: Optional[float] = None) -> bool:
    """释放蒸馏锁。可选 rollback 到之前的 mtime。"""
    if prior_mtime is not None:
        # Rollback — rewind mtime so time-gate passes again
        try:
            os.utime(LOCK_FILE, (prior_mtime, prior_mtime))
        except Exception:
            pass
        return True

    # Normal release — delete lock
    try:
        LOCK_FILE.unlink()
        return True
    except Exception:
        return False


def hours_since_last_consolidation() -> float:
    """距上次蒸馏的小时数"""
    last = read_last_consolidated_at()
    if last == 0:
        return float('inf')  # never consolidated
    return (time.time() - last) / 3600


if __name__ == "__main__":
    h = hours_since_last_consolidation()
    if h == float('inf'):
        print("从未蒸馏过")
    else:
        print(f"上次蒸馏: {h:.1f} 小时前")
    print(f"锁文件: {'存在' if LOCK_FILE.exists() else '不存在'}")

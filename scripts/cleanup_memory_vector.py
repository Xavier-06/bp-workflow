#!/usr/bin/env python3
"""
向量记忆到期清理脚本

功能：
  1. 按 category+天数 清理过期条目（key_data 默认 90 天，其余 180 天）
  2. 检查 user_preferences 语义重复（用 search 逐条比对）
  3. 清理 conversations 全量（不存对话历史）

用法：
  python3 scripts/cleanup_memory_vector.py [--dry-run] [--max-age 90]
"""
import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "memory_agent"
sys.path.insert(0, str(ROOT))

from memory_store import MemoryStore

DEFAULT_MAX_DAYS = {
    "key_data": 90,
    "past_errors": 365,
    "user_preferences": 365,
    "conversations": 0,  # always clear
}

SIMILARITY_DUPE_THRESHOLD = 0.85


def cleanup_expired(ms: MemoryStore, max_age: dict, dry_run: bool = False):
    """清理超过 max_days 的条目。"""
    total_deleted = 0
    now = datetime.now()

    for cat, days in max_age.items():
        col = ms.client.get_collection(cat)
        results = col.get(include=["documents", "metadatas"])

        if not results["documents"]:
            continue

        to_delete = []
        for doc_id, doc, meta in zip(results["ids"], results["documents"], results["metadatas"]):
            ts_str = meta.get("timestamp", "") if meta else ""
            if not ts_str:
                continue
            try:
                ts = datetime.fromisoformat(ts_str)
            except ValueError:
                continue

            if days == 0:
                # conversations: always delete
                to_delete.append(doc_id)
                continue

            age = (now - ts).days
            if age > days:
                to_delete.append(doc_id)
                label = f"  🗑️ [{cat}] expired({age}d): '{doc[:60]}...'"
                print(label)

        if to_delete:
            total_deleted += len(to_delete)
            if not dry_run:
                col.delete(ids=to_delete)
            print(f"  → [{'DRY RUN' if dry_run else 'DELETED'}] {len(to_delete)} items from {cat}")

    if total_deleted == 0:
        print("✅ 无过期条目")
    else:
        print(f"\n📊 Total {'would delete' if dry_run else 'deleted'}: {total_deleted}")


def dedup_preferences(ms: MemoryStore, dry_run: bool = False):
    """检查 user_preferences 语义重复。"""
    col = ms.client.get_collection("user_preferences")
    results = col.get(include=["documents", "metadatas"])

    if len(results["documents"]) < 2:
        print("✅ user_preferences 条目太少，无需去重")
        return

    deleted = 0
    for i, (doc_a, meta_a) in enumerate(zip(results["documents"], results["metadatas"])):
        similar = ms.search(doc_a, top_k=2, categories=["user_preferences"])
        for s in similar:
            if s["content"] == doc_a:
                continue  # same
            if s["score"] >= SIMILARITY_DUPE_THRESHOLD:
                # Find doc_a's ID
                doc_a_id = results["ids"][i]
                doc_b_score = s["score"]
                print(f"  ⚠️  语义重复 (score={doc_b_score:.2f})：")
                print(f"    A: '{doc_a[:60]}...'")
                print(f"    B: '{s['content'][:60]}...'")
                # Keep the one with later timestamp
                ts_a = meta_a.get("timestamp", "") if meta_a else ""
                ts_b = s["metadata"].get("timestamp", "") if s["metadata"] else ""
                if ts_a >= ts_b:
                    delete_id = s.get("metadata", {}).get("id", "")
                    if delete_id:
                        print(f"    → Delete B (older)")
                        if not dry_run:
                            col.delete(ids=[delete_id])
                            deleted += 1
                    else:
                        # Can't find ID from search result, skip
                        print(f"    → Cannot locate ID, skip")
                else:
                    print(f"    → Delete A (older): {doc_a_id}")
                    if not dry_run:
                        col.delete(ids=[doc_a_id])
                        deleted += 1
                break  # one match is enough

    if deleted > 0:
        print(f"\n📊 Deduped {deleted} items from user_preferences")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="预览不删除")
    ap.add_argument("--max-age", type=int, default=None, help="override max age for key_data")
    args = ap.parse_args()

    ms = MemoryStore()
    max_age = dict(DEFAULT_MAX_DAYS)
    if args.max_age:
        max_age["key_data"] = args.max_age

    print(f"=== 向量记忆到期清理 {'[DRY RUN]' if args.dry_run else ''} ===")
    print(f"  key_data: {max_age['key_data']}d | prefs: {max_age['user_preferences']}d | errors: {max_age['past_errors']}d\n")

    cleanup_expired(ms, max_age, dry_run=args.dry_run)

    print(f"\n=== 语义检查 ===")
    dedup_preferences(ms, dry_run=args.dry_run)

    print(f"\n=== Final Stats ===")
    for cat in ["user_preferences", "past_errors", "key_data"]:
        c = ms.client.get_collection(cat)
        print(f"  {cat}: {c.count()}")


if __name__ == "__main__":
    main()

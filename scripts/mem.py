#!/usr/bin/env python3
"""
mem.py - 统一记忆 CLI（使用主 venv，连接 memory_agent/memory_db）
用法:
  python3 scripts/mem.py search "腾讯财务"
  python3 scripts/mem.py add "内容" --type data_points
  python3 scripts/mem.py stats
  python3 scripts/mem.py add-error "错误描述"
"""
from __future__ import annotations
import sys, json, argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from memory.memory_bridge import search_memory, add_memory, get_memory_stats, get_bridge

CATEGORY_MAP = {
    'preferences': 'user_preferences',
    'errors': 'past_errors',
    'data_points': 'key_data',
    'conversations': 'conversations',
}


def cmd_search(query: str, top_k: int = 5):
    results = search_memory(query, top_k=top_k)
    if not results:
        print(json.dumps([], ensure_ascii=False))
        return
    for r in results:
        print(f"[{r['score']:.2f}] [{r['category']}] {r['content']}")


def cmd_add(content: str, memory_type: str = 'preferences', metadata: dict = None):
    category = CATEGORY_MAP.get(memory_type, 'user_preferences')
    doc_id = add_memory(content, category=category, metadata=metadata or {})
    if doc_id is None:
        print(json.dumps({'id': None, 'status': 'duplicate', 'category': category}, ensure_ascii=False))
    else:
        print(json.dumps({'id': doc_id, 'status': 'added', 'category': category}, ensure_ascii=False))


def cmd_stats():
    stats = get_memory_stats()
    print(json.dumps(stats, ensure_ascii=False, indent=2))


def cmd_list(memory_type: str = None):
    bridge = get_bridge()
    if not bridge.is_available():
        print(json.dumps({'error': bridge._error}, ensure_ascii=False))
        return
    cat = CATEGORY_MAP.get(memory_type, memory_type) if memory_type else None
    cols = [cat] if cat else list(bridge._collections.keys())
    for col_name in cols:
        col = bridge._collections.get(col_name)
        if not col or col.count() == 0:
            continue
        res = col.get(limit=20, include=['documents', 'metadatas'])
        print(f'\n=== {col_name} ({col.count()} items) ===')
        for doc, meta in zip(res['documents'], res['metadatas']):
            ts = meta.get('created_at', meta.get('timestamp', ''))[:10]
            print(f'  [{ts}] {doc[:120]}')


def cmd_add_error(description: str):
    doc_id = add_memory(description, category='past_errors', metadata={'type': 'error'})
    if doc_id is None:
        print(json.dumps({'id': None, 'status': 'duplicate', 'category': 'past_errors'}, ensure_ascii=False))
    else:
        print(json.dumps({'id': doc_id, 'status': 'added', 'category': 'past_errors'}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description='Memory CLI - 统一向量记忆接口')
    sub = parser.add_subparsers(dest='cmd')

    p = sub.add_parser('search', help='检索记忆')
    p.add_argument('query')
    p.add_argument('--top-k', '-k', type=int, default=5)

    p = sub.add_parser('add', help='添加记忆')
    p.add_argument('content')
    p.add_argument('--type', '-t', default='preferences',
                   choices=['preferences', 'errors', 'data_points', 'conversations'])

    p = sub.add_parser('add-error', help='记录错误教训')
    p.add_argument('description')

    sub.add_parser('stats', help='查看统计')
    sub.add_parser('list', help='列出所有记忆').add_argument(
        '--type', '-t', choices=['preferences', 'errors', 'data_points', 'conversations'], default=None)

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        return

    if args.cmd == 'search':
        cmd_search(args.query, args.top_k)
    elif args.cmd == 'add':
        cmd_add(args.content, args.type)
    elif args.cmd == 'add-error':
        cmd_add_error(args.description)
    elif args.cmd == 'stats':
        cmd_stats()
    elif args.cmd == 'list':
        cmd_list(getattr(args, 'type', None))


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Memory system bridge — 统一 ChromaDB 向量库接口

修复记录 (2026-04-03):
  - 修正 sys.path 指向 memory_agent/ (旧版指向已废弃的 memory_system/)
  - memory_agent/memory_store.py (17KB) 为最新，memory_system/ (6KB) 已废弃
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEMORY_AGENT = ROOT / 'memory_agent'
ENV_FILE = ROOT / '.credentials' / 'investment-research.env'

# load env file if present
if ENV_FILE.exists():
    for line in ENV_FILE.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

sys.path.insert(0, str(MEMORY_AGENT))

from memory_store import MemoryStore  # type: ignore
from instruction_store import InstructionStore  # type: ignore
from work_log import WorkLog  # type: ignore

CATEGORY_MAP = {
    'preferences': 'user_preferences',
    'errors': 'past_errors',
    'data_points': 'key_data',
    'conversations': 'conversations',
}


def cmd_search(query: str, top_k: int = 5):
    store = MemoryStore()
    results = store.search(query, top_k=top_k)
    print(json.dumps(results, ensure_ascii=False, indent=2))


def cmd_add(content: str, memory_type: str = 'preferences'):
    store = MemoryStore()
    category = CATEGORY_MAP.get(memory_type, 'user_preferences')
    doc_id = store.add_memory(content, category=category)
    if doc_id is None:
        print(json.dumps({'id': None, 'status': 'duplicate', 'backend': 'memory_agent'}, ensure_ascii=False))
    else:
        print(json.dumps({'id': doc_id, 'status': 'added', 'backend': 'memory_agent'}, ensure_ascii=False))


def cmd_stats():
    store = MemoryStore()
    print(json.dumps(store.get_stats(), ensure_ascii=False, indent=2))


def cmd_agents():
    store = InstructionStore()
    print(json.dumps(store.list_all(), ensure_ascii=False, indent=2))


def cmd_context():
    wl = WorkLog()
    print(json.dumps({
        'active_context': wl.get_active_context(),
        'todos': wl.get_todos(),
    }, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser(description='Memory system bridge CLI')
    sub = ap.add_subparsers(dest='command')

    s = sub.add_parser('search')
    s.add_argument('query')
    s.add_argument('--top-k', '-k', type=int, default=5)

    a = sub.add_parser('add')
    a.add_argument('content')
    a.add_argument('--type', '-t', default='preferences', choices=['preferences', 'errors', 'data_points', 'conversations'])

    sub.add_parser('stats')
    sub.add_parser('agents')
    sub.add_parser('context')

    args = ap.parse_args()
    if args.command == 'search':
        cmd_search(args.query, args.top_k)
    elif args.command == 'add':
        cmd_add(args.content, args.type)
    elif args.command == 'stats':
        cmd_stats()
    elif args.command == 'agents':
        cmd_agents()
    elif args.command == 'context':
        cmd_context()
    else:
        ap.print_help()
        raise SystemExit(1)


if __name__ == '__main__':
    main()

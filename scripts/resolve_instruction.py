#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEMORY_AGENT = ROOT / 'memory_agent'
sys.path.insert(0, str(MEMORY_AGENT))

from instruction_store import InstructionStore  # type: ignore


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest='cmd')

    l = sp.add_parser('list')

    g = sp.add_parser('get')
    g.add_argument('key')
    g.add_argument('--text-only', action='store_true')

    m = sp.add_parser('match')
    m.add_argument('query')
    m.add_argument('--top-k', type=int, default=3)

    e = sp.add_parser('export')
    e.add_argument('keys', nargs='+')

    args = ap.parse_args()
    store = InstructionStore()

    if args.cmd == 'list':
        print(json.dumps(store.list_all(), ensure_ascii=False, indent=2))
    elif args.cmd == 'get':
        if args.text_only:
            print(store.get_instruction_text(args.key))
        else:
            inst = store.get_instruction(args.key)
            if not inst:
                raise SystemExit(f'Instruction not found: {args.key}')
            print(json.dumps(inst, ensure_ascii=False, indent=2))
    elif args.cmd == 'match':
        print(json.dumps(store.match_by_keywords(args.query)[:args.top_k], ensure_ascii=False, indent=2))
    elif args.cmd == 'export':
        print(store.export_for_prompt(args.keys))
    else:
        ap.print_help()
        raise SystemExit(1)


if __name__ == '__main__':
    main()

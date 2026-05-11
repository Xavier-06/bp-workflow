#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'memory_agent'))

from instruction_store import InstructionStore  # type: ignore


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('query', nargs='?', default='')
    ap.add_argument('--key')
    ap.add_argument('--top-k', type=int, default=3)
    ap.add_argument('--full', action='store_true')
    args = ap.parse_args()

    store = InstructionStore()
    if args.key:
        inst = store.get_instruction(args.key)
        if not inst:
            raise SystemExit(f'Instruction not found: {args.key}')
        payload = {'selected': [{'key': args.key, **inst}]}
    else:
        matches = store.match_by_keywords(args.query)
        payload = {'selected': matches[:args.top_k]}

    if not args.full:
        slim = []
        for item in payload['selected']:
            slim.append({
                'key': item.get('key'),
                'name': item.get('name'),
                'industry': item.get('industry'),
                'role': item.get('role'),
                'description': item.get('description'),
                'keywords': item.get('keywords', []),
                'instruction_length': len(item.get('instruction', '')),
                'score': item.get('score'),
            })
        payload = {'selected': slim}

    print(json.dumps(payload, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()

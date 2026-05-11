#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / 'config' / 'ir-runtime.json'

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--field')
    args = ap.parse_args()
    data = json.loads(CFG.read_text(encoding='utf-8'))
    if args.json or not args.field:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    cur = data
    for part in args.field.split('.'):
        cur = cur[part]
    if isinstance(cur, (dict, list)):
        print(json.dumps(cur, ensure_ascii=False, indent=2))
    else:
        print(cur)

if __name__ == '__main__':
    main()

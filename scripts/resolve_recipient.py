#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / 'config' / 'recipients.json'

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('alias')
    ap.add_argument('--field', choices=['channel', 'target', 'display_name', 'notes'], default='target')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    if not CONFIG.exists():
        print(f'❌ 配置文件不存在: {CONFIG}', file=sys.stderr)
        print('请创建 recipients.json 或通过 .env 配置通知目标', file=sys.stderr)
        raise SystemExit(1)

    data = json.loads(CONFIG.read_text(encoding='utf-8'))
    rec = data.get('recipients', {}).get(args.alias)
    if not rec:
        print(f'Unknown recipient alias: {args.alias}', file=sys.stderr)
        raise SystemExit(1)
    if args.json:
        print(json.dumps(rec, ensure_ascii=False, indent=2))
    else:
        print(rec.get(args.field, ''))

if __name__ == '__main__':
    main()

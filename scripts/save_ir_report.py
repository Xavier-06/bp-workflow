#!/usr/bin/env python3
from __future__ import annotations
import argparse, shutil, json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT/'reports'
ARTIFACTS = ROOT/'data'/'tasks'
REPORTS.mkdir(parents=True, exist_ok=True)
ARTIFACTS.mkdir(parents=True, exist_ok=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('source')
    ap.add_argument('--title', required=True)
    ap.add_argument('--kind', default='memo', choices=['memo','report','brief','review'])
    args = ap.parse_args()
    src = Path(args.source)
    if not src.exists():
        raise SystemExit(f'source not found: {src}')
    stamp = datetime.now().strftime('%Y-%m-%d')
    ext = src.suffix or '.md'
    safe_title = args.title.replace('/', '-').strip()
    dst = REPORTS / f'{safe_title}_{stamp}{ext}'
    shutil.copy2(src, dst)
    print(json.dumps({'saved_to': str(dst), 'kind': args.kind}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()

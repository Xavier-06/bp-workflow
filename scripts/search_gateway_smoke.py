#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from search.gateway import search


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('task_type')
    ap.add_argument('query')
    ap.add_argument('--market', default='generic')
    ap.add_argument('--ticker', default='')
    ap.add_argument('--company', default='')
    ap.add_argument('--max-results', type=int, default=5)
    ap.add_argument('--no-full-text', action='store_true')
    args = ap.parse_args()
    rows = search(
        task_type=args.task_type,
        query=args.query,
        market=args.market,
        ticker=args.ticker,
        company=args.company,
        max_results=args.max_results,
        need_full_text=not args.no_full_text,
    )
    print(json.dumps([r.to_dict() for r in rows], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

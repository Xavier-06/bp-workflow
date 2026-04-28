#!/usr/bin/env python3
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from search_gateway import search, verify_engines

QUERIES = [
    '江苏立卓信息技术有限公司',
    '立卓信息 射阳大米集团',
    '智慧农业 竞品 2025',
    'smart agriculture listed companies china',
    'Top Cloud-Agri competitor',
]


def relevance_score(q: str, rows: list[dict]) -> int:
    q_tokens = [t.lower() for t in q.replace('-', ' ').split() if len(t) >= 2]
    score = 0
    for r in rows[:3]:
        text = ((r.get('title','') + ' ' + r.get('content','') + ' ' + r.get('url','')).lower())
        hits = sum(1 for t in q_tokens if t in text)
        score += hits
    return score


def main() -> int:
    report = {'verify': verify_engines(), 'results': []}
    bad = 0
    for q in QUERIES:
        rows = search(q, max_results=5)
        score = relevance_score(q, rows)
        item = {
            'query': q,
            'count': len(rows),
            'score': score,
            'top3': [
                {'title': r.get('title',''), 'url': r.get('url',''), 'engine': r.get('engine','')}
                for r in rows[:3]
            ],
            'pass': len(rows) >= 3 and score >= 2,
        }
        if not item['pass']:
            bad += 1
        report['results'].append(item)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if bad == 0 else 2

if __name__ == '__main__':
    raise SystemExit(main())

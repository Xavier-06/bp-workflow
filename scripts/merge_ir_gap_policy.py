#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'


def load_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def confidence(item: dict) -> str:
    score = 0
    if item.get('url'):
        score += 1
    if item.get('scrapling_excerpt') and len(item['scrapling_excerpt']) >= 120:
        score += 1
    if any(x in (item.get('url') or '').lower() for x in ['gov', 'edu', 'people.com', 'stpi', 'kpmg', 'lek.com']):
        score += 1
    if any(x in (item.get('title') or '') for x in ['政策', '监管', '指引', '意见', '标准']):
        score += 1
    return 'high' if score >= 3 else 'medium' if score >= 2 else 'low'


def normalize_policy_rows(rows: list[dict]) -> list[dict]:
    out = []
    seen = set()
    for item in rows:
        key = item.get('url') or item.get('title')
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({
            'section': '政策 / 技术变化',
            'source_title': item.get('title', ''),
            'claim': item.get('content', ''),
            'evidence_excerpt': item.get('scrapling_excerpt', '')[:400],
            'source_url': item.get('url', ''),
            'source_type': 'pdf' if '.pdf' in (item.get('url', '')).lower() else 'web',
            'confidence': confidence(item),
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('evidence_json')
    ap.add_argument('gap_policy_json')
    args = ap.parse_args()

    evidence_path = Path(args.evidence_json)
    gap_path = Path(args.gap_policy_json)
    evidence = load_json(evidence_path)
    gap = load_json(gap_path)
    task_id = evidence.get('task_id')

    existing = evidence.get('rows', [])
    policy_extra = normalize_policy_rows(gap.get('rows', []))

    seen = {(r.get('source_title'), r.get('source_url')) for r in existing}
    merged = existing[:]
    added = 0
    for row in policy_extra:
        key = (row.get('source_title'), row.get('source_url'))
        if key in seen:
            continue
        merged.append(row)
        seen.add(key)
        added += 1

    out = {'task_id': task_id, 'rows': merged}
    out_path = TASKS_DIR / f'{task_id}-evidence-v2.json'
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'task_id': task_id, 'output': str(out_path), 'added_policy_rows': added, 'total_rows': len(merged)}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()

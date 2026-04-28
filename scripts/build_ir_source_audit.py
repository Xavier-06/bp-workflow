#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
TASKS = ROOT / 'data' / 'tasks'

ESTIMATE_HINTS = ['预计', '预期', '假设', '推算', '估算', '可能', '或将']


def classify(row: dict) -> str:
    claim = (row.get('claim') or '').strip()
    url = (row.get('source_url') or '').strip()
    if not url.startswith('http'):
        return 'process_or_query'
    if any(k in claim for k in ESTIMATE_HINTS):
        return 'estimate_or_inference'
    return 'retrieved_fact'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('task_id')
    args = ap.parse_args()

    evidence_json = TASKS / f'{args.task_id}-evidence.json'
    if not evidence_json.exists():
        raise SystemExit(f'evidence not found: {evidence_json}')

    data = json.loads(evidence_json.read_text(encoding='utf-8'))
    rows = data.get('rows', [])

    out_rows = []
    counts = {'retrieved_fact': 0, 'estimate_or_inference': 0, 'process_or_query': 0}
    for i, r in enumerate(rows, start=1):
        t = classify(r)
        counts[t] += 1
        out_rows.append({
            'idx': i,
            'section': r.get('section', ''),
            'classification': t,
            'claim': (r.get('claim') or '').strip(),
            'source_title': (r.get('source_title') or '').strip(),
            'source_url': (r.get('source_url') or '').strip(),
            'confidence': r.get('confidence', ''),
            'fetched_at': datetime.fromtimestamp(evidence_json.stat().st_mtime).isoformat(timespec='seconds'),
        })

    out_json = TASKS / f'{args.task_id}-source-audit.json'
    out_md = TASKS / f'{args.task_id}-source-audit.md'

    payload = {
        'task_id': args.task_id,
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'counts': counts,
        'rows': out_rows,
        'policy': {
            'retrieved_fact': '有可追溯URL的检索事实（不代表真实性已终审）',
            'estimate_or_inference': '带有假设/推算/预期语义的内容',
            'process_or_query': '流程说明、待补问题、查询模板残留，不能当事实结论',
        }
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    lines = [
        f'# Source Audit - {args.task_id}',
        '',
        f"- generated_at: {payload['generated_at']}",
        f"- retrieved_fact: {counts['retrieved_fact']}",
        f"- estimate_or_inference: {counts['estimate_or_inference']}",
        f"- process_or_query: {counts['process_or_query']}",
        '',
        '| # | section | classification | claim | source | confidence |',
        '|---|---|---|---|---|---|',
    ]

    for r in out_rows:
        claim = (r['claim'] or '').replace('|', ' ')[:120]
        source = (r['source_title'] or r['source_url'] or '').replace('|', ' ')[:80]
        lines.append(f"| {r['idx']} | {r['section']} | {r['classification']} | {claim} | {source} | {r['confidence']} |")

    out_md.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({'task_id': args.task_id, 'source_audit_json': str(out_json), 'source_audit_md': str(out_md), 'counts': counts}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

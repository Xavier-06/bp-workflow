#!/usr/bin/env python3
"""
BP 交付前硬门禁

检查：
- phase4_dispatch.json status=done
- 4 个 phase4 输出齐全且每份>=500字
- 每份至少 2 个 URL
- 总 URL >= 8
- bp_verify_result.json 不是 FAIL

不通过则禁止 Phase5 继续。
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
TASKS_DIR = WORKSPACE / 'tasks'

FILES = [
    'bp_step4_team.md',
    'bp_step4_tech.md',
    'bp_step4_industry.md',
    'bp_step4_competition.md',
]


def run(task_id: str) -> dict:
    task_dir = TASKS_DIR / task_id
    issues = []
    metrics = {}

    dispatch_path = task_dir / 'phase4_dispatch.json'
    if not dispatch_path.exists():
        issues.append('missing phase4_dispatch.json')
    else:
        dispatch = json.loads(dispatch_path.read_text(encoding='utf-8'))
        metrics['dispatch_status'] = dispatch.get('status')
        if dispatch.get('status') != 'done':
            issues.append(f"phase4_dispatch status != done ({dispatch.get('status')})")

    total_urls = 0
    per_file = {}
    for name in FILES:
        fp = task_dir / name
        if not fp.exists():
            issues.append(f'missing {name}')
            continue
        text = fp.read_text(encoding='utf-8')
        length = len(text.strip())
        urls = len(re.findall(r'https?://', text))
        per_file[name] = {'length': length, 'url_count': urls}
        total_urls += urls
        if length < 500:
            issues.append(f'{name} too short ({length})')
        if urls < 2:
            issues.append(f'{name} citations too few ({urls})')

    metrics['files'] = per_file
    metrics['total_urls'] = total_urls
    if total_urls < 8:
        issues.append(f'total citations too few ({total_urls})')

    verify_path = task_dir / 'bp_verify_result.json'
    if verify_path.exists():
        verify = json.loads(verify_path.read_text(encoding='utf-8'))
        metrics['verify_verdict'] = verify.get('verdict')
        if verify.get('verdict') == 'FAIL':
            issues.append('bp_verify_result verdict=FAIL')
    else:
        issues.append('missing bp_verify_result.json')

    verdict = 'PASS' if not issues else 'FAIL'
    result = {
        'task_id': task_id,
        'verdict': verdict,
        'issues': issues,
        'metrics': metrics,
    }
    out = task_dir / 'bp_delivery_gate.json'
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--task-id', required=True)
    args = ap.parse_args()
    result = run(args.task_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['verdict'] == 'PASS' else 2)


if __name__ == '__main__':
    main()

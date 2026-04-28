#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
TASKS = ROOT / 'data' / 'tasks'

HOOKS = [
    'search-plan-review',
    'clean-evidence-review',
    'analysis-writer-polish',
]


def hook_spawn_receipt(task_id: str, hook: str) -> Path:
    return TASKS / f'{task_id}-{hook}-spawn.json'


def load_json(path: Path, default=None):
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return default


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('task_id')
    args = ap.parse_args()

    pkg_path = TASKS / f'{args.task_id}.json'
    manifest_path = TASKS / f'{args.task_id}-execution-manifest.json'

    if not pkg_path.exists():
        raise SystemExit(f'task package not found: {pkg_path}')

    pkg = json.loads(pkg_path.read_text(encoding='utf-8'))
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}

    instruction_keys = pkg.get('instruction_keys', [])
    model_route = pkg.get('model_route', {})
    events = manifest.get('events', [])

    receipts = []
    for hook in HOOKS:
        path = hook_spawn_receipt(args.task_id, hook)
        data = load_json(path, {}) or {}
        if isinstance(data, dict) and (data.get('childSessionKey') or data.get('runId')):
            receipts.append({
                'hook': hook,
                'path': str(path),
                'label': data.get('label'),
                'childSessionKey': data.get('childSessionKey'),
                'runId': data.get('runId'),
                'status': data.get('status'),
                'runtime': data.get('runtime', 'subagent'),
            })

    out_json = TASKS / f'{args.task_id}-execution-audit.json'
    out_md = TASKS / f'{args.task_id}-execution-audit.md'

    multi_agent = len(receipts) > 0
    payload = {
        'task_id': args.task_id,
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'multi_agent_real_collab': multi_agent,
        'execution_mode': manifest.get('execution_mode', 'single-orchestrator-script-pipeline'),
        'model_route': model_route,
        'instruction_keys_loaded': instruction_keys,
        'events_count': len(events),
        'events': events,
        'subagent_spawn_receipts': receipts,
        'valuation_execution': {
            'independent_agent_session': any(r.get('hook') in ('clean-evidence-review', 'analysis-writer-polish') for r in receipts),
            'executor': 'subagent sessions + script pipeline' if multi_agent else 'main orchestrator script pipeline',
            'model': model_route.get('preferred_model', 'unknown'),
            'note': '已检测到真实 subagent spawn receipt。' if multi_agent else '本轮未生成带 childSessionKey/runId 的真实 subagent 派发证据。'
        }
    }

    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    lines = [
        f'# Execution Audit - {args.task_id}',
        '',
        f"- generated_at: {payload['generated_at']}",
        f"- execution_mode: {payload['execution_mode']}",
        f"- multi_agent_real_collab: {payload['multi_agent_real_collab']}",
        f"- preferred_model: {model_route.get('preferred_model', 'unknown')}",
        f"- fallback_model: {model_route.get('fallback_model', 'unknown')}",
        '',
        '## Instruction Keys Loaded',
    ]

    for k in instruction_keys:
        lines.append(f'- {k}')

    lines += [
        '',
        '## Real Subagent Spawn Receipts',
    ]
    if receipts:
        for r in receipts:
            lines.append(f"- {r['hook']} | childSessionKey={r.get('childSessionKey')} | runId={r.get('runId')} | label={r.get('label')}")
    else:
        lines.append('- none')

    lines += [
        '',
        '## 估值/预测执行披露',
        f"- independent_agent_session: {payload['valuation_execution']['independent_agent_session']}",
        f"- executor: {payload['valuation_execution']['executor']}",
        f"- model: {payload['valuation_execution']['model']}",
        f"- note: {payload['valuation_execution']['note']}",
        '',
        '## Execution Timeline (from manifest)',
        '| at | type | action | status | elapsed_s |',
        '|---|---|---|---|---|',
    ]

    for e in events:
        lines.append(f"| {e.get('at','')} | {e.get('type','')} | {e.get('action','')} | {e.get('status','')} | {e.get('elapsed_s','')} |")

    out_md.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({
        'task_id': args.task_id,
        'execution_audit_json': str(out_json),
        'execution_audit_md': str(out_md),
        'events': len(events),
        'real_subagent_receipts': len(receipts),
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

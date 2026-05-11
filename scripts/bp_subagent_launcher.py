#!/usr/bin/env python3
"""
BP Phase 4 Subagent Launcher

真正把 phase4_dispatch.json 里的 4 个 BP 子代理发出去，生成 spawn receipt，
供 run_bp_pipeline.py --auto 直接调用。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'tasks'

ROLE_TO_KEY = {
    'bp_团队与合规': 'team',
    'bp_技术与产品': 'tech',
    'bp_行业与供应链': 'industry',
    'bp_竞争与结论': 'competition',
}


def _slug(role_name: str) -> str:
    return ROLE_TO_KEY.get(role_name, role_name.replace('bp_', '').replace('与', '_').replace(' ', '_'))


def _build_brief(task_id: str, dispatch: dict, sub: dict) -> Path:
    task_dir = TASKS_DIR / task_id
    slug = _slug(sub['role_name'])
    brief_path = task_dir / f'bp_phase4_brief_{slug}.md'

    lines = [
        f'# BP Phase4 Brief — {sub["role_name"]}',
        '',
        f'- Task ID: {task_id}',
        f'- Output file: `{Path(sub["output_file"]).relative_to(ROOT)}`',
        '',
        '## 你的任务',
        '- 严格围绕你负责的维度完成尽调分析。',
        '- 必须自行补充外部搜索验证。',
        '- 最终输出必须包含：事实、判断、Red Flags、至少 3 个来源 URL。',
        '- 禁止写内部术语：子代理、dispatch、Phase、handoff、Step 0/1/2/3/4/5。',
        '- 直接把最终 Markdown 写到指定 output file。',
        '',
        '## 角色说明',
        sub.get('description', ''),
        '',
        '## 关键输入文件（都在 workspace 内）',
    ]

    candidates = [
        task_dir / 'bp_ocr_text.txt',
        task_dir / 'bp_step0_profile.json',
        task_dir / 'bp_step0_profile.md',
        task_dir / 'company_verify_report.json',
        task_dir / 'bp_gap_report.json',
        task_dir / 'bp_presearch_results.json',
    ]
    candidates += sorted(task_dir.glob('bp_presearch_step*.md'))
    candidates += sorted(task_dir.glob('bp_gap_driven_round*.md'))
    candidates += sorted((task_dir / 'body_content').glob('*.json')) if (task_dir / 'body_content').exists() else []

    for p in candidates:
        if p.exists():
            lines.append(f'- `{p.relative_to(ROOT)}`')

    lines += [
        '',
        '## 子任务键值输入',
        '```json',
        json.dumps(sub.get('key_inputs', {}), ensure_ascii=False, indent=2),
        '```',
        '',
        '## 执行要求',
        '- 先读 OCR / Step0 / 工商验证 / Gap 报告，再补搜索。',
        '- 你的外部判断必须和来源一一对应。',
        '- 如果某点搜不到，要明确写“未找到独立外部证据”，不要编。',
    ]

    brief_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return brief_path


def _spawn_one(task_id: str, sub: dict) -> dict:
    task_dir = TASKS_DIR / task_id
    slug = _slug(sub['role_name'])
    output_path = Path(sub['output_file'])
    receipt_path = task_dir / f'bp_phase4_spawn_{slug}.json'

    if output_path.exists() and output_path.stat().st_size > 50:
        return {'role': sub['role_name'], 'status': 'already_exists', 'output': str(output_path)}

    brief_path = _build_brief(task_id, {}, sub)
    label = f'{task_id}-bp-phase4-{slug}'
    rel_brief = str(brief_path.relative_to(ROOT))
    rel_output = str(output_path.relative_to(ROOT))
    rel_receipt = str(receipt_path.relative_to(ROOT))

    child_task = (
        f'You are the BP phase4 analyst for role {sub["role_name"]} on task {task_id}. '
        f'Read the brief at `{rel_brief}` and follow it exactly. '
        f'Write your final markdown to `{rel_output}`. '
        f'Your markdown MUST include at least 3 source URLs and substantial analysis. '
        f'Do not modify any other files.'
    )

    message = (
        f'Use the sessions_spawn tool exactly once with runtime "subagent", mode "run", cleanup "keep", '
        f'thinking "high", label "{label}", and task "{child_task}". '
        f'After the tool returns accepted, write a JSON file to `{rel_receipt}` containing keys '
        f'task_id, role, label, status, runId, childSessionKey, runtime, thinking. '
        f'Set runtime to "subagent", thinking to "high". Then stop.'
    )

    cmd = [
        'openclaw', 'agent', '--agent', 'main',
        '--thinking', 'high', '--timeout', '120', '--json',
        '--message', message,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        return {
            'role': sub['role_name'],
            'status': 'spawn_failed',
            'error': (proc.stderr or proc.stdout or '')[:500],
        }

    if not receipt_path.exists():
        return {'role': sub['role_name'], 'status': 'receipt_missing'}

    try:
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    except Exception as e:
        return {'role': sub['role_name'], 'status': 'receipt_invalid', 'error': str(e)}

    if not (receipt.get('childSessionKey') or receipt.get('runId')):
        return {'role': sub['role_name'], 'status': 'receipt_invalid', 'error': 'missing childSessionKey/runId'}

    return {
        'role': sub['role_name'],
        'status': 'spawned',
        'label': label,
        'runId': receipt.get('runId'),
        'childSessionKey': receipt.get('childSessionKey'),
        'output': str(output_path),
        'receipt': str(receipt_path),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--task-id', required=True)
    args = ap.parse_args()

    task_dir = TASKS_DIR / args.task_id
    dispatch_path = task_dir / 'phase4_dispatch.json'
    if not dispatch_path.exists():
        print(json.dumps({'status': 'no_dispatch', 'task_id': args.task_id}, ensure_ascii=False))
        raise SystemExit(1)

    dispatch = json.loads(dispatch_path.read_text(encoding='utf-8'))
    subs = dispatch.get('subagents', [])
    results = []
    for sub in subs:
        results.append(_spawn_one(args.task_id, sub))
        time.sleep(1)

    ok = all(r.get('status') in ('spawned', 'already_exists') for r in results)
    print(json.dumps({'task_id': args.task_id, 'status': 'ok' if ok else 'partial', 'results': results}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if ok else 2)


if __name__ == '__main__':
    main()

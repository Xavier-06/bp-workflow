#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'

ARTIFACT_ORDER = [
    'package',
    'brief',
    'runner',
    'subtasks',
    'subtask_scope',
    'subtask_data',
    'subtask_industry',
    'search_plan',
    'packet',
    'packet_filled',
    'evidence',
    'reviewer',
    'evidence_clean',
    'analysis',
    'final_memo',
    'final_memo_instruction_guided',
]


def p(task_id: str, suffix: str) -> Path:
    return TASKS_DIR / f'{task_id}{suffix}'


def build_manifest(task_id: str) -> dict:
    files = {
        'package': p(task_id, '.json'),
        'brief': p(task_id, '-brief.md'),
        'runner': p(task_id, '-runner.md'),
        'subtasks': p(task_id, '-subtasks.json'),
        'subtask_scope': p(task_id, '-S01.md'),
        'subtask_data': p(task_id, '-S02.md'),
        'subtask_industry': p(task_id, '-S03.md'),
        'search_plan': p(task_id, '-S02-search-plan.json'),
        'packet': p(task_id, '-S02-packet.md'),
        'packet_filled': p(task_id, '-S02-packet-filled.md'),
        'evidence': p(task_id, '-evidence.json'),
        'reviewer': p(task_id, '-reviewer.json'),
        'evidence_clean': p(task_id, '-evidence-clean.json'),
        'analysis': p(task_id, '-analysis-draft.md'),
        'final_memo': p(task_id, '-final-memo.md'),
        'final_memo_instruction_guided': p(task_id, '-final-memo-instruction-guided.md'),
    }

    artifacts = {}
    completed = []
    missing = []
    for key, path in files.items():
        exists = path.exists()
        artifacts[key] = {'path': str(path), 'exists': exists}
        if exists:
            completed.append(key)
        else:
            missing.append(key)

    status = 'closed-draft' if not missing else 'incomplete'
    return {
        'task_id': task_id,
        'status': status,
        'completed_count': len(completed),
        'missing_count': len(missing),
        'completed': completed,
        'missing': missing,
        'artifacts': artifacts,
        'next_recommended_steps': [
            '把 final memo 再做一轮 polish，压长句和原文味',
            '把风险催化表和移交说明单独结构化输出',
            '让子任务自动接力推进，而不是只在主会话里手动推进',
        ]
    }


def render_md(manifest: dict) -> str:
    lines = [
        f"# IR Runner Bundle - {manifest['task_id']}",
        '',
        f"- 状态：{manifest['status']}",
        f"- 已完成产物：{manifest['completed_count']}",
        f"- 缺失产物：{manifest['missing_count']}",
        '',
        '## 已完成产物',
    ]
    for key in manifest['completed']:
        lines.append(f"- {key} -> {manifest['artifacts'][key]['path']}")
    lines += ['', '## 缺失产物']
    if manifest['missing']:
        for key in manifest['missing']:
            lines.append(f"- {key}")
    else:
        lines.append('- 无')
    lines += ['', '## 下一步建议']
    for item in manifest['next_recommended_steps']:
        lines.append(f'- {item}')
    return '\n'.join(lines) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('task_id')
    args = ap.parse_args()
    manifest = build_manifest(args.task_id)
    json_path = TASKS_DIR / f'{args.task_id}-bundle.json'
    md_path = TASKS_DIR / f'{args.task_id}-bundle.md'
    json_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    md_path.write_text(render_md(manifest), encoding='utf-8')
    print(json.dumps({'task_id': args.task_id, 'bundle_json': str(json_path), 'bundle_md': str(md_path), 'status': manifest['status'], 'completed_count': manifest['completed_count'], 'missing_count': manifest['missing_count']}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()

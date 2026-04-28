#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'

HOOKS = {
    'search-plan-review': {
        'role': 'builder_search',
        'title': 'Search-plan review',
        'goal': '检查 search plan 是否对题，必要时直接修订原 search plan 文件，然后给出通过/不通过结论。',
        'inputs': ['package', 'search_plan'],
        'result_kind': 'json',
    },
    'clean-evidence-review': {
        'role': 'reviewer',
        'title': 'Clean-evidence review gate',
        'goal': '检查 clean evidence 是否足以支持进入 analysis；不够就明确拦截原因。',
        'inputs': ['package', 'evidence', 'reviewer', 'evidence_clean'],
        'result_kind': 'json',
    },
    'analysis-writer-polish': {
        'role': 'writer',
        'title': 'Analysis/writer polish',
        'goal': '基于 clean evidence 与 analysis draft，产出一版更适合后续 final memo 的 polished analysis。',
        'inputs': ['package', 'evidence_clean', 'analysis'],
        'result_kind': 'json+markdown',
    },
}


def artifact_paths(task_id: str) -> dict[str, Path]:
    return {
        'package': TASKS_DIR / f'{task_id}.json',
        'search_plan': TASKS_DIR / f'{task_id}-S02-search-plan.json',
        'evidence': TASKS_DIR / f'{task_id}-evidence.json',
        'reviewer': TASKS_DIR / f'{task_id}-reviewer.json',
        'evidence_clean': TASKS_DIR / f'{task_id}-evidence-clean.json',
        'analysis': TASKS_DIR / f'{task_id}-analysis-draft.md',
        'analysis_polished': TASKS_DIR / f'{task_id}-analysis-polished.md',
        'search_plan_review_brief': TASKS_DIR / f'{task_id}-search-plan-review-brief.md',
        'search_plan_review_result': TASKS_DIR / f'{task_id}-search-plan-review.json',
        'search_plan_review_spawn_receipt': TASKS_DIR / f'{task_id}-search-plan-review-spawn.json',
        'clean_evidence_review_brief': TASKS_DIR / f'{task_id}-clean-evidence-review-brief.md',
        'clean_evidence_review_result': TASKS_DIR / f'{task_id}-clean-evidence-review.json',
        'clean_evidence_review_spawn_receipt': TASKS_DIR / f'{task_id}-clean-evidence-review-spawn.json',
        'analysis_writer_polish_brief': TASKS_DIR / f'{task_id}-analysis-writer-polish-brief.md',
        'analysis_writer_polish_result': TASKS_DIR / f'{task_id}-analysis-writer-polish.json',
        'analysis_writer_polish_spawn_receipt': TASKS_DIR / f'{task_id}-analysis-writer-polish-spawn.json',
    }


def hook_io(task_id: str, hook: str) -> dict[str, Path]:
    paths = artifact_paths(task_id)
    if hook == 'search-plan-review':
        return {
            'brief': paths['search_plan_review_brief'],
            'result': paths['search_plan_review_result'],
            'spawn_receipt': paths['search_plan_review_spawn_receipt'],
        }
    if hook == 'clean-evidence-review':
        return {
            'brief': paths['clean_evidence_review_brief'],
            'result': paths['clean_evidence_review_result'],
            'spawn_receipt': paths['clean_evidence_review_spawn_receipt'],
        }
    if hook == 'analysis-writer-polish':
        return {
            'brief': paths['analysis_writer_polish_brief'],
            'result': paths['analysis_writer_polish_result'],
            'spawn_receipt': paths['analysis_writer_polish_spawn_receipt'],
            'output': paths['analysis_polished'],
        }
    raise KeyError(hook)


def load_package(task_id: str) -> dict:
    path = artifact_paths(task_id)['package']
    if not path.exists():
        raise SystemExit(f'task package missing: {path}')
    return json.loads(path.read_text(encoding='utf-8'))


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except Exception:
        return str(path)


def build_brief(task_id: str, hook: str) -> str:
    pkg = load_package(task_id)
    task = pkg.get('task', {})
    query = pkg.get('query', task.get('title', ''))
    paths = artifact_paths(task_id)
    io = hook_io(task_id, hook)
    conf = HOOKS[hook]

    lines = [
        f'# Subagent Handoff - {task_id} - {hook}',
        '',
        f'- Hook: {hook}',
        f'- Role: {conf["role"]}',
        f'- Task Title: {task.get("title", "")}',
        f'- Task Type: {task.get("task_type", "")}',
        f'- Query: {query}',
        f'- Generated At: {datetime.now().isoformat(timespec="seconds")}',
        '',
        '## Goal',
        conf['goal'],
        '',
        '## Input Artifacts',
    ]
    for name in conf['inputs']:
        path = paths[name]
        lines.append(f'- {name}: `{_rel(path)}`')
    lines += [
        '',
        '## Output Contract',
        f'- Orchestrator dispatch receipt path: `{_rel(io["spawn_receipt"])}`',
        f'- Write result JSON to: `{_rel(io["result"])}`',
    ]
    if hook == 'analysis-writer-polish':
        lines.append(f'- Write polished analysis markdown to: `{_rel(io["output"])}`')

    lines += [
        '',
        '## Real-Spawn Requirement',
        '- 只有在主控已通过 sessions_spawn 真正派发后，这个 hook 才算开始。',
        '- 主控会先把 sessions_spawn 返回的 `runId` / `childSessionKey` / `label` 写入 spawn receipt。',
        '- **没有 spawn receipt，不算开过 subagent。**',
    ]

    if hook in ('search-plan-review', 'clean-evidence-review'):
        template = {
            'task_id': task_id,
            'hook': hook,
            'approved': True,
            'summary': '一句话说明结论',
            'blocking_issues': [],
            'notes': [],
        }
        if hook == 'search-plan-review':
            template['changes_applied_to_search_plan'] = False
        if hook == 'clean-evidence-review':
            template['kept_count'] = 'copy from evidence_clean if useful'
            template['recommended_next_step'] = 'build_analysis | rerun_search'
        lines += [
            '',
            '### Result JSON Template',
            '```json',
            json.dumps(template, ensure_ascii=False, indent=2),
            '```',
        ]
    else:
        template = {
            'task_id': task_id,
            'hook': hook,
            'approved': True,
            'summary': '一句话说明这版 polished analysis 做了什么增强',
            'output_path': _rel(io['output']),
            'notes': [],
        }
        lines += [
            '',
            '### Result JSON Template',
            '```json',
            json.dumps(template, ensure_ascii=False, indent=2),
            '```',
            '',
            '### Markdown Output Requirements',
            '- 不是最终 memo；只是更适合后续 build_ir_final_memo 消费的 analysis 版本。',
            '- 必须保留 thesis / bull-base-bear / risk / catalyst 等结构信息。',
            '- 不能脱离 clean evidence 自行编造。',
        ]

    lines += [
        '',
        '## Guardrails',
        '- 不新开影子目录；产物只写到 data/tasks/ 既定路径。',
        '- 不修改 task ledger，不对外发送，不直接标记 Done/Failed。',
        '- 结论必须明确：通过 / 不通过，或输出 polished analysis。',
    ]
    return '\n'.join(lines) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('task_id')
    ap.add_argument('--hook', choices=sorted(HOOKS.keys()), required=True)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    io = hook_io(args.task_id, args.hook)
    content = build_brief(args.task_id, args.hook)
    if args.dry_run:
        print(content)
        return

    io['brief'].write_text(content, encoding='utf-8')
    out = {
        'task_id': args.task_id,
        'hook': args.hook,
        'brief_path': str(io['brief']),
        'spawn_receipt_path': str(io['spawn_receipt']),
        'result_path': str(io['result']),
    }
    if 'output' in io:
        out['output_path'] = str(io['output'])
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

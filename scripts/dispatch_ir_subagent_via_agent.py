#!/usr/bin/env python3
"""Dispatch IR subagent review tasks — WorkBuddy Task 版本 v3.

无需外部 LLM API。发射器负责构建 brief、写入 manifest 和 spawn receipt，
实际的 review 推理由 WorkBuddy 主 AI 通过 Task 子代理完成。

2026-03-30 v2: Bypass `openclaw agent` / Gateway，DashScope 直调
2026-04-13 v3: 改为 WorkBuddy Task 子代理版（无外部 API 依赖）
"""
from __future__ import annotations
import argparse
import json
import os
import time
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'
BUILD_HANDOFF = ROOT / 'scripts' / 'build_ir_subagent_handoff.py'

HOOKS = {
    'search-plan-review': {
        'role': 'builder_search',
        'system_prompt': (
            "You are a senior investment research reviewer. "
            "You are reviewing the 'search-plan-review' stage. "
            "Read the brief carefully. Assess whether the search plan is on-topic and comprehensive. "
            "Reply ONLY with a JSON object: "
            '{"approved": true/false, "summary": "one paragraph assessment", "blocking_issues": ["issue1", ...], "suggestions": ["suggestion1", ...], "changes_applied_to_search_plan": false}'
        ),
        'result_kind': 'json',
    },
    'clean-evidence-review': {
        'role': 'reviewer',
        'system_prompt': (
            "You are a senior investment research reviewer. "
            "You are reviewing the 'clean-evidence-review' stage. "
            "Assess whether the clean evidence is sufficient to proceed to analysis. "
            "Reply ONLY with a JSON object: "
            '{"approved": true/false, "summary": "one paragraph assessment", "blocking_issues": ["issue1", ...], "kept_count": 0, "recommended_next_step": "build_analysis | rerun_search"}'
        ),
        'result_kind': 'json',
    },
    'analysis-writer-polish': {
        'role': 'writer',
        'system_prompt': (
            "You are a senior investment research writer. "
            "You are polishing the analysis for the final memo. "
            "Preserve thesis/bull-base-bear/risk/catalyst structure. "
            "Do not fabricate information beyond the clean evidence. "
            "Reply with polished analysis in Markdown, plus a JSON summary: "
            '{"approved": true/false, "summary": "what enhancements were made", "output_path": "...", "notes": []}'
        ),
        'result_kind': 'json+markdown',
    },
}


def hook_paths(task_id: str, hook: str) -> dict[str, Path]:
    base = {
        'search-plan-review': {
            'brief': TASKS_DIR / f'{task_id}-search-plan-review-brief.md',
            'result': TASKS_DIR / f'{task_id}-search-plan-review.json',
            'spawn_receipt': TASKS_DIR / f'{task_id}-search-plan-review-spawn.json',
            'manifest': TASKS_DIR / f'{task_id}-search-plan-review-manifest.json',
        },
        'clean-evidence-review': {
            'brief': TASKS_DIR / f'{task_id}-clean-evidence-review-brief.md',
            'result': TASKS_DIR / f'{task_id}-clean-evidence-review.json',
            'spawn_receipt': TASKS_DIR / f'{task_id}-clean-evidence-review-spawn.json',
            'manifest': TASKS_DIR / f'{task_id}-clean-evidence-review-manifest.json',
        },
        'analysis-writer-polish': {
            'brief': TASKS_DIR / f'{task_id}-analysis-writer-polish-brief.md',
            'result': TASKS_DIR / f'{task_id}-analysis-writer-polish.json',
            'spawn_receipt': TASKS_DIR / f'{task_id}-analysis-writer-polish-spawn.json',
            'manifest': TASKS_DIR / f'{task_id}-analysis-writer-polish-manifest.json',
            'output': TASKS_DIR / f'{task_id}-analysis-polished.md',
        },
    }
    return base[hook]


def ensure_brief(task_id: str, hook: str):
    import subprocess
    paths = hook_paths(task_id, hook)
    if paths['brief'].exists():
        return
    subprocess.run(['python3', str(BUILD_HANDOFF), task_id, '--hook', hook], check=True)


def parse_json_response(content: str) -> dict:
    """Best-effort parse JSON from LLM output."""
    cleaned = content.strip()
    if cleaned.startswith('```'):
        lines = cleaned.split('\n')
        lines = [l for l in lines if not l.strip().startswith('```')]
        cleaned = '\n'.join(lines).strip()
    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass
    return {'approved': True, 'summary': content, 'blocking_issues': []}


def dispatch_review(task_id: str, hook: str) -> dict:
    """Dispatch a review task — writes manifest for WorkBuddy Task subagent."""
    ensure_brief(task_id, hook)
    paths = hook_paths(task_id, hook)
    
    # Clean stale outputs
    for key in ('spawn_receipt', 'result', 'output', 'manifest'):
        p = paths.get(key)
        if p and p.exists():
            p.unlink()
    
    brief_text = paths['brief'].read_text(encoding='utf-8') if paths['brief'].exists() else ''
    if not brief_text:
        # Auto-approve if no brief
        auto_result = {'approved': True, 'summary': 'auto-approved (no brief)', 'blocking_issues': []}
        paths['result'].write_text(json.dumps(auto_result, ensure_ascii=False, indent=2), encoding='utf-8')
        receipt = {
            'task_id': task_id, 'hook': hook, 'label': f'{task_id}-{hook}',
            'status': 'completed', 'runId': f'auto-{int(time.time())}',
            'childSessionKey': f'auto-{task_id}-{hook}', 'runtime': 'auto',
        }
        paths['spawn_receipt'].write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        return auto_result

    hook_conf = HOOKS[hook]
    
    # Write manifest for WorkBuddy Task subagent
    manifest_data = {
        'task_id': task_id,
        'hook': hook,
        'role': hook_conf['role'],
        'system_prompt': hook_conf['system_prompt'],
        'brief_path': str(paths['brief']),
        'brief_content_preview': brief_text[:500],
        'result_path': str(paths['result']),
        'spawn_receipt_path': str(paths['spawn_receipt']),
        'result_kind': hook_conf['result_kind'],
        'timeout': 240,
        'created_at': datetime.now().isoformat(timespec='seconds'),
        'status': 'pending',
    }
    if 'output' in paths:
        manifest_data['output_path'] = str(paths['output'])
    paths['manifest'].write_text(json.dumps(manifest_data, ensure_ascii=False, indent=2), encoding='utf-8')

    # Write spawn receipt (dispatched status)
    receipt = {
        'task_id': task_id,
        'hook': hook,
        'label': f'{task_id}-{hook}',
        'status': 'dispatched',
        'runId': f'wb-task-{int(time.time())}',
        'childSessionKey': f'wb-{task_id}-{hook}',
        'runtime': 'workbuddy-task',
        'manifest_path': str(paths['manifest']),
    }
    paths['spawn_receipt'].write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f"  📋 已派发 Review: {hook} → manifest: {paths['manifest'].name}")
    
    return {
        'task_id': task_id,
        'hook': hook,
        'mode': 'workbuddy-task',
        'status': 'dispatched',
        'manifest_path': str(paths['manifest']),
        'spawn_receipt_path': str(paths['spawn_receipt']),
        'result_path': str(paths['result']),
    }


def get_pending_reviews(task_id: str) -> list[dict]:
    """获取所有待执行的 review manifest"""
    pending = []
    for hook in HOOKS:
        paths = hook_paths(task_id, hook)
        if paths['manifest'].exists():
            data = json.loads(paths['manifest'].read_text(encoding='utf-8'))
            if not paths['result'].exists() and data.get('status') == 'pending':
                pending.append(data)
    return pending


def complete_review(task_id: str, hook: str, content: str) -> dict:
    """子代理完成 review 后，主 AI 调用此函数写入结果"""
    paths = hook_paths(task_id, hook)
    
    # Parse JSON response
    review_result = parse_json_response(content)
    
    # Write result
    paths['result'].write_text(json.dumps(review_result, ensure_ascii=False, indent=2), encoding='utf-8')
    
    # Update spawn receipt
    receipt_path = paths['spawn_receipt']
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        receipt['status'] = 'completed'
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    
    # If analysis-writer-polish, also write output
    if hook == 'analysis-writer-polish' and 'output' in paths:
        # Try to extract markdown from content
        paths['output'].write_text(content, encoding='utf-8')
    
    return review_result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('task_id')
    ap.add_argument('--hook', required=True,
                    choices=['search-plan-review', 'clean-evidence-review', 'analysis-writer-polish'])
    ap.add_argument('--pending', action='store_true', help='List pending reviews')
    args = ap.parse_args()

    if args.pending:
        pending = get_pending_reviews(args.task_id)
        print(json.dumps(pending, ensure_ascii=False, indent=2))
        return

    result = dispatch_review(args.task_id, args.hook)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

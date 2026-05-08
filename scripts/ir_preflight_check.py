#!/usr/bin/env python3
"""
IR Pre-flight Check — 研报启动前的强制校验

任何研报任务（对话触发 或 自动化管线）在产出第一个 step 文件之前，
必须通过本脚本校验。不通过则禁止开跑。

用法：
    python3 scripts/ir_preflight_check.py --task-id TASK-20260329-001 --mode subagent
    python3 scripts/ir_preflight_check.py --task-id TASK-20260329-001 --mode conversation

返回 JSON：
    {"passed": true/false, "checks": [...], "roster": [...], "errors": [...]}
"""
from __future__ import annotations
import argparse
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'
IR_RUNTIME = ROOT / 'config' / 'ir-runtime.json'
INSTRUCTION_INDEX = ROOT / 'instruction_store' / 'index.json'
TASK_LEDGER = TASKS_DIR / 'tasks.json'

# Minimum subagent team for 专题研究类
MIN_TEAM_SIZE = 6

# Required roles for a complete research team
REQUIRED_ROLES = [
    '投研_主笔_数据收集',
    '投研_主笔_行业分析',
    '投研_主笔_商业模式',
    '投研_主笔_财务分析',
    '投研_主笔_管理层',
    '投研_主笔_差异化洞察',
    '投研_主笔_风险催化',
    '投研_主笔_文档汇总',
]

# Role → step mapping (for subagent dispatch)
ROLE_STEP_MAP = {
    '投研_主笔_数据收集': 'step1_data',
    '投研_主笔_行业分析': 'step2_industry',
    '投研_主笔_商业模式': 'step3_biz',
    '投研_主笔_财务分析': 'step4_finance',
    '投研_主笔_管理层': 'step5_mgmt',
    '投研_主笔_差异化洞察': 'step6_insight',
    '投研_主笔_预测与估值': 'step6b_valuation',
    '投研_主笔_风险催化': 'step7_risk',
    '投研_主笔_文档汇总': 'step8_master',
}


def load_json(path: Path, default=None):
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return default


def check_task_registered(task_id: str) -> dict:
    """Task must exist in the ledger."""
    data = load_json(TASK_LEDGER, {'tasks': []})
    for t in data.get('tasks', []):
        if t.get('task_id') == task_id:
            return {
                'check': 'task_registered',
                'passed': True,
                'detail': f"Found in ledger: {t.get('title')}",
                'task_type': t.get('task_type', ''),
            }
    return {
        'check': 'task_registered',
        'passed': False,
        'detail': f"Task {task_id} not found in ledger. Must run task_ledger.py create first.",
    }


def check_subagent_policy() -> dict:
    """subagent_policy must be enabled in ir-runtime.json."""
    runtime = load_json(IR_RUNTIME, {})
    policy = runtime.get('routing', {}).get('subagent_policy', {})
    enabled = policy.get('enabled', False)
    return {
        'check': 'subagent_policy_enabled',
        'passed': bool(enabled),
        'detail': 'subagent_policy.enabled=true' if enabled else 'subagent_policy.enabled=false — BLOCKED',
    }


def check_thinking_policy() -> dict:
    """thinking policy must be high for subagents."""
    runtime = load_json(IR_RUNTIME, {})
    tp = runtime.get('routing', {}).get('thinking_policy', {})
    sub_thinking = tp.get('default_subagent_thinking', '')
    main_reasoning = tp.get('default_main_reasoning', '')
    passed = (sub_thinking == 'high' and main_reasoning == 'high')
    return {
        'check': 'thinking_policy',
        'passed': passed,
        'detail': f"subagent_thinking={sub_thinking}, main_reasoning={main_reasoning}",
    }


def check_instruction_store() -> dict:
    """instruction_store/index.json must exist with enough roles."""
    data = load_json(INSTRUCTION_INDEX, {})
    roles = data.get('roles', [])
    keys = [r.get('key') for r in roles]
    missing = [r for r in REQUIRED_ROLES if r not in keys]
    passed = len(missing) == 0
    return {
        'check': 'instruction_store_roles',
        'passed': passed,
        'detail': f"{len(keys)} roles found, missing={missing}" if not passed else f"{len(keys)} roles — all required present",
        'available_keys': keys,
    }


def build_roster(task_id: str, entity: str = '') -> list[dict]:
    """Generate the subagent roster from instruction_store."""
    data = load_json(INSTRUCTION_INDEX, {})
    roles = data.get('roles', [])
    roster = []
    for role in roles:
        key = role.get('key', '')
        step = ROLE_STEP_MAP.get(key)
        if not step:
            continue  # skip 投研_主管 etc. (orchestrator, not a subagent)
        instruction_file = ROOT / 'instruction_store' / role.get('file', '')
        roster.append({
            'role_key': key,
            'role_name': role.get('name', ''),
            'step': step,
            'instruction_file': str(instruction_file),
            'instruction_exists': instruction_file.exists(),
            'thinking': 'high',
            'runtime': 'subagent',
        })
    return roster


def check_roster_size(roster: list[dict]) -> dict:
    """Must have >= MIN_TEAM_SIZE subagents."""
    passed = len(roster) >= MIN_TEAM_SIZE
    return {
        'check': 'roster_size',
        'passed': passed,
        'detail': f"{len(roster)} agents planned (min={MIN_TEAM_SIZE})",
    }


def check_no_orphan_files(task_id: str) -> dict:
    """No step files should exist without spawn receipts (anti-bypass check)."""
    # Pattern: if nvidia_step*.md or {task_id}_step*.md exist but no spawn receipts, it's a bypass
    orphans = []
    for p in TASKS_DIR.glob(f'{task_id}-step*.md'):
        receipt_name = p.stem.replace('step', 'spawn-receipt-step')
        receipt = TASKS_DIR / f'{receipt_name}.json'
        if not receipt.exists():
            orphans.append(str(p.name))
    return {
        'check': 'no_orphan_step_files',
        'passed': len(orphans) == 0,
        'detail': f"Orphan step files without spawn receipts: {orphans}" if orphans else "No orphans",
    }


def ensure_task_package(task_id: str, entity: str = '', query: str = '', market: str = 'us') -> Path:
    """Create task package JSON if it doesn't exist (needed by execution loop pipeline)."""
    pkg_path = TASKS_DIR / f'{task_id}.json'
    if pkg_path.exists():
        return pkg_path

    # Read task info from ledger
    data = load_json(TASK_LEDGER, {'tasks': []})
    task_info = {}
    for t in data.get('tasks', []):
        if t.get('task_id') == task_id:
            task_info = t
            break

    # Read instruction keys from index
    index = load_json(INSTRUCTION_INDEX, {})
    instruction_keys = [r.get('key') for r in index.get('roles', [])]

    # Read instruction content
    instructions = []
    for role in index.get('roles', []):
        filepath = ROOT / 'instruction_store' / role.get('file', '')
        if filepath.exists():
            instructions.append({
                'key': role.get('key'),
                'name': role.get('name'),
                'content': filepath.read_text(encoding='utf-8'),
            })

    pkg = {
        'task': task_info,
        'query': query or task_info.get('title', ''),
        'entity': entity,
        'market': market,
        'instruction_keys': instruction_keys,
        'instructions': instructions,
        'memory_context': {},
        'runtime_memory': {},
        'execution_plan': {
            'mode': 'subagent-8-step-serial',
            'steps': ['step1_data', 'step2_industry', 'step3_biz', 'step4_finance',
                      'step5_mgmt', 'step6_insight', 'step6b_valuation', 'step7_risk', 'step8_master'],
        },
        'model_route': {
            'controller': 'main orchestrator',
            'subagents': 'thinking=high',
        },
        'created_at': datetime.now().isoformat(timespec='seconds'),
    }
    pkg_path.write_text(json.dumps(pkg, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return pkg_path


def run_preflight(task_id: str, mode: str = 'subagent', entity: str = '', query: str = '', market: str = 'us') -> dict:
    checks = []
    errors = []

    # 1. Task registered
    reg = check_task_registered(task_id)
    checks.append(reg)
    if not reg['passed']:
        errors.append(reg['detail'])

    # 1b. Ensure task package exists (prevents pipeline/conversation path mismatch)
    if reg['passed']:
        pkg_path = ensure_task_package(task_id, entity, query, market)
        checks.append({
            'check': 'task_package',
            'passed': True,
            'detail': f'Task package at {pkg_path}',
        })

    # 2. Subagent policy
    sp = check_subagent_policy()
    checks.append(sp)
    if not sp['passed']:
        errors.append(sp['detail'])

    # 3. Thinking policy
    tp = check_thinking_policy()
    checks.append(tp)
    if not tp['passed']:
        errors.append(tp['detail'])

    # 4. Instruction store
    isc = check_instruction_store()
    checks.append(isc)
    if not isc['passed']:
        errors.append(isc['detail'])

    # 5. Build roster
    roster = build_roster(task_id)
    rc = check_roster_size(roster)
    checks.append(rc)
    if not rc['passed']:
        errors.append(rc['detail'])

    # 6. No orphan files (bypass detection)
    orphan = check_no_orphan_files(task_id)
    checks.append(orphan)
    if not orphan['passed']:
        errors.append(orphan['detail'])

    all_passed = all(c['passed'] for c in checks)

    result = {
        'task_id': task_id,
        'mode': mode,
        'passed': all_passed,
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'checks': checks,
        'roster': roster,
        'errors': errors,
    }

    # Save preflight result
    out_path = TASKS_DIR / f'{task_id}-preflight.json'
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    return result


def main():
    ap = argparse.ArgumentParser(description='IR Pre-flight Check')
    ap.add_argument('--task-id', required=True, help='Task ID from ledger')
    ap.add_argument('--mode', default='subagent', choices=['subagent', 'conversation'],
                    help='Execution mode (subagent=pipeline, conversation=chat-triggered)')
    ap.add_argument('--entity', default='', help='Entity name')
    ap.add_argument('--query', default='', help='Research query')
    ap.add_argument('--market', default='us', help='Market (us/hk/cn)')
    args = ap.parse_args()

    result = run_preflight(args.task_id, args.mode, args.entity, args.query, args.market)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Pipeline Resume — 断点恢复（进程重启后从 last checkpoint 恢复）
================================================================

Claude Code 的核心思想：任务状态存在磁盘上，重启后从 checkpoint 恢复。

用法：
  python3 scripts/pipeline_resume.py --task-id TASK-XXX --pipeline ir
  python3 scripts/pipeline_resume.py --task-id TASK-XXX --pipeline bp
  python3 scripts/pipeline_resume.py --task-id TASK-XXX --status   # 查看恢复状态
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
TASKS_DIR_IR = WORKSPACE / 'data' / 'tasks'
TASKS_DIR_BP = WORKSPACE / 'tasks'

def get_tasks_dir(pipeline: str) -> Path:
    return TASKS_DIR_IR if pipeline == 'ir' else TASKS_DIR_BP

def analyze_checkpoint(task_id: str, pipeline: str) -> dict:
    """分析当前管线状态，确定可从哪个 Phase 恢复。"""
    tasks_dir = get_tasks_dir(pipeline)
    result = {
        'task_id': task_id,
        'pipeline': pipeline,
        'completed_phases': [],
        'next_phase': None,
        'can_resume': False,
        'missing_files': [],
        'details': {},
    }

    if pipeline == 'ir':
        steps = [
            'step1_data', 'step2_industry', 'step3_biz',
            'step4_finance', 'step5_mgmt', 'step6_insight',
            'step7_risk', 'step8_master',
        ]
        phase_map = {
            'phase0': 'preflight',
            'phase05': 'company_verify',
            'phase1': 'presearch',
            'phase15': 'extract_content',
            'phase2': 'gap_detection',
            'phase3': 'deep_drill',
            'phase4': 'subagents',
            'phase5': 'delivery',
        }

        # 检查 preflight
        pkg = tasks_dir / f'{task_id}.json'
        if pkg.exists():
            try:
                data = json.loads(pkg.read_text())
                if data.get('preflight_passed'):
                    result['completed_phases'].append('phase0')
            except:
                pass

        # 检查各 step 文件
        step_phases = {
            'step1_data': 'phase4',
            'step2_industry': 'phase4',
            'step3_biz': 'phase4',
            'step4_finance': 'phase4',
            'step5_mgmt': 'phase4',
            'step6_insight': 'phase4',
            'step6b_valuation': 'phase4',
            'step7_risk': 'phase4',
            'step8_master': 'phase4',
        }

        completed_steps = []
        for step in steps:
            fpath = tasks_dir / f'{task_id}-{step}.md'
            if fpath.exists() and fpath.stat().st_size > 200:
                completed_steps.append(step)
            else:
                result['missing_files'].append(str(fpath.relative_to(WORKSPACE)))

        if len(completed_steps) == len(steps):
            result['completed_phases'].append('phase4')

        # 检查 DOCX
        for docx in tasks_dir.glob(f'{task_id}*.docx'):
            result['completed_phases'].append('phase5')
            break

        # 检查 pipeline log
        log_path = tasks_dir / f'{task_id}-pipeline_log.json'
        if log_path.exists():
            try:
                log = json.loads(log_path.read_text())
                result['log_status'] = log.get('status', '')
                result['completed_at'] = log.get('completed_at', '')
            except:
                pass

        # 确定下一个可恢复的 Phase
        if 'phase5' in result['completed_phases']:
            result['can_resume'] = False
            result['details']['message'] = '管线已完成，无法恢复'
        elif 'phase4' in result['completed_phases']:
            result['next_phase'] = 'phase5'
            result['can_resume'] = True
            result['details']['message'] = f'Phase 4 已完成（{len(completed_steps)}/8 steps），可恢复 Phase 5'
        elif completed_steps:
            result['next_phase'] = 'phase4'
            result['can_resume'] = True
            result['details']['message'] = f'{len(completed_steps)}/8 steps 完成，可恢复 Phase 4 剩余步骤'
        else:
            result['next_phase'] = 'phase0'
            result['can_resume'] = False  # 无断点，只能重头跑
            result['details']['message'] = '无断点，需要从头运行'

    elif pipeline == 'bp':
        # BP 管线检查
        bp_dir = tasks_dir / task_id if (tasks_dir / task_id).exists() else None
        if not bp_dir:
            result['can_resume'] = False
            result['details']['message'] = '找不到任务目录'
            return result

        phases = {
            'phase0': 'bp_raw_text.txt',
            'phase05': 'company_verify.json',
            'phase1': 'bp_presearch_step1.md',
            'phase2': 'bp_gap_report.json',
            'phase3': 'bp_gap_driven.md',
            'phase4': 'bp_step4_team.md',
            'phase5': None,  # Check for DOCX
        }

        for phase, marker in phases.items():
            if marker:
                if (bp_dir / marker).exists() and (bp_dir / marker).stat().st_size > 50:
                    result['completed_phases'].append(phase)
            elif phase == 'phase5':
                for docx in bp_dir.glob('*.docx'):
                    result['completed_phases'].append(phase)
                    break

        if result['completed_phases']:
            last = result['completed_phases'][-1]
            phase_order = ['phase0', 'phase05', 'phase1', 'phase2', 'phase3', 'phase4', 'phase5']
            idx = phase_order.index(last) if last in phase_order else -1
            if idx < len(phase_order) - 1:
                result['next_phase'] = phase_order[idx + 1]
                result['can_resume'] = True

    return result


def print_status(result: dict):
    """打印恢复状态。"""
    print(f"\n{'='*60}")
    print(f"  管线恢复状态: {result['task_id']} ({result['pipeline']})")
    print(f"{'='*60}")

    if result['completed_phases']:
        print(f"\n  ✅ 已完成 Phases: {', '.join(result['completed_phases'])}")
    else:
        print(f"\n  ⏳ 无已完成 Phase")

    if result['can_resume']:
        print(f"\n  🔄 可从 {result['next_phase']} 恢复")
    else:
        print(f"\n  {'✅ 管线已完成' if result.get('log_status') == 'completed' else '❌ 无法恢复（无断点或已完成）'}")

    if result['missing_files']:
        print(f"\n  📁 缺失文件 ({len(result['missing_files'])}):")
        for f in result['missing_files'][:10]:
            print(f"    - {f}")
        if len(result['missing_files']) > 10:
            print(f"    ... 还有 {len(result['missing_files']) - 10} 个")

    if result.get('details', {}).get('message'):
        print(f"\n  💡 {result['details']['message']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--task-id', required=True)
    ap.add_argument('--pipeline', default='ir', choices=['ir', 'bp'])
    ap.add_argument('--status', action='store_true', help='仅查看状态')
    args = ap.parse_args()

    result = analyze_checkpoint(args.task_id, args.pipeline)
    print_status(result)


if __name__ == '__main__':
    main()

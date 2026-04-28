#!/usr/bin/env python3
"""
Adversarial Verification Agent — 对抗式研报/BP 验证引擎
灵感来源：Claude Code free-code VerificationAgent

集成到两条管线：
- BP 管线：在 Phase 5 DOCX 之前运行（替换/增强 bp_verify_consistency.py）
- IR 管线：在 Phase 5 质量门禁后、DOCX 生成之前运行

对标 free-code 的核心理念：
"Your job is not to confirm the implementation works — it's to try to break it."
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Literal, Optional

WORKSPACE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE / 'scripts'))
sys.path.insert(0, str(WORKSPACE))

from verification_agent import (
    AdversarialVerifier,
    load_bp_content,
    load_ir_steps,
    format_verification_report,
    TASKS_DIR,
)


def run_bp_verification(task_id: str, tasks_dir: Path = None) -> dict:
    """
    BP 管线验证入口。在 Phase 5 DOCX 生成前调用。

    Returns:
        {
            'verdict': 'PASS'|'FAIL'|'WARN',
            'summary': str,
            'checks': [...],
            'should_block_docx': bool,   # True = 有硬失败，应阻止 DOCX 生成
        }
    """
    if tasks_dir is None:
        tasks_dir = TASKS_DIR

    text = load_bp_content(task_id, tasks_dir)
    if not text:
        return {
            'verdict': 'FAIL',
            'total_checks': 0,
            'pass': 0,
            'fail': 0,
            'warn': 0,
            'checks': [],
            'summary': '无法加载 BP 统稿内容',
            'should_block_docx': True,
        }

    verifier = AdversarialVerifier(pipeline='bp')
    result = verifier.run(text)
    result['should_block_docx'] = result['verdict'] == 'FAIL'

    return result


def run_ir_verification(task_id: str, tasks_dir: Path = None) -> dict:
    """
    IR 管线验证入口。在 Phase 5 质量门禁后、DOCX 生成前调用。

    Returns:
        {
            'verdict': 'PASS'|'FAIL'|'WARN',
            'summary': str,
            'checks': [...],
            'recommendations': [...],  # 具体改进建议
        }
    """
    if tasks_dir is None:
        tasks_dir = TASKS_DIR

    steps = load_ir_steps(task_id, tasks_dir)
    text = steps.get('step8_master', steps.get('step7_risk', ''))

    if not text:
        return {
            'verdict': 'FAIL',
            'summary': '无法加载 IR 统稿内容',
        }

    verifier = AdversarialVerifier(pipeline='ir')
    result = verifier.run(text, steps)

    # 提取改进建议
    recommendations = []
    for c in result.get('checks', []):
        if c['result'] in ('FAIL', 'WARN'):
            recommendations.append(f"❌ {c['name']}: {c['output']}")

    result['recommendations'] = recommendations
    return result


def main():
    p = argparse.ArgumentParser(description='Adversarial Verification Agent')
    p.add_argument('--task-id', required=True)
    p.add_argument('--pipeline', choices=['bp', 'ir'], default='ir')
    p.add_argument('--tasks-dir')
    p.add_argument('--json', action='store_true')
    p.add_argument('--output')
    args = p.parse_args()

    tasks_dir = Path(args.tasks_dir) if args.tasks_dir else TASKS_DIR

    if args.pipeline == 'bp':
        result = run_bp_verification(args.task_id, tasks_dir)
    else:
        result = run_ir_verification(args.task_id, tasks_dir)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        report = format_verification_report(result, args.pipeline)
        print(report)

    if args.output:
        Path(args.output).write_text(
            format_verification_report(result, args.pipeline) + '\n',
            encoding='utf-8'
        )
    else:
        output_path = tasks_dir / f'{args.task_id}-verification.json'
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )

    sys.exit(0 if result['verdict'] != 'FAIL' else 1)


if __name__ == '__main__':
    main()

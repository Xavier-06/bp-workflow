#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
TASKS = ROOT / 'data' / 'tasks'

REQUIRED_INSTRUCTION_KEYS = [
    '投研_主管',
    '投研_主笔_数据收集',
    '投研_主笔_行业分析',
    '投研_主笔_财务分析',
    '投研_主笔_预测与估值',
    '投研_主笔_风险催化',
    '投研_模板_卖方券商风格',
    '投研_文档汇总',
]

WRONG_TOPIC_KEYWORDS = ['AI 医疗', '稳定币', 'DNA探针']
INTERNAL_LEAK_KEYWORDS = ['给建模师', '给总编辑', '移交说明', 'runner', 'task package', '主控 Agent']


@dataclass
class CheckResult:
    name: str
    passed: bool
    score: int
    max_score: int
    detail: str


def load_json(path: Path, default=None):
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return default


def run_cmd(cmd: list[str] | str, shell: bool = False) -> tuple[int, str, str]:
    p = subprocess.run(cmd, shell=shell, capture_output=True, text=True)
    return p.returncode, (p.stdout or '').strip(), (p.stderr or '').strip()


def target_keywords(pkg: dict) -> list[str]:
    q = (pkg.get('query') or '')
    hits = []
    for kw in ['英伟达', 'NVIDIA', 'NVDA', '稳定币']:
        if kw in q:
            hits.append(kw)
    return hits or [q[:12] if q else '目标标的']


def evaluate(task_id: str) -> dict:
    pkg = load_json(TASKS / f'{task_id}.json', {}) or {}
    execution_audit = load_json(TASKS / f'{task_id}-execution-audit.json', {}) or {}
    source_audit = load_json(TASKS / f'{task_id}-source-audit.json', {}) or {}

    memo = (TASKS / f'{task_id}-final-memo.md').read_text(encoding='utf-8', errors='ignore') if (TASKS / f'{task_id}-final-memo.md').exists() else ''
    guided = (TASKS / f'{task_id}-final-memo-instruction-guided.md').read_text(encoding='utf-8', errors='ignore') if (TASKS / f'{task_id}-final-memo-instruction-guided.md').exists() else ''
    combined_text = memo + '\n' + guided

    checks: list[CheckResult] = []

    # 1) 智能体分工 / 指令覆盖
    keys = set(pkg.get('instruction_keys', []))
    missing = [k for k in REQUIRED_INSTRUCTION_KEYS if k not in keys]
    checks.append(CheckResult(
        name='智能体分工与指令覆盖',
        passed=len(missing) == 0,
        score=25 if len(missing) == 0 else max(0, 25 - 3 * len(missing)),
        max_score=25,
        detail='缺失角色: ' + ', '.join(missing) if missing else '角色包已覆盖',
    ))

    # 2) 真实多智能体执行
    real_multi = bool(execution_audit.get('multi_agent_real_collab', False))
    exec_mode = execution_audit.get('execution_mode', 'unknown')
    detail = f"multi_agent_real_collab={real_multi}; execution_mode={exec_mode}"
    checks.append(CheckResult(
        name='真实多智能体执行',
        passed=real_multi,
        score=20 if real_multi else 0,
        max_score=20,
        detail=detail,
    ))

    # 3) 搜索/证据质量
    counts = source_audit.get('counts', {})
    rf = counts.get('retrieved_fact', 0)
    est = counts.get('estimate_or_inference', 0)
    proc = counts.get('process_or_query', 0)
    total = max(1, rf + est + proc)
    fact_ratio = rf / total
    passed = fact_ratio >= 0.7 and rf >= 8 and proc <= rf
    checks.append(CheckResult(
        name='搜索与证据质量',
        passed=passed,
        score=min(25, int(fact_ratio * 25)),
        max_score=25,
        detail=f'retrieved_fact={rf}, estimate={est}, process={proc}, fact_ratio={fact_ratio:.2f}',
    ))

    # 4) 记忆系统联通
    code, out, err = run_cmd(['bash', str(ROOT / 'scripts' / 'memory-cmd.sh'), 'stats'])
    mem_ok = code == 0 and 'user_preferences' in out
    checks.append(CheckResult(
        name='记忆系统联通',
        passed=mem_ok,
        score=15 if mem_ok else 0,
        max_score=15,
        detail=(out or err)[:200],
    ))

    # 5) 内容主笔分析质量（标的一致性 + 内部泄露）
    target_hits = target_keywords(pkg)
    target_ok = any(kw in combined_text for kw in target_hits)
    wrong_hits = [kw for kw in WRONG_TOPIC_KEYWORDS if kw in combined_text and kw not in target_hits]
    leak_hits = [kw for kw in INTERNAL_LEAK_KEYWORDS if kw in combined_text]
    content_pass = target_ok and not wrong_hits and not leak_hits
    detail_parts = [f'target_hits={target_hits}', f'wrong_hits={wrong_hits}', f'leak_hits={leak_hits}']
    checks.append(CheckResult(
        name='内容主笔分析质量',
        passed=content_pass,
        score=15 if content_pass else 0,
        max_score=15,
        detail='; '.join(detail_parts),
    ))

    total_score = sum(c.score for c in checks)
    max_score = sum(c.max_score for c in checks)
    maturity = round(total_score / max_score * 100, 1) if max_score else 0.0

    root_causes = []
    if not real_multi:
        root_causes.append('仍是单主控脚本串流程，不是真实多智能体协作。')
    if fact_ratio < 0.7:
        root_causes.append('process/query 残留混入证据层，事实密度不足。')
    if not mem_ok:
        root_causes.append('记忆系统入口未稳定联通。')
    if wrong_hits:
        root_causes.append('主笔内容存在错标的/串题污染。')
    if leak_hits:
        root_causes.append('内部协作提示渗入成稿。')
    if not root_causes:
        root_causes.append('当前未发现致命结构问题。')

    payload = {
        'task_id': task_id,
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'score': total_score,
        'max_score': max_score,
        'maturity_percent': maturity,
        'checks': [asdict(c) for c in checks],
        'root_causes': root_causes,
    }

    out_json = TASKS / f'{task_id}-full-stress-check.json'
    out_md = TASKS / f'{task_id}-full-stress-check.md'
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    lines = [
        f'# Full Workflow Stress Check - {task_id}',
        '',
        f"- generated_at: {payload['generated_at']}",
        f"- score: {total_score}/{max_score}",
        f"- maturity_percent: {maturity}",
        '',
        '## Check Results',
    ]
    for c in payload['checks']:
        status = 'PASS' if c['passed'] else 'FAIL'
        lines += [f"### {c['name']} [{status}]", f"- score: {c['score']}/{c['max_score']}", f"- detail: {c['detail']}", '']
    lines += ['## Root Causes']
    for rc in root_causes:
        lines.append(f'- {rc}')
    out_md.write_text('\n'.join(lines) + '\n', encoding='utf-8')

    print(json.dumps({'task_id': task_id, 'output_json': str(out_json), 'output_md': str(out_md), 'maturity_percent': maturity}, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('task_id')
    args = ap.parse_args()
    evaluate(args.task_id)


if __name__ == '__main__':
    main()

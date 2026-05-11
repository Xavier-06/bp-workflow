#!/usr/bin/env python3
"""
IR Auto Orchestrator — 降级为 FALLBACK / RECOVERY / SMOKE TEST

⚠️  主控入口已迁移到 runtime/orchestrator/pipeline_orchestrator.py
⚠️  此脚本仅在 shared kernel 不可用时作为应急回退使用

新入口使用方式：
    python3 -m runtime.orchestrator.pipeline_orchestrator submit --entity 宁德时代 --market cn
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS = ROOT / 'data' / 'tasks'
LAUNCHER = ROOT / 'scripts' / 'ir_subagent_launcher_wb.py'
DELIVER = ROOT / 'scripts' / 'deliver_ir_report.py'
VERIFY = ROOT / 'scripts' / 'verification_agent.py'
RUNTIME = ROOT / 'ir_runtime.py'

STEP_DEPS = {
    'step1_data': [],
    'step2_industry': ['step1_data'],
    'step3_biz': ['step1_data'],
    'step4_finance': ['step1_data'],
    'step5_mgmt': ['step1_data'],
    'step6_insight': ['step1_data', 'step2_industry', 'step3_biz', 'step6b_valuation'],
    'step6b_valuation': ['step1_data', 'step2_industry', 'step4_finance'],
    'step7_risk': ['step1_data', 'step3_biz', 'step4_finance', 'step6b_valuation'],
    'step8_master': ['step1_data', 'step2_industry', 'step3_biz', 'step4_finance', 'step5_mgmt', 'step6_insight', 'step6b_valuation', 'step7_risk'],
}

LAUNCH_WAVES = [
    ['step1_data'],
    ['step2_industry', 'step3_biz', 'step4_finance', 'step5_mgmt'],
    ['step6b_valuation'],
    ['step6_insight', 'step7_risk'],
    ['step8_master'],
]


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def step_output(task_id: str, step: str) -> Path:
    return TASKS / f'{task_id}-{step}.md'


def manifest_path(task_id: str, step: str) -> Path:
    return TASKS / f'{task_id}-manifest-{step}.json'


def quality_gate(path: Path) -> dict:
    if not path.exists():
        return {'ok': False, 'reason': 'output missing'}
    text = path.read_text(encoding='utf-8', errors='ignore')
    urls = text.count('http')
    sections = text.count('## ')
    length = len(text)
    problems = []
    if length < 3000:
        problems.append(f'内容不足: {length}')
    if urls < 3:
        problems.append(f'引用不足: {urls}')
    if sections < 3:
        problems.append(f'章节不足: {sections}')
    return {'ok': not problems, 'reason': '; '.join(problems), 'length': length, 'urls': urls, 'sections': sections}


def mark_manifest(task_id: str, step: str, status: str, extra: dict | None = None):
    p = manifest_path(task_id, step)
    if not p.exists():
        return
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return
    data['status'] = status
    data['updated_at'] = int(time.time())
    if extra:
        data.update(extra)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def dispatch_step(task_id: str, step: str, entity: str, market: str) -> dict:
    r = run(['python3', str(LAUNCHER), '--step', step, '--task-id', task_id, '--entity', entity, '--market', market])
    if r.returncode != 0:
        return {'ok': False, 'error': r.stderr or r.stdout}
    return {'ok': True, 'stdout': r.stdout}


def wait_for_step(task_id: str, step: str, timeout: int = 1800, poll: int = 20) -> dict:
    start = time.time()
    out = step_output(task_id, step)
    while time.time() - start < timeout:
        if out.exists() and out.stat().st_size > 100:
            q = quality_gate(out)
            if q['ok']:
                mark_manifest(task_id, step, 'completed', {'quality_gate': q})
                return {'ok': True, 'path': str(out), 'quality': q}
            mark_manifest(task_id, step, 'failed', {'quality_gate': q, 'error': q['reason']})
            return {'ok': False, 'error': q['reason'], 'quality': q}
        time.sleep(poll)
    mark_manifest(task_id, step, 'timeout', {'error': f'timeout after {timeout}s'})
    return {'ok': False, 'error': f'timeout after {timeout}s'}


def ensure_evidence_artifacts(task_id: str):
    ev = TASKS / f'{task_id}-evidence.json'
    if not ev.exists():
        step1 = step_output(task_id, 'step1_data')
        if step1.exists():
            text = step1.read_text(encoding='utf-8', errors='ignore')
            rows = []
            for line in text.splitlines():
                if 'http' in line:
                    rows.append({
                        'section': 'step1_data',
                        'claim': line[:200],
                        'source_title': '',
                        'source_url': line[line.find('http'):].strip(),
                        'confidence': 'medium',
                    })
            ev.write_text(json.dumps({'task_id': task_id, 'rows': rows}, ensure_ascii=False, indent=2), encoding='utf-8')
    run(['python3', str(ROOT / 'scripts' / 'build_ir_source_audit.py'), task_id])


def run_full(task_id: str, entity: str, market: str, session_id: str) -> dict:
    results = {'task_id': task_id, 'waves': []}
    for wave in LAUNCH_WAVES:
        wave_res = []
        for step in wave:
            missing = [dep for dep in STEP_DEPS[step] if not step_output(task_id, dep).exists()]
            if missing:
                wave_res.append({'step': step, 'ok': False, 'error': f'deps missing: {missing}'})
                continue
            d = dispatch_step(task_id, step, entity, market)
            if not d['ok']:
                wave_res.append({'step': step, 'ok': False, 'error': d['error']})
                continue
            w = wait_for_step(task_id, step)
            wave_res.append({'step': step, **w})
            if not w['ok']:
                return {'ok': False, 'failed_step': step, 'waves': results['waves'] + [wave_res]}
        results['waves'].append(wave_res)

    ensure_evidence_artifacts(task_id)
    v = run(['python3', str(VERIFY), '--task-id', task_id, '--pipeline', 'ir'])
    d = run(['python3', str(DELIVER), task_id, '--session-id', session_id])
    return {
        'ok': d.returncode == 0,
        'waves': results['waves'],
        'verification': v.stdout if v.stdout else v.stderr,
        'delivery': d.stdout if d.stdout else d.stderr,
    }


def main():
    ap = argparse.ArgumentParser(description='IR 自动续跑 orchestrator')
    ap.add_argument('task_id')
    ap.add_argument('--entity', required=True)
    ap.add_argument('--market', default='hk')
    ap.add_argument('--session-id', required=True)
    args = ap.parse_args()
    result = run_full(args.task_id, args.entity, args.market, args.session_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result.get('ok') else 1)


if __name__ == '__main__':
    main()

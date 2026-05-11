#!/usr/bin/env python3
"""
IR Contradiction Checker — Perplexity 跨源矛盾检测
==================================================

Perplexity Deep Research 核心能力：同一事实需要多来源交叉验证，
不同来源的量化数据矛盾时需要自动标记。

检查范围：
1. 财务数据对账（step1 vs step4）
2. 行业数据交叉（step2 vs step5）
3. 估值一致性（step6 vs step4）
4. 风险一致性（step7 vs step3）
5. 时效性检查（引用数据是否过时）

用法：
  python3 scripts/ir_contradiction_checker.py --task-id TASK-XXX
"""
from __future__ import annotations
import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

WORKSPACE = Path(__file__).resolve().parent.parent
TASKS_DIR = WORKSPACE / 'data' / 'tasks'

STEP_ORDER = [
    'step1_data', 'step2_industry', 'step3_biz', 'step4_finance',
    'step5_mgmt', 'step6_insight', 'step7_risk', 'step8_master',
]

STEP_NAMES = {
    'step1_data': '行情与基础数据',
    'step2_industry': '行业与市场格局',
    'step3_biz': '业务模式',
    'step4_finance': '财务分析',
    'step5_mgmt': '管理与治理',
    'step6_insight': '投资洞察',
    'step6b_valuation': '预测与估值',
    'step7_risk': '风险提示',
    'step8_master': '统稿',
}

# 时效性阈值（多少年前的数据需要标注）
DATA_STALENESS_YEARS = 2
CURRENT_YEAR = datetime.now().year


def extract_numbers(text: str, step: str) -> list[dict]:
    """从文本中提取量化数据（数字+上下文）。"""
    numbers = []
    # 金额模式
    for m in re.finditer(r'([0-9,]+(?:\.[0-9]+)?)(\s*)(亿元|万元|亿美元|百万|万亿|亿|万|元|美元)?(?:\s*(元|美元|RMB|USD|港元)?)?', text):
        val = m.group(1).replace(',', '')
        unit = (m.group(3) or '') + (m.group(4) or '')
        context = _get_context(text, m.start(), 100)
        numbers.append({
            'raw': m.group(0),
            'value': float(val) if '.' in val else int(val),
            'unit': unit,
            'context': context,
            'step': step,
            'line': text[:m.start()].count('\n') + 1,
            'type': 'money',
        })

    # 百分比
    for m in re.finditer(r'([0-9]+(?:\.[0-9]+)?)\s*%', text):
        context = _get_context(text, m.start(), 100)
        numbers.append({
            'raw': m.group(0),
            'value': float(m.group(1)),
            'unit': '%',
            'context': context,
            'step': step,
            'line': text[:m.start()].count('\n') + 1,
            'type': 'pct',
        })

    # 关键指标（市盈率、ROE 等）
    for m in re.finditer(r'(市盈率|市净率|ROE|毛利率|净利率|负债率|PE|PB|市值)\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?)', text):
        context = _get_context(text, m.start(), 100)
        numbers.append({
            'raw': m.group(0),
            'metric': m.group(1),
            'value': float(m.group(2)),
            'unit': '',
            'context': context,
            'step': step,
            'line': text[:m.start()].count('\n') + 1,
            'type': 'metric',
        })

    return numbers


def _get_context(text: str, pos: int, radius: int) -> str:
    start = max(0, pos - radius)
    end = min(len(text), pos + radius)
    snippet = text[start:end].replace('\n', ' ').strip()
    return '...' + snippet if start > 0 else snippet


def check_financial_contradiction(step1_nums: list, step4_nums: list) -> list[dict]:
    """检查 step1（基本数据）和 step4（财务分析）之间的财务矛盾。"""
    contradictions = []

    # 提取市盈率对比
    s1_pe = [n for n in step1_nums if n.get('metric', '').lower() in ('pe', '市盈率')]
    s4_pe = [n for n in step4_nums if n.get('metric', '').lower() in ('pe', '市盈率')]
    if s1_pe and s4_pe:
        diff = abs(s1_pe[0]['value'] - s4_pe[0]['value'])
        avg = (s1_pe[0]['value'] + s4_pe[0]['value']) / 2
        if avg > 0 and diff / avg > 0.2:  # 差异 >20%
            contradictions.append({
                'type': 'PE_ratio_mismatch',
                'severity': 'HIGH',
                'step1': f"PE={s1_pe[0]['value']}（{s1_pe[0]['context'][:80]}）",
                'step4': f"PE={s4_pe[0]['value']}（{s4_pe[0]['context'][:80]}）",
                'detail': f'市盈率差异 {diff:.1f}（{diff/avg*100:.1f}%），需要统一口径',
            })

    # 提取市值对比
    s1_mcap = [n for n in step1_nums if n.get('metric', '') == '市值' or ('市值' in n.get('context', ''))]
    s4_mcap = [n for n in step4_nums if '市值' in n.get('context', '')]
    if s1_mcap and s4_mcap:
        diff = abs(s1_mcap[0]['value'] - s4_mcap[0]['value'])
        avg = (s1_mcap[0]['value'] + s4_mcap[0]['value']) / 2
        if avg > 0 and diff / avg > 0.3:  # 差异 >30%
            contradictions.append({
                'type': 'market_cap_mismatch',
                'severity': 'MEDIUM',
                'step1': f"市值={s1_mcap[0]['value']}（{s1_mcap[0]['unit']}）",
                'step4': f"市值={s4_mcap[0]['value']}（{s4_mcap[0]['unit']}）",
                'detail': f'市值差异 {diff:.1f}（{diff/avg*100:.1f}%），可能因更新时间不同',
            })

    # 提取营收对比
    s1_rev = [n for n in step1_nums if '营收' in n.get('context', '').lower() or '收入' in n.get('context', '').lower()]
    s4_rev = [n for n in step4_nums if '营收' in n.get('context', '').lower() or '收入' in n.get('context', '').lower() or 'revenue' in n.get('context', '').lower()]
    if s1_rev and s4_rev:
        diff = abs(s1_rev[0]['value'] - s4_rev[0]['value'])
        avg = (s1_rev[0]['value'] + s4_rev[0]['value']) / 2
        if avg > 0 and diff / avg > 0.2:
            contradictions.append({
                'type': 'revenue_mismatch',
                'severity': 'HIGH',
                'step1': f"营收={s1_rev[0]['value']}（{s1_rev[0]['unit']}）",
                'step4': f"营收={s4_rev[0]['value']}（{s4_rev[0]['unit']}）",
                'detail': f'营收差异 {diff:.1f}（{diff/avg*100:.1f}%）',
            })

    return contradictions


def check_industry_contradiction(step2_nums: list, step5_nums: list) -> list[dict]:
    """检查行业数据（step2）vs 管理层信息（step5）的一致性。"""
    contradictions = []

    # 市场份额交叉验证
    s2_share = [n for n in step2_nums if '份额' in n.get('context', '') or '市占' in n.get('context', '')]
    s5_share = [n for n in step5_nums if '份额' in n.get('context', '')]
    if s2_share and s5_share:
        diff = abs(s2_share[0]['value'] - s5_share[0]['value'])
        avg = (s2_share[0]['value'] + s5_share[0]['value']) / 2
        if avg > 0 and diff / avg > 0.3:
            contradictions.append({
                'type': 'market_share_mismatch',
                'severity': 'MEDIUM',
                'step2': f"市占={s2_share[0]['value']}%",
                'step5': f"市占={s5_share[0]['value']}%",
                'detail': f'市场份额差异 {diff:.1f}pp',
            })

    return contradictions


def check_valuation_contradiction(step4_nums: list, step6_nums: list) -> list[dict]:
    """检查财务估值（step4）vs 投资洞察（step6）的一致性。"""
    contradictions = []

    # 目标价 vs 当前价
    s4_price = [n for n in step4_nums if '股价' in n.get('context', '') or 'price' in n.get('context', '').lower()]
    s6_target = [n for n in step6_nums if '目标' in n.get('context', '') or 'target' in n.get('context', '').lower()]
    if s6_target:
        target = s6_target[0]['value']
        current = s4_price[0]['value'] if s4_price else None
        if current and target > 0:
            upside = (target - current) / current * 100
            if upside > 100 or upside < -50:
                contradictions.append({
                    'type': 'valuation_extreme',
                    'severity': 'LOW',
                    'detail': f'目标价 {target} vs 当前价 {current}，上行空间 {upside:.1f}%，偏差极端',
                    'step4': f"当前价={current}",
                    'step6': f"目标价={target}",
                })

    return contradictions


def check_temporal_staleness(all_numbers: list) -> list[dict]:
    """检查数据是否过时（超过阈值年份）。"""
    stale = []
    current_year = CURRENT_YEAR

    for num in all_numbers:
        ctx = num.get('context', '').lower()
        # 提取年份
        year_match = re.search(r'(20[1-2][0-9])\s*年', ctx)
        if year_match:
            yr = int(year_match.group(1))
            if yr < current_year - DATA_STALENESS_YEARS:
                stale.append({
                    'type': 'data_staleness',
                    'severity': 'MEDIUM',
                    'context': num['context'][:100],
                    'year_mentioned': yr,
                    'current_year': current_year,
                    'step': num['step'],
                    'detail': f'引用 {yr} 年数据（当前 {current_year} 年），已过期 {current_year - yr} 年',
                })

    return stale


def check_missing_citations(task_id: str) -> list[dict]:
    """检查缺少来源引用的 step。"""
    issues = []
    for step in STEP_ORDER:
        fpath = TASKS_DIR / f'{task_id}-{step}.md'
        if not fpath.exists():
            issues.append({
                'type': 'missing_step',
                'severity': 'HIGH',
                'step': step,
                'detail': f'{STEP_NAMES.get(step, step)} 文件缺失',
            })
            continue

        text = fpath.read_text(encoding='utf-8')
        urls = len(re.findall(r'https?://', text))
        if urls == 0 and len(text) > 500:
            issues.append({
                'type': 'no_citations',
                'severity': 'HIGH',
                'step': step,
                'detail': f'{len(text)} 字符内容，但无任何来源 URL',
            })
        elif urls < 2 and len(text) > 2000:
            issues.append({
                'type': 'low_citations',
                'severity': 'MEDIUM',
                'step': step,
                'detail': f'{len(text)} 字符内容，仅 {urls} 个 URL',
            })

    return issues


def run_contradiction_check(task_id: str) -> dict:
    """执行完整矛盾检测流程。"""
    step_numbers = {}
    all_numbers = []

    # 1. 提取所有 step 的量化数据
    for step in STEP_ORDER:
        fpath = TASKS_DIR / f'{task_id}-{step}.md'
        if fpath.exists():
            text = fpath.read_text(encoding='utf-8')
            nums = extract_numbers(text, step)
            step_numbers[step] = nums
            all_numbers.extend(nums)

    # 2. 财务对账
    contradictions = []
    if 'step1_data' in step_numbers and 'step4_finance' in step_numbers:
        contradictions.extend(check_financial_contradiction(
            step_numbers['step1_data'], step_numbers['step4_finance']
        ))

    # 3. 行业交叉
    if 'step2_industry' in step_numbers and 'step5_mgmt' in step_numbers:
        contradictions.extend(check_industry_contradiction(
            step_numbers['step2_industry'], step_numbers['step5_mgmt']
        ))

    # 4. 估值一致性
    if 'step4_finance' in step_numbers and 'step6_insight' in step_numbers:
        contradictions.extend(check_valuation_contradiction(
            step_numbers['step4_finance'], step_numbers['step6_insight']
        ))

    # 5. 时效性检查
    staleness = check_temporal_staleness(all_numbers)

    # 6. 缺失来源检查
    citation_issues = check_missing_citations(task_id)

    # 汇总
    all_issues = contradictions + staleness + citation_issues
    high_count = sum(1 for i in all_issues if i.get('severity') == 'HIGH')
    medium_count = sum(1 for i in all_issues if i.get('severity') == 'MEDIUM')
    low_count = sum(1 for i in all_issues if i.get('severity') == 'LOW')

    return {
        'total_quant_claims': len(all_numbers),
        'contradictions': contradictions,
        'staleness': staleness,
        'citation_issues': citation_issues,
        'summary': {
            'total_issues': len(all_issues),
            'high': high_count,
            'medium': medium_count,
            'low': low_count,
            'passed': high_count == 0,
        },
        'detail': all_issues,
    }


def print_report(result: dict):
    """打印矛盾检测报告。"""
    s = result['summary']
    print(f"\n{'='*60}")
    print("  矛盾检测报告")
    print(f"{'='*60}")
    print(f"\n  量化声明: {result['total_quant_claims']} 条")
    print(f"  问题总数: {s['total_issues']} (高 {s['high']} / 中 {s['medium']} / 低 {s['low']})")
    print(f"  状态: {'✅ 通过' if s['passed'] else '❌ 发现高优先级问题'}")

    if result['contradictions']:
        print(f"\n  ⚠️ 数据矛盾 ({len(result['contradictions'])} 处):")
        for c in result['contradictions']:
            print(f"    [{c['severity']}] {c['type']}")
            print(f"      {c.get('detail', '')}")

    if result['staleness']:
        print(f"\n  ⏰ 过时数据 ({len(result['staleness'])} 处):")
        for s_item in result['staleness'][:5]:
            print(f"    [{s_item['severity']}] {s_item['detail']}")

    if result['citation_issues']:
        print(f"\n  🔗 来源问题 ({len(result['citation_issues'])} 处):")
        for c in result['citation_issues'][:5]:
            print(f"    [{c['severity']}] {c['step']}: {c['detail']}")

    # 写入文件
    task_id = result.get('task_id', '')
    if task_id:
        report_path = TASKS_DIR / f'{task_id}-contradiction-report.json'
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"\n  报告已写入: {report_path}")


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--task-id', required=True)
    args = ap.parse_args()

    result = run_contradiction_check(args.task_id)
    result['task_id'] = args.task_id
    print_report(result)

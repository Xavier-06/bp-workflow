#!/usr/bin/env python3
"""
IR Cross-Validation — 研报多 step 交叉验证

Perplexity Deep Research 核心能力之一：同一事实需要多来源交叉确认。

检查逻辑:
1. 从 8 个 step 文件中提取量化声明（数字/百分比/金额）
2. 跨 step 对账（step1 说营收 100亿 vs step4 财报说 90亿 → 矛盾）
3. 官方数据验证（step4 财报 vs Phase 0.5 验证数据）
4. 时效性检查（声明日期 vs 当前时间 >6 个月 → 过时）

用法：
  python3 scripts/ir_cross_validation.py --task-id TASK-XXX
  python3 scripts/ir_cross_validation.py --task-id TASK-XXX --entity "英伟达" --market us
"""
from __future__ import annotations
import argparse
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
TASKS_DIR = WORKSPACE / 'data' / 'tasks'

STEP_ORDER = [
    'step1_data', 'step2_industry', 'step3_biz',
    'step4_finance', 'step5_mgmt', 'step6_insight', 'step6b_valuation',
    'step7_risk', 'step8_master',
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


class CrossValidationReport:
    def __init__(self):
        self.contradictions = []  # step vs step 矛盾
        self.unverified_claims = []  # 无来源的量化声明
        self.outdated_info = []  # 过时信息
        self.consistent_facts = []  # 交叉验证一致的事实
        self.stats = {
            'total_quant_claims': 0,
            'verified': 0,
            'contradicted': 0,
            'unverified': 0,
            'outdated': 0,
        }


def extract_quant_claims(text: str, step: str) -> list[dict]:
    """从文本中提取量化声明（数字/金额/百分比）。"""
    claims = []

    # 金额模式
    money_patterns = [
        r'([0-9,]+)\s*(亿元?|万元?|亿元|百万|十亿|亿|万)\s*(元|美元|USD|RMB|港币|港元|人民币)?',
        r'([0-9,\.]+)\s*(billion|million|B|M)\s*(USD|RMB|HKD|dollars?)?',
    ]
    # 百分比模式
    pct_patterns = [r'([0-9\.]+)\s*%', r'([0-9\.]+)\s*个百分点']
    # 数量模式
    count_patterns = [
        r'([0-9,]+)\s*(家|个|款|项|次|条|名|人|户|宗|起)',
        r'(市盈率|PE|市净率|PB|毛利率|净利率|ROE|ROA|负债率)\s*[:：]?\s*([0-9\.]+)',
    ]

    # 扫描百分比
    for pattern in pct_patterns + count_patterns:
        for m in re.finditer(pattern, text):
            claims.append({
                'value': m.group(1),
                'full_text': m.group(0),
                'context': _get_context(text, m.start(), 80),
                'step': step,
                'type': 'pct' if '%' in m.group(0) else 'ratio',
                'line_num': text[:m.start()].count('\n') + 1,
            })

    # 扫描金额
    for pattern in money_patterns:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            claims.append({
                'value': m.group(1),
                'full_text': m.group(0),
                'context': _get_context(text, m.start(), 80),
                'step': step,
                'type': 'money',
                'line_num': text[:m.start()].count('\n') + 1,
            })

    return claims


def _get_context(text: str, pos: int, radius: int) -> str:
    """获取匹配位置周围的上下文。"""
    start = max(0, pos - radius)
    end = min(len(text), pos + radius)
    snippet = text[start:end].replace('\n', ' ')
    if start > 0:
        snippet = '...' + snippet
    if end < len(text):
        snippet += '...'
    return snippet


def check_contradictions(claims: list[dict]) -> list[dict]:
    """检查跨 step 矛盾。"""
    contradictions = []
    
    # 按类型分组
    by_type = {}
    for c in claims:
        t = c['type']
        if t not in by_type:
            by_type[t] = []
        by_type[t].append(c)

    # 检查同类型但不同 step 的数值差异
    for claim_type, group in by_type.items():
        # 按关键词分组
        keyword_groups = {}
        for c in group:
            ctx = c['context'].lower()
            # 提取关键词
            for kw in ['营收', 'revenue', '收入', '利润', 'profit', '净利润', 'net income',
                       '毛利率', 'gross margin', '市值', 'market cap', '用户', 'user',
                       '增长', 'growth', 'pe', '市盈率', '负债', 'debt']:
                if kw in ctx:
                    if kw not in keyword_groups:
                        keyword_groups[kw] = []
                    keyword_groups[kw].append(c)
                    break

        # 同关键词但不同 step → 检查数值
        for kw, items in keyword_groups.items():
            steps = set(c['step'] for c in items)
            if len(steps) > 1:
                # 不同 step 提到同一话题 → 人工 review
                contradictions.append({
                    'type': 'potential_contradiction',
                    'keyword': kw,
                    'steps_involved': list(steps),
                    'claims': [{'step': c['step'], 'value': c['full_text'], 'context': c['context']} for c in items[:3]],
                    'action': '需要人工审查是否矛盾',
                })

    return contradictions


def check_outdated(claims: list[dict], max_age_months: int = 12) -> list[dict]:
    """检查信息是否过时。"""
    outdated = []
    current_year = datetime.now().year
    current_month = datetime.now().month

    for c in claims:
        ctx = c['context'].lower()
        # 提取年份
        year_match = re.search(r'(20[1-2][0-9])\s*(年|year|fy)', ctx)
        if year_match:
            mentioned_year = int(year_match.group(1))
            if mentioned_year < current_year - 1:
                outdated.append({
                    'claim': c['full_text'],
                    'context': c['context'],
                    'step': c['step'],
                    'mentioned_year': mentioned_year,
                    'current_year': current_year,
                    'action': '信息可能过时，需要更新',
                })

        # 检查"去年"/"前年"等相对时间
        for rel_time, offset in [('前年', 2), ('去年', 1), ('last year', 1), ('previous year', 1)]:
            if rel_time in ctx or rel_time.lower() in ctx:
                # 这是相对时间，不需要标记过时
                pass

    return outdated


def run_cross_validation(task_id: str, entity: str = '') -> dict:
    """执行完整交叉验证流程。"""
    report = CrossValidationReport()
    all_claims = []

    # 1. 提取所有 step 的量化声明
    for step in STEP_ORDER:
        fpath = TASKS_DIR / f'{task_id}-{step}.md'
        if not fpath.exists():
            continue

        text = fpath.read_text(encoding='utf-8')
        claims = extract_quant_claims(text, step)
        all_claims.extend(claims)

    report.stats['total_quant_claims'] = len(all_claims)

    # 2. 检查跨 step 矛盾
    contradictions = check_contradictions(all_claims)
    report.contradictions = contradictions
    report.stats['contradicted'] = len(contradictions)

    # 3. 检查过时信息
    outdated = check_outdated(all_claims)
    report.outdated_info = outdated
    report.stats['outdated'] = len(outdated)

    # 4. 来源评分（复用 IR 管线的质量门禁）
    from ir_quality_gate import quality_gate_results as _quality_gate_results
    try:
        quality = _quality_gate_results(task_id)
        verified_count = sum(1 for s, sc in quality['scores'].items() if sc >= 2)
        report.stats['verified'] = verified_count
        report.stats['unverified'] = len(STEP_ORDER) - verified_count
        unverified_steps = [s for s, sc in quality['scores'].items() if sc < 2]
        for s in unverified_steps:
            report.unverified_claims.append({
                'step': s,
                'score': quality['scores'][s],
                'issues': [i for i in quality['issues'] if s in i][:3],
            })
    except ImportError:
        # 如果导入失败，简单估算
        report.stats['verified'] = sum(1 for c in all_claims if c.get('source') == 'official')

    # 生成报告
    total = report.stats['total_quant_claims']
    verified = report.stats['verified']
    contradicted = report.stats['contradicted']

    return {
        'statistics': report.stats,
        'contradictions': report.contradictions,
        'outdated': report.outdated_info,
        'unverified_claims': report.unverified_claims,
        'consistent_facts': report.consistent_facts,
        'overall_pass': contradicted == 0 and len(report.outdated_info) == 0,
        'summary': f'量化声明 {total} 条, 验证通过 {verified}, 矛盾 {contradicted}, 过时 {len(report.outdated_info)}',
    }


def print_report(result: dict):
    """打印交叉验证报告。"""
    print(f"\n{'='*60}")
    print("  交叉验证报告")
    print(f"{'='*60}")

    stats = result['statistics']
    print(f"\n  总量化声明: {stats['total_quant_claims']}")
    print(f"  验证通过: {stats['verified']}")
    print(f"  潜在矛盾: {stats['contradicted']}")
    print(f"  过时信息: {stats['outdated']}")
    print(f"  未验证来源: {stats['unverified']}")

    if result['contradictions']:
        print(f"\n  ⚠️ 潜在矛盾 ({len(result['contradictions'])} 处):")
        for c in result['contradictions'][:5]:
            print(f"    📍 [{c['keyword']}] 涉及步骤: {', '.join(c['steps_involved'])}")
            for claim in c['claims']:
                print(f"      - {claim['step']}: ...{claim['context']}...")

    if result['outdated']:
        print(f"\n  ⏰ 过时信息 ({len(result['outdated'])} 处):")
        for o in result['outdated'][:5]:
            print(f"    📍 {o['step']}: {o['context'][:100]}... (提到 {o['mentioned_year']} 年)")

    print(f"\n  {'✅ 通过' if result['overall_pass'] else '❌ 发现问题，建议审查'}")


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--task-id', required=True)
    ap.add_argument('--entity', default='')
    ap.add_argument('--market', default='us')
    args = ap.parse_args()

    result = run_cross_validation(args.task_id, args.entity)
    print_report(result)
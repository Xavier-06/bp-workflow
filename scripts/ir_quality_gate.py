#!/usr/bin/env python3
"""
IR 质量评估标准 — IR 管线和交叉验证模块共享
从 run_ir_pipeline.py 提取，避免循环依赖。
"""
from __future__ import annotations
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
TASKS_DIR_IR = WORKSPACE / 'data' / 'tasks'

STEP_ORDER = [
    'step1_data', 'step2_industry', 'step3_biz',
    'step4_finance', 'step5_mgmt', 'step6_insight',
    'step6b_valuation', 'step7_risk', 'step8_master',
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

MIN_OVERALL_SCORE = 18  # 9 维度，每维 0-3，≥18 才达标（平均 2/3）

RED_FLAGS = ['待补', '待填', 'TODO', '无法验证', '无法获取', '需要进一步', '[待补]']

OFFICIAL_DOMAINS = ['sec.gov', 'hkexnews.hk', 'cninfo.com.cn', 'szse.cn', 'sse.com.cn',
                    'ir.', 'investor.', 'investors.']
REPUTABLE_DOMAINS = ['reuters.com', 'bloomberg.com', 'wsj.com', 'ft.com', 'economist.com',
                     'scmp.com', 'caixin.com', '36kr.com', 'cls.cn', 'eastmoney.com',
                     'xueqiu.com', 'zhihu.com', 'wikipedia.org']


def check_step_quality(text: str) -> int:
    """单 step 质量评分 (0-3)。"""
    sz = len(text)
    if sz < 200:
        return 0

    text_lower = text.lower()
    official_count = sum(1 for d in OFFICIAL_DOMAINS if d in text_lower)
    reputable_count = sum(1 for d in REPUTABLE_DOMAINS if d in text_lower)
    url_count = text.count('http')

    if official_count >= 2 and sz > 2000:
        score = 3
    elif (official_count >= 1 or reputable_count >= 2) and sz > 1000:
        score = 2
    elif url_count >= 1:
        score = 1
    else:
        score = 0

    flags = sum(1 for flag in RED_FLAGS if flag in text)
    if flags >= 3 and score > 1:
        score = max(1, score - 1)

    return score


def quality_gate_results(task_id: str, step_order=None, step_names=None,
                         min_score=None, tasks_dir=None) -> dict:
    """
    通用质量门禁。从 run_ir_pipeline.py 的 _quality_gate_results 提取。
    参数全部可选，使用模块默认值。
    """
    if step_order is None:
        step_order = STEP_ORDER
    if step_names is None:
        step_names = STEP_NAMES
    if min_score is None:
        min_score = MIN_OVERALL_SCORE
    if tasks_dir is None:
        tasks_dir = TASKS_DIR_IR

    scores = {}
    issues = []
    for step in step_order:
        fpath = tasks_dir / f'{task_id}-{step}.md'
        if not fpath.exists():
            scores[step] = 0
            issues.append(f"❰{step}❱ 文件缺失")
            continue

        text = fpath.read_text(encoding='utf-8')
        sz = len(text)
        if sz < 200:
            scores[step] = 0
            issues.append(f"❰{step}❱ 内容过短 ({sz} 字符)")
            continue

        score = check_step_quality(text)

        flags = sum(1 for flag in RED_FLAGS if flag in text)
        if flags >= 3 and score > 1:
            issues.append(f"❰{step}❱ {flags} 处红旗标记")

        scores[step] = score
        if score < 2:
            label = step_names.get(step, step)
            text_lower = text.lower()
            official_count = sum(1 for d in OFFICIAL_DOMAINS if d in text_lower)
            reputable_count = sum(1 for d in REPUTABLE_DOMAINS if d in text_lower)
            url_count = text.count('http')
            issues.append(f"❰{label}❱ 得分 {score}/3"
                         f"(官方={official_count}, 权威={reputable_count}, URL={url_count})")

    total = sum(scores.values())
    return {
        'scores': scores,
        'total': total,
        'max_possible': len(step_order) * 3,
        'passed': total >= min_score,
        'issues': issues,
        'threshold': min_score,
    }

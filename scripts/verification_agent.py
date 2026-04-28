#!/usr/bin/env python3
"""
Adversarial Verification Agent v2 — 对抗式研报/BP 验证
灵感来源：Claude Code free-code VerificationAgent（完整移植）

与现有验证的区别：
- bp_verify_consistency.py: 确认式（找泄露/占位 → PASS）
- ir_quality_gate.py:       打分式（来源数+字数 → 过阈值 PASS）
- ir_cross_validation.py:   对账式（跨 step 矛盾 → 标记）
- **verification_agent.py:  对抗式（主动证明报告是错的 → 找不到才 PASS）**

6 类验证（对标 free-code 的 VERIFICATION STRATEGY + ADVERSARIAL PROBES）：
1. L1_Internal 信息泄露
2. L2_Placeholder 占位残留
3. L3_Contradiction 内部矛盾（结论 vs 分析）
4. L4_Number_Claim 数字声明可验证性
5. L5_Logic_Flaw 逻辑漏洞
6. L6_Adversarial 反向论证（对标 free-code）

对标 free-code 的「识别你自己的合理化冲动」：
- "代码看起来对" → 运行它
- "测试已经过了" → 测试者是 LLM，独立验证
- "这可能需要太久" → 不是你的决定

输出格式（对标 free-code 的 REQUIRED OUTPUT FORMAT）：
  每条检查必须有：Check / Verification / Output / Result
  最后必须有：VERDICT: PASS 或 VERDICT: FAIL

用法：
  python3 verification_agent.py --task-id TASK-XXX --pipeline ir
  python3 verification_agent.py --task-id TASK-XXX --pipeline bp
  python3 verification_agent.py --docx /path/to/report.docx --pipeline ir
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Literal, Optional

WORKSPACE = Path(__file__).resolve().parent.parent
TASKS_DIR = WORKSPACE / 'data' / 'tasks'

sys.path.insert(0, str(Path(__file__).resolve().parent))

# ── 内部信息泄露（共用 bp_verify_consistency.py 的黑名单） ──
LEAK_PATTERNS = [
    (r'/Users/\S+', '内部文件路径'),
    (r'file://\S+', '内部文件 URI'),
    (r'sessions_spawn', '会话派发指令'),
    (r'\bsubagent\b', '子代理术语'),
    (r'instruction_store\w*', '指令库路径'),
    (r'\.openclaw/\S+', 'OpenClaw 内部路径'),
    (r'scripts/[^\s,.;]+\.py', '脚本路径'),
    (r'bp_presearch\w*', '内部脚本名'),
    (r'bp_preflight\w*', '内部脚本名'),
    (r'thinking=high', '推理参数'),
    (r'Step [0-4]', 'Step 编号'),
    (r'step[1-7]_', 'step 脚本名'),
    (r'下游子代理', '内部术语'),
    (r'搜索词组合', '内部术语'),
    (r'主控必须', '内部指令'),
    (r'输出.*行.*通过', '自检打分'),
    (r'信条[：:]', '内部信条'),
    (r'找到发动机.*标记油箱', '内部信条'),
    (r'简历上写的都是广告', '内部格言'),
    (r'搜索查询[：:]', '搜索调试信息'),
    (r'搜索结果.*条.*无.*匹配', '搜索调试信息'),
]

PLACEHOLDER_PATTERNS = [
    (r'未识[^\s]{0,3}', '占位：未识别'),
    (r'待补充', '占位：待补充'),
    (r'待填写', '占位：待填写'),
    (r'\[待补\]', '占位：[待补]'),
    (r'需要进一步[^\s]{0,10}研究', '占位：需进一步研究'),
    (r'TODO', '占位：TODO'),
]

# ── 数据类 ──────────────────────────────────────────────────
@dataclass
class VerificationCheck:
    """单条验证检查（对标 free-code 的 Check 格式）"""
    name: str
    verification: str
    output: str
    result: Literal['PASS', 'FAIL', 'WARN']
    detail: str = ''


# ── 报告内容提取 ──────────────────────────────────────────────
def load_bp_content(task_id: str, tasks_dir: Path = TASKS_DIR) -> Optional[str]:
    """加载 BP 统稿内容（支持多种文件名格式）"""
    # Priority 1: 统稿文件
    report_file = tasks_dir / f'{task_id}-bp_final_report.md'
    if report_file.exists():
        return report_file.read_text(encoding='utf-8')
    for f in tasks_dir.glob(f'{task_id}*final*'):
        return f.read_text(encoding='utf-8')

    # Priority 2: BP step files (合并所有 step)
    combined = ''
    for f in sorted(tasks_dir.glob(f'{task_id}-step*.md')):
        combined += f.read_text(encoding='utf-8') + '\n\n'
    if combined.strip():
        return combined

    # Priority 3: tasks/ 子目录下的 step 文件
    sub_dir = tasks_dir / task_id
    if sub_dir.exists():
        combined2 = ''
        for f in sorted(sub_dir.glob(f'{task_id}-step*.md')):
            combined2 += f.read_text(encoding='utf-8') + '\n\n'
        if combined2.strip():
            return combined2

    return None


def load_ir_steps(task_id: str, tasks_dir: Path = TASKS_DIR) -> dict[str, str]:
    """加载 IR 管线各 step 内容"""
    steps = {}
    step_names = ['step1_data', 'step2_industry', 'step3_biz',
                  'step4_finance', 'step5_mgmt', 'step6_insight',
                  'step7_risk', 'step8_master']
    for s in step_names:
        f = tasks_dir / f'{task_id}-{s}.md'
        if f.exists():
            steps[s] = f.read_text(encoding='utf-8')
    return steps


def load_report_content(task_id: str = None, docx_path: str = None,
                        pipeline: str = 'ir', tasks_dir: Path = TASKS_DIR) -> Optional[str]:
    """统一报告内容加载"""
    if task_id:
        if pipeline == 'bp':
            return load_bp_content(task_id, tasks_dir)
        else:
            steps = load_ir_steps(task_id, tasks_dir)
            return steps.get('step8_master', steps.get('step7_risk', ''))
    return None


# ── 数字提取 ──────────────────────────────────────────────────
def extract_claims(text: str) -> list[dict]:
    """
    从文本中提取量化声明（对标 free-code 的 claim cards）。

    v2 修复：只提取有明确单位或货币的数字，避免年份、逗号等匹配。
    """
    claims = []
    if not text:
        return claims

    # 金额/营收/利润 — 必须有单位（亿/万/百万/等），单独数字不算
    amount_pattern = r'(\d{1,3}(?:[,\.]\d{1,2})?(?:\.\d+)?)\s*(亿|万|百万|千万)'
    for m in re.finditer(amount_pattern, text):
        amount = m.group(1)
        unit = m.group(2)
        start = max(0, m.start() - 100)
        end = min(len(text), m.end() + 100)
        context = text[start:end].strip()
        claims.append({
            'type': 'amount',
            'value': f'{amount}{unit}',
            'context': context[:200],
        })

    # 百分比
    pct_pattern = r'(\d{1,3}\.\d{1,2}|\d{1,3})\s*%'
    for m in re.finditer(pct_pattern, text):
        pct = m.group(1)
        start = max(0, m.start() - 80)
        end = min(len(text), m.end() + 80)
        context = text[start:end].strip()
        claims.append({
            'type': 'percentage',
            'value': f'{pct}%',
            'context': context[:200],
        })

    # 日期/时效 — 年份，但要排除明显是金额上下文的
    year_pattern = r'(20[0-2]\d)\s*年'
    for m in re.finditer(year_pattern, text):
        year = m.group(1)
        claims.append({
            'type': 'date',
            'value': year,
            'context': text[max(0,m.start()):m.start()+100],
        })

    return claims


# ── 对抗式验证引擎 ────────────────────────────────────────────
class AdversarialVerifier:
    """
    对标 Claude Code free-code 的 VerificationAgent：

    不是"确认报告能用"
    而是"找到报告哪里错了"

    6 类验证：
    1. L1_Internal    内部信息泄露
    2. L2_Placeholder 占位残留
    3. L3_Contradiction 内部矛盾
    4. L4_Number_Claim   数字声明可验证性
    5. L5_Logic_Flaw   逻辑漏洞
    6. L6_Adversarial  反向论证（对标 free-code 的 ADVERSARIAL PROBES）
    """

    def __init__(self, pipeline: str = 'ir'):
        self.pipeline = pipeline
        self.checks: list[VerificationCheck] = []
        self.verdict: Literal['PASS', 'FAIL', 'WARN'] = 'PASS'

    # ────────── L1: 内部信息泄露 ──────────
    def check_internal_leaks(self, text: str):
        leaked = []
        for pattern, label in LEAK_PATTERNS:
            matches = list(re.findall(pattern, text, re.IGNORECASE))
            if matches:
                unique = list(set(matches))
                leaked.append((label, len(matches), unique[:2]))

        if leaked:
            for label, count, samples in leaked:
                sample_str = ', '.join(str(s)[:40] for s in samples)
                self.checks.append(VerificationCheck(
                    name='内部信息泄露检测',
                    verification=f'正则扫描 {len(LEAK_PATTERNS)} 个泄露模式',
                    output=f'{label}: {count} 处 (示例: {sample_str})',
                    result='FAIL',
                    detail='交付前必须清洗所有内部信息'
                ))
        else:
            self.checks.append(VerificationCheck(
                name='内部信息泄露检测',
                verification=f'正则扫描 {len(LEAK_PATTERNS)} 个泄露模式',
                output='无内部信息泄露',
                result='PASS',
            ))

    # ────────── L2: 占位残留 ──────────
    def check_placeholders(self, text: str):
        found = []
        for pattern, label in PLACEHOLDER_PATTERNS:
            matches = list(re.findall(pattern, text))
            if matches:
                found.append((label, len(matches)))

        if found:
            for label, count in found:
                self.checks.append(VerificationCheck(
                    name='占位提示残留',
                    verification=f'扫描 {len(PLACEHOLDER_PATTERNS)} 个占位模式',
                    output=f'{label}: {count} 处',
                    result='FAIL',
                    detail='最终报告不应有占位提示'
                ))
        else:
            self.checks.append(VerificationCheck(
                name='占位提示残留',
                verification=f'扫描 {len(PLACEHOLDER_PATTERNS)} 个占位模式',
                output='无占位提示残留',
                result='PASS',
            ))

    # ────────── L3: 内部矛盾 ──────────
    def check_contradictions(self, text: str, steps: dict = None):
        contradictions = []
        text_lower = text.lower()

        # 投资结论矛盾（对标 free-code 的 "recognize rationalizations"）
        negative_signals = ['不建议', '回避', '卖出', '减持', '不推荐', '慎入']
        positive_signals = ['买入', '推荐', '增持', '强烈推荐', '看好']

        neg_found = [w for w in negative_signals if w in text]
        pos_found = [w for w in positive_signals if w in text]

        if neg_found and pos_found:
            contradictions.append(
                f'投资结论矛盾：负面信号 {neg_found} vs 正面信号 {pos_found} — '
                '不能同时说"不建议"和"推荐"'
            )

        # 矛盾 2：风险提示在前但结论极度乐观
        if '风险' in text and ('强烈推荐' in text or '强烈推荐' in text_lower):
            risk_section_start = text.find('风险')
            risk_section = text[risk_section_start: risk_section_start + 500]
            if len(risk_section.strip().split('\n')) <= 2:
                contradictions.append(
                    f'风险提示过短但结论极度乐观 — '
                    '风险提示可能未被充分展开'
                )

        # 跨 step 数据矛盾
        if steps:
            self._check_cross_step_contradictions(steps, contradictions)

        if contradictions:
            for c in contradictions:
                self.checks.append(VerificationCheck(
                    name='内部矛盾检测',
                    verification='扫描投资结论矛盾 + 跨维度一致性',
                    output=c,
                    result='FAIL',
                ))
        else:
            self.checks.append(VerificationCheck(
                name='内部矛盾检测',
                verification='扫描投资结论矛盾 + 跨维度一致性',
                output='未发现明显内部矛盾',
                result='PASS',
            ))

    def _check_cross_step_contradictions(self, steps: dict, contradictions: list):
        """
        对标 free-code 的 "test suite results are context, not evidence" ——
        跨 step 对账不只是检查是否有数字，而是检查数字是否打架。
        """
        # 简单版本：检查不同 step 对同一家公司营收的引用是否一致
        revenues = {}
        for step, content in steps.items():
            matches = re.findall(r'营收.*?(\d+\.?\d*)\s*(亿|万|百万)', content)
            for val, unit in matches:
                key = f'{val}{unit}'
                if key not in revenues:
                    revenues[key] = []
                revenues[key].append(step)

        # 如果同一个数字在不同 step 中被引用 → good
        # 如果不同数字都被描述为"营收" → contradiction
        if len(revenues) > 3:
            contradictions.append(
                f'跨 step 数据：发现 {len(revenues)} 种不同的营收表述，'
                f'需人工确认一致性'
            )

    # ────────── L4: 数字声明可验证性 ──────────
    def check_number_claims(self, text: str):
        """
        对标 free-code 的 "A check without a Command run block is not a PASS" ——
        数字声明必须有来源标注，否则不算 PASS。
        """
        claims = extract_claims(text)

        if not claims:
            self.checks.append(VerificationCheck(
                name='数字声明可验证性',
                verification='提取量化声明（金额/百分比/日期）',
                output='未发现量化声明',
                result='WARN',
                detail='研报/尽调应有量化声明'
            ))
            return

        # 分析声明类型分布
        amount_count = sum(1 for c in claims if c['type'] == 'amount')
        pct_count = sum(1 for c in claims if c['type'] == 'percentage')

        # 检查金额是否有来源标注
        amounts_no_source = []
        for c in claims:
            val = c['value']
            # Skip trivial matches
            if len(val) < 3:
                continue
            ctx = c['context']
            if not any(kw in ctx for kw in
                      ['来源', '据', '摘自', '财报', '公告', 'SEC', 'HKEX',
                       '招股书', '年报', 'Q', 'H1', 'H2', 'FY', 'http',
                       'Wind', 'Bloomberg', '彭博', '万得']):
                amounts_no_source.append(c['value'])

        if amounts_no_source:
            unique_amounts = list(set(amounts_no_source))[:5]
            self.checks.append(VerificationCheck(
                name='数字声明可验证性',
                verification=f'提取 {amount_count} 个金额、{pct_count} 个百分比',
                output=f'{len(unique_amounts)} 个唯一金额声明无来源标注: {unique_amounts}',
                result='FAIL',
                detail='所有金额声明必须有明确来源标注'
            ))
        else:
            self.checks.append(VerificationCheck(
                name='数字声明可验证性',
                verification=f'提取 {amount_count} 个金额、{pct_count} 个百分比',
                output=f'{amount_count} 个金额声明均有来源标注',
                result='PASS',
            ))

    # ────────── L5: 逻辑漏洞 ──────────
    def check_logic_flaws(self, text: str, steps: dict = None):
        """
        对标 free-code 的 "Match rigor to stakes" ——
        高质量研报需要多维度交叉验证。
        """
        flaws = []

        # 风险提示是否充分（对标 free-code 的 "check regressions"）
        risk_section = ''
        risk_pos = text.find('风险')
        if risk_pos >= 0:
            risk_section = text[risk_pos: risk_pos + 500]

        if risk_section and len(risk_section.strip()) < 200:
            flaws.append('风险提示部分过短（<200 字符），可能未充分揭示风险')

        # 估值方法数量（对标 free-code 的 "run lint/type-check"）
        val_methods = sum(1 for kw in ['DCF', 'PE', 'PB', 'PS', 'EV/EBITDA',
                                        '市销率', '市盈率', '市净率', '现金流折现']
                          if kw in text)
        if val_methods <= 1 and len(text) > 2000:
            flaws.append(f'仅使用 {val_methods} 种估值方法，建议至少 2 种交叉验证')

        # 结论前必须有论证（对标 free-code 的 "evidence > assertion"）
        if any(kw in text for kw in ['买入', '推荐', '增持']) and len(text) < 3000:
            flaws.append('有明确投资建议但全文过短（<3000 字符），论证可能不充分')

        if flaws:
            for f in flaws:
                self.checks.append(VerificationCheck(
                    name='逻辑漏洞检测',
                    verification='检查风险提示、估值方法、论证完整性',
                    output=f,
                    result='WARN',
                ))
        else:
            self.checks.append(VerificationCheck(
                name='逻辑漏洞检测',
                verification='检查风险提示、估值方法、论证完整性',
                output='未发现明显逻辑漏洞',
                result='PASS',
            ))

    # ────────── L6: Adversarial Probe（反向论证） ──────────
    def check_adversarial(self, text: str):
        """
        对标 free-code 的 ADVERSARIAL PROBES：
        - Concurrency → 同时考虑多场景 → 是否只看单一情景？
        - Boundary → 边界值 → 是否只分析了"正常"情况？
        - Idempotency → 一致性 → 结论在不同假设下是否仍然成立？
        - Orphan operations → 孤立假设 → 是否引用了未展开的前提？

        free-code 原文："Before issuing PASS, must include at least one adversarial probe"
        """
        probes = []

        # 反面论证（bear case）
        has_counterarguments = any(kw in text for kw in
                                 ['不利', '挑战', '隐忧', '下行',
                                  'downside', 'bear case', '悲观', '另一方面',
                                  '负面'])

        if not has_counterarguments:
            probes.append(VerificationCheck(
                name='Adversarial: 反面论证',
                verification='扫描看空/不利/下行/风险等反面论证',
                output='未发现反面论证段落',
                result='WARN',
                detail='高质量研应包含看空/看多两种视角（对标 free-code）'
            ))
        else:
            probes.append(VerificationCheck(
                name='Adversarial: 反面论证',
                verification='扫描看空/不利/下行/风险等反面论证',
                output='发现反面论证',
                result='PASS',
            ))

        # 不确定性说明（对标 free-code 的 "before issuing FAIL"）
        has_uncertainty = any(kw in text.lower() for kw in
                            ['不确定', '假设', '前提', '取决于',
                             'uncertainty', 'may depend', '假设条件'])

        if not has_uncertainty:
            probes.append(VerificationCheck(
                name='Adversarial: 不确定性说明',
                verification='扫描关键假设和不确定性前提',
                output='未发现不确定性/假设条件说明',
                result='WARN',
                detail='应明确声明分析中的关键假设和不确定性'
            ))
        else:
            probes.append(VerificationCheck(
                name='Adversarial: 不确定性说明',
                verification='扫描关键假设和不确定性前提',
                output='发现关键假设/不确定性说明',
                result='PASS',
            ))

        # 情景分析（对标 free-code 的 "boundary values" / "edge cases"）
        has_scenarios = any(kw in text for kw in
                          ['情景', '乐观', '基准', '悲观',
                           'bull', 'bear', 'base', '情景分析',
                           '压力测试', '敏感性'])

        if not has_scenarios:
            probes.append(VerificationCheck(
                name='Adversarial: 情景分析',
                verification='扫描乐观/基准/悲观情景分析',
                output='未发现多情景分析',
                result='WARN',
                detail='高质量研报应包含乐观/基准/悲观多情景分析'
            ))
        else:
            probes.append(VerificationCheck(
                name='Adversarial: 情景分析',
                verification='扫描乐观/基准/悲观情景分析',
                output='发现多情景分析',
                result='PASS',
            ))

        self.checks.extend(probes)

    # ────────── BP 专用验证 ──────────
    def check_bp_specific(self, text: str):
        """
        BP 尽调特有验证（对标 free-code 的 type-specific strategy）
        """
        # 估值分析（对标 free-code 的 "run the build first"）
        has_valuation = any(kw in text for kw in
                          ['估值', '投前', '投后', '估值模型', 'valuation',
                           'pre-money', 'post-money'])
        if has_valuation:
            self.checks.append(VerificationCheck(
                name='BP: 估值分析',
                verification='扫描估值分析内容',
                output='发现估值分析',
                result='PASS',
            ))
        else:
            self.checks.append(VerificationCheck(
                name='BP: 估值分析',
                verification='扫描估值分析内容',
                output='未发现估值分析',
                result='WARN',
                detail='BP 尽调应包含估值分析'
            ))

        # 团队验证（对标 free-code 的 "check related functionality"）
        has_team = any(kw in text for kw in
                      ['创始人', '团队', 'CTO', 'CEO', '联合创始人',
                       'Co-founder', '核心团队'])
        if has_team:
            self.checks.append(VerificationCheck(
                name='BP: 团队验证',
                verification='扫描团队/创始人信息',
                output='发现团队信息',
                result='PASS',
            ))
        else:
            self.checks.append(VerificationCheck(
                name='BP: 团队验证',
                verification='扫描团队/创始人信息',
                output='未发现团队信息',
                result='WARN',
            ))

        # 竞品分析（对标 free-code 的 "check regressions"）
        has_competition = any(kw in text for kw in
                             ['竞品', '竞争', '竞品分析', '护城河',
                              '竞争对手', '差异化', '替代'])
        if not has_competition:
            self.checks.append(VerificationCheck(
                name='BP: 竞品分析',
                verification='扫描竞品分析/竞争格局',
                output='未发现竞品分析',
                result='WARN',
                detail='BP 尽调应包含竞品分析'
            ))
        else:
            self.checks.append(VerificationCheck(
                name='BP: 竞品分析',
                verification='扫描竞品分析/竞争格局',
                output='发现竞品分析',
                result='PASS',
            ))

    # ────────── IR 专用验证 ──────────
    def check_ir_specific(self, text: str, steps: dict = None):
        """
        IR 研报特有验证
        """
        # 财务数据来源（对标 free-code 的 "verify response shapes against expected"）
        has_financial = any(kw in text for kw in
                          ['财报', '年报', '季报', 'annual', 'filing',
                           '10-K', '20-F', 'HKEX', '年报披露',
                           'SEC', '审计报告'])
        if not has_financial:
            self.checks.append(VerificationCheck(
                name='IR: 财务数据来源',
                verification='扫描官方财务数据来源引用',
                output='未发现官方财务数据来源',
                result='FAIL',
                detail='IR 研报应引用官方财务数据（SEC/HKEX/年报等）'
            ))
        else:
            self.checks.append(VerificationCheck(
                name='IR: 财务数据来源',
                verification='扫描官方财务数据来源引用',
                output='发现官方财务数据来源',
                result='PASS',
            ))

        # 同业对比（对标 free-code 的 "spot-check observable behavior"）
        has_peer = any(kw in text for kw in
                      ['同业', '可比', 'peer', '对标', '相比', '对比',
                       '同行', '行业平均', '行业均值'])
        if not has_peer:
            self.checks.append(VerificationCheck(
                name='IR: 同业对比',
                verification='扫描同业对比/可比公司分析',
                output='未发现同业对比',
                result='WARN',
                detail='IR 研报应包含同业对比分析'
            ))
        else:
            self.checks.append(VerificationCheck(
                name='IR: 同业对比',
                verification='扫描同业对比/可比公司分析',
                output='发现同业对比',
                result='PASS',
            ))

    # ────────── 运行全部验证 ──────────
    def run(self, text: str, steps: dict = None) -> dict:
        """
        运行全部 6 类验证 + 管线专用验证。

        对标 free-code 的 REQUIRED STEPS：
        1. Read → 2. Build → 3. Tests → 4. Lint → 5. Regressions
        - L1 = Read（内容是否有泄露）
        - L2 = Tests（占位残留 = 测试不完整）
        - L3 = Regressions（矛盾 = 前后不一致）
        - L4 = Lint（数字声明必须有来源 = 格式要求）
        - L5 = Build（逻辑完整性 = 基本通过才往下走）
        - L6 = Adversarial（对标 free-code 的 core 特色）
        """
        if not text or len(text.strip()) < 200:
            return {
                'verdict': 'FAIL',
                'checks': [],
                'summary': '内容不足 200 字符，无法验证',
            }

        # L1-L6 通用验证
        self.check_internal_leaks(text)
        self.check_placeholders(text)
        self.check_contradictions(text, steps)
        self.check_number_claims(text)
        self.check_logic_flaws(text, steps)
        self.check_adversarial(text)

        # 管线专用验证
        if self.pipeline == 'bp':
            self.check_bp_specific(text)
        else:
            self.check_ir_specific(text, steps)

        # 计算 verdict（对标 free-code 的 VERDICT: PASS/FAIL/PARTIAL）
        fail_count = sum(1 for c in self.checks if c.result == 'FAIL')
        warn_count = sum(1 for c in self.checks if c.result == 'WARN')
        pass_count = sum(1 for c in self.checks if c.result == 'PASS')

        if fail_count > 0:
            self.verdict = 'FAIL'
        elif warn_count >= 3:
            self.verdict = 'WARN'
        else:
            self.verdict = 'PASS'

        return {
            'verdict': self.verdict,
            'total_checks': len(self.checks),
            'pass': pass_count,
            'fail': fail_count,
            'warn': warn_count,
            'checks': [asdict(c) for c in self.checks],
            'summary': f'VERDICT: {self.verdict} '
                       f'({pass_count} 通过, {fail_count} 失败, {warn_count} 警告)',
        }


# ── 报告输出 ──────────────────────────────────────────────────
def format_verification_report(result: dict, report_type: str = 'ir') -> str:
    """
    对标 free-code 的 OUTPUT FORMAT：
    ### Check: [name]
    **Verification:** [what was done]
    **Output:** [observed result]
    **Result:** PASS/FAIL/WARN
    """
    lines = []
    lines.append(f"# Adversarial Verification Report ({report_type})")
    lines.append('')
    lines.append(f"## Overall: {result['verdict']}")
    lines.append(f"- 总检查数: {result['total_checks']}")
    lines.append(f"- 通过: {result['pass']}")
    lines.append(f"- 失败: {result['fail']}")
    lines.append(f"- 警告: {result['warn']}")
    lines.append('')

    failed = [c for c in result['checks'] if c['result'] == 'FAIL']
    warned = [c for c in result['checks'] if c['result'] == 'WARN']
    passed = [c for c in result['checks'] if c['result'] == 'PASS']

    for label, group in [('❌ FAILED', failed), ('⚠️ WARNINGS', warned), ('✅ PASSED', passed)]:
        if not group:
            continue
        lines.append(f'## {label}')
        lines.append('')
        for c in group:
            lines.append(f"### Check: {c['name']}")
            lines.append(f"**Verification:** {c['verification']}")
            lines.append(f"**Output:** {c['output']}")
            if c.get('detail'):
                lines.append(f"**Detail:** {c['detail']}")
            lines.append(f"**Result:** {c['result']}")
            lines.append('')

    lines.append(f"VERDICT: {result['verdict']}")
    return '\n'.join(lines)


# ── 管线集成入口 ──────────────────────────────────────────────
def run_verification(task_id: str, pipeline: str = 'ir',
                    tasks_dir: Path = None) -> dict:
    """
    管线调用入口。供 run_ir_pipeline.py 和 run_bp_pipeline.py 使用。

    Returns:
        dict with verdict, checks, summary
    """
    if tasks_dir is None:
        tasks_dir = TASKS_DIR

    text = load_report_content(task_id=task_id, pipeline=pipeline, tasks_dir=tasks_dir)

    steps = None
    if pipeline == 'ir':
        steps = load_ir_steps(task_id, tasks_dir)

    if not text:
        return {
            'verdict': 'FAIL',
            'summary': '无法加载报告内容',
            'checks': [],
        }

    verifier = AdversarialVerifier(pipeline=pipeline)
    return verifier.run(text, steps)


# ── 命令行入口 ────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description='Adversarial Verification Agent')
    p.add_argument('--task-id', help='任务 ID')
    p.add_argument('--pipeline', choices=['bp', 'ir'], default='ir')
    p.add_argument('--tasks-dir', help='任务目录路径')
    p.add_argument('--output', help='输出文件路径')
    p.add_argument('--json', action='store_true', help='JSON 格式输出')
    args = p.parse_args()

    tasks_dir = Path(args.tasks_dir) if args.tasks_dir else TASKS_DIR

    text = load_report_content(
        task_id=args.task_id,
        pipeline=args.pipeline,
        tasks_dir=tasks_dir,
    )

    if not text:
        print('❌ 无法加载报告内容')
        print(f'   task_id={args.task_id}, pipeline={args.pipeline}')
        sys.exit(1)

    steps = None
    if args.pipeline == 'ir':
        steps = load_ir_steps(args.task_id, tasks_dir)

    verifier = AdversarialVerifier(pipeline=args.pipeline)
    result = verifier.run(text, steps)

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
        print(f'\n📄 报告已保存: {args.output}')
    elif args.task_id:
        output_file = tasks_dir / f'{args.task_id}-verification.json'
        output_file.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
        print(f'\n📄 结果已保存: {output_file}')

    sys.exit(0 if result['verdict'] != 'FAIL' else 1)


if __name__ == '__main__':
    main()

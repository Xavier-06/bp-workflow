#!/usr/bin/env python3
"""
verify_step1_completeness.py — Step 1 数据包完整性门禁

在 Step 1（数据收集）完成后、Step 2-7 启动前，强制运行。
检查数据包关键字段的覆盖率，不达标则阻塞管线。

用法：
    python3 scripts/verify_step1_completeness.py --task-id TASK-20260330-001
    python3 scripts/verify_step1_completeness.py --file data/tasks/popmart_step1_data.md

返回 JSON + exit code:
    exit 0 = PASS, exit 1 = BLOCK, exit 2 = WARN

门禁规则：
    - 关键字段覆盖率 < 50% → BLOCK
    - 关键字段覆盖率 50%-70% → WARN
    - 关键字段覆盖率 > 70% → PASS
    - overall score < 0.35 → BLOCK（即使关键字段刚好过线，整体太空也拦）
    - not_filled_markers > 30 且 overall < 0.5 → WARN 升级为 BLOCK

v2 (2026-03-31): 新增算术交叉验算、完整资产负债表/现金流检查、分部收入、
    政府补贴、股权稀释、审计意见、估值方法适用性检查
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'

# ─── 字段定义 ──────────────────────────────────────

CRITICAL_FIELDS = [
    ('stock_price', '股价/市值', [
        r'(?:股价|price|HK\$|USD|CNY)\s*[:：]?\s*[\d,.]+',
        r'(?:市值|market\s*cap).*[\d,.]+',
    ]),
    ('shares_outstanding', '总股本/流通股', [
        r'(?:总股本|shares?\s*outstanding|流通股|issued\s*shares?)\s*[:���]?\s*[\d,.]+\s*(?:亿|百万|million|billion|万|股)?',
    ]),
    ('revenue_latest', '最新年度营收(精确值)', [
        r'(?:营收|revenue|收入)\s*[:：]?\s*(?:RMB|HKD|USD|HK\$)?\s*[\d,.]+\s*(?:亿|billion|million)',
    ]),
    ('net_profit_latest', '最新年度净利润(精确值)', [
        r'(?:净利(?:润)?|net\s*(?:profit|income|loss))\s*[:：]?\s*[-]?(?:RMB|HKD|USD|HK\$)?\s*[\d,.]+\s*(?:亿|billion|million)',
    ]),
    ('pe_ratio', 'PE估值', [
        r'(?:PE|P/E|市盈率)\s*[:：]?\s*[-]?[\d,.]+[x倍]?',
        r'(?:PE|P/E)\s*(?:\(TTM\))?\s*[:：]?\s*(?:N/?A|负|亏损)',  # 亏损公司 PE=N/A 也算填充
    ]),
    ('revenue_history_multi_year', '历史营收(≥2个不同年度的精确数据)', [
        r'(?:202[0-5])\s*\|.*(?:营收|revenue|收入).*[\d,.]+',
    ]),
    ('gross_margin', '毛利率(精确值)', [
        r'(?:毛利率|gross\s*margin)\s*[:：]?\s*[\d,.]+%',
    ]),
    ('cash_and_equivalents', '现金及等价物/账上现金', [
        r'(?:现金|cash\s*(?:and\s*)?(?:equivalents?|balance)|账上现金|货币资金)\s*[:：]?\s*(?:RMB|HKD|USD|HK\$)?\s*[\d,.]+\s*(?:亿|billion|million)',
    ]),
    ('segment_revenue', '分部/业务线收入拆分', [
        r'(?:分部|segment|业务线|产品线)\s*.*(?:收入|revenue|占比)\s*.*[\d,.]+',
        r'(?:收入构成|revenue\s*(?:breakdown|mix|split))\s*.*[\d,.]+',
    ]),
]

IMPORTANT_FIELDS = [
    ('net_margin', '净利率', [
        r'(?:净利率|net\s*margin)\s*[:：]?\s*[-]?[\d,.]+%',
    ]),
    ('analyst_target', '分析师目标价/评级', [
        r'(?:目标价|target\s*price)\s*[:：]?\s*[\d,.]+',
        r'(?:评级|rating)\s*[:：]?\s*(?:买入|buy|hold|sell|增持|中性|outperform|overweight)',
    ]),
    ('operating_cash_flow', '经营现金流', [
        r'(?:经营现金流|operating\s*cash\s*flow|OCF)\s*.*[-]?[\d,.]+',
    ]),
    ('free_cash_flow', '自由现金流', [
        r'(?:自��现金流|free\s*cash\s*flow|FCF)\s*.*[-]?[\d,.]+',
    ]),
    ('total_debt', '负债/资产负债', [
        r'(?:总负债|total\s*(?:debt|liabilities)|负债合计|有息负债|net\s*(?:debt|cash))\s*.*[\d,.]+',
    ]),
    ('market_share', '市场份额/竞争格局', [
        r'(?:市场份额|market\s*share|CR[35])\s*.*[\d,.]+%?',
    ]),
    ('industry_size', '行业市场规模', [
        r'(?:行业.*规模|market\s*size|TAM|SAM)\s*.*[\d,.]+\s*(?:亿|billion|万亿|trillion)',
    ]),
    ('management', '管理层/大股东', [
        r'(?:CEO|创始人|实控人|管理层|大股东|founder|chairman)\s*[:：]?\s*\S+',
    ]),
    ('overseas_revenue', '海外/分部收入占比', [
        r'(?:海外|overseas|international|境外).*(?:收入|revenue|占比).*[\d,.]+',
    ]),
    ('capex', '资本开支', [
        r'(?:CapEx|资本开支|资本支出|capital\s*expenditure)\s*.*[\d,.]+',
    ]),
    ('eps', 'EPS', [
        r'(?:EPS|每股收益|earnings\s*per\s*share)\s*[:：]?\s*[-]?[\d,.]+',
    ]),
    ('52w_range', '52周高低', [
        r'(?:52[Ww周]|52.week).*[\d,.]+',
    ]),
    ('dividend_buyback', '分红/回购', [
        r'(?:分红|dividend|回购|buyback|repurchase).*[\d,.]+',
    ]),
    ('store_count', '门店/渠道数量', [
        r'(?:门店|store|shop|outlet|渠道)\s*[:：]?\s*(?:超过|约|>\s*)?[\d,.]+\s*(?:家|台|个)?',
    ]),
    ('government_subsidy', '政府补贴/补助', [
        r'(?:政府补贴|补助|补助金|government\s*(?:subsid|grant))\s*.*[\d,.]+',
        r'(?:其他收入|other\s*income).*(?:补贴|补助|subsid)',
    ]),
    ('equity_dilution', '股权稀释/配售/增发', [
        r'(?:配售|增发|稀释|dilut|placement|offering|募资)\s*.*[\d,.]+',
    ]),
    ('audit_opinion', '审计意见', [
        r'(?:审计意见|audit\s*opinion|无保留|qualified|unqualified|非标|going\s*concern)',
    ]),
    ('receivables_inventory', '应收账款/存货', [
        r'(?:应收账款|accounts?\s*receivable|存货|inventory)\s*.*[\d,.]+',
    ]),
    ('employee_count', '员工人数', [
        r'(?:员工|employee|staff|人数|headcount)\s*[:：]?\s*(?:约|超过)?[\d,.]+\s*(?:人|名)?',
    ]),
    ('rd_expense', '研发费用/占比', [
        r'(?:研发费用|R&D|research\s*(?:and\s*)?development)\s*.*[\d,.]+',
    ]),
]

# 字段旁边有这些标记的，视为"未真实填充"
UNRELIABLE_MARKERS = re.compile(
    r'(?:未获取|推算|待(?:补充|核实)|需(?:进一步)?核实|信息有限|N/A(?!.*亏损)|待确认)',
    re.IGNORECASE,
)

# 计数用
NOT_FILLED_PATTERNS = [
    r'未获取',
    r'❌\s*未获取',
    r'⚠️\s*(?:部分获取|需补充)',
    r'需(?:进一步)?核实',
    r'待补充',
    r'待核实',
    r'待确认',
    r'N/A',
    r'推算',
    r'信息有限',
    r'数据缺失',
    r'公司未披露',
]


def read_step1_file(task_id: str = '', file_path: str = '') -> str | None:
    if file_path:
        p = Path(file_path)
        if not p.is_absolute():
            p = ROOT / file_path
        if p.exists():
            return p.read_text(encoding='utf-8')
        return None
    if task_id:
        candidates = [TASKS_DIR / f'{task_id}-step1_data.md']
        for f in TASKS_DIR.glob('*step1*data*.md'):
            if task_id.lower() in f.name.lower() or f.name.startswith(task_id):
                candidates.insert(0, f)
        for c in candidates:
            if c.exists():
                return c.read_text(encoding='utf-8')
    return None


def count_not_filled_markers(text: str) -> int:
    count = 0
    for pat in NOT_FILLED_PATTERNS:
        count += len(re.findall(pat, text, re.IGNORECASE))
    return count


def check_field_reliable(text: str, field_patterns: list[str]) -> bool:
    """检查字段是否被可靠地填充（不是旁边跟着"未获取"/"推算"）"""
    for pat in field_patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            start = max(0, m.start() - 30)
            end = min(len(text), m.end() + 30)
            context = text[start:end]
            if UNRELIABLE_MARKERS.search(context):
                continue
            return True
    return False


def check_multi_year_revenue(text: str) -> bool:
    """特殊检查：是否有 ≥2 个不同年度的精确营收数据（不是"推算"）"""
    year_pattern = re.compile(r'(202[0-5])\s*[\|｜]?\s*.*?(?:营收|revenue|收入)\s*.*?([\d,.]+)\s*(?:亿|billion|million)', re.IGNORECASE)
    table_pattern = re.compile(r'\|\s*(202[0-5])\s*\|.*?([\d,.]+).*?(?:亿|billion|million)', re.IGNORECASE)

    years_with_data = set()
    for pat in [year_pattern, table_pattern]:
        for m in pat.finditer(text):
            year = m.group(1)
            context_start = max(0, m.start() - 20)
            context_end = min(len(text), m.end() + 20)
            context = text[context_start:context_end]
            if not UNRELIABLE_MARKERS.search(context):
                years_with_data.add(year)

    return len(years_with_data) >= 2


# ─── 算术交叉验算 ─────────────────────────────────

def extract_number(text: str, patterns: list[str]) -> float | None:
    """提取第一个匹配的数字值"""
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1).replace(',', ''))
            except (ValueError, IndexError):
                continue
    return None


def run_arithmetic_checks(text: str) -> list[dict]:
    """算术交叉验算"""
    issues = []

    # 1. 市值 = 股价 × 总股本 验算
    price = extract_number(text, [
        r'(?:股价|price|收盘价)\s*[:：]?\s*(?:HK\$|HKD|USD|CNY)?\s*([\d,.]+)',
    ])
    shares = extract_number(text, [
        r'(?:总股本|shares?\s*outstanding|已发行股份)\s*[:：]?\s*([\d,.]+)\s*(?:亿|百万)',
    ])
    mcap = extract_number(text, [
        r'(?:市值|market\s*cap)\s*[:：]?\s*(?:HK\$|HKD|USD|CNY)?\s*([\d,.]+)\s*(?:亿|billion)',
    ])
    shares_unit = None
    if shares is not None:
        if re.search(r'(?:总股本|shares?\s*outstanding).*?[\d,.]+\s*亿', text, re.IGNORECASE):
            shares_unit = '亿'
        elif re.search(r'(?:总股本|shares?\s*outstanding).*?[\d,.]+\s*百万', text, re.IGNORECASE):
            shares_unit = '百万'

    if price and shares and mcap:
        # 统一到亿
        shares_in_yi = shares
        if shares_unit == '百万':
            shares_in_yi = shares / 100  # 百万 → 亿
        elif shares_unit is None and shares > 100:
            # 可能是原始股数（如 432735396），转亿
            shares_in_yi = shares / 1e8

        calc_mcap = price * shares_in_yi
        if mcap > 0:
            diff_pct = abs(calc_mcap - mcap) / mcap
            if diff_pct > 0.1:  # 10% 偏差
                issues.append({
                    'check': 'market_cap_arithmetic',
                    'severity': 'ERROR',
                    'detail': f'市值验算不通过：股价 {price} × 总股本 {shares}{shares_unit or ""}  ≈ {calc_mcap:.1f}亿，但报告市值 = {mcap}亿，偏差 {diff_pct:.0%}',
                    'impact': '所有基于市值的估值倍数（PS/PB/EV）可能都是错的',
                })

    # 2. 营收 × 净利率 ≈ 净利润 验算
    revenue = extract_number(text, [
        r'(?:营收|revenue|收入)\s*[:：]?\s*(?:RMB|HKD|USD|HK\$)?\s*([\d,.]+)\s*(?:亿|billion)',
    ])
    net_margin = extract_number(text, [
        r'(?:净利率|net\s*margin)\s*[:：]?\s*(-?[\d,.]+)%',
    ])
    net_profit = extract_number(text, [
        r'(?:净利(?:润)?|net\s*(?:profit|income|loss))\s*[:：]?\s*(?:亏损\s*)?(?:RMB|HKD|USD|HK\$)?\s*(-?[\d,.]+)\s*(?:亿|billion)',
    ])
    if revenue and net_margin and net_profit:
        calc_profit = revenue * net_margin / 100
        if abs(net_profit) > 0.1:  # 避免除以零
            diff_pct = abs(calc_profit - net_profit) / abs(net_profit)
            if diff_pct > 0.15:  # 15% 偏差
                issues.append({
                    'check': 'profit_margin_arithmetic',
                    'severity': 'WARNING',
                    'detail': f'净利验算：营收 {revenue}亿 × 净利率 {net_margin}% ≈ {calc_profit:.2f}亿，但报告净利润 = {net_profit}亿，偏差 {diff_pct:.0%}',
                    'impact': '净利率或净利润数字可能有误',
                })

    # 3. 分析师评级人数加总验算
    analyst_counts = re.findall(
        r'(\d+)\s*(?:位|人|个)\s*(?:给予)?[\'\"「]?\s*(?:强力买入|强烈买入|买入|增持|持有|中性|卖出|减持|强力卖出|Strong\s*Buy|Buy|Hold|Sell|Strong\s*Sell)',
        text, re.IGNORECASE
    )
    if len(analyst_counts) >= 3:
        total_found = sum(int(x) for x in analyst_counts)
        total_claimed_m = re.search(r'(\d+)\s*(?:位|人|个)\s*(?:覆盖|coverage)?\s*(?:分析师|analyst)', text, re.IGNORECASE)
        if total_claimed_m:
            total_claimed = int(total_claimed_m.group(1))
            if total_found != total_claimed:
                issues.append({
                    'check': 'analyst_count_arithmetic',
                    'severity': 'ERROR',
                    'detail': f'分析师评级加总不一致：各评级共 {total_found} 位（{"+".join(analyst_counts)}），但声称 {total_claimed} 位',
                    'impact': '评级分布数据不可信',
                })

    # 4. PE × EPS ≈ 股价 验算
    pe = extract_number(text, [
        r'(?:PE|P/E|市盈率)\s*(?:\(TTM\))?\s*[:：]?\s*([\d,.]+)[x倍]?',
    ])
    eps = extract_number(text, [
        r'(?:EPS|每股收益)\s*[:：]?\s*(?:HK\$|HKD|USD|CNY)?\s*([\d,.]+)',
    ])
    if pe and eps and price:
        calc_price = pe * eps
        if price > 0:
            diff_pct = abs(calc_price - price) / price
            if diff_pct > 0.1:
                issues.append({
                    'check': 'pe_eps_arithmetic',
                    'severity': 'WARNING',
                    'detail': f'PE×EPS验算：PE {pe} × EPS {eps} = {calc_price:.2f}，但股价 = {price}，偏差 {diff_pct:.0%}',
                    'impact': 'PE 或 EPS 可能有误',
                })

    # 5. 海外收入占比合理性（国内+海外应≈100%）
    domestic_pct = extract_number(text, [
        r'(?:国内|中国|内地|大陆|domestic)\s*.*?(?:收入|revenue).*?(?:占比|占)\s*[:：]?\s*([\d,.]+)%',
    ])
    overseas_pct = extract_number(text, [
        r'(?:海外|overseas|international|境外)\s*.*?(?:收入|revenue).*?(?:占比|占)\s*[:：]?\s*([\d,.]+)%',
    ])
    if domestic_pct and overseas_pct:
        total_pct = domestic_pct + overseas_pct
        if abs(total_pct - 100) > 5:  # 允许5%误差（可能有"其他"分类）
            issues.append({
                'check': 'revenue_split_arithmetic',
                'severity': 'WARNING',
                'detail': f'收入占比加总：国内 {domestic_pct}% + 海外 {overseas_pct}% = {total_pct}%，偏离100%',
                'impact': '收入地区拆分数据可能不准确',
            })

    return issues


# ─── 估值方法适用性检查 ─────────────────────────────

def check_valuation_method_suitability(text: str) -> list[dict]:
    """检查数据包中的盈利状态，预警不适用的估值方法"""
    issues = []

    # 检查是否亏损
    is_loss = bool(re.search(r'(?:净利率|net\s*margin)\s*[:：]?\s*-[\d,.]+%', text, re.IGNORECASE))
    is_loss = is_loss or bool(re.search(r'(?:净(?:亏损|利润))\s*[:：]?\s*(?:亏损|-)[\d,.]+', text, re.IGNORECASE))
    is_loss = is_loss or bool(re.search(r'(?:PE|P/E)\s*[:：]?\s*(?:N/?A|负|亏损|不适用)', text, re.IGNORECASE))

    if is_loss:
        issues.append({
            'check': 'valuation_method_warning',
            'severity': 'INFO',
            'detail': '公司当前亏损：DCF 高度依赖远期假设（终端价值占比极高），建议以 PS/EV-Revenue 为主估值方法，DCF 仅作参考。预测与估值 Agent 必须标注"DCF 结果仅供参考，因自由现金流为负"。',
            'impact': '如果 DCF 用乐观假设，目标价会被系统性高估',
        })

    # 检查是否 pre-revenue
    revenue = extract_number(text, [
        r'(?:营收|revenue|收入)\s*[:：]?\s*(?:RMB|HKD|USD|HK\$)?\s*([\d,.]+)\s*(?:亿|billion)',
    ])
    if revenue is not None and revenue < 1:
        issues.append({
            'check': 'pre_revenue_warning',
            'severity': 'INFO',
            'detail': f'公司年营收仅 {revenue} 亿，属于 pre-revenue/早期阶段。PS 法的可比公司必须选同阶段的公司，不能用已盈利的传统行业公司做可比。',
            'impact': '可比公司选错 → PS 倍数不可比 → 目标价失真',
        })

    return issues


def verify(text: str) -> dict:
    filled_critical = []
    missing_critical = []
    filled_important = []
    missing_important = []

    for field_id, field_name, patterns in CRITICAL_FIELDS:
        if field_id == 'revenue_history_multi_year':
            if check_multi_year_revenue(text):
                filled_critical.append({'field': field_id, 'name': field_name})
            else:
                missing_critical.append({'field': field_id, 'name': field_name})
        else:
            if check_field_reliable(text, patterns):
                filled_critical.append({'field': field_id, 'name': field_name})
            else:
                missing_critical.append({'field': field_id, 'name': field_name})

    for field_id, field_name, patterns in IMPORTANT_FIELDS:
        if check_field_reliable(text, patterns):
            filled_important.append({'field': field_id, 'name': field_name})
        else:
            missing_important.append({'field': field_id, 'name': field_name})

    total_critical = len(CRITICAL_FIELDS)
    total_important = len(IMPORTANT_FIELDS)
    total = total_critical + total_important
    filled = len(filled_critical) + len(filled_important)

    critical_coverage = len(filled_critical) / total_critical if total_critical > 0 else 0
    overall_score = filled / total if total > 0 else 0
    not_filled_count = count_not_filled_markers(text)

    # 算术交叉验算
    arithmetic_issues = run_arithmetic_checks(text)
    arithmetic_errors = [i for i in arithmetic_issues if i['severity'] == 'ERROR']

    # 估值方法适用性检查
    valuation_warnings = check_valuation_method_suitability(text)

    # 判定
    if critical_coverage < 0.5:
        verdict = 'BLOCK'
        reason = f'关键字段覆盖率仅 {critical_coverage:.0%}（{len(filled_critical)}/{total_critical}），数据严重不足'
    elif overall_score < 0.35:
        verdict = 'BLOCK'
        reason = f'整体字段覆盖率仅 {overall_score:.0%}（{filled}/{total}），即使关键字段勉强过线，整体数据太空'
    elif not_filled_count > 30 and overall_score < 0.5:
        verdict = 'BLOCK'
        reason = f'文件中有 {not_filled_count} 处"未获取"标记且整体覆盖率仅 {overall_score:.0%}，数据严重不足'
    elif arithmetic_errors:
        verdict = 'BLOCK'
        error_labels = [e['check'] for e in arithmetic_errors]
        reason = f'算术交叉验算发现 {len(arithmetic_errors)} 个严重错误：{error_labels}。数据自相矛盾，必须修正后再继续'
    elif critical_coverage < 0.7:
        verdict = 'WARN'
        reason = f'关键字段覆盖率 {critical_coverage:.0%}（{len(filled_critical)}/{total_critical}），建议补搜关键数据后再继续'
    elif overall_score < 0.5:
        verdict = 'WARN'
        reason = f'整体覆盖率 {overall_score:.0%}（{filled}/{total}），部分重要字段缺失'
    else:
        verdict = 'PASS'
        reason = f'关键字段覆盖率 {critical_coverage:.0%}，整体覆盖率 {overall_score:.0%}，数据基本充足'

    return {
        'passed': verdict != 'BLOCK',
        'verdict': verdict,
        'reason': reason,
        'score': round(overall_score, 3),
        'critical_coverage': round(critical_coverage, 3),
        'total_fields': total,
        'filled_fields': filled,
        'critical_total': total_critical,
        'critical_filled': len(filled_critical),
        'important_total': total_important,
        'important_filled': len(filled_important),
        'missing_critical': missing_critical,
        'missing_important': missing_important,
        'not_filled_markers': not_filled_count,
        'arithmetic_issues': arithmetic_issues,
        'valuation_warnings': valuation_warnings,
        'checked_at': datetime.now().isoformat(timespec='seconds'),
    }


def main():
    ap = argparse.ArgumentParser(description='Step 1 数据包完整性门禁')
    ap.add_argument('--task-id', default='', help='Task ID')
    ap.add_argument('--file', default='', help='直接指定 Step 1 文件路径')
    args = ap.parse_args()

    if not args.task_id and not args.file:
        print('Error: must provide --task-id or --file', file=sys.stderr)
        raise SystemExit(1)

    text = read_step1_file(task_id=args.task_id, file_path=args.file)
    if text is None:
        result = {
            'passed': False,
            'verdict': 'BLOCK',
            'reason': 'Step 1 数据文件不存在',
            'score': 0,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(1)

    result = verify(text)

    if args.task_id:
        out_path = TASKS_DIR / f'{args.task_id}-step1-verify.json'
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    print(json.dumps(result, ensure_ascii=False, indent=2))

    if result['verdict'] == 'BLOCK':
        raise SystemExit(1)
    elif result['verdict'] == 'WARN':
        raise SystemExit(2)


if __name__ == '__main__':
    main()

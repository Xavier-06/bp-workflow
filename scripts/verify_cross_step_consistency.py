#!/usr/bin/env python3
"""
verify_cross_step_consistency.py — Step 8 统稿前的跨章节数据一致性检查

扫描所有 step 文件，对同一指标在不同 step 中的值做交叉比对。
不一致的条目输出为 WARNING/ERROR。

用法：
    python3 scripts/verify_cross_step_consistency.py --task-id TASK-20260330-001
    python3 scripts/verify_cross_step_consistency.py --dir data/tasks --prefix popmart_step

输出：JSON 报告 + 人可读摘要

v2 (2026-03-31): 新增估值假设一致性检查、目标价验算、重复内容检测、
    系统路径泄露扫描、可比公司适当性检查
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from collections import defaultdict, Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'

# ─── 指标提取模式 ─────────────────────────────────

METRIC_EXTRACTORS = {
    'revenue_2024': {
        'label': '2024年营收',
        'patterns': [
            r'2024\s*[\|｜]?\s*(?:营收|revenue|收入)[^\d]*?([\d,.]+)\s*(?:亿|billion)',
            r'(?:营收|revenue|收入).*2024[^\d]*?([\d,.]+)\s*(?:亿|billion)',
            r'2024.*?(?:营收|revenue|收入)\s*(?:[:：]\s*)?([\d,.]+)\s*(?:亿|billion)',
        ],
    },
    'revenue_2025': {
        'label': '2025年营收/预测',
        'patterns': [
            r'2025\s*[\|｜]?\s*(?:营收|revenue|收入)[^\d]*?([\d,.]+)\s*(?:亿|billion)',
            r'(?:营收|revenue|收入).*2025[^\d]*?([\d,.]+)\s*(?:亿|billion)',
        ],
    },
    'revenue_2026': {
        'label': '2026年营收/预测',
        'patterns': [
            r'2026\s*[\|｜]?\s*(?:营收|revenue|收入)[^\d]*?([\d,.]+)\s*(?:亿|billion)',
            r'(?:营收|revenue|收入).*2026[^\d]*?([\d,.]+)\s*(?:亿|billion)',
        ],
    },
    'net_profit_2024': {
        'label': '2024年净利润',
        'patterns': [
            r'2024.*?(?:净利(?:润)?|net\s*(?:profit|income))\s*[^\d]*?(-?[\d,.]+)\s*(?:亿|billion)',
            r'(?:净利(?:润)?|net\s*(?:profit|income)).*2024[^\d]*?(-?[\d,.]+)\s*(?:亿|billion)',
        ],
    },
    'gross_margin_2024': {
        'label': '2024年毛利率',
        'patterns': [
            r'2024.*?(?:毛利率|gross\s*margin)\s*[^\d]*?([\d,.]+)%',
            r'(?:毛利率|gross\s*margin).*2024[^\d]*?([\d,.]+)%',
        ],
    },
    'net_margin_2024': {
        'label': '2024年净利率',
        'patterns': [
            r'2024.*?(?:净利率|net\s*margin)\s*[^\d]*?(-?[\d,.]+)%',
            r'(?:净利率|net\s*margin).*2024[^\d]*?(-?[\d,.]+)%',
        ],
    },
    'pe_ratio': {
        'label': 'PE估值',
        'patterns': [
            r'(?:PE|P/E|市盈率)\s*(?:\(TTM\))?\s*[:：]?\s*([\d,.]+)[x倍]?',
        ],
    },
    'market_cap': {
        'label': '市值',
        'patterns': [
            r'(?:市值|market\s*cap)\s*[:：]?\s*(?:HK\$|HKD|USD|CNY)?\s*([\d,.]+)\s*(?:亿|billion)',
        ],
    },
    'store_count_domestic': {
        'label': '国内门店数',
        'patterns': [
            r'(?:国内|中国|内地|大陆|domestic).*?(?:门店|store|shop).*?(?:超过|约|>)?\s*([\d,]+)\s*(?:家|stores)',
        ],
    },
    'store_count_overseas': {
        'label': '海外门店数',
        'patterns': [
            r'(?:海外|overseas|international|境外).*?(?:门店|store|shop).*?(?:超过|约|>)?\s*([\d,]+)\s*(?:家|stores)',
        ],
    },
    'overseas_revenue_pct': {
        'label': '海外收入占比',
        'patterns': [
            r'(?:海外|overseas|international).*?(?:收入|revenue).*?(?:占比|占).*?([\d,.]+)%',
        ],
    },
    'buyback_amount': {
        'label': '回购金额',
        'patterns': [
            r'(?:回购|buyback|repurchase).*?([\d,.]+)\s*(?:亿|billion).*?(?:港元|HKD|人民币|RMB|元)',
            r'([\d,.]+)\s*(?:亿|billion).*?(?:港元|HKD|人民币|RMB).*?(?:回购|buyback|repurchase)',
        ],
    },
    'target_price': {
        'label': '目标价',
        'patterns': [
            r'(?:目标价|target\s*price)\s*[:：]?\s*(?:HK\$|HKD|USD)?\s*([\d,.]+)',
        ],
    },
    'eps': {
        'label': 'EPS',
        'patterns': [
            r'(?:EPS|每股收益)\s*[:：]?\s*(?:HK\$|HKD|USD)?\s*(-?[\d,.]+)',
        ],
    },
    'shares_outstanding': {
        'label': '总股本',
        'patterns': [
            r'(?:总股本|shares?\s*outstanding)\s*[:：]?\s*([\d,.]+)\s*(?:亿|百万|million)',
        ],
    },
}


def extract_values(text: str, patterns: list[str]) -> list[tuple[float, str]]:
    results = []
    for pat in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            try:
                val_str = m.group(1).replace(',', '')
                val = float(val_str)
                context_start = max(0, m.start() - 50)
                context_end = min(len(text), m.end() + 50)
                context = text[context_start:context_end].replace('\n', ' ').strip()
                results.append((val, context))
            except (ValueError, IndexError):
                continue
    return results


def check_arithmetic(text: str) -> list[dict]:
    """检查文本中的算术一致性"""
    issues = []

    # 分析师评级加总
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
                    'type': 'arithmetic',
                    'severity': 'ERROR',
                    'label': '分析师评级加总',
                    'detail': f'声称 {total_claimed} 位分析师，但各评级加总为 {total_found}（{"+".join(analyst_counts)}={total_found}）',
                })

    return issues


# ─── v2 新增：估值假设一致性 ──────────────────────

def check_valuation_scenario_consistency(files: dict[str, str]) -> list[dict]:
    """检查 DCF/可比估值的输入假设是否与情景分析的基准/中性情景一致"""
    issues = []

    # 合并所有 step 文本
    all_text = '\n'.join(files.values())

    # 1. 提取情景分析中的中性/基准情景营收
    neutral_rev_patterns = [
        r'(?:中性|基准|base\s*case).*?(?:营收|revenue)\s*[:：]?\s*(?:约)?\s*([\d,.]+)\s*(?:亿|billion)',
        r'(?:中性|基准|base\s*case).*?(?:概率\s*\d+%).*?(?:营收|revenue)\s*[:：]?\s*([\d,.]+)\s*(?:亿|billion)',
    ]
    neutral_profit_patterns = [
        r'(?:中性|基准|base\s*case).*?(?:净利(?:润)?|net\s*(?:profit|income))\s*[:：]?\s*(-?[\d,.]+)\s*(?:亿|billion)',
    ]
    optimistic_rev_patterns = [
        r'(?:乐观|牛市|bull\s*case).*?(?:营收|revenue)\s*[:：]?\s*([\d,.]+)\s*(?:亿|billion)',
    ]

    def first_match(text, patterns):
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                try:
                    return float(m.group(1).replace(',', ''))
                except (ValueError, IndexError):
                    pass
        return None

    neutral_rev = first_match(all_text, neutral_rev_patterns)
    neutral_profit = first_match(all_text, neutral_profit_patterns)
    optimistic_rev = first_match(all_text, optimistic_rev_patterns)

    # 2. 提取 DCF 中使用的营收/利润假设
    dcf_rev_patterns = [
        r'DCF.*?(?:营收|revenue)\s*[:：]?\s*([\d,.]+)\s*(?:亿|billion)',
        r'(?:自由现金流|FCF)\s*(?:预测|projection).*?(?:营收|revenue)\s*[:：]?\s*([\d,.]+)',
    ]
    dcf_profit_patterns = [
        r'DCF.*?(?:净利(?:润)?|net\s*(?:profit|income))\s*[:：]?\s*(-?[\d,.]+)\s*(?:亿|billion)',
    ]
    dcf_rev = first_match(all_text, dcf_rev_patterns)
    dcf_profit = first_match(all_text, dcf_profit_patterns)

    # 3. 提取可比估值法使用的营收
    comp_rev_patterns = [
        r'(?:可比|comparable|relative)\s*(?:估值|valuation).*?(?:营收|revenue)\s*[:：]?\s*([\d,.]+)\s*(?:亿|billion)',
        r'PS\s*(?:法|method|valuation).*?(?:营收|revenue)\s*[:：]?\s*([\d,.]+)\s*(?:亿|billion)',
    ]
    comp_rev = first_match(all_text, comp_rev_patterns)

    # 检查 DCF 是否用了乐观假设而非基准
    if dcf_rev and neutral_rev and optimistic_rev:
        if abs(dcf_rev - optimistic_rev) / optimistic_rev < 0.1 and abs(dcf_rev - neutral_rev) / max(neutral_rev, 0.01) > 0.3:
            issues.append({
                'type': 'valuation_scenario_mismatch',
                'severity': 'ERROR',
                'label': 'DCF 假设偷换',
                'detail': f'DCF 使用营收 {dcf_rev}亿 ≈ 乐观情景 {optimistic_rev}亿，而非中性情景 {neutral_rev}亿。目标价被系统性高估。',
            })

    # 检查可比估值法是否用了乐观假设
    if comp_rev and neutral_rev and optimistic_rev:
        if abs(comp_rev - optimistic_rev) / optimistic_rev < 0.1 and abs(comp_rev - neutral_rev) / max(neutral_rev, 0.01) > 0.3:
            issues.append({
                'type': 'valuation_scenario_mismatch',
                'severity': 'ERROR',
                'label': '可比估值营收假设偷换',
                'detail': f'可比估值法使用营收 {comp_rev}亿 ≈ 乐观情景，而非中性情景 {neutral_rev}亿。目标价被系统性高估。',
            })

    # 检查 DCF 用了正利润但情景分析说亏损
    if dcf_profit is not None and neutral_profit is not None:
        if dcf_profit > 0 and neutral_profit < 0:
            issues.append({
                'type': 'valuation_scenario_mismatch',
                'severity': 'ERROR',
                'label': 'DCF 盈利假设与情景矛盾',
                'detail': f'DCF 假设净利润 +{dcf_profit}亿（盈利），但中性情景净利润 {neutral_profit}亿（亏损）。DCF 结果不可信。',
            })

    return issues


# ─── v2 新增：重复内容检测 ──────────────────────

def check_content_repetition(files: dict[str, str]) -> list[dict]:
    """检测 step8 统稿中的重复内容占比"""
    issues = []

    master_text = ''
    for key, text in files.items():
        if 'step8' in key or 'master' in key:
            master_text = text
            break

    if not master_text or len(master_text) < 1000:
        return issues

    # 提取所有实质性句子（去掉短行和标题）
    sentences = []
    for line in master_text.split('\n'):
        stripped = line.strip()
        if len(stripped) > 20 and not stripped.startswith('#'):
            # 规范化
            normalized = re.sub(r'\s+', ' ', stripped).lower()
            sentences.append(normalized)

    if len(sentences) < 10:
        return issues

    # 统计高频重复短语（10字以上）
    phrase_counts = Counter()
    for s in sentences:
        # 切分为 n-gram 短语
        words = s.split()
        for n in range(5, min(len(words), 15)):
            for i in range(len(words) - n + 1):
                phrase = ' '.join(words[i:i+n])
                if len(phrase) > 20:
                    phrase_counts[phrase] += 1

    # 找出重复 >= 4 次的短语
    repeated = [(phrase, count) for phrase, count in phrase_counts.items() if count >= 4]
    repeated.sort(key=lambda x: -x[1])

    if len(repeated) > 5:
        top_repeated = repeated[:10]
        issues.append({
            'type': 'content_repetition',
            'severity': 'WARNING',
            'label': '内容重复',
            'detail': f'统稿中发现 {len(repeated)} 个重复 4 次以上的短语。Top 3: {[f"「{p[:40]}...」×{c}" for p, c in top_repeated[:3]]}',
        })

    # 段落级重复：同一段落出现 3 次以上
    para_counts = Counter()
    for s in sentences:
        if len(s) > 50:
            # 取前 60 字符作为段落指纹
            fingerprint = s[:60]
            para_counts[fingerprint] += 1

    dup_paras = [(p, c) for p, c in para_counts.items() if c >= 3]
    if dup_paras:
        issues.append({
            'type': 'paragraph_duplication',
            'severity': 'WARNING',
            'label': '段落级重复',
            'detail': f'{len(dup_paras)} 个段落出现 ≥3 次。研报需要去重和信息密度优化。',
        })

    return issues


# ─── v2 新增：系统路径/命令泄露扫描 ──────────────

def check_path_leakage(files: dict[str, str]) -> list[dict]:
    """扫描研报中是否泄露了内部系统路径、工具命令、工作流元数据"""
    issues = []

    # 只检查 step8/master（最终产出）
    master_text = ''
    for key, text in files.items():
        if 'step8' in key or 'master' in key:
            master_text = text
            break

    if not master_text:
        return issues

    leak_patterns = [
        (r'/Users/\w+/', 'macOS 用户目录路径'),
        (r'/home/\w+/', 'Linux 用户目录路径'),
        (r'\.openclaw/', 'OpenClaw 工作目录'),
        (r'data/tasks/', '任务目录路径'),
        (r'TASK-\d{8}-\d{3}', '内部任务 ID'),
        (r'python3?\s+scripts/', 'Python 脚本调用命令'),
        (r'(?:bin/yf|ddgs|tavily)', '内部工具名'),
        (r'sessions_spawn|sessions_send', 'OpenClaw 内部命令'),
        (r'subagent|sub-agent|子代理', '子代理工作流术语（不应出现在最终研报中）'),
        (r'step\d+_\w+\.md', '内部 step 文件名'),
        (r'spawn[-_]receipt', 'spawn receipt 元数据'),
        (r'thinking\s*=\s*high', '模型参数'),
        (r'pre-search|presearch', '预搜索工作流术语'),
    ]

    leaked = []
    for pat, desc in leak_patterns:
        matches = re.findall(pat, master_text, re.IGNORECASE)
        if matches:
            leaked.append(f'{desc}（{len(matches)}处，如: {matches[0][:50]}）')

    if leaked:
        issues.append({
            'type': 'path_leakage',
            'severity': 'ERROR',
            'label': '系统路径/命令泄露',
            'detail': f'最终研报中暴露了 {len(leaked)} 类内部信息：{"; ".join(leaked[:5])}',
        })

    return issues


# ─── v2 新增：可比公司适当性 ──────────────────

def check_comparable_appropriateness(files: dict[str, str]) -> list[dict]:
    """检查可比公司选择是否适当（亏损公司不应用已盈利公司做可比 PE）"""
    issues = []
    all_text = '\n'.join(files.values())

    # 检查目标公司是否亏损
    is_loss = bool(re.search(r'(?:净利率|net\s*margin)\s*[:：]?\s*-[\d,.]+%', all_text, re.IGNORECASE))
    is_loss = is_loss or bool(re.search(r'(?:PE|P/E)\s*[:：]?\s*(?:N/?A|负|亏损)', all_text, re.IGNORECASE))

    if not is_loss:
        return issues

    # 如果目标公司亏损，检查是否用了 PE 做主估值
    pe_valuation = re.search(r'(?:PE|P/E)\s*(?:法|method|valuation|估值).*?(?:目标价|target|fair\s*value)', all_text, re.IGNORECASE)
    if pe_valuation:
        issues.append({
            'type': 'comparable_method_mismatch',
            'severity': 'WARNING',
            'label': '亏损公司不宜用 PE 估值',
            'detail': '目标公司当前亏损（PE 为负/N/A），使用 PE 法做主估值不当。建议改用 PS/EV-Revenue。',
        })

    # 检查可比公司 PS 倍数是否差距过大（如��标公司 PS=30x，可比公司 PS=3-5x）
    target_ps_m = re.search(r'(?:PS|P/S)\s*(?:\(TTM\))?\s*[:：]?\s*([\d,.]+)[x倍]?', all_text, re.IGNORECASE)
    if target_ps_m:
        target_ps = float(target_ps_m.group(1).replace(',', ''))
        # 找可比公司的 PS
        comp_ps_matches = re.findall(
            r'(?:可比|comparable).*?(?:PS|P/S)\s*[:：]?\s*([\d,.]+)[x倍]?',
            all_text, re.IGNORECASE
        )
        if comp_ps_matches:
            comp_ps_values = [float(v.replace(',', '')) for v in comp_ps_matches if float(v.replace(',', '')) > 0]
            if comp_ps_values:
                avg_comp_ps = sum(comp_ps_values) / len(comp_ps_values)
                if target_ps > 0 and avg_comp_ps > 0 and target_ps / avg_comp_ps > 5:
                    issues.append({
                        'type': 'comparable_ps_mismatch',
                        'severity': 'WARNING',
                        'label': '可比公司 PS 倍数差距过大',
                        'detail': f'目标 PS={target_ps:.1f}x，可比公司平均 PS={avg_comp_ps:.1f}x，差距 {target_ps/avg_comp_ps:.0f} 倍。可比公司可能不在同一估值逻辑下。',
                    })

    return issues


def load_step_files(task_id: str = '', dir_path: str = '', prefix: str = '') -> dict[str, str]:
    """加载所有 step 文件"""
    files = {}
    search_dir = Path(dir_path) if dir_path else TASKS_DIR

    if task_id:
        for f in search_dir.glob(f'{task_id}-step*.md'):
            step = re.search(r'step(\d+)_(\w+)', f.name)
            if step:
                key = f'step{step.group(1)}_{step.group(2)}'
                files[key] = f.read_text(encoding='utf-8')
        for f in search_dir.glob(f'{task_id}*step*.md'):
            step = re.search(r'step(\d+)_(\w+)', f.name)
            if step:
                key = f'step{step.group(1)}_{step.group(2)}'
                if key not in files:
                    files[key] = f.read_text(encoding='utf-8')

    if prefix:
        for f in search_dir.glob(f'{prefix}*.md'):
            step = re.search(r'step(\d+)_(\w+)', f.name)
            if step:
                key = f'step{step.group(1)}_{step.group(2)}'
                files[key] = f.read_text(encoding='utf-8')
            elif 'master' in f.name.lower():
                files['master'] = f.read_text(encoding='utf-8')

    if task_id:
        master = search_dir / f'{task_id}-step8_master.md'
        if master.exists() and 'step8_master' not in files:
            files['step8_master'] = master.read_text(encoding='utf-8')

    return files


def verify_consistency(files: dict[str, str]) -> dict:
    """核心：跨 step 数据一致性检查"""
    inconsistencies = []
    arithmetic_issues = []

    # 1. 对每个指标，提取各 step 中的值，检查一致性
    for metric_id, config in METRIC_EXTRACTORS.items():
        label = config['label']
        patterns = config['patterns']

        values_by_step = {}
        for step_name, text in files.items():
            vals = extract_values(text, patterns)
            if vals:
                values_by_step[step_name] = vals

        if len(values_by_step) < 2:
            continue

        all_vals = set()
        for step_vals in values_by_step.values():
            for v, _ in step_vals:
                all_vals.add(v)

        if len(all_vals) <= 1:
            continue

        details = []
        for step_name, vals in sorted(values_by_step.items()):
            for v, ctx in vals:
                details.append({
                    'step': step_name,
                    'value': v,
                    'context': ctx[:120],
                })

        vals_list = sorted(all_vals)
        if len(vals_list) >= 2:
            ratio = max(vals_list) / min(vals_list) if min(vals_list) > 0 else float('inf')
            severity = 'ERROR' if ratio > 2 else 'WARNING'
        else:
            severity = 'WARNING'

        inconsistencies.append({
            'metric': metric_id,
            'label': label,
            'severity': severity,
            'unique_values': sorted(all_vals),
            'details': details,
        })

    # 2. 算术检查
    all_text = '\n'.join(files.values())
    arithmetic_issues = check_arithmetic(all_text)

    # 3. v2 新增检查
    scenario_issues = check_valuation_scenario_consistency(files)
    repetition_issues = check_content_repetition(files)
    leakage_issues = check_path_leakage(files)
    comparable_issues = check_comparable_appropriateness(files)

    all_issues = inconsistencies + arithmetic_issues + scenario_issues + repetition_issues + leakage_issues + comparable_issues

    # 统计
    errors = [i for i in all_issues if i.get('severity') == 'ERROR']
    warnings = [i for i in all_issues if i.get('severity') == 'WARNING']

    passed = len(errors) == 0
    verdict = 'PASS' if passed else 'FAIL'
    if not passed:
        reason = f'{len(errors)} 个严重问题'
    elif warnings:
        verdict = 'WARN'
        reason = f'无严重问题，但有 {len(warnings)} 个警告'
    else:
        reason = '所有检查通过'

    return {
        'passed': passed,
        'verdict': verdict,
        'reason': reason,
        'error_count': len(errors),
        'warning_count': len(warnings),
        'inconsistencies': [i for i in all_issues if 'metric' in i],
        'arithmetic_issues': arithmetic_issues,
        'scenario_issues': scenario_issues,
        'repetition_issues': repetition_issues,
        'leakage_issues': leakage_issues,
        'comparable_issues': comparable_issues,
        'steps_checked': list(files.keys()),
        'checked_at': datetime.now().isoformat(timespec='seconds'),
    }


def main():
    ap = argparse.ArgumentParser(description='跨 Step 数据一致性检查 v2')
    ap.add_argument('--task-id', default='', help='Task ID')
    ap.add_argument('--dir', default='', help='Step 文件目录')
    ap.add_argument('--prefix', default='', help='Step 文件前缀')
    args = ap.parse_args()

    if not args.task_id and not args.prefix:
        print('Error: must provide --task-id or --prefix', file=sys.stderr)
        raise SystemExit(1)

    files = load_step_files(task_id=args.task_id, dir_path=args.dir, prefix=args.prefix)
    if not files:
        print(json.dumps({'passed': False, 'verdict': 'FAIL', 'reason': 'No step files found'}, indent=2))
        raise SystemExit(1)

    result = verify_consistency(files)

    if args.task_id:
        out_path = TASKS_DIR / f'{args.task_id}-consistency-check.json'
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    print(json.dumps(result, ensure_ascii=False, indent=2))

    if result['verdict'] == 'FAIL':
        raise SystemExit(1)
    elif result['verdict'] == 'WARN':
        raise SystemExit(2)


if __name__ == '__main__':
    main()

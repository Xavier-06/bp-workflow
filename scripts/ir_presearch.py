#!/usr/bin/env python3
"""
IR Pre-search — 在 subagent 发射前，用 research_api 跑一轮搜索
把结果存到 data/tasks/TASK-XXX-search-stepN.md，subagent 直接读

v4 (2026-04-06): 港股/A 股搜索自动追加股票代码消歧 + 噪音过滤增强

用法：
    python3 scripts/ir_presearch.py --task-id TASK-XXX --entity "公司名" --market hk --ticker 02283
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'

# SSL env
os.environ.setdefault('SSL_CERT_FILE', '/opt/homebrew/etc/openssl@3/cert.pem')
os.environ.setdefault('REQUESTS_CA_BUNDLE', '/opt/homebrew/etc/openssl@3/cert.pem')

CURRENT_YEAR = datetime.now().year
PREV_YEAR = CURRENT_YEAR - 1

# Step-specific search queries — 每个 step 5-12 条，覆盖中英文
# {entity} 会被替换为实际标的名, {year} 替换为当前年份, {prev_year} 上一年
STEP_QUERIES = {
    'step1_data': [
        # 行情/估值
        '{entity} stock price market cap PE ratio {year}',
        '{entity} shares outstanding total issued shares {prev_year}',
        # 年报核心
        '{entity} annual report {prev_year} revenue net profit gross margin',
        '{entity} {prev_year} 年报 营收 净利润 毛利率 经营现金流',
        '{entity} {prev_year} annual results revenue breakdown segment',
        # 分析师
        '{entity} analyst target price rating consensus {year}',
        '{entity} analyst coverage buy hold sell rating count',
        # 分部/地区
        '{entity} overseas revenue international segment breakdown {prev_year}',
        '{entity} 海外 收入 占比 分部 地区 {prev_year} {year}',
        # 资产负债表/现金流
        '{entity} cash and equivalents total debt balance sheet {prev_year}',
        '{entity} 现金 负债 应收账款 存货 资产负债表 {prev_year}',
        '{entity} operating cash flow free cash flow capex {prev_year}',
        # 回购/分红/配售
        '{entity} share buyback dividend repurchase {year}',
        '{entity} placement offering dilution share issuance history',
        '{entity} 配售 增发 稀释 募资 历史',
        # 特殊项
        '{entity} government subsidy grant income {prev_year}',
        '{entity} 政府补贴 补助 收入 {prev_year}',
        '{entity} audit opinion auditor report {prev_year}',
        '{entity} related party transactions {prev_year}',
        # 员工
        '{entity} employee count headcount R&D staff {prev_year}',
        '{entity} 员工 人数 研发 占比 {prev_year}',
    ],
    'step2_industry': [
        '{entity} industry market size growth rate {year}',
        '{entity} industry market size TAM SAM {year}',
        '{entity} competitors market share competitive landscape {year}',
        '{entity} 行业 市场规模 增速 竞争格局 {year}',
        '{entity} industry drivers trends risks regulation',
        '{entity} competitor product shipment volume delivery {prev_year} {year}',
        '{entity} 竞争对手 出货量 产量 融资 {year}',
        '{entity} industry policy government support subsidy',
    ],
    'step3_biz': [
        '{entity} business model revenue breakdown segments {prev_year}',
        '{entity} revenue by product line segment {prev_year} annual report',
        '{entity} 收入构成 业务线 分部收入 {prev_year}',
        '{entity} moat competitive advantage differentiation',
        '{entity} unit economics gross margin pricing power',
        '{entity} customer retention rate member ARPU',
        '{entity} production capacity target output volume {year}',
        '{entity} key customers order backlog pipeline {year}',
    ],
    'step4_finance': [
        '{entity} financial results revenue profit cash flow 3 year trend',
        '{entity} {prev_year} annual report income statement balance sheet cash flow',
        '{entity} valuation PE PB PS DCF target price {year}',
        '{entity} free cash flow capex operating cash flow {prev_year}',
        '{entity} 财务分析 营收 净利润 现金流 毛利率 {prev_year}',
        '{entity} debt ratio net cash leverage interest coverage {prev_year}',
        '{entity} inventory turnover days receivable days working capital',
        '{entity} ROE ROIC return on equity invested capital {prev_year}',
        '{entity} revenue quality core profit excluding subsidies',
    ],
    'step5_mgmt': [
        '{entity} CEO management team background experience',
        '{entity} corporate governance board directors ownership structure',
        '{entity} share buyback amount repurchase plan {year}',
        '{entity} 管理层 CEO 创始人 大股东 股权结构',
        '{entity} capital allocation dividend policy M&A history',
        '{entity} 回购 金额 港元 股份数 {year}',
        '{entity} insider buying selling major shareholder change {year}',
        '{entity} 大股东 减持 增持 锁定期 {year}',
        '{entity} stock option RSU employee incentive plan',
        '{entity} related party transaction connected transaction {prev_year}',
    ],
    'step6_insight': [
        '{entity} non-consensus bull case contrarian view {year}',
        '{entity} undervalued catalyst upcoming events {year}',
        '{entity} market blind spot overlooked positive factor',
        '{entity} 被低估 催化剂 非共识 {year}',
        '{entity} short interest short selling ratio {year}',
    ],
    'step6b_valuation': [
        '{entity} DCF valuation WACC discount rate terminal value',
        '{entity} comparable company PE PB PS EV/EBITDA valuation',
        '{entity} analyst consensus target price {year}',
        '{entity} 估值 目标价 可比公司 敏感性分析',
        '{entity} revenue growth forecast earnings projection {year}',
    ],
    'step7_risk': [
        '{entity} key risks bear case downside scenario {year}',
        '{entity} competition threat regulatory risk',
        '{entity} catalyst timeline upcoming events earnings date {year}',
        '{entity} 风险 挑战 竞争 监管 {year}',
        '{entity} going concern cash burn rate runway',
        '{entity} 持续经营 现金消耗 {year}',
        '{entity} dilution risk placement offering frequency impact',
        '{entity} lock-up expiry shareholder selling pressure',
    ],
}



# 港股/A 股专属：HKEX/官方源定向搜索 + 英文版高优 query
# 用于消除中文歧义 + 直达年报原文
HKEX_QUERIES = {
    'step1_data': [
        '{entity_en} {ticker} annual report {prev_year} results revenue profit HKEX',
        '{entity_en} {ticker} {prev_year} full year results announcement',
        '{ticker} HKEX annual results {prev_year}',
    ]
}

# ============================================================
# 噪音过滤集成 (v3, 2026-04-04)
# ============================================================

def _apply_noise_filter(query: str, entity: str, market: str) -> str:
    """应用搜索词噪音过滤"""
    try:
        sys.path.insert(0, str(ROOT))
        from scripts.ir_noise_filter import build_search_query
        return build_search_query(entity, query, market)
    except Exception:
        return query


def _check_step_noise(results_dict: dict, entity: str) -> dict:
    """检查单步搜索结果的噪音比率"""
    try:
        sys.path.insert(0, str(ROOT))
        from scripts.ir_noise_filter import check_noise_ratio
        search_results = results_dict.get('raw_results', [])
        if not search_results:
            return {'status': 'no_results', 'ratio': 1.0}
        ratio, report = check_noise_ratio(search_results, entity)
        return {'status': 'checked', 'ratio': ratio, 'report': report}
    except Exception:
        return {'status': 'error'}


# ============================================================
# Presearch runner
# ============================================================

def run_presearch(task_id: str, entity: str, market: str = 'us', steps: list[str] | None = None,
                 ticker: str = '', english_name: str = '') -> dict:
    """
    运行预搜索。v5 (2026-04-06 修复)：
    1. 港股/A 股搜索前 3 条强制纯英文（公司英文名 + 代码 + HKEX）
    2. 逐条搜索，不再拼接成一个超长字符串
    3. 加 HKEX 披露易定向搜索
    """
    sys.path.insert(0, str(ROOT))
    from scripts.search_gateway import search as gateway_search

    if steps is None:
        steps = list(STEP_QUERIES.keys())

    disambig_suffix = ''
    clean_ticker = ''
    if market in ('hk', 'cn') and ticker:
        clean_ticker = ticker.replace('.HK', '').replace('.SZ', '').replace('.SH', '')
        disambig_suffix = f' {clean_ticker}'

    # 默认英文名为空，港股/A 股从 ticker 推断
    entity_en = english_name or ''

    results = {}
    total_noise_alerts = 0

    for step_name in steps:
        queries = STEP_QUERIES.get(step_name, [])
        if not queries:
            continue

        # 替换模板变量
        def fmt(q):
            return q.format(entity=entity, year=CURRENT_YEAR, prev_year=PREV_YEAR,
                           entity_en=entity_en, ticker=clean_ticker)

        # 港股/A 股：前 3 条强制英文 (HKEX_QUERIES)
        hkex_queries = []
        if market in ('hk', 'cn') and clean_ticker:
            hkex_queries = HKEX_QUERIES.get(step_name, [])
        
        MAX_QUERIES_PER_STEP = 8  # presearch 是粗筛，不需要 20+ 条
        all_queries = []
        if hkex_queries:
            all_queries = [_apply_noise_filter(fmt(q), entity, market) for q in hkex_queries]
        all_queries += [_apply_noise_filter(fmt(q) + disambig_suffix, entity, market) for q in queries]
        all_queries = all_queries[:MAX_QUERIES_PER_STEP]

        output_path = TASKS_DIR / f'{task_id}-search-{step_name}.md'
        if output_path.exists() and output_path.stat().st_size > 500:
            results[step_name] = {'status': 'cached', 'path': str(output_path)}
            continue

        # ★ 轻量搜索：直接用 search_gateway（单次搜索 2-5s），
        #   不再用 run_research（多轮迭代搜索 ~158s/次）
        all_memo_lines = []
        total_accepted = 0
        all_citations = {}
        citation_counter = 1
        any_noise = False

        print(f'  📡 {step_name}: {len(all_queries)} queries ...', flush=True)
        for i, single_query in enumerate(all_queries):
            try:
                rows = gateway_search(single_query, max_results=8, timeout=20)
                if rows:
                    all_memo_lines.append(f'### [{i+1}] {single_query[:120]}')
                    all_memo_lines.append('')
                    for row in rows:
                        title = row.get('title', '') or ''
                        url = row.get('url', '') or ''
                        snippet = row.get('content', '') or row.get('snippet', '') or ''
                        engine = row.get('engine', '?')
                        if url:
                            all_citations[str(citation_counter)] = url
                            all_memo_lines.append(f'- [{engine}] [{title}]({url})')
                            if snippet:
                                all_memo_lines.append(f'  > {snippet[:300]}')
                            citation_counter += 1
                            total_accepted += 1
                    all_memo_lines.append('')

                # 噪音检查
                noise_report = _check_step_noise({'raw_results': rows}, entity)
                if noise_report.get('ratio', 0) > 0.6:
                    any_noise = True

            except Exception as e:
                all_memo_lines.append(f'⚠ Query {i+1} 失败: {str(e)[:100]}')

            # 控制调用量：每条 query 之间短暂等待
            if i < len(all_queries) - 1:
                import time
                time.sleep(0.5)

        # 如果噪音率过高，追加告警
        if any_noise:
            total_noise_alerts += 1
            noise_note = f'\n> ⚠️ 噪音告警: 部分搜索结果存在噪音 (>60%)，建议检查搜索词策略。\n'
        else:
            noise_note = ''

        lines = [
            f'# Pre-search Results: {step_name}',
            f'',
            f'- Entity: {entity}',
            f'- Entity (EN): {entity_en if entity_en else "N/A"}',
            f'- Ticker: {clean_ticker if clean_ticker else "N/A"}',
            f'- Market: {market}',
            f'- Queries: {len(all_queries)} (HKEX english: {len(hkex_queries)})',
            f'- Accepted evidence: {total_accepted}',
            f'- Generated: {datetime.now().isoformat(timespec="seconds")}',
            f'',
            f'## Search Memo',
            f'',
            '\n'.join(all_memo_lines) if all_memo_lines else '_No search results._',
            noise_note,
            f'',
            f'## Citations',
            f'',
        ]
        for idx, url in sorted(all_citations.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else 0):
            lines.append(f'[{idx}] {url}')

        output_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        results[step_name] = {
            'status': 'ok',
            'path': str(output_path),
            'accepted_count': total_accepted,
            'memo_length': sum(len(l) for l in all_memo_lines),
            'query_count': len(all_queries),
            'hkex_query_count': len(hkex_queries),
            'noise_alert': any_noise,
        }

    summary = {
        'task_id': task_id,
        'entity': entity,
        'entity_en': entity_en,
        'ticker': clean_ticker,
        'market': market,
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'steps': results,
        'total_noise_alerts': total_noise_alerts,
        'disambiguation_suffix': disambig_suffix,
    }

    if total_noise_alerts > 0:
        summary['warning'] = f'{total_noise_alerts} 个 step 存在高噪音搜索结果 (>60%)，可能影响 Gap 检测准确性'

    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--task-id', required=True)
    ap.add_argument('--entity', required=True)
    ap.add_argument('--market', default='us')
    ap.add_argument('--ticker', default='', help='股票代码（港股/A 股必填，用于搜索消歧）')
    ap.add_argument('--english-name', default='', help='公司英文名（便于英文搜索，如 TK Group Holdings）')
    ap.add_argument('--steps', nargs='*', help='Specific steps to pre-search')
    args = ap.parse_args()

    result = run_presearch(args.task_id, args.entity, args.market, args.steps, args.ticker, args.english_name)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

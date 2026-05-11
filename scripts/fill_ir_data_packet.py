#!/usr/bin/env python3
"""
fill_ir_data_packet.py v2 - 用 run_research() 替代 Tavily/legacy 搜索
接口兼容旧版：接收 search_plan JSON，输出 {subtask_id}-packet-filled.md

v2.1: 搜索完成后自动调用域名黑名单过滤（ir_evidence_blacklist），
      在渲染前剔除无关来源。
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / 'data' / 'tasks'
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

# SSL fix
CERT = '/opt/homebrew/etc/openssl@3/cert.pem'
if Path(CERT).exists():
    os.environ.setdefault('SSL_CERT_FILE', CERT)
    os.environ.setdefault('REQUESTS_CA_BUNDLE', CERT)
    os.environ.setdefault('CURL_CA_BUNDLE', CERT)
    os.environ.setdefault('SSL_CERT_DIR', '/opt/homebrew/etc/openssl@3/certs')

# 引用共享黑名单模块
from ir_evidence_blacklist import is_blacklisted


def parse_search_plan(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def detect_market(plan: dict) -> str:
    tc = plan.get('target_company', {}) or {}
    ticker = (tc.get('ticker') or '').upper()
    exchange = (tc.get('exchange') or '').upper()
    topic = (plan.get('topic') or plan.get('original_query') or '').upper()
    if exchange == 'HKEX' or ticker.endswith('.HK') or '.HK' in topic:
        return 'hk'
    if exchange in {'NASDAQ', 'NYSE', 'AMEX'}:
        return 'us'
    if re.search(r'\b(10-K|10-Q|8-K|NASDAQ|NYSE|SEC)\b', topic):
        return 'us'
    return 'generic'


def infer_entity(plan: dict) -> str:
    """从 search_plan 提取研究主体名称"""
    tc = plan.get('target_company', {}) or {}
    name = tc.get('name') or tc.get('chinese_name') or tc.get('english_name') or ''
    if name:
        return name.strip()
    # fallback: 从 original_query 提取
    query = plan.get('original_query') or plan.get('topic') or ''
    # 去掉常见前缀
    for prefix in ['研究', '分析', '关于', '调查']:
        query = query.replace(prefix, '')
    return query.strip().split()[0] if query.strip() else '未知标的'


def infer_ticker(plan: dict) -> str:
    tc = plan.get('target_company', {}) or {}
    return tc.get('ticker') or ''


def filter_evidence_by_blacklist(state) -> dict:
    """在渲染前用域名黑名单过滤 runner 返回的 evidence。
    返回 {'filtered_count': int, 'dropped_urls': list[str]}"""
    filtered_count = 0
    dropped_urls = []

    original_evidence = list(state.all_evidence)
    kept = []
    for ev in original_evidence:
        url = ev.url or ''
        if url and is_blacklisted(url):
            ev.accepted = False
            filtered_count += 1
            dropped_urls.append(url)
        kept.append(ev)

    # 更新 state 的 evidence（保留所有但标记 accepted=False）
    state.all_evidence = kept
    return {'filtered_count': filtered_count, 'dropped_urls': dropped_urls}


def render_packet(plan: dict, state, market: str) -> str:
    """把 ResearchState 渲染成 packet-filled.md 格式"""
    entity = state.plan.entity
    ticker = infer_ticker(plan)
    subtask_id = plan.get('subtask_id', 'unknown')
    now = datetime.now().strftime('%Y-%m-%d %H:%M')

    lines = [
        f'# 数据包：{entity} ({subtask_id})',
        f'生成时间：{now} | 市场：{market} | 搜索轮数：{state.rounds_used}',
        '',
    ]

    # 估值快照
    vd = getattr(state, 'valuation_data', {})
    if vd and vd.get('price'):
        lines += [
            '## 估值快照（Yahoo Finance）',
            f'- Ticker: {vd.get("ticker", ticker)}',
            f'- 股价: {vd.get("price")}',
            f'- P/E: {vd.get("pe_ratio", "N/A")}',
            f'- P/S: {vd.get("ps_ratio", "N/A")}',
            f'- 市值: {vd.get("market_cap", "N/A")}',
            f'- 52W区间: {vd.get("52w_low", "N/A")} – {vd.get("52w_high", "N/A")}',
            f'- EPS TTM: {vd.get("eps_ttm", "N/A")}',
            '',
        ]

    # 证据列表
    accepted = [e for e in state.all_evidence if e.accepted]
    lines += [
        f'## 搜索证据（{len(accepted)} 条 accepted / {len(state.all_evidence)} 条总计）',
        '',
    ]

    for i, ev in enumerate(accepted, 1):
        title = ev.title or '(无标题)'
        url = ev.url or ''
        domain = ev.domain or ''
        sf = getattr(ev, 'source_family', 'other')
        conf = getattr(ev, 'confidence', 'low')
        pub = ev.published_at or ''
        snippet = (ev.snippet or '')[:300].replace('\n', ' ')
        ft_len = len(ev.full_text or '')

        lines += [
            f'### [{i}] {title}',
            f'- 来源: [{domain}]({url}) | 类型: {sf} | 置信度: {conf} | 发布: {pub}',
            f'- 正文长度: {ft_len} 字符',
            f'- 摘要: {snippet}',
            '',
        ]

        # 如果有正文，输出前 1500 字
        if ev.full_text and len(ev.full_text) > 200:
            excerpt = ev.full_text[:1500].replace('\n', ' ')
            lines += [
                f'<full_text_excerpt>',
                excerpt,
                '</full_text_excerpt>',
                '',
            ]

    # citation map
    if state.citation_map:
        lines += ['## 来源索引', '']
        for url, info in sorted(state.citation_map.items(), key=lambda x: x[1]['index']):
            idx = info['index']
            t = info.get('title', '')[:80]
            d = info.get('domain', '')
            lines.append(f'{idx}. [{t}]({url}) — {d}')
        lines.append('')

    # gap / 缺口
    if state.unanswered_subquestions:
        lines += ['## 证据缺口', '']
        for sq in state.unanswered_subquestions:
            lines.append(f'- {sq}')
        lines.append('')

    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('search_plan_path')
    args = ap.parse_args()

    plan_path = Path(args.search_plan_path)
    plan = parse_search_plan(plan_path)

    # 验证
    validation = plan.get('validation', {}) or {}
    if validation and not validation.get('ok', True):
        print(json.dumps({
            'subtask_id': plan.get('subtask_id'),
            'blocked': True,
            'reason': validation.get('reason'),
            'action': validation.get('action'),
        }, ensure_ascii=False, indent=2))
        raise SystemExit(2)

    market = detect_market(plan)
    entity = infer_entity(plan)
    ticker = infer_ticker(plan)
    query = plan.get('original_query') or plan.get('topic') or f'研究{entity}'
    subtask_id = plan.get('subtask_id', 'unknown')

    print(f'[fill_ir_data_packet v2.1] entity={entity!r} market={market} ticker={ticker}', flush=True)

    # 调用 runner 搜索（单次，不重复）
    from research.runner import ResearchRunner
    runner = ResearchRunner(max_fetch_per_round=10, snippet_only=False, max_rounds=3)
    state = runner.run('company_research', query, entity=entity, market=market)

    # ── 域名黑名单过滤：在渲染前剔除无关来源 ──
    blacklist_result = filter_evidence_by_blacklist(state)
    if blacklist_result['filtered_count'] > 0:
        print(f'[fill_ir_data_packet] 域名黑名单过滤：剔除 {blacklist_result["filtered_count"]} 条来源', flush=True)
        for url in blacklist_result['dropped_urls'][:5]:
            print(f'  - {url}', flush=True)

    # 渲染输出
    out_path = TASKS_DIR / f'{subtask_id}-packet-filled.md'
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_packet(plan, state, market), encoding='utf-8')

    accepted_count = sum(1 for e in state.all_evidence if e.accepted)
    summary = {
        'subtask_id': subtask_id,
        'filled_packet': str(out_path),
        'result_count': accepted_count,
        'market': market,
        'entity': entity,
        'rounds': state.rounds_used,
        'valuation': getattr(state, 'valuation_data', {}),
        'citations': len(state.citation_map),
        'blacklist_filtered': blacklist_result['filtered_count'],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

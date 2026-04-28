#!/usr/bin/env python3
"""
IR 研报管线 — 上市公司官方数据验证层

针对上市公司，从三大市场的官方/准官方渠道验证：
  - A 股：巨潮资讯（cninfo.com.cn）/ 上交所（sse.com.cn）/ 深交所（szse.cn）
  - 港股：港交所披露易（hkexnews.hk）
  - 美股：SEC EDGAR（sec.gov）
  
验证内容：
  1. 公司基本信息（上市状态、股票代码、行业分类）
  2. 最新财年收入/利润数据（与公开数据交叉验证）
  3. 近期重大公告/事件（并购、高管变动、股权激励等）
  4. 审计意见（是否有保留意见/强调事项）
  5. 大股东/管理层变动
  
用法：
  python3 scripts/ir_company_verify.py --task-id TASK-XXX --entity "英伟达" --market us
  python3 scripts/ir_company_verify.py --task-id TASK-XXX --entity "腾讯" --market hk
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

os.environ.setdefault('SSL_CERT_FILE', '/opt/homebrew/etc/openssl@3/cert.pem')
os.environ.setdefault('REQUESTS_CA_BUNDLE', '/opt/homebrew/etc/openssl@3/cert.pem')

WORKSPACE = Path(__file__).resolve().parent.parent
TASKS_DIR = WORKSPACE / 'data' / 'tasks'
SCRIPTS_DIR = WORKSPACE / 'scripts'
sys.path.insert(0, str(SCRIPTS_DIR))

CURRENT_YEAR = datetime.now().year
PREV_YEAR = CURRENT_YEAR - 1

# ── 市场 → 官方查询模板 ──

MARKET_VERIFY_QUERIES = {
    'us': [
        # SEC EDGAR
        '"10-K" site:sec.gov {entity}',
        '"10-Q" site:sec.gov {entity}',
        '"8-K" site:sec.gov {entity}',
        'DEF 14A proxy statement site:sec.gov {entity}',
        # Yahoo Finance / Seeking Alpha 等
        '{entity} annual report revenue {year}',
        '{entity} SEC filing insider buying selling',
        '{entity} auditor opinion {year}',
    ],
    'hk': [
        '{entity} 港股 年报 业绩 {year}',
        '{entity} 港股 财报 营收 净利润 {prev_year}',
        '{entity} 董事 变动 高管离职',
        '{entity} 回购 增持 减持 {year}',
        '{entity} hkexnews annual report',
    ],
    'cn': [
        # 巨潮
        'site:cninfo.com.cn {entity} 年度报告',
        'site:cninfo.com.cn {entity} 业绩快报',
        'site:cninfo.com.cn {entity} 股东 大股东 减持',
        'site:cninfo.com.cn {entity} 董监高 变动',
        'site:cninfo.com.cn {entity} 审计 意见',
        '{entity} 年报 营业收入 净利润 {year}',
        '{entity} 限售 解禁 减持公告',
    ],
}


def _do_search(query: str, max_results: int = 5, timeout: int = 15) -> list:
    """统一搜索网关，带单次超时保护"""
    import concurrent.futures
    def _inner():
        try:
            from search_gateway import search as _gw
            return _gw(query, max_results=max_results, timeout=min(timeout, 15))
        except ImportError:
            try:
                from searxng_search import search as _old
                return _old(query, max_results=max_results, timeout=min(timeout, 15))
            except Exception:
                return []
        except Exception:
            return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(_inner)
        try:
            return fut.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            print(f" ⏱️ 超时({timeout}s)", end='', flush=True)
            return []


def _extract_financial_snippet(results: list, entity: str) -> list:
    """从搜索结果中提取财务相关片段"""
    snippets = []
    money_patterns = [
        r'营收?\s*([0-9,]+\.?\d*)\s*(亿 | 万|million|billion)',
        r'净利\s*润?\s*([0-9,]+\.?\d*)\s*(亿 | 万|million|billion)',
        r'revenue\s*[\$￥]?\s*([0-9,]+\.?\d*)\s*(亿 | 万|B|M)',
        r'earnings?\s*\$?\s*([0-9,]+\.?\d*)\s*(bill | million|B|M)',
        r'EPS\s*[\$￥]?\s*([0-9]+\.?\d*)',
        r'毛利率\s*([0-9]+\.?\d*)\s*%',
        r'operating margin\s*([0-9]+\.?\d*)\s*%',
    ]
    for r in results:
        text = f"{r.get('title', '')} {r.get('content', '')} {r.get('snippet', '')}"
        for pat in money_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                snippets.append({
                    'text': text[:200],
                    'url': r.get('url', ''),
                    'metric': f"{m.group(0)[:40]}",
                })
                break
    return snippets


def _extract_events_snippet(results: list) -> list:
    """提取重大事件"""
    events = []
    event_keywords = [
        '并购', '收购', '重组', 'divest', 'acquisition', 'merger',
        '高管离职', 'CEO 辞', 'cfo resign', 'ceo resign',
        '股权激励', 'RSU', 'stock option', '员工持股',
        '减持', '增持', 'insider buying', 'insider selling',
        '审计', 'auditor change', '审计意见',
        '回购', 'buyback', 'share repurchase',
        '配售', '增发', 'placement', 'offering',
    ]
    for r in results:
        text = f"{r.get('title', '')} {r.get('content', '')}".lower()
        matched = [kw for kw in event_keywords if kw.lower() in text]
        if matched:
            events.append({
                'keywords': matched,
                'title': r.get('title', ''),
                'url': r.get('url', ''),
                'snippet': r.get('content', '')[:200],
            })
    return events


def run(task_id: str, entity: str = '', market: str = 'us') -> dict:
    import datetime
    year = datetime.datetime.now().year
    prev_year = year - 1
    
    if not entity:
        # 尝试从 task package 获取
        pkg_path = TASKS_DIR / f'{task_id}.json'
        if pkg_path.exists():
            pkg = json.loads(pkg_path.read_text(encoding='utf-8'))
            entity = pkg.get('entity', pkg.get('query', ''))
    
    if not entity:
        print("❌ 需要提供 --entity 参数")
        return {'error': 'no_entity'}
    
    print(f"\n{'='*60}")
    print(f"🏛️ 上市公司官方数据验证: {entity} ({market})")
    print(f"{'='*60}")
    
    # 1. 构建查询
    templates = MARKET_VERIFY_QUERIES.get(market, MARKET_VERIFY_QUERIES['us'])
    queries = [
        t.format(entity=entity, year=year, prev_year=prev_year)
        for t in templates
    ]
    # 加通用验证查询（中英文混合，适配中文公司名）
    universal = [
        f'{entity} 年报 annual report {prev_year}',
        f'{entity} 研报 券商 评级 {year}',
    ]
    queries.extend(universal)
    
    # 2. 执行搜索
    all_results = []
    total_queries = len(queries)
    for i, q in enumerate(queries, 1):
        print(f"  [{i}/{total_queries}] {q[:60]}...", end='', flush=True)
        results = _do_search(q, max_results=5)
        print(f"→ {len(results)} 条")
        for r in results:
            r['_query'] = q
        all_results.extend(results)
        time.sleep(0.3)
    
    print(f"\n  总结果: {len(all_results)}")
    
    # 3. 分类提取
    financial_snippets = _extract_financial_snippet(all_results, entity)
    events = _extract_events_snippet(all_results)
    
    # 4. 官方源计数
    official_count = 0
    official_domains = ['sec.gov', 'hkexnews.hk', 'cninfo.com.cn', 'sse.com.cn', 'szse.cn']
    for r in all_results:
        url = r.get('url', '').lower()
        if any(d in url for d in official_domains):
            official_count += 1
    
    # 5. Yahoo Finance 估值补充
    valuation_data = {}
    try:
        sys.path.insert(0, str(WORKSPACE))
        from tasks.valuation_enricher import enrich_with_yahoo
        valuation_data = enrich_with_yahoo(entity)
        if valuation_data:
            ticker = valuation_data.get('ticker', '')
            price = valuation_data.get('price', 'N/A')
            pe = valuation_data.get('pe_ratio', 'N/A')
            print(f"\n  📈 Yahoo Finance: {ticker} | 价格=${price} | PE={pe}")
        else:
            print(f"\n  📈 Yahoo Finance: 未找到对应 ticker")
    except Exception as e:
        print(f"\n  📈 Yahoo Finance: 获取失败 ({e})")
        valuation_data = {'error': str(e)}
    
    # 6. 组装报告
    report = {
        'task_id': task_id,
        'entity': entity,
        'market': market,
        'verify_time': time.strftime('%Y-%m-%d %H:%M:%S'),
        'total_queries': total_queries,
        'total_results': len(all_results),
        'official_source_count': official_count,
        'official_sources_found': official_count > 0,
        'financial_data': financial_snippets[:10],
        'key_events': events[:10],
        'valuation_data': valuation_data,
        'source_urls': list(set(r.get('url', '') for r in all_results if r.get('url')))[:20],
    }
    
    # 保存 JSON
    report_path = TASKS_DIR / f'{task_id}-ir_company_verify.json'
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    
    # 保存 Markdown
    md_lines = [
        f'# 上市公司官方数据验证 — {entity}',
        f'',
        f'**验证时间**: {time.strftime("%Y-%m-%d %H:%M:%S")}',
        f'**市场**: {market.upper()}',
        f'**官方源**: {official_count} 条 {"✅ 找到" if official_count > 0 else "⚠️ 未找到"}',
        f'**查询数**: {total_queries}',
        f'**结果数**: {len(all_results)}',
        f'',
        f'## 估值数据 (Yahoo Finance)',
        f'',
    ]
    if valuation_data.get('ticker'):
        md_lines.append(f'| 字段 | 值 |')
        md_lines.append(f'|------|-----|')
        md_lines.append(f'| Ticker | {valuation_data["ticker"]} |')
        md_lines.append(f'| 价格 | ${valuation_data.get("price", "N/A")} |')
        md_lines.append(f'| PE | {valuation_data.get("pe_ratio", "N/A")} |')
        md_lines.append(f'| PS | {valuation_data.get("ps_ratio", "N/A")} |')
        md_lines.append(f'| PB | {valuation_data.get("pb_ratio", "N/A")} |')
        md_lines.append(f'| 市值 | {valuation_data.get("market_cap", "N/A")} |')
        md_lines.append(f'| 52W 高 | ${valuation_data.get("52w_high", "N/A")} |')
        md_lines.append(f'| 52W 低 | ${valuation_data.get("52w_low", "N/A")} |')
        md_lines.append(f'| 收入 TTM | {valuation_data.get("revenue_ttm", "N/A")} |')
        md_lines.append(f'| EPS TTM | ${valuation_data.get("eps_ttm", "N/A")} |')
    else:
        md_lines.append(f'- 未找到对应 ticker 或获取失败')
    md_lines.append('')
    
    if financial_snippets:
        md_lines.append(f'## 财务数据交叉验证 ({len(financial_snippets)} 条)')
        md_lines.append(f'')
        for i, s in enumerate(financial_snippets[:5], 1):
            md_lines.append(f'{i}. **{s["metric"]}**')
            md_lines.append(f'   - {s["text"][:150]}')
            md_lines.append(f'   - [来源]({s["url"]})')
            md_lines.append(f'')
    
    if events:
        md_lines.append(f'## 重大事件 ({len(events)} 条)')
        md_lines.append(f'')
        for i, e in enumerate(events[:5], 1):
            md_lines.append(f'{i}. **{", ".join(e["keywords"])}**')
            md_lines.append(f'   - {e["title"]}')
            md_lines.append(f'   - {e["snippet"][:150]}')
            md_lines.append(f'   - [来源]({e["url"]})')
            md_lines.append(f'')
    
    md_path = TASKS_DIR / f'{task_id}-ir_company_verify.md'
    md_path.write_text('\n'.join(md_lines) + '\n', encoding='utf-8')
    
    # 打印摘要
    print(f"\n  📁 JSON: {report_path}")
    print(f"  📁 MD: {md_path}")
    
    return report


def main():
    ap = argparse.ArgumentParser(description='IR 上市公司官方数据验证')
    ap.add_argument('--task-id', required=True)
    ap.add_argument('--entity', default='', help='Entity name')
    ap.add_argument('--market', default='us', choices=['us', 'hk', 'cn'])
    args = ap.parse_args()
    run(args.task_id, args.entity, args.market)


if __name__ == '__main__':
    main()

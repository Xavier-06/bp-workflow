#!/usr/bin/env python3
"""
搜索三引擎压测 — Yahoo + DDG + SearXNG 互补性验证

验证三个搜索引擎返回不同、互补的结果：
- Yahoo: 金融数据（股票行情、财务指标）
- DDG: 通用搜索（新闻、分析、评论）
- SearXNG: 元搜索（聚合多引擎，覆盖面最广）

压测维度：
1. 同一查询三引擎结果去重率（越低越好 → 互补性强）
2. 各引擎独立返回量
3. 各引擎响应时间
4. 金融 vs 通用查询路由是否正确
"""
from __future__ import annotations

import json
import time
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from search.adapters.yahoo import YahooAdapter
from search.adapters.ddg import DDGAdapter
from search.adapters.searxng import SearXNGAdapter
from search.config import searxng_urls


# 压测查询集
TEST_QUERIES = [
    # 金融查询（应优先走 Yahoo）
    {'query': 'AAPL', 'type': 'financial', 'desc': '美股 ticker'},
    {'query': '0700.HK', 'type': 'financial', 'desc': '港股 ticker'},
    {'query': 'Tesla stock price earnings', 'type': 'financial', 'desc': '金融关键词'},
    {'query': '腾讯 市值', 'type': 'financial', 'desc': '中文金融查询'},
    
    # 通用查询（应走 SearXNG/DDG）
    {'query': 'AI chip market size 2025', 'type': 'general', 'desc': '英文通用'},
    {'query': '中国新能源行业分析', 'type': 'general', 'desc': '中文通用'},
    {'query': 'BYD competitive landscape', 'type': 'general', 'desc': '竞品分析'},
    {'query': 'semiconductor supply chain risk', 'type': 'general', 'desc': '供应链风险'},
]


def extract_domain_set(hits) -> set[str]:
    """从搜索结果提取域名集合"""
    domains = set()
    for h in hits:
        domain = getattr(h, 'domain', '') or ''
        if domain:
            domains.add(domain)
    return domains


def extract_title_set(hits) -> set[str]:
    """从搜索结果提取标题集合（归一化）"""
    titles = set()
    for h in hits:
        title = getattr(h, 'title', '') or ''
        if title:
            titles.add(title.strip().lower()[:60])
    return titles


def run_stress_test():
    print("=" * 70)
    print("🔍 搜索三引擎压测 — Yahoo + DDG + SearXNG 互补性验证")
    print("=" * 70)
    
    # 初始化适配器
    yahoo = YahooAdapter(timeout=20)
    ddg = DDGAdapter()
    searxng = SearXNGAdapter(searxng_urls(), timeout=20)
    
    # 健康检查
    print("\n📊 健康检查:")
    yahoo_ok = yahoo.healthcheck()
    print(f"  Yahoo:  {'✅ 在线' if yahoo_ok else '❌ 离线'}")
    print(f"  DDG:    ✅ 在线 (无需 healthcheck)")
    searxng_ok = searxng.healthcheck()
    print(f"  SearXNG: {'✅ 在线' if searxng_ok else '❌ 离线 (可选)'}")
    
    results = []
    
    for i, q in enumerate(TEST_QUERIES):
        print(f"\n{'─' * 60}")
        print(f"  [{i+1}/{len(TEST_QUERIES)}] {q['desc']}: \"{q['query']}\" ({q['type']})")
        print(f"{'─' * 60}")
        
        row = {'query': q['query'], 'type': q['type'], 'desc': q['desc'], 'engines': {}}
        
        # --- Yahoo ---
        t0 = time.perf_counter()
        try:
            yahoo_hits = yahoo.search(q['query'], max_results=8, market='us')
            yahoo_ms = int((time.perf_counter() - t0) * 1000)
            yahoo_domains = extract_domain_set(yahoo_hits)
            yahoo_titles = extract_title_set(yahoo_hits)
            print(f"  Yahoo:  {len(yahoo_hits)} 条, {yahoo_ms}ms, 域名: {len(yahoo_domains)}")
            row['engines']['yahoo'] = {
                'count': len(yahoo_hits), 'ms': yahoo_ms,
                'domains': sorted(yahoo_domains), 'titles': sorted(yahoo_titles),
            }
        except Exception as e:
            yahoo_ms = int((time.perf_counter() - t0) * 1000)
            print(f"  Yahoo:  ❌ 失败 ({yahoo_ms}ms): {repr(e)[:100]}")
            row['engines']['yahoo'] = {'count': 0, 'ms': yahoo_ms, 'error': repr(e)[:200]}
        
        # --- DDG ---
        t0 = time.perf_counter()
        try:
            ddg_hits = ddg.search(q['query'], max_results=8, market='us')
            ddg_ms = int((time.perf_counter() - t0) * 1000)
            ddg_domains = extract_domain_set(ddg_hits)
            ddg_titles = extract_title_set(ddg_hits)
            print(f"  DDG:    {len(ddg_hits)} 条, {ddg_ms}ms, 域名: {len(ddg_domains)}")
            row['engines']['ddg'] = {
                'count': len(ddg_hits), 'ms': ddg_ms,
                'domains': sorted(ddg_domains), 'titles': sorted(ddg_titles),
            }
        except Exception as e:
            ddg_ms = int((time.perf_counter() - t0) * 1000)
            print(f"  DDG:    ❌ 失败 ({ddg_ms}ms): {repr(e)[:100]}")
            row['engines']['ddg'] = {'count': 0, 'ms': ddg_ms, 'error': repr(e)[:200]}
        
        # --- SearXNG ---
        t0 = time.perf_counter()
        try:
            searxng_hits = searxng.search(q['query'], max_results=8, market='us')
            searxng_ms = int((time.perf_counter() - t0) * 1000)
            searxng_domains = extract_domain_set(searxng_hits)
            searxng_titles = extract_title_set(searxng_hits)
            print(f"  SearXNG: {len(searxng_hits)} 条, {searxng_ms}ms, 域名: {len(searxng_domains)}")
            row['engines']['searxng'] = {
                'count': len(searxng_hits), 'ms': searxng_ms,
                'domains': sorted(searxng_domains), 'titles': sorted(searxng_titles),
            }
        except Exception as e:
            searxng_ms = int((time.perf_counter() - t0) * 1000)
            print(f"  SearXNG: ❌ 失败 ({searxng_ms}ms): {repr(e)[:100]}")
            row['engines']['searxng'] = {'count': 0, 'ms': searxng_ms, 'error': repr(e)[:200]}
        
        # 互补性分析
        all_titles = set()
        engine_titles = {}
        for eng_name in ('yahoo', 'ddg', 'searxng'):
            eng_data = row['engines'].get(eng_name, {})
            titles = set(eng_data.get('titles', []))
            engine_titles[eng_name] = titles
            all_titles.update(titles)
        
        # 计算两两重叠
        overlap_pairs = {}
        engines_with_data = [e for e in ('yahoo', 'ddg', 'searxng') if engine_titles.get(e)]
        for j, e1 in enumerate(engines_with_data):
            for e2 in engines_with_data[j+1:]:
                overlap = engine_titles[e1] & engine_titles[e2]
                overlap_pct = len(overlap) / max(1, min(len(engine_titles[e1]), len(engine_titles[e2]))) * 100
                overlap_pairs[f'{e1}_vs_{e2}'] = {
                    'overlap_count': len(overlap),
                    'overlap_pct': round(overlap_pct, 1),
                }
                print(f"  重叠 {e1}↔{e2}: {len(overlap)} 条 ({overlap_pct:.0f}%)")
        
        # 互补率 = 独有标题数 / 总标题数
        unique_count = 0
        for eng_name, titles in engine_titles.items():
            others = all_titles - titles
            unique_count += len(titles - others)
        complementarity = unique_count / max(1, len(all_titles)) * 100
        
        row['overlap'] = overlap_pairs
        row['complementarity_pct'] = round(complementarity, 1)
        row['total_unique_titles'] = len(all_titles)
        
        print(f"  📊 互补率: {complementarity:.0f}% ({unique_count} 独有 / {len(all_titles)} 总)")
        
        results.append(row)
    
    # ─── 汇总 ───
    print(f"\n{'=' * 70}")
    print("📈 压测汇总")
    print(f"{'=' * 70}")
    
    total_yahoo = sum(r['engines'].get('yahoo', {}).get('count', 0) for r in results)
    total_ddg = sum(r['engines'].get('ddg', {}).get('count', 0) for r in results)
    total_searxng = sum(r['engines'].get('searxng', {}).get('count', 0) for r in results)
    
    avg_yahoo_ms = sum(r['engines'].get('yahoo', {}).get('ms', 0) for r in results) / max(1, len(results))
    avg_ddg_ms = sum(r['engines'].get('ddg', {}).get('ms', 0) for r in results) / max(1, len(results))
    avg_searxng_ms = sum(r['engines'].get('searxng', {}).get('ms', 0) for r in results) / max(1, len(results))
    
    avg_complementarity = sum(r.get('complementarity_pct', 0) for r in results) / max(1, len(results))
    
    print(f"  Yahoo:   总 {total_yahoo} 条, 平均 {avg_yahoo_ms:.0f}ms")
    print(f"  DDG:     总 {total_ddg} 条, 平均 {avg_ddg_ms:.0f}ms")
    print(f"  SearXNG: 总 {total_searxng} 条, 平均 {avg_searxng_ms:.0f}ms")
    print(f"  平均互补率: {avg_complementarity:.0f}%")
    
    # 判定
    if avg_complementarity >= 60:
        print(f"\n  ✅ 三引擎互补性强 — 各引擎搜索结果差异大，不可替代")
    elif avg_complementarity >= 40:
        print(f"\n  ⚠️ 三引擎互补性中等 — 有重叠但也有互补")
    else:
        print(f"\n  ❌ 三引擎互补性弱 — 结果重叠度高")
    
    # 保存结果
    output_path = ROOT / 'data' / 'search_stress_test_results.json'
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'summary': {
            'yahoo_total': total_yahoo,
            'ddg_total': total_ddg,
            'searxng_total': total_searxng,
            'avg_yahoo_ms': round(avg_yahoo_ms),
            'avg_ddg_ms': round(avg_ddg_ms),
            'avg_searxng_ms': round(avg_searxng_ms),
            'avg_complementarity_pct': round(avg_complementarity, 1),
        },
        'queries': results,
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n  📄 详细结果已保存: {output_path}")
    
    return results


if __name__ == '__main__':
    run_stress_test()

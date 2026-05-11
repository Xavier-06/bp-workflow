#!/usr/bin/env python3
"""
market_news 稳定性回归测试 (优化版)
- 只用本地 searxng，跳过 Tavily 加速测试
- 对每个 fixture 连跑 5 次，记录指标
"""

import json
import sys
import time
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from collections import Counter
from difflib import SequenceMatcher

# Add workspace to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from search.adapters.searxng import SearXNGAdapter
from search.fetch import fetch_hit
from search.models import Evidence


def load_json(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return {}


def load_market_news_rules() -> dict:
    return load_json(ROOT / 'config' / 'search' / 'market_news_rules.json')


def load_domain_lists() -> dict:
    return load_json(ROOT / 'config' / 'search' / 'domain_lists.json')


def load_fixtures() -> list[dict]:
    fixtures_dir = ROOT / 'config' / 'search' / 'fixtures'
    fixtures = []
    for f in sorted(fixtures_dir.glob('market_news_*.json')):
        fixtures.append(json.loads(f.read_text(encoding='utf-8')))
    return fixtures


def run_market_news_direct(query: str, company: str | None = None, freshness_hours: int = 72, max_results: int = 10) -> tuple[list[Evidence], dict]:
    """直接调用 searxng 进行 market_news 搜索，跳过 Tavily"""
    adapter = SearXNGAdapter(['http://127.0.0.1:18080'])
    rules = load_market_news_rules()
    cfg = load_domain_lists()
    
    # 渲染查询
    base = (company or query).strip()
    query_texts = [
        f'{base} 新闻',
        f'{base} 最新消息 最新进展',
        f'{base} 发布 宣布 报道',
    ]
    
    # 搜索
    all_hits = []
    for qt in query_texts:
        hits = adapter.search(qt, max_results=max_results, freshness_hours=freshness_hours, allow_fallback=False)
        all_hits.extend(hits)
        time.sleep(0.3)
    
    # 预过滤 (SearchHit 级)
    blocking = rules.get('blocking', {})
    blocked_domains = blocking.get('blocked_domains', cfg.get('news_blocked_domains', []))
    blocked_url_patterns = blocking.get('blocked_url_patterns', cfg.get('news_blocked_url_patterns', []))
    blocked_title_patterns = blocking.get('blocked_title_patterns', cfg.get('news_blocked_title_patterns', []))
    
    prefiltered = []
    prefilter_blocked = 0
    for hit in all_hits:
        domain = (hit.domain or '').lower()
        url = (hit.url or '').lower()
        title = (hit.title or '').lower()
        
        # 域名黑名单
        if any(bd == domain or bd in domain for bd in blocked_domains):
            prefilter_blocked += 1
            continue
        
        # URL 模式黑名单
        if any(pat.lower() in url for pat in blocked_url_patterns):
            prefilter_blocked += 1
            continue
        
        # 标题模式黑名单
        if any(pat.lower() in title for pat in blocked_title_patterns):
            prefilter_blocked += 1
            continue
        
        prefiltered.append(hit)
    
    # Evidence 级过滤
    trust_tiers = rules.get('trust_tiers', {})
    preferred_domains = trust_tiers.get('trusted_news_domains', cfg.get('news_preferred_domains', []))
    quality_gates = rules.get('quality_gates', {})
    hard_drop_reasons = set(quality_gates.get('hard_drop_reasons', []))
    soft_drop_reasons = set(quality_gates.get('soft_drop_reasons', []))
    min_content_length = quality_gates.get('min_content_length', 220)
    
    seen_urls = set()
    seen_titles = set()
    kept = []
    drop_counts = Counter()
    debug_rows = []
    
    for hit in prefiltered:
        ev = fetch_hit(hit)
        ev.drop_reasons = []
        
        # 时间检查
        if not ev.published_at:
            ev.drop_reasons.append('missing_publish_time')
        elif _is_too_old(ev.published_at, freshness_hours):
            ev.drop_reasons.append('too_old')
        
        # 内容检查
        text_blob = (ev.full_text or ev.snippet or '').strip()
        if len(text_blob) < min_content_length:
            ev.drop_reasons.append('thin_content')
        
        # 去重检查
        url_key = _canonical_url(ev.url)
        title_key = _normalize_title(ev.title)
        
        if url_key in seen_urls:
            ev.drop_reasons.append('duplicate_url')
        if title_key in seen_titles:
            ev.drop_reasons.append('duplicate_title')
        if _is_similar_title(title_key, seen_titles):
            ev.drop_reasons.append('duplicate_similar_title')
        
        # 信任检查
        if not any(dom in ev.domain for dom in preferred_domains):
            ev.drop_reasons.append('untrusted_news_source')
        
        # 判断是否接受
        hard_drops = [r for r in ev.drop_reasons if r in hard_drop_reasons]
        soft_drops = [r for r in ev.drop_reasons if r in soft_drop_reasons]
        
        accepted = len(hard_drops) == 0 and len(soft_drops) < 2
        
        if accepted:
            seen_urls.add(url_key)
            seen_titles.add(title_key)
            kept.append(ev)
        
        for r in ev.drop_reasons:
            drop_counts[r] += 1
        
        debug_rows.append({
            'domain': ev.domain,
            'accepted': accepted,
            'drop_reasons': ev.drop_reasons,
        })
    
    return kept, {
        'raw_result_count': len(all_hits),
        'prefilter_blocked_count': prefilter_blocked,
        'prefiltered_count': len(prefiltered),
        'kept_count': len(kept),
        'drop_reasons': dict(drop_counts),
        'kept_domains': list(set(e.domain for e in kept)),
        'debug_sample': debug_rows[:3],
    }


def _canonical_url(url: str) -> str:
    from urllib.parse import urlparse, urlunparse
    parsed = urlparse(url)
    clean = parsed._replace(query='', fragment='')
    return urlunparse(clean).rstrip('/').lower()


def _normalize_title(title: str) -> str:
    text = re.sub(r'\s+', '', (title or '').lower())
    text = re.sub(r'[\-_|｜:：【】\[\]（）()""\'\.,，。！？!？]', '', text)
    return text


def _is_similar_title(title_key: str, seen_titles: set[str]) -> bool:
    for existing in seen_titles:
        if SequenceMatcher(None, title_key, existing).ratio() >= 0.9:
            return True
    return False


def _is_too_old(published_at: str, freshness_hours: int) -> bool:
    try:
        if ',' in published_at:
            dt = parsedate_to_datetime(published_at)
        else:
            dt = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt < datetime.now(timezone.utc) - timedelta(hours=freshness_hours)
    except:
        return False


def run_stability_test(fixture: dict, runs: int = 5) -> dict:
    """对单个 fixture 运行多次测试"""
    print(f"\n{'='*60}")
    print(f"Fixture: {fixture['name']}")
    print(f"Query: {fixture.get('query', 'N/A')}")
    print(f"Expected min kept: {fixture.get('expected_min_kept_count', 0)}")
    print(f"{'='*60}")
    
    results = []
    
    for i in range(runs):
        print(f"\n--- Run {i+1}/{runs} ---", end='', flush=True)
        
        kept, stats = run_market_news_direct(
            query=fixture.get('query', ''),
            company=fixture.get('company'),
            freshness_hours=fixture.get('freshness_hours', 72),
            max_results=fixture.get('max_results', 10),
        )
        
        result = {
            'run': i + 1,
            'kept_count': len(kept),
            'raw_result_count': stats['raw_result_count'],
            'prefilter_blocked_count': stats['prefilter_blocked_count'],
            'prefiltered_count': stats['prefiltered_count'],
            'drop_reasons': stats['drop_reasons'],
            'kept_domains': stats['kept_domains'][:5],
        }
        results.append(result)
        
        print(f" -> raw={stats['raw_result_count']}, blocked={stats['prefilter_blocked_count']}, kept={len(kept)}")
        
        time.sleep(0.5)
    
    # 汇总
    kept_counts = [r['kept_count'] for r in results]
    expected_min = fixture.get('expected_min_kept_count', 0)
    pass_count = sum(1 for c in kept_counts if c >= expected_min)
    
    summary = {
        'fixture_name': fixture['name'],
        'expected_min_kept': expected_min,
        'runs': runs,
        'pass_count': pass_count,
        'pass_rate': f"{pass_count}/{runs}",
        'passed': pass_count >= runs - 1,
        'kept_counts': kept_counts,
        'all_kept_domains': list(set(d for r in results for d in r.get('kept_domains', []))),
        'aggregate_drop_reasons': _aggregate_drop_reasons(results),
    }
    
    status = "✅ PASS" if summary['passed'] else "❌ FAIL"
    print(f"\nSUMMARY: {summary['pass_rate']} - {status}")
    print(f"Kept counts: {kept_counts}")
    
    return summary


def _aggregate_drop_reasons(results: list) -> dict:
    all_reasons = Counter()
    for r in results:
        for reason, count in r.get('drop_reasons', {}).items():
            all_reasons[reason] += count
    return dict(all_reasons.most_common(10))


def main():
    print("market_news 稳定性回归测试")
    print("="*60)
    
    # 检查 searxng
    import requests
    try:
        resp = requests.get('http://127.0.0.1:18080/healthz', timeout=5)
        print(f"SearXNG healthcheck: {resp.text.strip()}")
    except Exception as e:
        print(f"ERROR: SearXNG not available: {e}")
        print("请先启动 SearXNG 或使用 DDG 备选搜索")
        return 1
    
    fixtures = load_fixtures()
    print(f"Loaded {len(fixtures)} fixtures: {[f['name'] for f in fixtures]}")
    
    all_summaries = []
    for fixture in fixtures:
        summary = run_stability_test(fixture, runs=5)
        all_summaries.append(summary)
    
    # 最终汇总
    print("\n" + "="*80)
    print("FINAL SUMMARY - ALL FIXTURES")
    print("="*80)
    
    all_passed = True
    for s in all_summaries:
        status = "✅ PASS" if s['passed'] else "❌ FAIL"
        print(f"\n{s['fixture_name']}: {status}")
        print(f"  Expected min: {s['expected_min_kept']}, Got: {s['kept_counts']}")
        print(f"  Pass rate: {s['pass_rate']}")
        print(f"  All kept domains: {s['all_kept_domains'][:5]}")
        if not s['passed']:
            all_passed = False
    
    # 保存结果
    output_path = ROOT / 'data' / 'search_gateway' / 'regression_results.json'
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    output = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'summaries': all_summaries,
        'overall_passed': all_passed,
    }
    
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n详细结果已保存到: {output_path}")
    
    if all_passed:
        print("\n🎉 所有 fixture 稳定通过!")
        return 0
    else:
        print("\n⚠️ 部分 fixture 未通过稳定性测试")
        return 1


if __name__ == '__main__':
    sys.exit(main())
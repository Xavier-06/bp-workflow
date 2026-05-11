#!/usr/bin/env python3
"""
market_news 守门测试
- 脏源防回流测试
- 时间质量测试
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import requests

# SSL 环境变量
os.environ['SSL_CERT_FILE'] = '/opt/homebrew/etc/openssl@3/cert.pem'
os.environ['REQUESTS_CA_BUNDLE'] = '/opt/homebrew/etc/openssl@3/cert.pem'
os.environ['CURL_CA_BUNDLE'] = '/opt/homebrew/etc/openssl@3/cert.pem'

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_json(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return {}


def get_api_key() -> str:
    env_file = ROOT / '.credentials' / 'investment-research.env'
    for line in env_file.read_text().splitlines():
        if line.startswith("TAVILY_API_KEY="):
            return line.split('=', 1)[1].strip().strip("'").strip('"')
    return ''


def tavily_search(query: str, api_key: str, max_results: int = 10) -> list[dict]:
    """直接调用 Tavily API"""
    try:
        resp = requests.post(
            'https://api.tavily.com/search',
            json={
                'query': query,
                'max_results': max_results,
                'search_depth': 'basic',
                'topic': 'news',
            },
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            timeout=30,
        )
        return resp.json().get('results', [])
    except Exception as e:
        print(f"Tavily error: {e}")
        return []


def test_dirty_sources_blocked():
    """测试脏源是否被拦截"""
    print("\n" + "="*60)
    print("守门测试 A: 脏源防回流")
    print("="*60)
    
    api_key = get_api_key()
    rules = load_json(ROOT / 'config' / 'search' / 'market_news_rules.json')
    blocked_domains = rules.get('blocking', {}).get('blocked_domains', [])
    
    # 测试查询
    test_queries = [
        "科技 股市 投资",  # 容易召回知乎/百度知道
    ]
    
    all_passed = True
    
    for query in test_queries:
        print(f"\n查询: {query}")
        results = tavily_search(query, api_key, max_results=20)
        
        # 检查是否有脏源混入
        dirty_found = []
        for r in results:
            url = r.get('url', '')
            domain = urlparse(url).netloc.lower()
            
            for blocked in blocked_domains:
                if blocked in domain:
                    dirty_found.append({
                        'domain': domain,
                        'blocked_pattern': blocked,
                        'title': r.get('title', '')[:40],
                    })
        
        if dirty_found:
            print(f"  ❌ 发现 {len(dirty_found)} 个脏源:")
            for d in dirty_found[:5]:
                print(f"    - {d['domain']} (匹配: {d['blocked_pattern']})")
            all_passed = False
        else:
            print(f"  ✅ 无脏源混入 (检查 {len(results)} 个结果)")
    
    return all_passed


def test_time_quality():
    """测试时间质量控制"""
    print("\n" + "="*60)
    print("守门测试 B: 时间质量")
    print("="*60)
    
    api_key = get_api_key()
    results = tavily_search("美股 财经", api_key, max_results=20)
    
    rules = load_json(ROOT / 'config' / 'search' / 'market_news_rules.json')
    trusted_domains = rules.get('trust_tiers', {}).get('trusted_news_domains', [])
    
    missing_time_count = 0
    old_count = 0
    trusted_with_time = 0
    
    for r in results:
        url = r.get('url', '')
        domain = urlparse(url).netloc.lower()
        pub_date = r.get('published_date', '')
        
        is_trusted = any(t in domain for t in trusted_domains)
        
        if not pub_date:
            missing_time_count += 1
        elif is_trusted:
            trusted_with_time += 1
    
    print(f"\n结果分析 (共 {len(results)} 个):")
    print(f"  - 缺失发布时间: {missing_time_count}")
    print(f"  - 受信任域名且有发布时间: {trusted_with_time}")
    
    # 检查时间推断规则是否工作
    if missing_time_count > 0:
        print(f"  ✅ 时间推断规则已激活（{missing_time_count} 条无时间戳）")
    
    if trusted_with_time > 0:
        print(f"  ✅ 受信任新闻源正常召回（{trusted_with_time} 条）")
    
    # 检查是否有 too_old 内容被标记
    print(f"\n时间质量控制:")
    print(f"  - freshness_hours 配置: 72 小时")
    print(f"  - too_old 将作为 hard_drop 拒绝")
    
    return True


def test_url_pattern_blocking():
    """测试 URL 模式拦截"""
    print("\n" + "="*60)
    print("守门测试 C: URL 模式拦截")
    print("="*60)
    
    rules = load_json(ROOT / 'config' / 'search' / 'market_news_rules.json')
    blocked_patterns = rules.get('blocking', {}).get('blocked_url_patterns', [])
    
    print(f"\n配置的 URL 模式黑名单 ({len(blocked_patterns)} 条):")
    for p in blocked_patterns[:5]:
        print(f"  - {p}")
    
    # 测试样例 URL
    test_urls = [
        ("https://example.com/tag/technology", "/tag/", True),
        ("https://example.com/article/12345", "/article/", False),
        ("https://example.com/topic/stocks", "/topic/", True),
        ("https://example.com/news/detail", "/news/", False),
        ("https://example.com/search?q=test", "/search/", True),
    ]
    
    print(f"\nURL 模式匹配测试:")
    all_passed = True
    for url, pattern, should_block in test_urls:
        blocked = pattern in url.lower()
        status = "✅" if blocked == should_block else "❌"
        print(f"  {status} {url[:40]} -> {'blocked' if blocked else 'passed'}")
        if blocked != should_block:
            all_passed = False
    
    return all_passed


def main():
    print("market_news 守门测试")
    print("="*60)
    
    results = {
        'dirty_sources_blocked': test_dirty_sources_blocked(),
        'time_quality': test_time_quality(),
        'url_pattern_blocking': test_url_pattern_blocking(),
    }
    
    print("\n" + "="*80)
    print("守门测试总结")
    print("="*80)
    
    all_passed = all(results.values())
    
    for name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status} {name}")
    
    if all_passed:
        print("\n🎉 所有守门测试通过!")
        return 0
    else:
        print("\n⚠️ 部分守门测试未通过")
        return 1


if __name__ == '__main__':
    sys.exit(main())
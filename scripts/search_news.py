#!/usr/bin/env python3
"""通用新闻搜索 - 用 SearXNG/DDG 替代 Tavily"""
import sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

def search_news(query: str, max_results: int = 5) -> list:
    results = []
    # 先试 SearXNG
    try:
        from search.adapters.searxng import SearXNGAdapter
        adapter = SearXNGAdapter(['http://127.0.0.1:18080'])
        hits = adapter.search(query, max_results=max_results)
        for h in hits:
            results.append({'title': h.title, 'url': h.url, 'snippet': h.snippet or '', 'source': h.domain or ''})
        if results:
            return results
    except Exception as e:
        pass
    # 降级 DDG
    try:
        from search.adapters.ddg import DDGAdapter
        adapter = DDGAdapter()
        hits = adapter.search(query, max_results=max_results)
        for h in hits:
            results.append({'title': h.title, 'url': h.url, 'snippet': h.snippet or '', 'source': h.domain or ''})
    except Exception:
        pass
    return results

if __name__ == '__main__':
    q = sys.argv[1] if len(sys.argv) > 1 else 'latest news'
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    print(json.dumps(search_news(q, n), ensure_ascii=False, indent=2))
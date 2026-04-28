#!/usr/bin/env python3
"""
搜索路由优化 — 根据查询类型自动选择最佳引擎

根因分析 (2026-04-04):
  CN(18081) 全部引擎失效 → EN(18080) 中文编码偶发乱码 → DDG CLI 中文搜索最可靠
  修复：不靠记忆，靠代码自动路由
"""
import subprocess
import sys
import os
import re
import urllib.request
import urllib.parse
import json
from typing import Optional

# ─── 路由规则 ────────────────────────────────────────
# 1. 含中文字符 + 不含英文 → DDG CLI（中文搜索可靠）
# 2. 含中文 + 股票代码 → DDG CLI
# 3. 纯英文 → SearXNG EN (18080)
# 4. 混合查询 → DDG CLI

EN_URL = 'http://127.0.0.1:18080'


def is_chinese_query(query: str) -> bool:
    """检测是否包含中文字符"""
    return any('\u4e00' <= c <= '\u9fff' for c in query)


def is_stock_query(query: str) -> bool:
    """检测是否包含股票代码"""
    return bool(re.search(r'\d{4,6}\.HK|HKEX|\d{4,6}', query))


def search(query: str, max_results: int = 10, **kwargs) -> list:
    """
    自动路由搜索引擎。
    
    中文查询 → DDG CLI
    英文查询 → SearXNG EN (18080)
    """
    has_chinese = is_chinese_query(query)
    has_stock = is_stock_query(query)
    
    if has_chinese or has_stock:
        return _search_ddg(query, max_results)
    else:
        return _search_searxng_en(query, max_results)


def _search_ddg(query: str, max_results: int = 10) -> list:
    """DDG CLI 搜索（中文最优）"""
    try:
        r = subprocess.run(
            ['ddgs', 'text', '-q', query, '-m', str(max_results)],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, 'LC_ALL': 'en_US.UTF-8'}
        )
        
        if r.returncode != 0 or not r.stdout.strip():
            return []
        
        results = []
        lines = r.stdout.strip().split('\n')
        current = {}
        
        for line in lines:
            line = line.strip()
            if line.startswith('title'):
                if current.get('title'):
                    results.append(current)
                current = {'title': line[6:].strip()[:120], 'url': '', 'content': ''}
            elif line.startswith('href'):
                current['url'] = line[5:].strip()
            elif line.startswith('body'):
                current['content'] = line[5:].strip()[:500]
            elif line.startswith('======'):
                if current.get('title'):
                    results.append(current)
                    current = {}
        
        if current.get('title'):
            results.append(current)
        
        # Convert to standard format
        return [
            {
                'title': r.get('title', ''),
                'url': r.get('url', ''),
                'content': r.get('content', ''),
                'engine': 'ddg',
                'source': 'ddg-cli',
            }
            for r in results[:max_results]
        ]
    
    except Exception as e:
        print(f"⚠️ DDG CLI failed: {e}", file=sys.stderr)
        return []


def _search_searxng_en(query: str, max_results: int = 10) -> list:
    """SearXNG EN 搜索 (127.0.0.1:18080)"""
    try:
        q = urllib.parse.quote(query)
        url = f'{EN_URL}/search?q={q}&format=json&language=all&results={max_results}'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read().decode('utf-8', errors='replace'))
        items = data.get('results', [])
        return [
            {
                'title': i.get('title', ''),
                'url': i.get('url', ''),
                'content': i.get('content', ''),
                'engine': i.get('engine', 'searxng'),
                'source': 'searxng-en',
            }
            for i in items[:max_results]
        ]
    except Exception as e:
        print(f"⚠️ SearXNG EN failed: {e}", file=sys.stderr)
        return _search_ddg(query, max_results)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        queries = [
            '东江集团控股 02283 注塑模具',
            '注塑行业市场规模 2025',
            'Bubble Mart 泡泡玛特 财报',
            'Python tutorial',
        ]
    else:
        queries = [sys.argv[1]]
    
    for q in queries:
        print(f'\n🔍 "{q}"')
        results = search(q, max_results=5)
        print(f'   Found {len(results)} results')
        for r in results[:3]:
            print(f'   ✅ [{r["engine"]}] {r["title"][:80]}')
            print(f'      {r["url"][:80]}')

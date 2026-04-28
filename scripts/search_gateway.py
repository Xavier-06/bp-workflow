#!/usr/bin/env python3
"""
统一搜索网关（修正版）

路由原则（与 scripts/search_router.py / search_config.md 对齐）：
- 中文 / 混合 / 股票代码查询：DDG CLI 优先
- 纯英文查询：SearXNG EN(18080) 优先
- 任一路径失败：自动 fallback 到另一条

保留旧接口：
    from scripts.search_gateway import search, search_many, verify_engines
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Dict, List

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

WORKSPACE = Path(__file__).resolve().parent.parent
CERT_PATH = '/opt/homebrew/etc/openssl@3/cert.pem'
if os.path.exists(CERT_PATH):
    os.environ.setdefault('SSL_CERT_FILE', CERT_PATH)
    os.environ.setdefault('REQUESTS_CA_BUNDLE', CERT_PATH)
    os.environ.setdefault('CURL_CA_BUNDLE', CERT_PATH)

SEARXNG_EN_URL = os.getenv('SEARXNG_LOCAL_URL', 'http://127.0.0.1:18080').rstrip('/')
SEARXNG_ALT_URLS = [u.rstrip('/') for u in os.getenv('SEARXNG_ALT_URLS', 'http://127.0.0.1:8888').split(',') if u.strip()]
DDGS_BIN = os.getenv('DDGS_BIN', '/opt/homebrew/bin/ddgs')
DDGS_REGION = os.getenv('DDGS_REGION', 'wt-wt')
DDGS_BACKEND = os.getenv('DDGS_BACKEND', 'auto')
ALLOW_DDG_PYTHON_FALLBACK = os.getenv('ALLOW_DDG_PYTHON_FALLBACK', '0') in ('1', 'true', 'yes')

NOISE_HOSTS = [
    'freelancer.com', 'formula1.com', 'standard.co.uk', 'mfrbee.com', 'company-listing.org',
    'juejin.cn', 'bbc.com', 'bjmu.edu.cn', 'douyin.com', 'zhidao.baidu.com',
]


def _has_chinese(text: str) -> bool:
    return any('\u4e00' <= c <= '\u9fff' for c in text)


def _has_stock_code(text: str) -> bool:
    return bool(re.search(r'\b\d{4,6}(?:\.HK)?\b|HKEX|NASDAQ|NYSE|A股|港股|美股', text, re.IGNORECASE))


def _prefer_ddg(query: str) -> bool:
    return _has_chinese(query) or _has_stock_code(query)


def _is_noise_result(row: dict) -> bool:
    url = (row.get('url') or '').lower()
    title = (row.get('title') or '').lower()
    return any(host in url for host in NOISE_HOSTS) or any(host in title for host in NOISE_HOSTS)


def _dedupe_filter(rows: list, max_results: int) -> list:
    deduped = []
    seen = set()
    for r in rows:
        u = r.get('url', '')
        if not u or u in seen or _is_noise_result(r):
            continue
        seen.add(u)
        deduped.append(r)
    return deduped[:max_results]


def _parse_ddgs_text(stdout: str, max_results: int) -> list:
    results = []
    current = None
    for raw in stdout.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        if re.match(r'^\d+\.\s*=+', line):
            if current and current.get('title'):
                results.append(current)
            current = {'title': '', 'url': '', 'content': '', 'engine': 'ddg', 'source': 'ddg:cli', 'publishedDate': ''}
            continue
        if current is None:
            continue
        stripped = line.strip()
        if stripped.startswith('title'):
            current['title'] = stripped[5:].strip()
        elif stripped.startswith('href'):
            current['url'] = stripped[4:].strip()
        elif stripped.startswith('body'):
            current['content'] = stripped[4:].strip()
        elif current.get('content') and not re.match(r'^(title|href|body)\b', stripped):
            current['content'] += ' ' + stripped
    if current and current.get('title'):
        results.append(current)
    return _dedupe_filter(results, max_results)


def _ddg_search(query: str, max_results: int = 10) -> list:
    # 1) Rust ddgs CLI JSON output (preferred)
    try:
        cmd = [DDGS_BIN, 'text', '-q', query, '-m', str(max_results), '-o', 'json', '-r', DDGS_REGION, '-b', DDGS_BACKEND]
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, 'LC_ALL': 'en_US.UTF-8'}
        )
        if r.returncode == 0 and r.stdout.strip().startswith('['):
            rows = json.loads(r.stdout)
            parsed = [{
                'title': row.get('title', ''),
                'url': row.get('href', ''),
                'content': row.get('body', ''),
                'engine': f'ddg:{DDGS_BACKEND}',
                'source': 'ddg:cli-json',
                'publishedDate': row.get('date', ''),
            } for row in rows if row.get('href')]
            parsed = _dedupe_filter(parsed, max_results)
            if parsed:
                return parsed
        if r.returncode == 0 and r.stdout.strip():
            parsed = _parse_ddgs_text(r.stdout, max_results)
            if parsed:
                return parsed
    except Exception:
        pass

    # 2) Python 库 fallback（默认关闭：中文 query 易严重跑偏）
    if not ALLOW_DDG_PYTHON_FALLBACK:
        return []
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        with DDGS(timeout=15) as d:
            rows = list(d.text(query, max_results=max_results))
        parsed = [{
            'title': row.get('title', ''),
            'url': row.get('href', ''),
            'content': row.get('body', ''),
            'engine': 'ddg-python',
            'source': 'ddg:python',
            'publishedDate': '',
        } for row in rows if row.get('href')]
        return _dedupe_filter(parsed, max_results)
    except Exception:
        return []


def _searxng_en_health(timeout: int = 5) -> bool:
    for base in [SEARXNG_EN_URL] + [u for u in SEARXNG_ALT_URLS if u != SEARXNG_EN_URL]:
        try:
            r = requests.get(f'{base}/healthz', timeout=timeout)
            if r.status_code == 200:
                return True
        except Exception:
            pass
    return False


def _searxng_search(query: str, max_results: int = 10, timeout: int = 20) -> list:
    params = {
        'q': query,
        'format': 'json',
        'language': 'all',
        'results': max_results,
    }
    for base in [SEARXNG_EN_URL] + [u for u in SEARXNG_ALT_URLS if u != SEARXNG_EN_URL]:
        try:
            r = requests.get(
                f'{base}/search',
                params=params,
                timeout=timeout,
                headers={'User-Agent': 'OpenClawSearchGateway/2.0'},
                verify=False,
            )
            r.raise_for_status()
            data = r.json()
            out = []
            seen = set()
            for item in data.get('results', []):
                url = item.get('url') or item.get('href', '')
                if not url or url in seen:
                    continue
                seen.add(url)
                out.append({
                    'title': item.get('title', ''),
                    'url': url,
                    'content': item.get('content') or item.get('body', ''),
                    'engine': item.get('engine', 'searxng'),
                    'source': f'searxng:{base}',
                    'publishedDate': item.get('publishedDate', ''),
                })
                if len(out) >= max_results:
                    break
            if out:
                return _dedupe_filter(out, max_results)
        except Exception:
            pass
    return []


def search(query: str, max_results: int = 10, timeout: int = 25, prefer: str = 'auto') -> list:
    if prefer == 'ddg':
        results = _ddg_search(query, max_results=max_results)
        return results or _searxng_search(query, max_results=max_results, timeout=timeout)

    if prefer == 'searxng':
        results = _searxng_search(query, max_results=max_results, timeout=timeout)
        return results or _ddg_search(query, max_results=max_results)

    if _prefer_ddg(query):
        results = _ddg_search(query, max_results=max_results)
        return results or _searxng_search(query, max_results=max_results, timeout=timeout)

    results = _searxng_search(query, max_results=max_results, timeout=timeout)
    return results or _ddg_search(query, max_results=max_results)


def search_many(queries: List[str], max_results: int = 8, prefer: str = 'auto') -> Dict[str, list]:
    return {q: search(q, max_results=max_results, prefer=prefer) for q in queries}


def verify_engines() -> dict:
    return {
        'searxng_en': _searxng_en_health(),
        'searxng_cn': False,
        'ddg': os.path.exists(DDGS_BIN),
        'searxng_en_url': SEARXNG_EN_URL,
        'searxng_cn_url': None,
        'ddg_bin': DDGS_BIN,
        'route': 'cn/mixed->ddg, en->searxng',
        'ddg_region': DDGS_REGION,
        'ddg_backend': DDGS_BACKEND,
        'allow_ddg_python_fallback': ALLOW_DDG_PYTHON_FALLBACK,
        'searxng_alt_urls': SEARXNG_ALT_URLS,
    }


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('query', nargs='?')
    ap.add_argument('-n', '--max-results', type=int, default=10)
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--verify', action='store_true')
    ap.add_argument('--prefer', choices=['auto', 'ddg', 'searxng'], default='auto')
    args = ap.parse_args()

    if args.verify:
        print(json.dumps(verify_engines(), ensure_ascii=False, indent=2))
        raise SystemExit(0)

    if not args.query:
        ap.error('query required unless --verify')

    rows = search(args.query, max_results=args.max_results, prefer=args.prefer)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for i, r in enumerate(rows, 1):
            print(f'{i}. {r.get("title", "")}')
            print(f'   URL: {r.get("url", "")}')
            if r.get('content'):
                print(f'   {r.get("content", "")[:240]}')
            print()

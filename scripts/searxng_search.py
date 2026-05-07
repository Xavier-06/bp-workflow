#!/usr/bin/env python3
"""
SearXNG 搜索脚本 — 单实例（18080，走代理）

Google + Brave + Bing + 学术引擎 覆盖中英文搜索。
不需要 CN 直连实例（百度/搜狗直连也被反爬，360search 解析错误）。
"""
import sys
import os
import requests
from urllib.parse import quote

CERT_PATH = ''
for _p in ['/opt/homebrew/etc/openssl@3/cert.pem', '/usr/local/etc/openssl@3/cert.pem']:
    if os.path.exists(_p):
        CERT_PATH = _p
        break
if CERT_PATH:
    os.environ.setdefault('SSL_CERT_FILE', CERT_PATH)
    os.environ.setdefault('REQUESTS_CA_BUNDLE', CERT_PATH)

LOCAL_SEARXNG = os.getenv('SEARXNG_LOCAL_URL', 'http://127.0.0.1:8888').rstrip('/')
_NO_PROXY = {"http": None, "https": None}  # 本地 SearXNG 不走代理
FALLBACK_URLS = (
    os.environ.get('SEARXNG_URLS') or os.environ.get('SEARXNG_URL') or
    'https://searx.be,https://search.okonetwork.de,https://searx.info,https://paulgo.io,https://search.sapti.me'
)
FALLBACK_SEARXNGS = [
    u.strip().rstrip('/') for u in FALLBACK_URLS.split(',') if u.strip() and u.strip() != LOCAL_SEARXNG
]


def _healthcheck(instance, timeout=5):
    use_proxy = not any(instance.startswith(f'127.0.0.1') or instance.startswith('localhost') for _ in [1])
    proxies = None if use_proxy else _NO_PROXY
    for endpoint in ['/healthz', '/']:
        try:
            resp = requests.get(f'{instance}{endpoint}', timeout=timeout, proxies=proxies)
            if resp.status_code == 200:
                return True
        except Exception:
            continue
    return False


def _search_instance(instance, query, max_results, timeout):
    url = f"{instance}/search?q={quote(query)}&format=json"
    use_proxy = not any(instance.startswith(f'127.0.0.1') or instance.startswith('localhost') for _ in [1])
    proxies = None if use_proxy else _NO_PROXY
    resp = requests.get(url, timeout=timeout, proxies=proxies)
    resp.raise_for_status()
    data = resp.json()
    return data.get('results', [])[:max_results]


def search(query, max_results=10, timeout=25, force_instance=None):
    """
    搜索函数
    - force_instance: 强制指定实例 URL
    - 否则自动选实例（本地 → 降级）
    """
    if force_instance:
        instances = [(force_instance, 'forced')]
    else:
        instances = [(LOCAL_SEARXNG, 'localhost')]
    
    for instance, name in instances:
        if not _healthcheck(instance, timeout=5):
            print(f"[{name} {instance}] healthcheck 失败", file=sys.stderr)
            continue
        try:
            results = _search_instance(instance, query, max_results, timeout)
            if results:
                return results
            print(f"[{name}] 无结果", file=sys.stderr)
        except Exception as e:
            print(f"[{name}] 查询失败：{e}", file=sys.stderr)
            continue

    # 降级公共实例
    print("[本地实例失败] 降级公共 SearXNG", file=sys.stderr)
    for instance in FALLBACK_SEARXNGS:
        try:
            results = _search_instance(instance, query, max_results, timeout)
            if results:
                return results
        except Exception as e:
            print(f"[fallback {instance[:40]}] 失败：{e}", file=sys.stderr)
            continue
    
    print("所有 SearXNG 实例都无法连接", file=sys.stderr)
    return []


def main():
    if len(sys.argv) < 2:
        print("用法：python3 searxng_search.py <搜索词> [最大结果数]")
        sys.exit(1)
    query = sys.argv[1]
    max_results = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    results = search(query, max_results)
    if not results:
        print("未找到结果")
        return
    for i, r in enumerate(results, 1):
        print(f"{i}. {r.get('title', 'N/A')}")
        print(f"   {r.get('url', r.get('href', 'N/A'))}")
        content = r.get('content', '') or r.get('body', '')
        if content:
            print(f"   {content[:200]}")
        print(f"   [{r.get('engine', '?')}]")
        print()


if __name__ == "__main__":
    main()

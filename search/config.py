from __future__ import annotations
import json
import os
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / 'config' / 'search'
CACHE_DIR = ROOT / 'data' / 'search_cache'
ENV_FILE = ROOT / '.credentials' / 'investment-research.env'
DEFAULT_SEARXNG_LOCAL_URL = os.environ.get('SEARXNG_URL', '')
DEFAULT_SEARXNG_FALLBACK_URLS = [
    'https://searx.be',
    'https://search.okonetwork.de',
    'https://searx.info',
]


def load_env_file() -> None:
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'").strip('"'))


@lru_cache(maxsize=1)
def domain_lists() -> dict:
    return json.loads((CONFIG_DIR / 'domain_lists.json').read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def query_plans() -> dict:
    return json.loads((CONFIG_DIR / 'query_plans.json').read_text(encoding='utf-8'))


def searxng_local_url() -> str:
    return (os.environ.get('SEARXNG_LOCAL_URL') or DEFAULT_SEARXNG_LOCAL_URL).rstrip('/')

def searxng_cn_url() -> str:
    # ⚠️ DEPRECATED (2026-04-04): CN 实例已废弃，所有引擎失效
    # 中文搜索自动走 DDG CLI（见 search_router.py）
    return ''

def smart_searxng_url(query: str) -> str:
    """Smart routing: CN queries → CN instance, EN queries → local instance"""
    has_cn = any('\u4e00' <= c <= '\u9fff' for c in query)
    if has_cn:
        return searxng_cn_url()
    return searxng_local_url()


def searxng_fallback_urls() -> list[str]:
    env = os.environ.get('SEARXNG_URLS') or os.environ.get('SEARXNG_URL') or ''
    urls = [u.strip().rstrip('/') for u in env.split(',') if u.strip()]
    if not urls:
        urls = DEFAULT_SEARXNG_FALLBACK_URLS[:]
    local = searxng_local_url()
    return [u for u in urls if u and u != local]


def searxng_urls() -> list[str]:
    local = searxng_local_url()
    # CN(18081) 已弃用：只返回 EN + 公共实例 fallback
    # 中文搜索走 DDG CLI（search_router.py）
    urls = [u for u in [local, *searxng_fallback_urls()] if u]
    return urls

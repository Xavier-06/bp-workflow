"""
异步并发抓取模块
支持并发 fetch、超时控制、降级到 snippet
"""

from __future__ import annotations
import asyncio
import os
import re
import ssl
from datetime import datetime, timedelta, timezone
from html import unescape
from typing import NamedTuple
from urllib.parse import urlparse

import aiohttp
import certifi

from search.models import Evidence, SearchHit

MONTHS = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
}

# 创建 SSL Context
def _create_ssl_context() -> ssl.SSLContext:
    """创建 SSL context，使用 certifi 证书"""
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(certifi.where())
    return ctx

SSL_CONTEXT = _create_ssl_context()


class FetchResult(NamedTuple):
    """单次 fetch 结果"""
    url: str
    success: bool
    full_text: str | None
    published_at: str | None
    time_source: str
    time_confidence: str
    http_status: int | None
    error: str | None
    elapsed_ms: int


def extract_text_from_html(html: str) -> str:
    """从 HTML 提取纯文本"""
    html = re.sub(r'(?is)<script.*?>.*?</script>', ' ', html)
    html = re.sub(r'(?is)<style.*?>.*?</style>', ' ', html)
    html = re.sub(r'(?is)<noscript.*?>.*?</noscript>', ' ', html)
    text = re.sub(r'(?s)<[^>]+>', ' ', html)
    return re.sub(r'\s+', ' ', unescape(text)).strip()


def _to_iso(year: int, month: int, day: int) -> str:
    try:
        return datetime(year, month, day, tzinfo=timezone.utc).isoformat()
    except Exception:
        return ''


def _parse_absolute_date(text: str) -> str:
    if not text:
        return ''
    m = re.search(r'(20\d{2})-(\d{1,2})-(\d{1,2})', text)
    if m:
        return _to_iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r'(20\d{2})/(\d{1,2})/(\d{1,2})', text)
    if m:
        return _to_iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r'([A-Z][a-z]{2})\s+(\d{1,2}),\s*(20\d{2})', text)
    if m:
        month = MONTHS.get(m.group(1).lower(), 0)
        return _to_iso(int(m.group(3)), month, int(m.group(2))) if month else ''
    m = re.search(r'(20\d{2})年(\d{1,2})月(\d{1,2})日', text)
    if m:
        return _to_iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return ''


def _parse_relative_date(text: str) -> str:
    if not text:
        return ''
    now = datetime.now(timezone.utc)
    m = re.search(r'(\d+)\s*days?\s*ago', text, re.I)
    if m:
        return (now - timedelta(days=int(m.group(1)))).isoformat()
    m = re.search(r'(\d+)\s*hours?\s*ago', text, re.I)
    if m:
        return (now - timedelta(hours=int(m.group(1)))).isoformat()
    return ''


def _extract_time_from_html(html: str) -> tuple[str, str, str]:
    patterns = [
        (r'property=["\']article:published_time["\'][^>]*content=["\']([^"\']+)', 'meta', 'high'),
        (r'name=["\']pubdate["\'][^>]*content=["\']([^"\']+)', 'meta', 'high'),
        (r'itemprop=["\']datePublished["\'][^>]*content=["\']([^"\']+)', 'meta', 'high'),
        (r'<time[^>]*datetime=["\']([^"\']+)', 'page', 'high'),
    ]
    for pattern, source, confidence in patterns:
        m = re.search(pattern, html, re.I)
        if not m:
            continue
        val = m.group(1)
        parsed = _parse_absolute_date(val) or _parse_relative_date(val) or val.replace('Z', '+00:00')
        if parsed:
            return parsed, source, confidence
    text = extract_text_from_html(html[:12000])
    parsed = _parse_absolute_date(text) or _parse_relative_date(text)
    if parsed:
        return parsed, 'page', 'medium'
    return '', 'none', 'low'


def _extract_time_from_snippet(snippet: str) -> tuple[str, str, str]:
    parsed = _parse_absolute_date(snippet) or _parse_relative_date(snippet)
    if parsed:
        return parsed, 'snippet', 'medium'
    return '', 'none', 'low'


def _extract_time_from_url(url: str) -> tuple[str, str, str]:
    parsed = _parse_absolute_date(url)
    if parsed:
        return parsed, 'url', 'low'
    m = re.search(r'/(20\d{2})(\d{2})(\d{2})', url)
    if m:
        parsed = _to_iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if parsed:
            return parsed, 'url', 'low'
    return '', 'none', 'low'


async def fetch_single_url(
    url: str,
    session: aiohttp.ClientSession,
    timeout_seconds: float = 5.0,
) -> FetchResult:
    """异步抓取单个 URL"""
    import time
    start = time.perf_counter()
    
    if not url.startswith('http'):
        return FetchResult(
            url=url,
            success=False,
            full_text=None,
            published_at=None,
            time_source='none',
            time_confidence='low',
            http_status=None,
            error='invalid_url',
            elapsed_ms=0,
        )
    
    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=timeout_seconds),
            headers={'User-Agent': 'Mozilla/5.0 (compatible; OpenClawBot/2.0)'},
            ssl=SSL_CONTEXT,
        ) as resp:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            html = await resp.text()
            
            if not html:
                return FetchResult(
                    url=url,
                    success=False,
                    full_text=None,
                    published_at=None,
                    time_source='none',
                    time_confidence='low',
                    http_status=resp.status,
                    error='empty_body',
                    elapsed_ms=elapsed_ms,
                )
            
            text = extract_text_from_html(html)
            page_time, page_source, page_conf = _extract_time_from_html(html)
            
            return FetchResult(
                url=url,
                success=True,
                full_text=text[:12000] if text else None,
                published_at=page_time or None,
                time_source=page_source,
                time_confidence=page_conf,
                http_status=resp.status,
                error=None,
                elapsed_ms=elapsed_ms,
            )
            
    except asyncio.TimeoutError:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return FetchResult(
            url=url,
            success=False,
            full_text=None,
            published_at=None,
            time_source='none',
            time_confidence='low',
            http_status=None,
            error='timeout',
            elapsed_ms=elapsed_ms,
        )
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return FetchResult(
            url=url,
            success=False,
            full_text=None,
            published_at=None,
            time_source='none',
            time_confidence='low',
            http_status=None,
            error=repr(e)[:100],
            elapsed_ms=elapsed_ms,
        )


async def fetch_multiple_urls(
    urls: list[str],
    max_concurrency: int = 5,
    timeout_seconds: float = 5.0,
) -> list[FetchResult]:
    """并发抓取多个 URL，带并发限制"""
    connector = aiohttp.TCPConnector(limit=max_concurrency)
    
    async with aiohttp.ClientSession(connector=connector) as session:
        semaphore = asyncio.Semaphore(max_concurrency)
        
        async def fetch_with_semaphore(url: str) -> FetchResult:
            async with semaphore:
                return await fetch_single_url(url, session, timeout_seconds)
        
        tasks = [fetch_with_semaphore(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理可能的异常
        final_results = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                final_results.append(FetchResult(
                    url=urls[i],
                    success=False,
                    full_text=None,
                    published_at=None,
                    time_source='none',
                    time_confidence='low',
                    http_status=None,
                    error=repr(r)[:100],
                    elapsed_ms=0,
                ))
            else:
                final_results.append(r)
        
        return final_results


def fetch_urls_sync(
    urls: list[str],
    max_concurrency: int = 5,
    timeout_seconds: float = 5.0,
) -> list[FetchResult]:
    """同步接口：并发抓取多个 URL"""
    return asyncio.run(fetch_multiple_urls(urls, max_concurrency, timeout_seconds))


def hit_to_snippet_evidence(hit: SearchHit) -> Evidence:
    """将 SearchHit 转换为 snippet-only Evidence（不抓正文）"""
    now = datetime.now(timezone.utc).isoformat()
    
    # 从 snippet 提取时间
    snippet_time, snippet_source, snippet_conf = _extract_time_from_snippet(hit.snippet or '')
    url_time, url_source, url_conf = _extract_time_from_url(hit.url)
    
    published_at = hit.published_at or snippet_time or url_time
    time_source = 'engine' if hit.published_at else (snippet_source if snippet_time else url_source)
    time_confidence = 'high' if hit.published_at else (snippet_conf if snippet_time else url_conf)
    
    return Evidence(
        title=hit.title,
        url=hit.url,
        domain=hit.domain or urlparse(hit.url).netloc.lower(),
        source_type=hit.source_type,
        engine=hit.engine,
        published_at=published_at,
        fetched_at=now,
        snippet=hit.snippet,
        full_text=None,
        market=hit.market,
        ticker=hit.ticker,
        fetch_status='snippet_only',
        accepted=False,
        meta={'rank': hit.rank, 'raw_score': hit.raw_score},
        time_confidence=time_confidence,
        time_source=time_source,
    )


def merge_fetch_result_to_evidence(evidence: Evidence, fetch_result: FetchResult) -> Evidence:
    """将 fetch 结果合并到 Evidence"""
    if fetch_result.success and fetch_result.full_text:
        evidence.full_text = fetch_result.full_text
        evidence.fetch_status = 'ok'
        if fetch_result.published_at:
            evidence.published_at = fetch_result.published_at
            evidence.time_source = fetch_result.time_source
            evidence.time_confidence = fetch_result.time_confidence
        evidence.language = 'zh' if any('\u4e00' <= ch <= '\u9fff' for ch in fetch_result.full_text[:200]) else 'en'
    else:
        evidence.drop_reasons.append('fetch_failed')
        evidence.meta['fetch_error'] = fetch_result.error
        evidence.meta['fetch_elapsed_ms'] = fetch_result.elapsed_ms
    
    return evidence
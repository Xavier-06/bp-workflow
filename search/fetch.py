from __future__ import annotations
from datetime import datetime, timedelta, timezone
from html import unescape
import os
import re
from urllib.parse import urlparse

import requests

from search.models import Evidence, SearchHit

CERT = '/opt/homebrew/etc/openssl@3/cert.pem'
if os.path.exists(CERT):
    os.environ.setdefault('SSL_CERT_FILE', CERT)
    os.environ.setdefault('REQUESTS_CA_BUNDLE', CERT)
    os.environ.setdefault('CURL_CA_BUNDLE', CERT)
    os.environ.setdefault('SSL_CERT_DIR', '/opt/homebrew/etc/openssl@3/certs')

MONTHS = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
}


def extract_text_from_html(html: str) -> str:
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
        (r'name=["\']publishdate["\'][^>]*content=["\']([^"\']+)', 'meta', 'high'),
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


def fetch_hit(hit: SearchHit, timeout: int = 20) -> Evidence:
    now = datetime.now(timezone.utc).isoformat()
    evidence = Evidence(
        title=hit.title,
        url=hit.url,
        domain=hit.domain or urlparse(hit.url).netloc.lower(),
        source_type=hit.source_type,
        engine=hit.engine,
        published_at=hit.published_at,
        fetched_at=now,
        snippet=hit.snippet,
        market=hit.market,
        ticker=hit.ticker,
        fetch_status='failed',
        accepted=False,
        meta={'rank': hit.rank, 'raw_score': hit.raw_score},
        time_confidence='low',
        time_source='none',
    )
    if not hit.url.startswith('http'):
        evidence.drop_reasons.append('fetch_failed')
        evidence.meta['error'] = 'invalid_url'
        return evidence

    snippet_time, snippet_source, snippet_conf = _extract_time_from_snippet(hit.snippet or '')
    if snippet_time:
        evidence.published_at = snippet_time
        evidence.time_source = snippet_source
        evidence.time_confidence = snippet_conf

    try:
        resp = requests.get(
            hit.url,
            timeout=timeout,
            headers={'User-Agent': 'Mozilla/5.0 OpenClawSearchGateway/1.0'},
            verify=os.environ.get('REQUESTS_CA_BUNDLE', CERT),
        )
        evidence.meta['http_status'] = resp.status_code
        html = resp.text or ''
        text = extract_text_from_html(html)
        page_time, page_source, page_conf = _extract_time_from_html(html)
        if page_time:
            evidence.published_at = page_time
            evidence.time_source = page_source
            evidence.time_confidence = page_conf
        elif not evidence.published_at:
            url_time, url_source, url_conf = _extract_time_from_url(hit.url)
            if url_time:
                evidence.published_at = url_time
                evidence.time_source = url_source
                evidence.time_confidence = url_conf
        if text:
            evidence.full_text = text[:12000]
            evidence.fetch_status = 'ok' if resp.ok else 'partial'
            evidence.language = 'zh' if any('\u4e00' <= ch <= '\u9fff' for ch in text[:200]) else 'en'
            return evidence
        evidence.meta['error'] = f'empty_body_status_{resp.status_code}'
    except Exception as exc:
        evidence.meta['error'] = repr(exc)

    evidence.drop_reasons.append('fetch_failed')
    if not evidence.published_at:
        url_time, url_source, url_conf = _extract_time_from_url(hit.url)
        if url_time:
            evidence.published_at = url_time
            evidence.time_source = url_source
            evidence.time_confidence = url_conf
    return evidence

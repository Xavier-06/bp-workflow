from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import requests

from search.adapters.base import SearchAdapter
from search.models import SearchHit

logger = logging.getLogger(__name__)


def _local_session() -> requests.Session:
    """Create a session that never inherits env proxies for localhost access."""
    s = requests.Session()
    s.trust_env = False
    return s


class SearXNGAdapter(SearchAdapter):
    name = "searxng"

    @staticmethod
    def _has_chinese(text: str) -> bool:
        return any('\u4e00' <= c <= '\u9fff' for c in text)

    def __init__(self, base_urls: list[str], timeout: int = 20):
        cleaned = [u.rstrip('/') for u in base_urls if u]
        if not cleaned:
            cleaned = ['http://127.0.0.1:8888']
        self.base_urls = cleaned
        self.local_url = cleaned[0]
        self.fallback_urls = cleaned[1:]
        self.timeout = timeout
        self.last_failure: dict[str, Any] | None = None
        self.last_healthcheck_ok: bool | None = None
        self.last_used_fallback: bool = False
        self.last_result_count: int = 0
        self._session = _local_session()

    def healthcheck(self) -> bool:
        ok = False
        for idx, base_url in enumerate(self.base_urls):
            if self._healthcheck_url(base_url):
                ok = True
                if idx != 0:
                    self.base_urls = [base_url] + [u for u in self.base_urls if u != base_url]
                    self.local_url = self.base_urls[0]
                    self.fallback_urls = self.base_urls[1:]
                break
        self.last_healthcheck_ok = ok
        return ok

    def search(self, query: str, max_results: int = 10, market: str | None = None, freshness_hours: int | None = None, **kwargs: Any) -> list[SearchHit]:
        market = market or 'generic'
        ticker = kwargs.get('ticker') or ''
        allow_fallback = bool(kwargs.get('allow_fallback', True))
        engines = kwargs.get('engines')
        self.last_used_fallback = False
        self.last_result_count = 0
        self.last_failure = None

        if self.healthcheck():
            hits = self._search_single(
                self.local_url,
                query=query,
                max_results=max_results,
                market=market,
                ticker=ticker,
                freshness_hours=freshness_hours,
                engines=engines,
                language='zh-CN' if self._has_chinese(query) else 'en',
            )
            self.last_result_count = len(hits)
            if hits:
                return hits

        if not allow_fallback:
            if not self.last_failure:
                self.last_failure = {
                    'type': 'healthcheck_failed',
                    'provider': 'searxng',
                    'base_url': self.local_url,
                    'query': query,
                    'fallback_used': False,
                }
            return []

        self.last_used_fallback = True
        for base_url in self.fallback_urls:
            hits = self._search_single(
                base_url,
                query=query,
                max_results=max_results,
                market=market,
                ticker=ticker,
                freshness_hours=freshness_hours,
                engines=engines,
            )
            if hits:
                self.last_result_count = len(hits)
                return hits
        if not self.last_failure:
            self.last_failure = {
                'type': 'fallback_failed',
                'provider': 'searxng',
                'base_url': self.local_url,
                'query': query,
                'fallback_used': True,
            }
        return []

    def _healthcheck_url(self, base_url: str) -> bool:
        try:
            resp = self._session.get(f'{base_url}/healthz', timeout=5)
            if resp.ok:
                self.last_failure = None
                return True
            self.last_failure = {
                'type': 'healthcheck_status',
                'provider': 'searxng',
                'base_url': base_url,
                'status_code': resp.status_code,
            }
            return False
        except Exception as exc:
            self.last_failure = {
                'type': 'healthcheck_error',
                'provider': 'searxng',
                'base_url': base_url,
                'error': repr(exc),
            }
            return False

    def _search_single(
        self,
        base_url: str,
        *,
        query: str,
        max_results: int,
        market: str,
        ticker: str,
        freshness_hours: int | None,
        engines: str | None = None,
        **kwargs,
    ) -> list[SearchHit]:
        language = kwargs.get('language', 'en')
        params: dict[str, Any] = {'q': query, 'format': 'json', 'language': language}
        if engines:
            params['engines'] = engines
        else:
            params['results'] = max_results

        try:
            resp = self._session.get(
                f'{base_url}/search',
                params=params,
                timeout=self.timeout,
                headers={'User-Agent': 'OpenClawSearchGateway/1.0'},
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get('results', [])[:max_results]
            return [self._to_hit(item, idx=idx, market=market, ticker=ticker) for idx, item in enumerate(items, start=1)]
        except Exception as exc:
            self.last_failure = {
                'type': 'search_error',
                'provider': 'searxng',
                'base_url': base_url,
                'query': query,
                'error': repr(exc),
                'fallback_used': self.last_used_fallback,
            }
            logger.warning('searxng search failed: %s', self.last_failure)
            return []

    def _to_hit(self, item: dict[str, Any], *, idx: int, market: str, ticker: str) -> SearchHit:
        url = item.get('url') or item.get('href') or ''
        domain = urlparse(url).netloc.lower()
        return SearchHit(
            title=item.get('title', ''),
            url=url,
            domain=domain,
            engine=item.get('engine', 'searxng') or 'searxng',
            source_type='aggregator',
            market=market,
            ticker=ticker,
            published_at=item.get('publishedDate', '') or item.get('published_at', '') or '',
            snippet=item.get('content') or item.get('body') or '',
            rank=idx,
            raw_score=float(max(0, 100 - idx)),
        )

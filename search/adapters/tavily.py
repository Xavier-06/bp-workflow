from __future__ import annotations
from typing import Any
from urllib.parse import urlparse
import requests
from search.adapters.base import SearchAdapter
from search.models import SearchHit


class TavilyAdapter(SearchAdapter):
    name = "tavily"

    def __init__(self, api_key: str, timeout: int = 20):
        self.api_key = api_key.strip()
        self.timeout = timeout

    def search(self, query: str, **kwargs: Any) -> list[SearchHit]:
        if not self.api_key:
            return []
        max_results = int(kwargs.get('max_results', 6))
        market = kwargs.get('market') or 'generic'
        ticker = kwargs.get('ticker') or ''
        payload = {
            'query': query,
            'max_results': max_results,
            'search_depth': 'advanced',
            'topic': 'general',
            'include_answer': False,
            'include_raw_content': False,
        }
        try:
            resp = requests.post(
                'https://api.tavily.com/search',
                json=payload,
                headers={'Authorization': f'Bearer {self.api_key}', 'Content-Type': 'application/json'},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            rows = resp.json().get('results', [])
        except Exception:
            return []
        hits: list[SearchHit] = []
        for idx, item in enumerate(rows, start=1):
            url = item.get('url', '')
            hits.append(SearchHit(
                title=item.get('title', ''),
                url=url,
                domain=urlparse(url).netloc.lower(),
                engine='tavily',
                source_type='aggregator',
                market=market,
                ticker=ticker,
                snippet=item.get('content') or item.get('body') or '',
                rank=max(1, max_results - idx + 1),
                raw_score=float(item.get('score', max_results - idx)),
            ))
        return hits

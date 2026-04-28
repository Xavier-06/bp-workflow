"""Yahoo Finance Search Adapter — powered by WorkBuddy Yahoo Skill.

Bridges the IR pipeline's SearchHit model to Yahoo Finance search/quote APIs.
No API key required — uses the same public endpoints as the Yahoo Skill scripts.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from search.adapters.base import SearchAdapter
from search.models import SearchHit

logger = logging.getLogger(__name__)

# Yahoo Finance API endpoints (same as Yahoo Skill)
SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Accept-Encoding": "identity",
}


class YahooAdapter(SearchAdapter):
    """Yahoo Finance search adapter — no API key required.

    Two modes:
    - finance: symbol lookup + news via Yahoo Finance search API
    - web: generic web search falls through to DDG/SearXNG (returns [])
    """

    name = "yahoo"

    def __init__(self, timeout: int = 20):
        self._available = True
        self._timeout = timeout
        self.last_failure: dict[str, Any] | None = None

    def search(self, query: str, **kwargs: Any) -> list[SearchHit]:
        max_results = int(kwargs.get('max_results', 8))
        market = kwargs.get('market') or 'generic'
        ticker = kwargs.get('ticker') or ''

        # Only handle finance-related queries
        if not self._is_finance_query(query, ticker):
            return []

        return self._search_finance(query, max_results=max_results, market=market, ticker=ticker)

    def _is_finance_query(self, query: str, ticker: str) -> bool:
        """Detect if this looks like a finance query."""
        if ticker:
            return True
        q = query.strip()
        # Uppercase ticker: 1-5 chars, maybe with exchange suffix (e.g. 0700.HK)
        if re.match(r'^[A-Z]{1,5}(\.[A-Z]{1,2})?$', q):
            return True
        # Chinese stock codes: 6 digits
        if re.match(r'^\d{6}$', q):
            return True
        # Chinese characters — likely company name, always try Yahoo
        if re.search(r'[\u4e00-\u9fff]', q):
            return True
        # Finance keywords
        finance_kw = {
            'stock', 'share', '股价', '股票', '行情', '市值', '财报',
            'earnings', 'revenue', 'price target', 'PE', '估值',
            '年报', '季报', '利润', '营收', '研报',
        }
        q_lower = q.lower()
        return any(kw in q_lower for kw in finance_kw)

    def _search_finance(self, query: str, *, max_results: int, market: str, ticker: str) -> list[SearchHit]:
        """Search Yahoo Finance for symbol matches and related news.
        
        For Chinese queries, falls back to SearXNG/DDG since Yahoo Finance
        API doesn't support Chinese text directly. If a ticker is provided,
        we use that instead.
        """
        # Chinese text not supported by Yahoo Finance API
        # If we have a ticker, use it; otherwise, let DDG/SearXNG handle it
        actual_query = ticker if ticker and re.search(r'[\u4e00-\u9fff]', query) else query
        if not actual_query or re.search(r'[\u4e00-\u9fff]', actual_query):
            # Pure Chinese query without a ticker — skip, let other adapters handle
            return []

        try:
            payload = self._fetch_json(actual_query, quotes=max_results, news=max_results)
        except Exception as exc:
            self.last_failure = {
                'type': 'search_error',
                'provider': 'yahoo',
                'query': actual_query,
                'error': repr(exc),
            }
            logger.debug("Yahoo search failed: %s", exc)
            return []

        hits: list[SearchHit] = []

        # News items → SearchHits
        for idx, item in enumerate(payload.get('news', [])[:max_results], start=1):
            url = item.get('link', '')
            if not url:
                continue
            hits.append(SearchHit(
                title=item.get('title', ''),
                url=url,
                domain=urlparse(url).netloc.lower(),
                engine='yahoo',
                source_type='news',
                market=market,
                ticker=ticker,
                snippet=item.get('title', ''),
                published_at=self._parse_publish_time(item),
                rank=idx,
                raw_score=float(max(0, max_results - idx)),
            ))

        # Quote matches → SearchHits pointing to Yahoo Finance quote pages
        for idx, item in enumerate(payload.get('quotes', [])[:max_results], start=1):
            symbol = item.get('symbol', '')
            url = f"https://finance.yahoo.com/quote/{symbol}"
            name = item.get('shortname') or item.get('longname') or symbol
            hits.append(SearchHit(
                title=f"{name} ({symbol})",
                url=url,
                domain='finance.yahoo.com',
                engine='yahoo',
                source_type='financial_data',
                market=market,
                ticker=ticker,
                snippet=f"{name} - {item.get('quoteType', '')} - {item.get('exchDisp', '')}",
                rank=idx + len(hits),  # news first, quotes after
                raw_score=float(max(0, max_results - idx)),
            ))

        return hits[:max_results]

    def _fetch_json(self, query: str, quotes: int = 5, news: int = 5) -> dict[str, Any]:
        """Call Yahoo Finance search API directly (same as Yahoo Skill)."""
        params = urlencode({
            "q": query,
            "quotesCount": quotes,
            "newsCount": news,
            "enableFuzzyQuery": "false",
            "enableCb": "false",
        })
        req = Request(f"{SEARCH_URL}?{params}", headers=HEADERS)
        with urlopen(req, timeout=self._timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _parse_publish_time(item: dict) -> str:
        """Convert Yahoo publish timestamp to ISO string."""
        try:
            ts = item.get('provider_publish_time', 0)
            if ts and isinstance(ts, (int, float)):
                from datetime import datetime, timezone
                return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        except Exception:
            pass
        return ''

    def healthcheck(self) -> bool:
        """Quick healthcheck — try a minimal search."""
        try:
            self._fetch_json("AAPL", quotes=1, news=0)
            self.last_failure = None
            return True
        except Exception:
            return False

    def fetch_quote(self, symbol: str) -> dict | None:
        """Fetch a quote page snapshot (delegates to Yahoo Skill script if available)."""
        import subprocess, sys
        from pathlib import Path
        quote_script = Path.home() / ".workbuddy" / "skills" / "yahoo" / "yahoo_quote.py"
        if not quote_script.exists():
            return None
        try:
            result = subprocess.run(
                [sys.executable, str(quote_script), symbol],
                capture_output=True, text=True, timeout=20,
            )
            if result.returncode != 0:
                return None
            return {'raw_output': result.stdout}
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

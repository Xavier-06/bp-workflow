from __future__ import annotations

import os
from typing import Any

from search.adapters.base import SearchAdapter
from search.models import SearchHit


class DDGAdapter(SearchAdapter):
    name = "ddg"

    def search(self, query: str, **kwargs: Any) -> list[SearchHit]:
        """DDG Python API 直连搜索。

        中文搜索必须清除代理环境变量，否则会走 bing.com 然后超时。
        """
        saved_proxies = {}
        for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
            if key in os.environ:
                saved_proxies[key] = os.environ.pop(key)

        max_results = kwargs.get("max_results", 8)
        hits: list[SearchHit] = []
        try:
            from duckduckgo_search import DDGS

            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results, region="wt-wt"))
            for i, r in enumerate(results):
                url = r.get("href") or r.get("url") or ""
                if not url:
                    continue
                from urllib.parse import urlparse
                domain = urlparse(url).netloc.lower()
                hits.append(SearchHit(
                    title=r.get("title", ""),
                    url=url,
                    snippet=r.get("body", ""),
                    domain=domain,
                    engine="ddg",
                    source_type="web",
                    rank=i,
                ))
        except Exception:
            pass
        finally:
            for key, val in saved_proxies.items():
                os.environ[key] = val

        return hits

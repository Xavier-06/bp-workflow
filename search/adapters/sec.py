from __future__ import annotations
from typing import Any
from search.adapters.base import SearchAdapter
from search.models import SearchHit


class SECAdapter(SearchAdapter):
    name = "sec"

    def search(self, query: str, **kwargs: Any) -> list[SearchHit]:
        return []

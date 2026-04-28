from __future__ import annotations
from typing import Any
from search.adapters.base import SearchAdapter
from search.models import SearchHit


class HKEXAdapter(SearchAdapter):
    name = "hkex"

    def search(self, query: str, **kwargs: Any) -> list[SearchHit]:
        return []

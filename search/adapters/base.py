from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any
from search.models import SearchHit, Evidence


class SearchAdapter(ABC):
    name = "base"

    @abstractmethod
    def search(self, query: str, **kwargs: Any) -> list[SearchHit]:
        raise NotImplementedError

    def fetch(self, url: str, **kwargs: Any) -> Evidence | None:
        return None

    def healthcheck(self) -> bool:
        return True

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from .search_hit import SearchHit


@dataclass
class ProviderResult:
    provider: str
    ok: bool
    elapsed_ms: int
    hits: list[SearchHit] = field(default_factory=list)
    error: dict[str, Any] | None = None
    result_count: int = 0
    healthcheck_ok: bool | None = None
    fallback_used: bool = False

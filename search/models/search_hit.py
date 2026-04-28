from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SearchHit:
    """
    A single search result (URL-level).
    Compatible with Python 3.9+ (no slots=True which requires 3.10+).
    """
    title: str = ""
    url: str = ""
    domain: str = ""
    engine: str = ""
    score: float = 0.0
    published: str = ""
    snippet: str = ""
    body: str = ""
    metadata: dict = field(default_factory=dict)
    
    # Extra fields for downstream use (not always populated)
    source_type: str = ""
    market: str = ""
    ticker: str = ""
    rank: int = 0
    raw_score: float = 0.0
    published_at: str = ""

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)

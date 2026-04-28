from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class QueryPlan:
    task_type: str
    query: str = "{query}"
    freshness_hours: int | None = None
    max_results: int = 10
    allow_fallback: bool = True
    provider_order: list[str] = field(default_factory=lambda: ['searxng'])
    need_full_text: bool = True
    require_official_domain: bool = False
    query_templates: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, task_type: str, data: dict) -> "QueryPlan":
        return cls(
            task_type=task_type,
            query=str(data.get('query', '{query}')),
            freshness_hours=data.get('freshness_hours'),
            max_results=int(data.get('max_results', 10)),
            allow_fallback=bool(data.get('allow_fallback', data.get('fallback_allowed', True))),
            provider_order=list(data.get('provider_order', ['searxng'])),
            need_full_text=bool(data.get('need_full_text', True)),
            require_official_domain=bool(data.get('require_official_domain', False)),
            query_templates=list(data.get('query_templates', [])),
        )

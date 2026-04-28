from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class EntityResolution:
    entity_id: str
    company: str = ""
    ticker: str = ""
    market: str = "generic"
    aliases: list[str] = field(default_factory=list)


class EntityResolver:
    def resolve(self, company: str | None = None, ticker: str | None = None, market: str | None = None, aliases: list[str] | None = None) -> EntityResolution:
        company = (company or '').strip()
        ticker = (ticker or '').strip().upper()
        market = (market or 'generic').strip().lower()
        aliases = [a.strip() for a in (aliases or []) if a.strip()]
        base = ticker or company or 'unknown'
        entity_id = f'{market}:{base}'.lower()
        return EntityResolution(entity_id=entity_id, company=company, ticker=ticker, market=market, aliases=aliases)

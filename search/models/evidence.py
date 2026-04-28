"""
Evidence Model - Phase 2A 扩展版
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Literal
from urllib.parse import urlparse


@dataclass
class Evidence:
    """证据模型"""
    title: str
    url: str
    domain: str = ""
    
    # 源类型
    source_type: str = "aggregator"
    source_family: str = "other"
    is_official: bool = False
    is_filing: bool = False
    is_primary: bool = False
    
    # 文档类型
    document_type: str = ""
    
    engine: str = ""
    published_at: str = ""
    fetched_at: str = ""
    snippet: str = ""
    full_text: str = ""
    language: str = ""
    market: str = "generic"
    ticker: str = ""
    
    # 质量评估
    quality_score: float = 0.0
    source_rank: int = 0
    priority: int = 0
    confidence: str = "low"
    
    fetch_status: str = "failed"
    accepted: bool = False
    drop_reasons: list[str] = field(default_factory=list)
    
    meta: dict = field(default_factory=dict)
    time_confidence: str = "low"
    time_source: str = "none"

    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_hit(cls, hit, source_info: dict | None = None) -> "Evidence":
        """从 SearchHit 创建 Evidence"""
        from urllib.parse import urlparse
        
        domain = getattr(hit, 'domain', '') or urlparse(hit.url).netloc.lower()
        url = hit.url
        
        # 获取源信息
        if source_info is None:
            source_family = 'other'
            is_official = False
            is_filing = False
            is_primary = False
            priority = 0
        else:
            source_family = source_info.get('source_family', 'other')
            is_official = source_info.get('is_official', False)
            is_filing = source_info.get('is_filing', False)
            is_primary = source_info.get('is_primary', False)
            priority = source_info.get('priority', 0)
        
        # 推断 document_type
        document_type = ""
        url_lower = url.lower()
        if '10-k' in url_lower or '10k' in url_lower:
            document_type = '10-K'
        elif '10-q' in url_lower or '10q' in url_lower:
            document_type = '10-Q'
        elif '8-k' in url_lower or '8k' in url_lower:
            document_type = '8-K'
        elif 'earnings' in url_lower or 'transcript' in url_lower:
            document_type = 'earnings_transcript'
        elif '/ir' in url_lower or '/investor' in url_lower:
            document_type = 'ir_page'
        elif '/about' in url_lower or '/company' in url_lower:
            document_type = 'about_page'
        elif '/newsroom' in url_lower or '/press' in url_lower:
            document_type = 'press_release'
        
        # 计算置信度
        confidence = 'low'
        if is_official or is_filing:
            confidence = 'high'
        elif is_primary:
            confidence = 'medium'
        
        return cls(
            title=hit.title,
            url=url,
            domain=domain,
            source_type=source_family,
            source_family=source_family,
            is_official=is_official,
            is_filing=is_filing,
            is_primary=is_primary,
            document_type=document_type,
            engine=getattr(hit, 'engine', ''),
            published_at=getattr(hit, 'published_at', '') or '',
            snippet=getattr(hit, 'snippet', '') or '',
            priority=priority,
            confidence=confidence,
            fetch_status='snippet_only',
            meta={'rank': getattr(hit, 'rank', 0), 'raw_score': getattr(hit, 'raw_score', 0)},
        )
"""
Direct Source Resolver
优先直连高可信源，不走搜索引擎
"""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import sys
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sources.entity_profile import get_entity_profile, EntitySourceProfile


@dataclass
class DirectSource:
    """直接信源"""
    url: str
    source_type: str  # official, ir, newsroom, filing, rss
    domain: str
    priority: int
    is_official: bool = True
    description: str = ""


class DirectSourceResolver:
    """
    直接信源解析器
    
    职责：
    1. 根据 entity 获取官方信源列表
    2. 优先直连高可信源
    3. 不依赖搜索引擎发现
    """
    
    def __init__(self):
        pass
    
    def get_company_sources(self, entity: str) -> list[DirectSource]:
        """获取公司研究的直接信源"""
        profile = get_entity_profile(entity)
        
        if not profile:
            return self._fallback_company_sources(entity)
        
        sources = []
        
        # 1. IR 页面（最高优先级）
        for url in profile.ir_urls:
            sources.append(DirectSource(
                url=url,
                source_type='ir',
                domain=urlparse(url).netloc,
                priority=10,
                is_official=True,
                description='Investor Relations',
            ))
        
        # 2. 官方域名
        for domain in profile.official_domains:
            sources.append(DirectSource(
                url=f"https://{domain}",
                source_type='official',
                domain=domain,
                priority=9,
                is_official=True,
                description='Official Website',
            ))
        
        # 3. Newsroom
        for url in profile.newsroom_urls:
            sources.append(DirectSource(
                url=url,
                source_type='newsroom',
                domain=urlparse(url).netloc,
                priority=8,
                is_official=True,
                description='Official Newsroom',
            ))
        
        # 4. Filings
        for filing_source in profile.filing_sources:
            if filing_source == 'sec.gov':
                sources.append(DirectSource(
                    url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={entity}",
                    source_type='filing',
                    domain='sec.gov',
                    priority=7,
                    is_official=True,
                    description='SEC Filings',
                ))
            elif filing_source == 'hkexnews.hk':
                sources.append(DirectSource(
                    url=f"https://www.hkexnews.hk/index.htm",
                    source_type='filing',
                    domain='hkexnews.hk',
                    priority=7,
                    is_official=True,
                    description='HKEX Disclosures',
                ))
        
        return sources
    
    def get_news_sources(self, entity: str) -> list[DirectSource]:
        """获取新闻研究的直接信源"""
        profile = get_entity_profile(entity)
        
        if not profile:
            return self._fallback_news_sources(entity)
        
        sources = []
        
        # 1. Newsroom / Blog
        for url in profile.newsroom_urls:
            sources.append(DirectSource(
                url=url,
                source_type='newsroom',
                domain=urlparse(url).netloc,
                priority=10,
                is_official=True,
                description='Official Newsroom',
            ))
        
        # 2. IR News
        for url in profile.ir_urls:
            sources.append(DirectSource(
                url=url,
                source_type='ir',
                domain=urlparse(url).netloc,
                priority=9,
                is_official=True,
                description='IR News',
            ))
        
        return sources
    
    def _fallback_company_sources(self, entity: str) -> list[DirectSource]:
        """没有配置时的 fallback"""
        # 尝试推断官方域名
        entity_lower = entity.lower()
        common_tlds = ['.com', '.com.cn', '.cn']
        
        sources = []
        for tld in common_tlds:
            domain = f"{entity_lower}{tld}"
            sources.append(DirectSource(
                url=f"https://{domain}",
                source_type='official',
                domain=domain,
                priority=5,
                is_official=True,
                description='Inferred Official',
            ))
        
        return sources
    
    def _fallback_news_sources(self, entity: str) -> list[DirectSource]:
        """没有配置时的 fallback"""
        return []
    
    def check_domain_is_official(self, entity: str, domain: str) -> bool:
        """检查域名是否为该实体的官方域名"""
        profile = get_entity_profile(entity)
        if profile:
            return profile.is_official_domain(domain)
        return False
    
    def enrich_evidence_with_profile(self, entity: str, evidence_list: list) -> list:
        """使用 profile 信息增强证据的源分类"""
        profile = get_entity_profile(entity)
        
        if not profile:
            return evidence_list
        
        for ev in evidence_list:
            domain = getattr(ev, 'domain', '') or urlparse(getattr(ev, 'url', '')).netloc
            
            if profile.is_official_domain(domain):
                # 标记为官方源
                ev.is_official = True
                ev.source_family = 'official'
                ev.priority = 10
                
                # 检查 URL 类型
                url = getattr(ev, 'url', '').lower()
                if any(ir in url for ir in ['/ir', '/investor']):
                    ev.source_family = 'ir'
                    ev.document_type = 'ir_page'
                elif any(news in url for news in ['/newsroom', '/news', '/blog', '/press']):
                    ev.source_family = 'newsroom'
                    ev.document_type = 'press_release'
        
        return evidence_list


# 全局实例
_resolver: DirectSourceResolver | None = None

def get_resolver() -> DirectSourceResolver:
    global _resolver
    if _resolver is None:
        _resolver = DirectSourceResolver()
    return _resolver
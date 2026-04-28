"""
Entity Source Profile Loader - Phase 2A.3
支持 browser_fallback_enabled 等新字段
"""

from __future__ import annotations
import yaml
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class EntitySourceProfile:
    """实体信源配置"""
    name: str
    aliases: list[str] = field(default_factory=list)
    official_domains: list[str] = field(default_factory=list)
    ir_urls: list[str] = field(default_factory=list)
    newsroom_urls: list[str] = field(default_factory=list)
    press_urls: list[str] = field(default_factory=list)
    rss_feeds: list[str] = field(default_factory=list)
    blog_urls: list[str] = field(default_factory=list)
    sitemap_urls: list[str] = field(default_factory=list)
    archive_urls: list[str] = field(default_factory=list)
    filing_sources: list[str] = field(default_factory=list)
    browser_fallback_enabled: bool = False
    browser_fallback_reason: str = ""
    exchange: str = ""
    ticker: str = ""
    
    def matches_entity(self, entity: str) -> bool:
        """检查是否匹配该实体"""
        entity_lower = entity.lower()
        if entity_lower == self.name.lower():
            return True
        for alias in self.aliases:
            if alias.lower() == entity_lower:
                return True
        return False
    
    def is_official_domain(self, domain: str) -> bool:
        """检查域名是否为该实体的官方域名"""
        domain_lower = domain.lower()
        for official in self.official_domains:
            if official.lower() in domain_lower or domain_lower in official.lower():
                return True
        return False
    
    def needs_browser_fallback(self) -> bool:
        """是否需要浏览器 fallback"""
        return self.browser_fallback_enabled


_profiles: list[EntitySourceProfile] | None = None


def load_profiles() -> list[EntitySourceProfile]:
    """加载所有实体配置"""
    global _profiles
    
    if _profiles is not None:
        return _profiles
    
    profile_path = ROOT / 'data' / 'entity_profiles' / 'profiles.yaml'
    
    if not profile_path.exists():
        _profiles = []
        return _profiles
    
    with open(profile_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    
    profiles = []
    for entity_data in data.get('entities', []):
        profiles.append(EntitySourceProfile(
            name=entity_data.get('name', ''),
            aliases=entity_data.get('aliases', []),
            official_domains=entity_data.get('official_domains', []),
            ir_urls=entity_data.get('ir_urls', []),
            newsroom_urls=entity_data.get('newsroom_urls', []),
            press_urls=entity_data.get('press_urls', []),
            rss_feeds=entity_data.get('rss_feeds', []),
            blog_urls=entity_data.get('blog_urls', []),
            sitemap_urls=entity_data.get('sitemap_urls', []),
            archive_urls=entity_data.get('archive_urls', []),
            filing_sources=entity_data.get('filing_sources', []),
            browser_fallback_enabled=entity_data.get('browser_fallback_enabled', False),
            browser_fallback_reason=entity_data.get('browser_fallback_reason', ''),
            exchange=entity_data.get('exchange', ''),
            ticker=entity_data.get('ticker', ''),
        ))
    
    _profiles = profiles
    return profiles


def get_entity_profile(entity: str) -> EntitySourceProfile | None:
    """获取实体的信源配置"""
    profiles = load_profiles()
    for profile in profiles:
        if profile.matches_entity(entity):
            return profile
    return None